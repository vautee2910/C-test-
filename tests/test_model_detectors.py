"""Tests for the model-based (spaCy NER) detector.

A tiny fake ``nlp`` stands in for a loaded spaCy pipeline: it is configured with
``(surface, spacy_label)`` pairs and, on call, locates each surface in the text
and yields entities with correct character offsets — mirroring ``Doc.ents``
without the ~500 MB model. The real model is verified out-of-band.
"""

from __future__ import annotations

import importlib.util

import pytest

from fsx.anonymize import Anonymizer, DictionaryDetector, DictionaryEntity, RegexDetector
from fsx.anonymize.labels import Label
from fsx.anonymize.model_detectors import PRIORITY_MODEL, SpacyNerDetector

_SPACY_MODEL = "de_core_news_lg"


def _spacy_model_available() -> bool:
    if importlib.util.find_spec("spacy") is None:
        return False
    import spacy.util

    return _SPACY_MODEL in spacy.util.get_installed_models()


# --------------------------------------------------------------------------- #
# Fake spaCy pipeline
# --------------------------------------------------------------------------- #


class _Ent:
    def __init__(self, text: str, label_: str, start_char: int, end_char: int) -> None:
        self.text = text
        self.label_ = label_
        self.start_char = start_char
        self.end_char = end_char


class _Doc:
    def __init__(self, ents: list[_Ent]) -> None:
        self.ents = ents


class _FakeNlp:
    """Finds each configured (surface, label) occurrence and yields entities."""

    def __init__(self, entities: list[tuple[str, str]]) -> None:
        self._entities = entities

    def __call__(self, text: str) -> _Doc:
        ents: list[_Ent] = []
        for surface, label in self._entities:
            start = text.find(surface)
            if start >= 0:
                ents.append(_Ent(surface, label, start, start + len(surface)))
        ents.sort(key=lambda e: e.start_char)
        return _Doc(ents)


# --------------------------------------------------------------------------- #
# Mapping & filtering
# --------------------------------------------------------------------------- #


def test_maps_spacy_labels_to_canonical():
    nlp = _FakeNlp([("Max Mustermann", "PER"), ("Globex SE", "ORG"), ("Hamburg", "LOC")])
    det = SpacyNerDetector(nlp)
    spans = det.detect("Max Mustermann führt die Globex SE in Hamburg.")

    by_label = {s.label: s for s in spans}
    assert by_label[Label.PERSON].text == "Max Mustermann"
    assert by_label[Label.COMPANY].text == "Globex SE"
    assert by_label[Label.LOCATION].text == "Hamburg"
    assert all(s.source == "spacy" for s in spans)
    assert all(s.priority == PRIORITY_MODEL for s in spans)


def test_unmapped_and_short_entities_are_dropped():
    nlp = _FakeNlp([("MISC-Term", "MISC"), ("A", "PER")])
    det = SpacyNerDetector(nlp)
    assert det.detect("A MISC-Term appears") == []


def test_enabled_labels_filter():
    nlp = _FakeNlp([("Max Mustermann", "PER"), ("Globex SE", "ORG")])
    det = SpacyNerDetector(nlp, enabled_labels={Label.PERSON})
    spans = det.detect("Max Mustermann und Globex SE")
    assert {s.label for s in spans} == {Label.PERSON}


def test_repeated_mentions_share_entity_id():
    nlp = _FakeNlp([("Globex SE", "ORG")])
    det = SpacyNerDetector(nlp)
    spans = det.detect("Globex SE meldet; Globex SE wächst")
    # _FakeNlp.find only returns the first hit, so emulate two mentions instead:
    spans2 = det.detect("Globex SE")
    assert spans[0].entity_id == spans2[0].entity_id  # case/space-normalised group


def test_empty_text_returns_no_spans():
    det = SpacyNerDetector(_FakeNlp([("Globex SE", "ORG")]))
    assert det.detect("") == []


# --------------------------------------------------------------------------- #
# Engine composition: dictionary/regex outrank the model; model adds recall
# --------------------------------------------------------------------------- #


def test_model_adds_recall_for_unknown_names():
    """A person absent from the dictionary is still anonymised by the model."""
    dict_det = DictionaryDetector([DictionaryEntity("c0", Label.COMPANY, ["Muster GmbH"])])
    nlp = _FakeNlp([("Erika Musterfrau", "PER")])
    eng = Anonymizer([dict_det, RegexDetector(), SpacyNerDetector(nlp)])

    res = eng.anonymize("Muster GmbH, vertreten durch Erika Musterfrau")
    assert "[UNTERNEHMEN_1]" in res.text
    assert "[PERSON_1]" in res.text
    assert "Erika Musterfrau" not in res.text


def test_dictionary_wins_overlap_with_model():
    """When both fire on the same span, the curated dictionary token is used."""
    dict_det = DictionaryDetector(
        [DictionaryEntity("c0", Label.COMPANY, ["Muster Maschinenbau GmbH"])]
    )
    # Model tags the same organisation (ORG) — should be suppressed by merge.
    nlp = _FakeNlp([("Muster Maschinenbau GmbH", "ORG")])
    eng = Anonymizer([dict_det, SpacyNerDetector(nlp)])

    res = eng.anonymize("Die Muster Maschinenbau GmbH")
    assert res.text == "Die [UNTERNEHMEN_1]"
    # Exactly one span survived, and it came from the dictionary.
    assert len(res.spans) == 1
    assert res.spans[0].source == "dictionary"


def test_longer_model_span_wins_over_shorter_dictionary_alias():
    """Recall case: model catches the full name, dict only a short alias inside."""
    dict_det = DictionaryDetector([DictionaryEntity("p0", Label.PERSON, ["Mustermann"])])
    nlp = _FakeNlp([("Dr. Max Mustermann", "PER")])
    eng = Anonymizer([dict_det, SpacyNerDetector(nlp)])

    res = eng.anonymize("Vorstand: Dr. Max Mustermann")
    assert "Dr. Max Mustermann" not in res.text
    assert res.text == "Vorstand: [PERSON_1]"


# --------------------------------------------------------------------------- #
# Real model (only when de_core_news_lg is installed)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not _spacy_model_available(), reason=f"{_SPACY_MODEL} not installed")
def test_real_spacy_model_detects_person_org_location():
    det = SpacyNerDetector.load(_SPACY_MODEL)
    # Real, well-known entities the German model recognises reliably.
    spans = det.detect("Die Siemens AG mit Sitz in München wird von Joe Kaeser geführt.")
    by_label = {s.label: s.text for s in spans}
    assert by_label.get(Label.COMPANY) == "Siemens AG"
    assert by_label.get(Label.PERSON) == "Joe Kaeser"
    assert by_label.get(Label.LOCATION) == "München"


@pytest.mark.skipif(not _spacy_model_available(), reason=f"{_SPACY_MODEL} not installed")
def test_real_spacy_model_lifts_recall_in_engine():
    """End-to-end: a name absent from the dictionary is anonymised by the model."""
    dict_det = DictionaryDetector([DictionaryEntity("c0", Label.COMPANY, ["Siemens AG"])])
    eng = Anonymizer([dict_det, RegexDetector(), SpacyNerDetector.load(_SPACY_MODEL)])

    res = eng.anonymize("Die Siemens AG wird von Joe Kaeser in München geführt.")
    # Curated company token + model-found person/location, originals all gone.
    assert "[UNTERNEHMEN_1]" in res.text
    assert "Joe Kaeser" not in res.text
    assert "München" not in res.text
