"""Geometric table-reconstruction tests.

The synthetic word lists use coordinates taken from a real two-column German
balance sheet (AKTIVA | PASSIVA). These are *realistic fixtures*, not business
logic — the reconstructor itself contains no document-specific constants.
"""

from __future__ import annotations

from fsx.extract.tables import (
    Word,
    cluster_rows,
    detect_value_columns,
    find_column_gutters,
    merge_number_fragments,
    reconstruct_tables,
)


def _w(x0, x1, y, text):
    """Word at (x0..x1) on a row whose top is y (height 10)."""
    return Word(x0=x0, y0=y, x1=x1, y1=y + 10, text=text)


# A slice of a real Bilanz: AKTIVA on the left, PASSIVA on the right, with the
# two value columns (Geschäftsjahr / Vorjahr) right-aligned in each panel.
def _bilanz_words():
    return [
        # y=261
        _w(91, 95, 261, "I."), _w(102, 238, 261, "Immaterielle"),
        _w(480, 510, 261, "2.584,00"), _w(579, 595, 261, "4,00"),
        _w(640, 644, 261, "I."), _w(651, 726, 261, "Gezeichnetes"),
        _w(1020, 1059, 261, "260.000,00"), _w(1104, 1143, 261, "260.000,00"),
        # y=282 (left has values, right is a header-only row)
        _w(89, 95, 282, "II."), _w(102, 148, 282, "Sachanlagen"),
        _w(465, 510, 282, "1.784.101,83"), _w(549, 595, 282, "1.778.628,83"),
        _w(638, 644, 282, "II."), _w(651, 713, 282, "Gewinnrücklagen"),
        # y=303/304 (panels drift by 1px but are the same visual line)
        _w(87, 95, 303, "III."), _w(102, 154, 303, "Finanzanlagen"),
        _w(471, 510, 303, "330.000,00"), _w(555, 595, 303, "330.000,00"),
        _w(643, 650, 304, "1."), _w(657, 746, 304, "andere"),
        _w(1020, 1059, 304, "910.000,00"), _w(1104, 1143, 304, "980.000,00"),
        # y=329 (left-only summary)
        _w(97, 188, 329, "Summe"),
        _w(465, 510, 329, "2.116.685,83"), _w(549, 595, 329, "2.108.632,83"),
        # y=350 (right-only summary)
        _w(645, 719, 350, "Summe"),
        _w(1013, 1059, 350, "2.014.879,12"), _w(1098, 1143, 350, "2.083.667,31"),
    ]


def test_cluster_rows_merges_drifting_baselines():
    rows = cluster_rows(_bilanz_words())
    # The 303/304 drift collapses into one visual row; 5 rows total.
    assert len(rows) == 5


def test_single_gutter_detected_between_panels():
    rows = cluster_rows(_bilanz_words())
    gutters = find_column_gutters(rows)
    assert len(gutters) == 1
    assert 595 < gutters[0] < 645  # between AKTIVA values and PASSIVA labels


def test_dash_separated_prior_column_is_not_a_panel():
    # Bank sheets put the prior-year column far right, separated by dash
    # placeholders ("-,--"). Those are not labels, so the page must stay ONE
    # panel — otherwise the prior column gets stranded and the subtotal column is
    # mistaken for the prior year.
    rows = cluster_rows([
        _w(50, 200, 100, "Kassenbestand"),
        _w(300, 400, 100, "25.982.656,30"), _w(700, 740, 100, "17.150"),
        _w(50, 200, 120, "Guthaben"),
        _w(300, 400, 120, "10.104.936,96"), _w(690, 700, 120, "-,--"),
        _w(50, 200, 140, "Forderungen"),
        _w(300, 400, 140, "221.366.433,98"), _w(690, 700, 140, "-"),
    ])
    assert find_column_gutters(rows) == []


