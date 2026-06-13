"""End-to-end anonymisation engine tests."""

from __future__ import annotations

from fsx.anonymize import Anonymizer, DictionaryDetector, DictionaryEntity, RegexDetector
from fsx.anonymize.labels import Label


def _engine(entities=None, **regex_kw):
    return Anonymizer(
        [DictionaryDetector(entities or []), RegexDetector(**regex_kw)]
    )


def test_consistent_token_for_repeated_company():
    eng = _engine([DictionaryEntity("c0", Label.COMPANY, ["Muster GmbH"])])
    res = eng.anonymize("Muster GmbH ... später wieder Muster GmbH erwähnt")
    assert res.text.count("[UNTERNEHMEN_1]") == 2
    assert "Muster GmbH" not in res.text


def test_aliases_collapse_to_one_token():
    eng = _engine([DictionaryEntity("c0", Label.COMPANY, ["Muster Maschinenbau GmbH", "MMG"])])
    res = eng.anonymize("Die Muster Maschinenbau GmbH (MMG)")
    assert res.text.count("[UNTERNEHMEN_1]") == 2


def test_distinct_entities_get_distinct_numbers():
    eng = _engine(
        [
            DictionaryEntity("p0", Label.PERSON, ["Max Mustermann"]),
            DictionaryEntity("p1", Label.PERSON, ["Erika Musterfrau"]),
        ]
    )
    res = eng.anonymize("Max Mustermann und Erika Musterfrau")
    assert "[PERSON_1]" in res.text
    assert "[PERSON_2]" in res.text


def test_mixed_dictionary_and_regex():
    eng = _engine([DictionaryEntity("c0", Label.COMPANY, ["Muster GmbH"])])
    res = eng.anonymize("Muster GmbH, USt-IdNr. DE123456789, HRB 12345")
    assert "[UNTERNEHMEN_1]" in res.text
    assert "[USTID_1]" in res.text
    assert "[REGISTER_1]" in res.text
    assert "DE123456789" not in res.text


def test_longer_dictionary_span_wins_over_short_overlap():
    eng = _engine(
        [DictionaryEntity("c0", Label.COMPANY, ["Muster Maschinenbau", "Muster"])]
    )
    res = eng.anonymize("Die Muster Maschinenbau GmbH")
    # The full match is replaced once; the inner "Muster" alias must not also fire.
    assert res.text == "Die [UNTERNEHMEN_1] GmbH"


def test_mapping_is_recorded_for_audit():
    eng = _engine([DictionaryEntity("c0", Label.COMPANY, ["Muster GmbH"])])
    res = eng.anonymize("Muster GmbH")
    assert res.mapping == {"[UNTERNEHMEN_1]": "Muster GmbH"}


def test_token_numbering_stable_across_calls():
    eng = _engine([DictionaryEntity("c0", Label.COMPANY, ["Alpha AG"]),
                   DictionaryEntity("c1", Label.COMPANY, ["Beta AG"])])
    first = eng.anonymize("Alpha AG meldet")
    second = eng.anonymize("Beta AG und erneut Alpha AG")
    assert "[UNTERNEHMEN_1]" in first.text
    # Alpha keeps token 1 across calls; Beta becomes token 2.
    assert "[UNTERNEHMEN_2]" in second.text
    assert second.text.count("[UNTERNEHMEN_1]") == 1


def test_empty_text_is_noop():
    eng = _engine()
    res = eng.anonymize("")
    assert res.text == ""
    assert res.replaced_count == 0
