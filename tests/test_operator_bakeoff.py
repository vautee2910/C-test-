"""Replacement-operator bakeoff: our Anonymizer vs. presidio-anonymizer.

Deterministic (no heavy NER): both sides get the *same* spans, so this isolates
the *replacement* step. presidio-anonymizer is light (no spaCy); the tests skip
only if it is not installed. Conclusion captured as assertions: our engine keeps
**entity-consistent, numbered, entity-grouped** pseudonyms, which Presidio's
built-in operators do not (``replace`` collapses entities, ``mask`` leaks, ``hash``
is surface-based and unreadable).
"""

from __future__ import annotations

import pytest

from fsx.config import build_anonymizer

presidio_anonymizer = pytest.importorskip("presidio_anonymizer")
from presidio_anonymizer import AnonymizerEngine  # noqa: E402
from presidio_anonymizer.entities import OperatorConfig, RecognizerResult  # noqa: E402


def _our(cfg, text):
    return build_anonymizer(cfg).anonymize(text).text


# --------------------------------------------------------------------------- #
# Distinctness + repeat-consistency on two people
# --------------------------------------------------------------------------- #

def test_distinct_persons_and_repeats():
    text = "Max Mustermann und Erika Musterfrau, erneut Max Mustermann."
    cfg = {"people": ["Max Mustermann", "Erika Musterfrau"],
           "replacement_policy": {"person": "[PERSON_{n}]"}}
    ours = _our(cfg, text)
    # ours: two distinct people, Max consistent across both mentions
    assert ours.count("[PERSON_1]") == 2 and "[PERSON_2]" in ours
    assert "Mustermann" not in ours and "Musterfrau" not in ours

    res = [
        RecognizerResult(entity_type="PERSON", start=0, end=14, score=0.9),
        RecognizerResult(entity_type="PERSON", start=19, end=35, score=0.9),
        RecognizerResult(entity_type="PERSON", start=44, end=58, score=0.9),
    ]
    presidio = AnonymizerEngine().anonymize(text=text, analyzer_results=res).text
    # presidio default 'replace' collapses every person to one token: the two
    # different people and the repeat are indistinguishable.
    assert presidio.count("<PERSON>") == 3
    assert "[PERSON_2]" not in presidio  # no per-entity numbering


# --------------------------------------------------------------------------- #
# Entity grouping: a company's long & short name share one token (ours only)
# --------------------------------------------------------------------------- #

def test_entity_grouping_long_and_short_name():
    text = "Die Acme Maschinenbau GmbH (kurz Acme) meldet."
    cfg = {"company_aliases": ["Acme Maschinenbau GmbH", "Acme"],
           "replacement_policy": {"company": "[UNTERNEHMEN_{n}]"}}
    ours = _our(cfg, text)
    # both spellings collapse to the SAME token (they are one entity)
    assert ours.count("[UNTERNEHMEN_1]") == 2

    res = [
        RecognizerResult(entity_type="ORGANIZATION", start=4, end=26, score=0.9),  # long
        RecognizerResult(entity_type="ORGANIZATION", start=33, end=37, score=0.9),  # "Acme"
    ]
    ops = {"ORGANIZATION": OperatorConfig("hash", {})}
    hashed = AnonymizerEngine().anonymize(text=text, analyzer_results=res, operators=ops).text
    import re
    tokens = re.findall(r"\b[0-9a-f]{16,}\b", hashed)
    # presidio 'hash' is surface-based: the long and short name get DIFFERENT
    # hashes, so the entity link is lost (and the output is unreadable).
    assert len(set(tokens)) == 2


# --------------------------------------------------------------------------- #
# 'mask' leaks part of the name; our replacement removes it entirely
# --------------------------------------------------------------------------- #

def test_mask_operator_leaks_part_of_name():
    text = "Sachbearbeiter Max Mustermann."
    res = [RecognizerResult(entity_type="PERSON", start=15, end=29, score=0.9)]
    ops = {"PERSON": OperatorConfig("mask", {"masking_char": "*", "chars_to_mask": 4, "from_end": False})}
    masked = AnonymizerEngine().anonymize(text=text, analyzer_results=res, operators=ops).text
    assert "Mustermann" in masked  # the surname leaks through partial masking

    ours = _our({"people": ["Max Mustermann"], "replacement_policy": {"person": "[PERSON_{n}]"}}, text)
    assert "Mustermann" not in ours  # fully removed
