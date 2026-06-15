"""Anlagenspiegel reconstruction / column-mapping / fact tests.

Synthetic word lists model a real fixed-asset schedule (right-aligned movement
columns under multi-line headers); no document-specific constants in the code.
"""

from __future__ import annotations

from fsx.hgb.anlagenspiegel import (
    anlagenspiegel_facts,
    classify_column,
    reconstruct_anlagenspiegel,
)
from fsx.extract.tables import Word, merge_number_fragments
from fsx.schemas import StatementType


def _w(x0, x1, y, text):
    return Word(x0=x0, y0=y, x1=x1, y1=y + 9, text=text)


def test_merge_number_fragments_rejoins_space_thousands():
    row = [_w(732, 744, 200, "550"), _w(744, 770, 200, "415,00")]
    merged = merge_number_fragments(row)
    assert len(merged) == 1
    assert merged[0].text == "550.415,00"


def test_merge_does_not_join_distant_columns():
    row = [_w(250, 262, 200, "550"), _w(744, 770, 200, "415,00")]  # 480px apart
    assert len(merge_number_fragments(row)) == 2


def test_classify_column_keywords():
    assert classify_column("Zugänge EUR") == "zugaenge"
    assert classify_column("Abschreibung Geschäftsjahr") == "abschreibung_gj"
    assert classify_column("Buchwert Vorjahr 31.12.2020") == "buchwert_vorjahr"
    assert classify_column("Buchwert Geschäftsjahr 31.12.2021") == "buchwert_gj"
    assert classify_column("Anschaffungs- Herstellungskosten 31.12") == "ahk_ende"
    assert classify_column("Inhaltsverzeichnis") is None


def _anlagenspiegel_words():
    # Header band (110 < cy < 172): four movement columns.
    h = [
        _w(285, 320, 135, "Zugänge"),
        _w(480, 540, 135, "Abschreibung"), _w(480, 545, 146, "Geschäftsjahr"),
        _w(685, 735, 135, "Buchwert"), _w(685, 740, 146, "Geschäftsjahr"),
        _w(785, 835, 135, "Buchwert"), _w(790, 835, 146, "Vorjahr"),
    ]
    # Data rows: right-aligned values under each column.
    d = [
        _w(50, 120, 200, "Sachanlagen"),
        _w(270, 310, 200, "215.116,06"), _w(470, 510, 200, "195.400,06"),
        _w(670, 710, 200, "525.217,00"), _w(770, 810, 200, "505.501,00"),
        _w(50, 120, 220, "Summe"),
        _w(270, 310, 220, "489.606,35"), _w(470, 510, 220, "315.860,49"),
        _w(670, 710, 220, "1.102.432,00"), _w(770, 810, 220, "928.686,14"),
    ]
    return h + d


def test_reconstruct_maps_movement_columns():
    asp = reconstruct_anlagenspiegel(_anlagenspiegel_words())
    movements = [c.movement for c in asp.columns]
    assert movements == ["zugaenge", "abschreibung_gj", "buchwert_gj", "buchwert_vorjahr"]


def test_facts_emitted_with_book_value_time_series():
    asp = reconstruct_anlagenspiegel(_anlagenspiegel_words())
    facts = anlagenspiegel_facts(asp, company_id="C1", fiscal_year=2021, source_page=6)

    assert all(f.statement == StatementType.ANLAGENSPIEGEL for f in facts)

    sach = [f for f in facts if f.line_item_original_anonymized == "Sachanlagen"]
    by_concept = {(f.concept, f.fiscal_year): f.value for f in sach}
    assert by_concept[("zugaenge", 2021)] == 215116.06
    assert by_concept[("abschreibung_gj", 2021)] == 195400.06
    # Closing book value forms a 2-year series from the GJ/Vorjahr columns.
    assert by_concept[("buchwert_ende", 2021)] == 525217.00
    assert by_concept[("buchwert_ende", 2020)] == 505501.00
