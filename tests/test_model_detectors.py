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
from fsx.anonymize.model_detectors import (
    PRIORITY_MODEL,
    PrivacyFilterDetector,
    SpacyNerDetector,
    _privacy_spans,
)

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


def test_structural_noise_enumerators_are_dropped():
    # German statements are full of "I.", "II.", "a)" enumerators that spaCy
    # loves to mis-tag as a person/org. They must never become PII.
    nlp = _FakeNlp([("I.", "PER"), ("II.", "PER"), ("a)", "ORG"), ("1.", "LOC")])
    det = SpacyNerDetector(nlp)
    assert det.detect("I. II. a) 1.") == []


def test_stopwords_drop_domain_vocabulary():
    # Statement headings the model mis-tags as a company must be suppressed when
    # injected as stopwords — case- and whitespace-insensitive.
    nlp = _FakeNlp([("Bilanz", "ORG"), ("AKTIVA", "ORG"), ("Globex SE", "ORG")])
    det = SpacyNerDetector(nlp, stopwords=["bilanz", "aktiva"])
    spans = det.detect("Bilanz AKTIVA Globex SE")
    assert [s.text for s in spans] == ["Globex SE"]  # only the real company survives


def test_stopword_does_not_suppress_company_that_merely_contains_it():
    # The match is on the whole surface, so "Aktiva Verwaltungs GmbH" survives.
    nlp = _FakeNlp([("Aktiva Verwaltungs GmbH", "ORG")])
    det = SpacyNerDetector(nlp, stopwords=["aktiva"])
    spans = det.detect("Die Aktiva Verwaltungs GmbH meldet.")
    assert [s.text for s in spans] == ["Aktiva Verwaltungs GmbH"]


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


# --------------------------------------------------------------------------- #
# openai/privacy-filter detector (BIOES decode + mapping), model injected
# --------------------------------------------------------------------------- #


def _pf(tokens, **kw):
    """A PrivacyFilterDetector whose model is a fixed token-label list."""
    return PrivacyFilterDetector(lambda text: tokens, **kw)


def test_privacy_spans_decode_bioes_and_trim():
    text = "Max Mustermann in Berlin"
    tokens = [
        ("B-private_person", 0, 3),     # "Max"
        ("E-private_person", 3, 14),    # " Mustermann"
        ("O", 14, 17),                  # " in"
        ("S-private_address", 17, 24),  # " Berlin"
    ]
    spans = _privacy_spans([t[0] for t in tokens], [(t[1], t[2]) for t in tokens], text)
    assert spans == [("private_person", 0, 14), ("private_address", 18, 24)]


def test_privacy_detector_maps_categories_to_labels():
    text = "Max Mustermann in Berlin"
    tokens = [
        ("B-private_person", 0, 3), ("E-private_person", 3, 14),
        ("O", 14, 17), ("S-private_address", 17, 24),
    ]
    spans = _pf(tokens).detect(text)
    by = {s.label: s.text for s in spans}
    assert by[Label.PERSON] == "Max Mustermann"
    assert by[Label.ADDRESS] == "Berlin"
    assert all(s.priority == PRIORITY_MODEL and s.source == "privacy-filter" for s in spans)


def test_privacy_detector_new_b_starts_a_second_entity():
    text = "Anna Berta"
    tokens = [("B-private_person", 0, 4), ("B-private_person", 4, 10)]  # two people
    spans = _pf(tokens).detect(text)
    assert [s.text for s in spans] == ["Anna", "Berta"]


def test_privacy_detector_drops_subword_fragments():
    # The subword model tags "Ers" of "Erschienen" as a person; emitting it would
    # rewrite the word to "[PERSON]chienen". A span that cuts a word is rejected.
    text = "Erschienen im Oktober"
    tokens = [("S-private_person", 0, 3)]  # "Ers", followed by "chienen"
    assert _pf(tokens).detect(text) == []
    # A whole word at the same position is kept (word-boundary on both sides).
    assert [s.text for s in _pf([("S-private_person", 0, 3)]).detect("Ers Mustermann")] == ["Ers"]


def test_privacy_detector_respects_enabled_labels_and_stopwords():
    text = "Max in Bilanz"
    tokens = [
        ("S-private_person", 0, 3),      # Max -> kept
        ("O", 3, 6),
        ("S-private_address", 6, 13),    # " Bilanz" mis-tagged -> dropped by stopword
    ]
    spans = _pf(tokens, stopwords=["bilanz"], enabled_labels={Label.PERSON, Label.ADDRESS}).detect(text)
    assert [s.text for s in spans] == ["Max"]


def test_stopword_folds_enumerator_and_trailing_punctuation():
    # A model glues a heading's enumerator ("B. Umlaufvermögen") or an
    # abbreviation's dot ("Abschr.") onto the surface; the bare stopword must
    # still match after folding those structural decorations away.
    nlp = _FakeNlp([
        ("B. Umlaufvermögen", "PER"),
        ("Abschr.", "ORG"),
        ("Max Mustermann", "PER"),
    ])
    det = SpacyNerDetector(nlp, stopwords=["umlaufvermögen", "abschr"])
    spans = det.detect("B. Umlaufvermögen Abschr. Max Mustermann")
    assert [s.text for s in spans] == ["Max Mustermann"]


def test_lowercase_proper_noun_is_dropped_as_noise():
    # German proper nouns are capitalised; an all-lowercase PERSON/ORG/LOC span
    # ("dabei", a line-wrapped "gesetzli chen") is general-language NER noise.
    nlp = _FakeNlp([
        ("dabei", "PER"),
        ("gesetzli chen", "PER"),
        ("Max Mustermann", "PER"),
    ])
    det = SpacyNerDetector(nlp)
    spans = det.detect("dabei gesetzli chen Max Mustermann")
    assert [s.text for s in spans] == ["Max Mustermann"]


def test_privacy_detector_drops_lowercase_person_noise():
    text = "dabei Burmester"
    tokens = [
        ("S-private_person", 0, 5),   # "dabei" -> lowercase, dropped
        ("S-private_person", 6, 15),  # "Burmester" -> real name, kept
    ]
    assert [s.text for s in _pf(tokens).detect(text)] == ["Burmester"]
