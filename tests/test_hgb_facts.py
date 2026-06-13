"""Level-2 fact generation tests."""

from __future__ import annotations

import pytest

from fsx.extract.tables import LineItem, ReconstructedTable
from fsx.hgb.concepts import ConceptMatcher
from fsx.hgb.facts import (
    detect_scale,
    detect_statement,
    facts_from_tables,
    split_period_values,
)
from fsx.schemas import StatementType


def test_detect_statement_handles_hyphenated_and_continuation():
    assert detect_statement("Gewinn-und-Verlust-Rechnung der Commerzbank") == "guv"
    assert detect_statement("Gewinn- und Verlustrechnung vom 1. Januar") == "guv"
    # Multi-page balance sheet: a continuation page titled only "Aktivseite".
    assert detect_statement("8  Commerzbank  Aktivseite  Mio €  31.12.2025") == "bilanz"
    assert detect_statement("Passivseite  Mio €") == "bilanz"
    assert detect_statement("Allgemeine Auftragsbedingungen") is None


def test_detect_scale():
    assert detect_scale("Aktiva in Millionen €") == 1_000_000
    assert detect_scale("Mio. €  2025  2024") == 1_000_000
    assert detect_scale("Angaben in T€") == 1_000
    assert detect_scale("in Tausend Euro") == 1_000
    assert detect_scale("(30) Eigenkapital €  31.12.2025") == 1


def test_scale_applied_to_facts():
    matcher = ConceptMatcher.from_yaml()
    tables = {3: [_table([LineItem("III. Finanzanlagen", [None, 39487.0, 39593.0], y=1)])]}
    facts = facts_from_tables(
        tables, company_id="C1", fiscal_year=2025, matcher=matcher,
        statement_by_page={3: "bilanz"}, scale_by_page={3: 1_000_000},
    )
    assert all(f.scale == 1_000_000 for f in facts)


def test_split_period_values_total_row():
    # [inner(empty), current-total, prior]
    assert split_period_values([None, 2116685.83, 2108632.83]) == (2116685.83, 2108632.83)


def test_split_period_values_subitem_row():
    # [inner(own amount), group-total(shares row), prior] -> own amount, not total
    assert split_period_values([87105.41, 195718.52, 81441.66]) == (87105.41, 81441.66)


def test_split_period_values_two_columns():
    assert split_period_values([1000.0, 950.0]) == (1000.0, 950.0)


def test_split_period_values_single_column():
    assert split_period_values([1234.0]) == (1234.0, None)


def _table(items):
    return ReconstructedTable(n_columns=3, items=items)


def test_facts_current_and_prior_year_emitted():
    matcher = ConceptMatcher.from_yaml()
    tables = {
        5: [
            _table([
                LineItem("II. Sachanlagen", [None, 1784101.83, 1778628.83], y=1),
            ])
        ]
    }
    facts = facts_from_tables(tables, company_id="C1", fiscal_year=2023, matcher=matcher)
    assert len(facts) == 2
    by_year = {f.fiscal_year: f for f in facts}
    assert by_year[2023].concept == "sachanlagen"
    assert by_year[2023].value == 1784101.83
    assert by_year[2023].statement == StatementType.BILANZ
    assert by_year[2023].source_page == 5
    assert by_year[2022].value == 1778628.83


def test_negative_values_get_sign(matcher_value=None):
    matcher = ConceptMatcher.from_yaml()
    tables = {6: [_table([LineItem("6. Personalaufwand", [None, -662921.90, -711207.27], y=1)])]}
    facts = facts_from_tables(tables, company_id="C1", fiscal_year=2023, matcher=matcher)
    cur = next(f for f in facts if f.fiscal_year == 2023)
    assert cur.value < 0
    assert cur.sign == -1


def test_wrapped_label_merged_for_matching():
    matcher = ConceptMatcher.from_yaml()
    tables = {
        5: [
            _table([
                LineItem("III. Kassenbestand und Guthaben bei", [None, None, None], y=1),
                LineItem("Kreditinstituten", [None, 206908.14, 262581.34], y=2),
            ])
        ]
    }
    facts = facts_from_tables(tables, company_id="C1", fiscal_year=2023, matcher=matcher)
    cur = next(f for f in facts if f.fiscal_year == 2023)
    assert cur.concept == "kassenbestand_bankguthaben"
    assert cur.value == 206908.14


def test_unmatched_rows_produce_no_facts():
    matcher = ConceptMatcher.from_yaml()
    tables = {1: [_table([LineItem("Erläuterungen zur Musterauswertung", [None, 1.0, 2.0], y=1)])]}
    facts = facts_from_tables(tables, company_id="C1", fiscal_year=2023, matcher=matcher)
    assert facts == []