def test_misaligned_two_up_panels_split_on_few_candidates():
    # Real two-up balance sheets often print AKTIVA and PASSIVA with a different
    # number of lines, so the sides drift and only a couple of rows carry the
    # number-then-label pair across the gutter — below the consensus floor. The
    # gutter must still be found because value columns flank it on both sides.
    rows = cluster_rows([
        # AKTIVA value cols end ~510/595; PASSIVA value cols end ~1059/1143.
        # The rightmost AKTIVA value sits at ~595 consistently, so the few
        # cross-gutter candidates cluster tightly just left of the PASSIVA labels.
        _w(90, 240, 100, "Sachanlagen"),
        _w(465, 510, 100, "1.784.101,83"), _w(549, 595, 100, "1.778.628,83"),
        _w(640, 760, 100, "Eigenkapital"),
        _w(1013, 1059, 100, "2.014.879,12"), _w(1098, 1143, 100, "2.083.667,31"),
        # Only two rows present the AKTIVA-value -> PASSIVA-label pair (the rest
        # are label-only on one side), so the consensus count is just 2.
        _w(90, 240, 120, "Finanzanlagen"),
        _w(549, 595, 120, "330.000,00"),
        _w(640, 760, 120, "Rückstellungen"),
        _w(90, 240, 140, "Umlaufvermögen"),
        _w(640, 760, 140, "Verbindlichkeiten"),
        _w(1013, 1059, 140, "900.000,00"),
    ])
    gutters = find_column_gutters(rows)
    assert len(gutters) == 1
    assert 595 < gutters[0] < 640  # between AKTIVA values and PASSIVA labels


def test_two_value_columns_of_one_panel_are_not_split():
    # A single panel with two right-aligned value columns: numbers flank the gap
    # on both sides, but that gap is number-then-number (never a candidate), so
    # it must NOT be mistaken for a panel gutter.
    rows = cluster_rows([
        _w(90, 240, 100, "Sachanlagen"),
        _w(465, 510, 100, "1.784.101,83"), _w(549, 595, 100, "1.778.628,83"),
        _w(90, 240, 120, "Finanzanlagen"),
        _w(471, 510, 120, "330.000,00"), _w(555, 595, 120, "330.000,00"),
    ])
    assert find_column_gutters(rows) == []


def test_label_to_value_gap_is_not_a_gutter():
    # A single panel: label then two right-aligned value columns. The big gap
    # between label and values must NOT be mistaken for a panel gutter.
    rows = cluster_rows([
        _w(90, 240, 100, "Sachanlagen"),
        _w(465, 510, 100, "1.784.101,83"), _w(549, 595, 100, "1.778.628,83"),
        _w(90, 200, 120, "Finanzanlagen"),
        _w(471, 510, 120, "330.000,00"), _w(555, 595, 120, "330.000,00"),
    ])
    assert find_column_gutters(rows) == []


def test_value_columns_right_edge_clustering():
    left_words = [w for w in _bilanz_words() if w.x1 <= 600]
    anchors = detect_value_columns(left_words)
    assert len(anchors) == 2
    assert anchors[0] < anchors[1]
    assert abs(anchors[0] - 510) < 5  # Geschäftsjahr column right edge
    assert abs(anchors[1] - 595) < 5  # Vorjahr column right edge


def test_reconstruct_two_panels_with_correct_values():
    tables = reconstruct_tables(_bilanz_words())
    assert len(tables) == 2
    left, right = tables

    assert left.n_columns == 2 and right.n_columns == 2

    # AKTIVA: find the Sachanlagen row and check both years.
    sach = next(it for it in left.items if "Sachanlagen" in it.label)
    assert sach.values == [1784101.83, 1778628.83]

    imm = next(it for it in left.items if "Immaterielle" in it.label)
    assert imm.values == [2584.00, 4.00]

    # PASSIVA: Gezeichnetes Kapital.
    gez = next(it for it in right.items if "Gezeichnetes" in it.label)
    assert gez.values == [260000.00, 260000.00]

    # Header-only row (Gewinnrücklagen) is kept but carries no values.
    gw = next(it for it in right.items if "Gewinnrücklagen" in it.label)
    assert not gw.has_values


