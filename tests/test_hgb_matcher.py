"""HGB concept matcher tests (against the shipped knowledge base)."""

from __future__ import annotations

import pytest

from fsx.hgb.concepts import ConceptMatcher, normalise_label


@pytest.fixture(scope="module")
def matcher():
    return ConceptMatcher.from_yaml()


@pytest.mark.parametrize(
    "label, expected_norm",
    [
        ("II. Sachanlagen", "sachanlagen"),
        ("1. Roh-, Hilfs- und Betriebsstoffe", "roh hilfs und betriebsstoffe"),
        ("a) Löhne und Gehälter", "loehne und gehaelter"),
        ("III.   Finanzanlagen", "finanzanlagen"),
        ("Gezeichnetes Kapital (Stammkapital)", "gezeichnetes kapital"),  # note ref stripped
        ("Immaterielle Vermögensgegenstände (1)", "immaterielle vermoegensgegenstaende"),
    ],
)
def test_normalise_strips_enumerators_and_folds_umlauts(label, expected_norm):
    assert normalise_label(label) == expected_norm


@pytest.mark.parametrize(
    "label, concept, statement",
    [
        ("II. Sachanlagen", "sachanlagen", "bilanz"),
        ("III. Finanzanlagen", "finanzanlagen", "bilanz"),
        ("Summe Anlagevermögen", "summe_anlagevermoegen", "bilanz"),
        ("I. Gezeichnetes Kapital", "gezeichnetes_kapital", "bilanz"),
        ("Summe Eigenkapital", "summe_eigenkapital", "bilanz"),
        ("1. Umsatzerlöse", "umsatzerloese", "guv"),
        ("4. Personalaufwand", "personalaufwand", "guv"),
        ("a) Löhne und Gehälter", "loehne_gehaelter", "guv"),
    ],
)
def test_exact_concept_matches(matcher, label, concept, statement):
    m = matcher.match(label)
    assert m is not None
    assert m.concept == concept
    assert m.statement == statement
    assert m.confidence == 1.0


def test_wrapped_label_resolves_via_prefix(matcher):
    # The full multi-word name resolves even though it spans two visual rows.
    m = matcher.match("Kassenbestand und Guthaben bei Kreditinstituten")
    assert m is not None
    assert m.concept == "kassenbestand_bankguthaben"


def test_fuzzy_match_tolerates_minor_wording(matcher):
    m = matcher.match("Verbindlichkeiten gegenüber Kreditinstitute")  # missing trailing n
    assert m is not None
    assert m.concept == "verbindlichkeiten_kreditinstitute"
    assert m.confidence < 1.0


def test_comma_enumerator_is_stripped(matcher):
    # Some reports / OCR write "5," instead of "5." before the label.
    m = matcher.match("5, sonstige betriebliche Aufwendungen", statement="guv")
    assert m is not None
    assert m.concept == "sonstige_betriebliche_aufwendungen"


def test_section_filter_disambiguates_rechnungsabgrenzungsposten(matcher):
    aktiv = matcher.match("Rechnungsabgrenzungsposten", statement="bilanz", section="aktiva")
    passiv = matcher.match("Rechnungsabgrenzungsposten", statement="bilanz", section="passiva")
    assert aktiv.concept == "rechnungsabgrenzungsposten_aktiv"
    assert passiv.concept == "rechnungsabgrenzungsposten_passiv"


def test_bank_concepts_are_loaded_alongside_industrial(matcher):
    # The default matcher loads both the industrial and the bank KB.
    assert matcher.match("Forderungen an Kunden", statement="bilanz", section="aktiva").concept == "forderungen_kunden"
    assert matcher.match("Provisionserträge", statement="guv").concept == "provisionsertraege"
    assert matcher.match("Nachrangige Verbindlichkeiten", statement="bilanz", section="passiva").concept == "nachrangige_verbindlichkeiten"
    # An industrial concept still resolves from the same matcher.
    assert matcher.match("II. Sachanlagen").concept == "sachanlagen"


def test_unknown_label_returns_none(matcher):
    assert matcher.match("Erläuterungen zu dieser Musterauswertung") is None
    assert matcher.match("[UNTERNEHMEN_1]") is None


def test_classify_document_family_and_concept_paths():
    from fsx.hgb.concepts import (
        classify_document_family, concept_paths_for_family, DEFAULT_BANK_CONCEPTS,
    )
    bank = "Barreserve Forderungen an Kreditinstitute Forderungen an Kunden Zinserträge"
    assert classify_document_family(bank) == "bank"
    industrial = "Anlagevermögen Sachanlagen Umsatzerlöse Materialaufwand Personalaufwand"
    assert classify_document_family(industrial) == "hgb"
    # Industrial sheets carry bank loans and interest too — these must stay hgb,
    # not bank (driven by the distinctive HGB structure terms present).
    industrial_loans = (
        "Bilanz Gewinn- und Verlustrechnung Umsatzerlöse Sachanlagen "
        "Verbindlichkeiten gegenüber Kreditinstituten 250.000,00 "
        "Zinsen und ähnliche Aufwendungen Zinsaufwendungen 12.000,00"
    )
    assert classify_document_family(industrial_loans) == "hgb"
    # Documents that look like no family are "unknown" (no guessing), and fall
    # back to the base concepts only.
    assert classify_document_family("Mietvertrag zwischen den Parteien.") == "unknown"
    assert classify_document_family("Nur Zinserträge werden hier erwähnt.") == "unknown"
    assert DEFAULT_BANK_CONCEPTS in concept_paths_for_family("bank")
    assert DEFAULT_BANK_CONCEPTS not in concept_paths_for_family("hgb")
    assert DEFAULT_BANK_CONCEPTS not in concept_paths_for_family("unknown")
