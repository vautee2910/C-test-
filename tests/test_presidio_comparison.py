"""Real-engine comparison: Presidio vs. our German-tuned detectors.

Heavy/optional: building a Presidio ``AnalyzerEngine`` over spaCy takes ~minute,
so this is opt-in via ``FSX_PRESIDIO_E2E=1`` (and self-skips if Presidio or the
German model is unavailable). It documents, as executable evidence, *where each
is better*:

* our :class:`RegexDetector` owns German register/tax/address ids that Presidio
  misses or mis-tags;
* Presidio (its spaCy NER) adds PERSON/ORGANIZATION/LOCATION recall that pure
  regex cannot, on a par with our optional :class:`SpacyNerDetector`;
* with our shared stopwords, Presidio does not over-redact statement vocabulary.

Synthetic fixtures only.
"""

from __future__ import annotations

import os

import pytest

from fsx.anonymize.detectors import RegexDetector
from fsx.anonymize.labels import Label

_RUN = os.environ.get("FSX_PRESIDIO_E2E")

pytestmark = pytest.mark.skipif(
    not _RUN, reason="set FSX_PRESIDIO_E2E=1 to run the heavy Presidio comparison"
)


def _presidio_or_skip():
    try:
        from fsx.anonymize import PresidioDetector
    except Exception:  # pragma: no cover
        pytest.skip("presidio not importable")
    try:
        return PresidioDetector.load(stopwords={"bilanz", "aktiva", "passiva"})
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"presidio engine unavailable: {exc}")


@pytest.fixture(scope="module")
def presidio():
    return _presidio_or_skip()


def _labels(spans):
    return {s.label for s in spans}


# --- German structured IDs: our regex wins -------------------------------- #

def test_german_ids_caught_by_regex_but_not_presidio(presidio):
    text = "HRB 12345, USt-IdNr. DE123456789, Steuernummer 12/345/67890, 27404 Heeslingen"
    regex = _labels(RegexDetector().detect(text))
    assert {Label.COMMERCIAL_REGISTER, Label.VAT_ID, Label.TAX_NUMBER, Label.ADDRESS} <= regex

    pres = _labels(presidio.detect(text))
    # Presidio (NER+email+iban set) does NOT contribute these structured ids.
    assert Label.COMMERCIAL_REGISTER not in pres
    assert Label.VAT_ID not in pres
    assert Label.TAX_NUMBER not in pres


# --- Names / ORG / location: Presidio adds NER recall regex cannot -------- #

def test_presidio_adds_ner_recall_over_regex(presidio):
    text = "Der Bundesverband innovativer Handwerker e.V. und Mike Burmester aus Zeven."
    regex = _labels(RegexDetector().detect(text))
    assert Label.COMPANY not in regex and Label.PERSON not in regex  # regex has no NER

    pres = _labels(presidio.detect(text))
    assert Label.COMPANY in pres   # ORGANIZATION -> COMPANY
    assert Label.PERSON in pres


# --- Precision: no over-redaction of statement vocabulary ----------------- #

def test_presidio_does_not_over_redact_statement_vocabulary(presidio):
    text = "Bilanz: Aktiva, Passiva, Umsatzerlöse, Anlagevermögen, Jahresüberschuss"
    surfaces = {s.text for s in presidio.detect(text)}
    for term in ("Bilanz", "Aktiva", "Passiva", "Umsatzerlöse", "Anlagevermögen"):
        assert term not in surfaces
