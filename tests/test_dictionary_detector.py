"""Dictionary detector tests."""

from __future__ import annotations

from fsx.anonymize.detectors import DictionaryDetector, DictionaryEntity
from fsx.anonymize.labels import Label


def test_matches_case_insensitively():
    det = DictionaryDetector([DictionaryEntity("c0", Label.COMPANY, ["Muster GmbH"])])
    spans = det.detect("Die MUSTER GMBH erzielte ...")
    assert len(spans) == 1
    assert spans[0].label == Label.COMPANY


def test_respects_word_boundaries():
    det = DictionaryDetector([DictionaryEntity("p0", Label.PERSON, ["Mann"])])
    # "Personalaufwand" contains "mann" but must not match (word boundary).
    assert det.detect("Der Personalaufwand stieg") == []


def test_aliases_share_entity_id():
    det = DictionaryDetector(
        [DictionaryEntity("c0", Label.COMPANY, ["Muster Maschinenbau GmbH", "MMG"])]
    )
    spans = det.detect("Die Muster Maschinenbau GmbH (MMG) meldet")
    assert len(spans) == 2
    assert spans[0].entity_id == spans[1].entity_id == "c0"


def test_longest_alias_available_for_merge():
    # Both the long and short alias match; merge (done by engine) keeps longest.
    det = DictionaryDetector(
        [DictionaryEntity("c0", Label.COMPANY, ["Muster Maschinenbau", "Muster"])]
    )
    spans = det.detect("Die Muster Maschinenbau wächst")
    texts = {s.text for s in spans}
    assert "Muster Maschinenbau" in texts


def test_domain_matched():
    det = DictionaryDetector([DictionaryEntity("d0", Label.DOMAIN, ["muster-gmbh.de"])])
    spans = det.detect("Web: muster-gmbh.de online")
    assert len(spans) == 1
    assert spans[0].label == Label.DOMAIN


def test_alias_matches_across_a_line_break():
    # A company name wrapped across lines (justified prose) still matches — the
    # alias words are joined with \s+, so the newline between them is fine.
    det = DictionaryDetector(
        [DictionaryEntity("c0", Label.COMPANY, ["Muster Maschinenbau GmbH"])]
    )
    spans = det.detect("… der Muster Maschinenbau\nGmbH für das Jahr …")
    assert len(spans) == 1
    assert spans[0].entity_id == "c0"
    assert "Muster Maschinenbau" in spans[0].text


def test_alias_with_internal_spaced_punctuation_wraps():
    det = DictionaryDetector(
        [DictionaryEntity("c0", Label.COMPANY, ["Innovativer Handwerker e. V."])]
    )
    spans = det.detect("Auftraggeber Innovativer Handwerker e.\nV. beauftragte mich")
    assert len(spans) == 1
