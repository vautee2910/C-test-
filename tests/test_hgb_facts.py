"""Level-2 fact generation tests."""

from __future__ import annotations

from fsx.extract.tables import LineItem, ReconstructedTable
from fsx.hgb.concepts import ConceptMatcher
from fsx.hgb.facts import facts_from_tables, split_period_values
from fsx.schemas import StatementType


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


def test_emit_prior_year_can_be_disabled():
    matcher = ConceptMatcher.from_yaml()
    tables = {6: [_table([LineItem("1. Umsatzerlöse", [None, 2092019.57, 2175554.06], y=1)])]}
    facts = facts_from_tables(
        tables, company_id="C1", fiscal_year=2023, matcher=matcher, emit_prior_year=False
    )
    assert len(facts) == 1
    assert facts[0].fiscal_year == 2023