def test_statement_filter_blocks_cross_statement_match():
    # A GuV line mentioning "Anlagevermögens" must NOT bind to the Bilanz concept
    # when the page is known to be a GuV.
    matcher = ConceptMatcher.from_yaml()
    tables = {6: [_table([LineItem("Anlagevermögens", [None, 543.22, 635.65], y=1)])]}
    facts = facts_from_tables(
        tables, company_id="C1", fiscal_year=2023, matcher=matcher,
        statement_by_page={6: "guv"},
    )
    assert all(f.concept != "anlagevermoegen" for f in facts)


def test_subitem_with_enumerator_not_merged_into_header():
    # "8. sonstige betriebliche Aufwendungen" (header) + "a) Raumkosten" (sub) must
    # NOT merge — Raumkosten is unknown, so it yields no fact (no wrong total).
    matcher = ConceptMatcher.from_yaml()
    tables = {
        6: [
            _table([
                LineItem("8. sonstige betriebliche Aufwendungen", [None, None, None], y=1),
                LineItem("a) Raumkosten", [-75269.56, None, -75271.01], y=2),
            ])
        ]
    }
    facts = facts_from_tables(
        tables, company_id="C1", fiscal_year=2023, matcher=matcher,
        statement_by_page={6: "guv"},
    )
    assert facts == []


def test_jahresfehlbetrag_sign_is_flipped():
    # Bilanz prints a deficit as a positive equity-reducing amount; economically
    # it is a loss. The prior column (-492382.95) was actually a surplus.
    matcher = ConceptMatcher.from_yaml()
    tables = {5: [_table([LineItem("III. Jahresfehlbetrag", [None, None, 753840.66, -492382.95], y=1)])]}
    facts = facts_from_tables(
        tables, company_id="C1", fiscal_year=2021, matcher=matcher,
        statement_by_page={5: "bilanz"},
    )
    cur = next(f for f in facts if f.fiscal_year == 2021)
    prev = next(f for f in facts if f.fiscal_year == 2020)
    assert cur.concept == "jahresueberschuss"
    assert cur.value == pytest.approx(-753840.66)  # loss -> negative
    assert prev.value == pytest.approx(492382.95)  # prior surplus -> positive


def test_bilanzgewinn_not_flipped():
    matcher = ConceptMatcher.from_yaml()
    tables = {5: [_table([LineItem("III. Bilanzgewinn", [None, 844879.12, 843667.31], y=1)])]}
    facts = facts_from_tables(
        tables, company_id="C1", fiscal_year=2023, matcher=matcher,
        statement_by_page={5: "bilanz"},
    )
    cur = next(f for f in facts if f.fiscal_year == 2023)
    assert cur.value == pytest.approx(844879.12)


def test_orphan_subtotal_attaches_to_section_header():
    # Bank pattern: header (no value) -> sub-items (no concept) -> total (no label).
    matcher = ConceptMatcher.from_yaml()
    tables = {2: [ReconstructedTable(n_columns=2, items=[
        LineItem("Forderungen an Kreditinstitute", [None, None], y=1),
        LineItem("a) täglich fällig", [1626.0, 5562.0], y=2),
        LineItem("", [34329.0, 39806.0], y=3),  # label-less group total
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2024, matcher=matcher,
        statement_by_page={2: "bilanz"},
    )
    fk = [f for f in facts if f.concept == "forderungen_kreditinstitute" and f.fiscal_year == 2024]
    assert fk and fk[0].value == 34329.0


def test_grand_total_not_misattributed_to_header():
    # Once a header's child resolves on its own, a later label-less total (the
    # Bilanzsumme) must NOT be attached to the header.
    matcher = ConceptMatcher.from_yaml()
    tables = {5: [ReconstructedTable(n_columns=2, items=[
        LineItem("C. Verbindlichkeiten", [None, None], y=1),
        LineItem("1. Verbindlichkeiten gegenüber Kreditinstituten", [167328.0, 124543.0], y=2),
        LineItem("", [2740484.63, 2763737.11], y=3),  # Bilanzsumme, not a Verb. total
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2023, matcher=matcher,
        statement_by_page={5: "bilanz"},
    )
    assert not any(f.concept == "verbindlichkeiten" for f in facts)


def test_emit_prior_year_can_be_disabled():
    matcher = ConceptMatcher.from_yaml()
    tables = {6: [_table([LineItem("1. Umsatzerlöse", [None, 2092019.57, 2175554.06], y=1)])]}
    facts = facts_from_tables(
        tables, company_id="C1", fiscal_year=2023, matcher=matcher, emit_prior_year=False
    )
    assert len(facts) == 1
    assert facts[0].fiscal_year == 2023