def test_single_column_page_yields_one_table():
    words = [
        _w(90, 240, 100, "Umsatzerlöse"),
        _w(465, 510, 100, "1.000.000,00"), _w(549, 595, 100, "950.000,00"),
        _w(90, 240, 120, "Materialaufwand"),
        _w(465, 510, 120, "400.000,00"), _w(549, 595, 120, "380.000,00"),
    ]
    tables = reconstruct_tables(words)
    assert len(tables) == 1
    assert tables[0].n_columns == 2


def test_endash_negative_is_attached_to_number():
    # Bank GuV: "– 10 658" -> -10.658 (en dash sign + space thousands).
    row = [_w(400, 408, 100, "–"), _w(410, 420, 100, "10"), _w(421, 440, 100, "658")]
    merged = merge_number_fragments(row)
    assert len(merged) == 1
    assert merged[0].text == "-10.658"


def test_bare_integer_values_filled_into_columns():
    # Mio-€ layout: strong numbers (39.487/39.593) set the columns; bare ints
    # (14/16) right-align into them; the note ref "(2)" stays out of the values.
    words = [
        _w(50, 200, 100, "Sachanlagen"), _w(659, 678, 100, "(2)"),
        _w(725, 735, 100, "14"), _w(785, 795, 100, "16"),
        _w(50, 200, 120, "Finanzanlagen"), _w(659, 678, 120, "(3)"),
        _w(705, 735, 120, "39.487"), _w(765, 795, 120, "39.593"),
    ]
    tables = reconstruct_tables(words)
    t = tables[0]
    sach = next(it for it in t.items if "Sachanlagen" in it.label)
    assert sach.values == [14.0, 16.0]
    assert "(2)" in sach.label  # note ref not consumed as a value


def test_space_thousands_values_are_reconstructed():
    # Bank "Mio €" layout: 20.717 / 22.327 rendered with a space thousands sep.
    words = [
        _w(50, 120, 100, "Handelsbestand"),
        _w(462, 472, 100, "20"), _w(473, 491, 100, "717"),
        _w(513, 523, 100, "22"), _w(524, 542, 100, "327"),
    ]
    tables = reconstruct_tables(words)
    assert len(tables) == 1
    item = tables[0].items[0]
    assert item.label == "Handelsbestand"
    assert item.values == [20717.0, 22327.0]


def test_column_headers_named_for_clean_single_row():
    # A clean one-line header (period years) right above the body maps to the
    # value columns, so a host can name them for SQL.
    words = [
        _w(480, 510, 250, "2023"), _w(579, 609, 250, "2022"),
        _w(91, 200, 270, "Umsatzerlöse"),
        _w(465, 510, 270, "1.234,00"), _w(564, 609, 270, "1.100,00"),
        _w(91, 220, 290, "Materialaufwand"),
        _w(465, 510, 290, "5.678,00"), _w(564, 609, 290, "5.000,00"),
    ]
    table = reconstruct_tables(words)[0]
    assert table.n_columns == 2
    assert table.column_headers == ["2023", "2022"]


def test_column_headers_suppressed_for_non_period_header():
    # Naming is gated to *period* headers (the unambiguous statement case). A
    # cross-sectional breakdown (sector / category names, not years) cannot be
    # named reliably from geometry, so it stays positional ([]).
    words = [
        _w(465, 510, 250, "Insgesamt"), _w(564, 609, 250, "Männlich"),
        _w(91, 200, 270, "Beschäftigte"),
        _w(465, 510, 270, "1.234,00"), _w(564, 609, 270, "1.100,00"),
        _w(91, 220, 290, "Vollzeit"),
        _w(465, 510, 290, "5.678,00"), _w(564, 609, 290, "5.000,00"),
    ]
    table = reconstruct_tables(words)[0]
    assert table.column_headers == []
