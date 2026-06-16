"""Level-2 fact generation tests."""

from __future__ import annotations

import pytest

from fsx.extract.tables import LineItem, ReconstructedTable
from fsx.hgb.concepts import ConceptMatcher
from fsx.hgb.facts import (
    detect_has_prior_year,
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


def test_detect_statement_bare_aktiva_passiva_band_is_bilanz():
    # Small-entity balance sheets set the AKTIVA/PASSIVA band larger than the
    # "Bilanz zum …" title, so the dominant heading is just the band.
    assert detect_statement("AKTIVA") == "bilanz"
    assert detect_statement("PASSIVA  EUR  EUR") == "bilanz"
    assert detect_statement("AKTIVA PASSIVA") == "bilanz"


def test_detect_statement_guv_survives_ocr_dropped_und():
    # OCR font jitter can drop the small "und" span from "GEWINN- UND
    # VERLUSTRECHNUNG"; the GuV-specific "verlustrechnung" title still matches.
    assert detect_statement("GEWINN- VERLUSTRECHNUNG Geschäftsjahr Vorjahr") == "guv"


def test_dominant_heading_ignores_oversized_ocr_artifact():
    # A scanned page can carry a stray oversized "_" (a rule the OCR rendered as a
    # large glyph). It must not mask the real, smaller statement title.
    import fitz

    from fsx.hgb.facts import _dominant_heading

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Gewinn- und Verlustrechnung", fontsize=11)
    page.insert_text((72, 200), "_", fontsize=20)  # larger, but not a heading
    heading = _dominant_heading(page)
    doc.close()
    assert "Verlustrechnung" in heading
    assert detect_statement(heading) == "guv"


def test_detect_scale():
    assert detect_scale("Aktiva in Millionen €") == 1_000_000
    assert detect_scale("Mio. €  2025  2024") == 1_000_000
    assert detect_scale("Angaben in T€") == 1_000
    assert detect_scale("in Tausend Euro") == 1_000
    assert detect_scale("(30) Eigenkapital €  31.12.2025") == 1


def test_detect_period_scales_uniform_and_asymmetric():
    from fsx.hgb.facts import detect_period_scales
    # Uniform: both columns share the scale.
    assert detect_period_scales("Aktiva in Millionen €", 2025) == (1_000_000, 1_000_000)
    assert detect_period_scales("EUR EUR  2.740.484,63", 2025) == (1, 1)
    assert detect_period_scales("in Tausend Euro  1.234,5", 2025) == (1_000, 1_000)
    # Asymmetric bank sheet: current in full euro, prior in Tsd. EUR.
    bank = "Aktivseite  Euro Euro Euro  Tsd. EUR  25.982.656,30  17.150"
    assert detect_period_scales(bank, 2024) == (1, 1_000)


def test_prior_year_scale_can_differ_from_current():
    matcher = ConceptMatcher.from_yaml()
    tables = {3: [_table([LineItem("II. Sachanlagen", [None, 1000.0, 50.0], y=1)])]}
    facts = facts_from_tables(
        tables, company_id="C1", fiscal_year=2025, matcher=matcher,
        statement_by_page={3: "bilanz"}, scale_by_page={3: 1}, prior_scale_by_page={3: 1000},
    )
    cur = next(f for f in facts if f.fiscal_year == 2025)
    prev = next(f for f in facts if f.fiscal_year == 2024)
    assert cur.scale == 1 and prev.scale == 1000


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


def test_split_period_values_single_period_rightmost_is_current():
    # Single-period "EUR EUR" (sub-amount/total) layout, no prior column.
    assert split_period_values([None, 349216.83], has_prior=False) == (349216.83, None)
    assert split_period_values([100.0, 349216.83], has_prior=False) == (349216.83, None)


def test_detect_has_prior_year():
    assert detect_has_prior_year("Geschäftsjahr Vorjahr EUR EUR", 2024) is True
    assert detect_has_prior_year("zum 31.12.2025 31.12.2024", 2025) is True  # prior present
    assert detect_has_prior_year("vom 01.01.2024 bis 31.12.2024 EUR EUR", 2024) is False


def test_kontennachweis_heading_is_not_a_summary_statement():
    # Account-detail pages get their own key so no concepts match them.
    assert detect_statement("KONTENNACHWEIS zur Bilanz zum 31.12.2024") == "kontennachweis"
    assert detect_statement("Kontennachweis zur G.u.V.") == "kontennachweis"


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


def test_hyphenated_wrapped_label_is_dehyphenated():
    # German line break: "... Leis-" / "tungen" must rejoin to "Leistungen".
    matcher = ConceptMatcher.from_yaml()
    tables = {9: [_table([
        LineItem("1. Forderungen aus Lieferungen und Leis-", [None, None, None], y=1),
        LineItem("tungen", [130694.29, None, None], y=2),
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2024, matcher=matcher,
        statement_by_page={9: "bilanz"}, has_prior_by_page={9: False},
    )
    cur = next(f for f in facts if f.fiscal_year == 2024)
    assert cur.concept == "forderungen_lul"
    assert cur.value == 130694.29


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


def test_bestandsveraenderung_verminderung_is_negative():
    # A "Verminderung des Bestandes" (decrease) reduces output -> negative; the
    # group total arrives on a label-less subtotal row under the header.
    matcher = ConceptMatcher.from_yaml()
    tables = {5: [ReconstructedTable(n_columns=3, items=[
        LineItem("Verminderung des Bestandes an fertigen und unfertigen Erzeugnissen",
                 [None, None, None], y=1),
        LineItem("", [476971.19, None, 27519.18], y=2),
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2024, matcher=matcher,
        statement_by_page={5: "guv"},
    )
    cur = next(f for f in facts if f.fiscal_year == 2024 and f.concept == "bestandsveraenderung")
    assert cur.value == pytest.approx(-476971.19)


def test_bestandsveraenderung_erhoehung_stays_positive():
    matcher = ConceptMatcher.from_yaml()
    tables = {5: [ReconstructedTable(n_columns=3, items=[
        LineItem("Erhöhung des Bestandes an fertigen und unfertigen Erzeugnissen",
                 [None, None, None], y=1),
        LineItem("", [12000.0, None, 8000.0], y=2),
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2024, matcher=matcher,
        statement_by_page={5: "guv"},
    )
    cur = next(f for f in facts if f.fiscal_year == 2024 and f.concept == "bestandsveraenderung")
    assert cur.value == pytest.approx(12000.0)


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


def test_carryforward_uebertrag_rows_are_skipped():
    # A balance sheet that spills across pages repeats a running "Übertrag"
    # total; it must never be emitted as a fact (here it would otherwise mis-bind
    # the value to the preceding Rückstellungen header).
    matcher = ConceptMatcher.from_yaml()
    tables = {9: [ReconstructedTable(n_columns=2, items=[
        LineItem("1. Steuerrückstellungen", [49424.05, None], y=1),
        LineItem("Übertrag", [None, 166044.66], y=2),
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2024, matcher=matcher,
        statement_by_page={9: "bilanz"}, has_prior_by_page={9: False},
    )
    assert all(f.value != 166044.66 for f in facts)
    assert any(f.concept == "steuerrueckstellungen" for f in facts)


def test_stacked_aktiva_passiva_band_switches_section():
    # AKTIVA stacked above PASSIVA in one column: an explicit band row must
    # re-point the active section so each side matches in its own context.
    matcher = ConceptMatcher.from_yaml()
    tables = {9: [ReconstructedTable(n_columns=1, items=[
        LineItem("AKTIVA", [None], y=1),
        LineItem("II. Sachanlagen", [3264.0], y=2),
        LineItem("PASSIVA", [None], y=3),
        LineItem("1. Steuerrückstellungen", [49424.05], y=4),
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2024, matcher=matcher,
        statement_by_page={9: "bilanz"}, has_prior_by_page={9: False},
    )
    by_concept = {f.concept: f for f in facts}
    assert by_concept["sachanlagen"].section == "aktiva"
    assert by_concept["steuerrueckstellungen"].section == "passiva"


def test_multi_subgroup_parent_subtotal_is_suppressed():
    # "7. sonstige betriebliche Aufwendungen" is split into a) Raumkosten,
    # b) Versicherungen, ... each with its own subtotal and no printed grand
    # total. The first sub-group's subtotal must NOT be emitted as the parent.
    matcher = ConceptMatcher.from_yaml()
    tables = {16: [ReconstructedTable(n_columns=3, items=[
        LineItem("7. sonstige betriebliche Aufwendungen", [None, None, None], y=1),
        LineItem("a) Raumkosten", [None, None, None], y=2),
        LineItem("4210 Miete", [15922.5, None, 11910.0], y=3),
        LineItem("", [20991.84, None, 15704.19], y=4),
        LineItem("b) Versicherungen, Beiträge und Abgaben", [None, None, None], y=5),
        LineItem("4360 Versicherungen", [2582.18, None, 1998.24], y=6),
        LineItem("", [16800.25, None, 7929.92], y=7),
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2024, matcher=matcher,
        statement_by_page={16: "guv"},
    )
    assert all(f.concept != "sonstige_betriebliche_aufwendungen" for f in facts)


def test_single_subgroup_parent_subtotal_is_kept():
    # "6. Abschreibungen" has a single sub-group a) -> its subtotal IS the total.
    matcher = ConceptMatcher.from_yaml()
    tables = {16: [ReconstructedTable(n_columns=3, items=[
        LineItem("6. Abschreibungen", [None, None, None], y=1),
        LineItem("a) auf immaterielle Vermögensgegenstände des", [None, None, None], y=2),
        LineItem("Anlagevermögens und Sachanlagen", [None, None, None], y=3),
        LineItem("4830 Abschreibungen auf Sachanlagen", [3682.99, None, 9491.48], y=4),
        LineItem("", [7516.95, None, 9857.48], y=5),
        LineItem("7. sonstige betriebliche Aufwendungen", [None, None, None], y=6),
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2024, matcher=matcher,
        statement_by_page={16: "guv"},
    )
    cur = next(f for f in facts if f.concept == "abschreibungen" and f.fiscal_year == 2024)
    assert cur.value == pytest.approx(7516.95)


def test_fact_ids_are_deterministic_and_unique():
    matcher = ConceptMatcher.from_yaml()
    tables = {5: [_table([
        LineItem("II. Sachanlagen", [None, 1784101.83, 1778628.83], y=1),
        LineItem("III. Finanzanlagen", [None, 39487.0, 39593.0], y=2),
    ])]}
    a = facts_from_tables(tables, company_id="C1", fiscal_year=2023, matcher=matcher)
    b = facts_from_tables(tables, company_id="C1", fiscal_year=2023, matcher=matcher)
    # Re-running the same input yields byte-identical ids (no run-order counter).
    assert [f.fact_id for f in a] == [f.fact_id for f in b]
    # Distinct facts have distinct ids.
    assert len({f.fact_id for f in a}) == len(a)


def test_fact_id_is_stable_when_only_the_value_changes():
    # A re-extraction that corrects a digit keeps the same id, so the host engine
    # upserts (updates) the row instead of inserting a duplicate.
    matcher = ConceptMatcher.from_yaml()
    t1 = {5: [_table([LineItem("II. Sachanlagen", [None, 1784101.83, 1778628.83], y=1)])]}
    t2 = {5: [_table([LineItem("II. Sachanlagen", [None, 1784101.99, 1778628.83], y=1)])]}
    cur1 = next(f for f in facts_from_tables(t1, company_id="C1", fiscal_year=2023, matcher=matcher)
                if f.fiscal_year == 2023)
    cur2 = next(f for f in facts_from_tables(t2, company_id="C1", fiscal_year=2023, matcher=matcher)
                if f.fiscal_year == 2023)
    assert cur1.fact_id == cur2.fact_id
    assert cur1.value != cur2.value


def test_sonderposten_passiva_is_captured():
    # Subsidized/public entities (e.g. NOW GmbH) carry "Sonderposten aus
    # Zuschüssen für Investitionen" between equity and liabilities; without it the
    # balance sheet does not add up.
    matcher = ConceptMatcher.from_yaml()
    tables = {5: [ReconstructedTable(n_columns=2, items=[
        LineItem("B. Sonderposten aus Zuschüssen für", [None, None], y=1),
        LineItem("Investitionen", [1102432.0, 0.0], y=2),
    ])]}
    facts = facts_from_tables(
        tables, company_id="C", fiscal_year=2021, matcher=matcher,
        statement_by_page={5: "bilanz"},
    )
    cur = next(f for f in facts if f.fiscal_year == 2021)
    assert cur.concept == "sonderposten"
    assert cur.value == pytest.approx(1102432.0)


def test_emit_prior_year_can_be_disabled():
    matcher = ConceptMatcher.from_yaml()
    tables = {6: [_table([LineItem("1. Umsatzerlöse", [None, 2092019.57, 2175554.06], y=1)])]}
    facts = facts_from_tables(
        tables, company_id="C1", fiscal_year=2023, matcher=matcher, emit_prior_year=False
    )
    assert len(facts) == 1
    assert facts[0].fiscal_year == 2023


def test_wide_statistics_matrix_panel_is_suppressed():
    # A cross-sectional statistics matrix (e.g. a Destatis Jahrbuch table broken
    # down by Wirtschaftsbereich) has many value columns and no current/prior
    # period structure. There is no unambiguous "value" column, so the whole
    # panel must be suppressed rather than emitting an arbitrary column as a fact
    # (precision over recall). Mirrors the real 6-column Jahrbuch chapter 9.4.
    matcher = ConceptMatcher.from_yaml()
    tables = {278: [ReconstructedTable(n_columns=6, items=[
        LineItem("Anlagevermögen", [1093098.0, 162152.0, 41408.0, 72398.0, 122269.0, 153421.0], y=1),
        LineItem("Sachanlagen", [559232.0, 153001.0, 37486.0, 69314.0, 65913.0, 28351.0], y=2),
        LineItem("Umsatzerlöse", [440021.0, 28500.0, 9652.0, 10675.0, 157505.0, 17601.0], y=3),
    ])]}
    facts = facts_from_tables(tables, company_id="JB", fiscal_year=2019, matcher=matcher)
    assert facts == []


def test_three_column_statement_panel_still_emits():
    # A guard at >= 4 value columns must not touch ordinary statements, including
    # a current/prior/change three-column layout — those remain extractable.
    matcher = ConceptMatcher.from_yaml()
    tables = {5: [ReconstructedTable(n_columns=3, items=[
        LineItem("II. Sachanlagen", [None, 1784101.83, 1778628.83], y=1),
    ])]}
    facts = facts_from_tables(tables, company_id="C1", fiscal_year=2023, matcher=matcher)
    assert {f.concept for f in facts} == {"sachanlagen"}
