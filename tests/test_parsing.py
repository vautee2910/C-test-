"""Tests for the PyMuPDF parsing adapter.

Synthetic PDFs are generated at runtime with ``fitz`` into ``tmp_path`` so no
binary fixtures are committed. The anonymiser is built from a small in-test
config dict, mirroring what the real engagement config would supply.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from fsx.config import build_anonymizer
from fsx.parsing import PyMuPDFParser, parse_pdf
from fsx.parsing.pymupdf_parser import _anonymize_cells
from fsx.schemas import BlockType, RawDocument


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_CONFIG = {
    "company_aliases": ["Muster Maschinenbau GmbH", "MMG"],
    "replacement_policy": {"company": "[UNTERNEHMEN_{n}]"},
}


def _make_anonymizer():
    return build_anonymizer(_CONFIG)


def _make_pdf(tmp_path: Path, pages: list[list[tuple[float, float, str]]]) -> Path:
    """Write a PDF where each page is a list of ``(x, y, text)`` insertions."""
    doc = fitz.open()
    for items in pages:
        page = doc.new_page()
        for x, y, text in items:
            page.insert_text((x, y), text)
    path = tmp_path / "synthetic.pdf"
    doc.save(path)
    doc.close()
    return path


def _all_block_text(raw: RawDocument) -> str:
    return "\n".join(
        block.text_anonymized for page in raw.pages for block in page.blocks
    )


# --------------------------------------------------------------------------- #
# Anonymisation of block text
# --------------------------------------------------------------------------- #


def test_block_text_is_anonymised(tmp_path: Path):
    company = "Muster Maschinenbau GmbH"
    iban = "DE89 3704 0044 0532 0130 00"
    email = "info@example.com"
    line = f"{company} IBAN {iban} Kontakt {email}"
    pdf = _make_pdf(tmp_path, [[(72, 72, line)]])

    raw = parse_pdf(
        pdf,
        anonymizer=_make_anonymizer(),
        document_id="DOC1",
        company_id="C1",
        fiscal_year=2023,
    )

    text = _all_block_text(raw)

    # Pseudonym tokens are present...
    assert "[UNTERNEHMEN_1]" in text
    assert "[IBAN_1]" in text
    assert "[EMAIL_1]" in text
    # ...and the originals are gone.
    assert company not in text
    assert iban not in text
    assert email not in text


def test_pages_and_bbox_populated_and_empty_blocks_skipped(tmp_path: Path):
    pdf = _make_pdf(
        tmp_path,
        [
            [(72, 72, "Bilanz zum 31.12.2023")],
            [(72, 72, "Gewinn- und Verlustrechnung")],
        ],
    )

    raw = parse_pdf(
        pdf,
        anonymizer=_make_anonymizer(),
        document_id="DOC1",
        company_id="C1",
        fiscal_year=2023,
    )

    assert [p.page for p in raw.pages] == [1, 2]
    # Every emitted block has a 4-tuple bbox and non-empty text.
    for page in raw.pages:
        assert page.blocks  # no all-empty pages here
        for block in page.blocks:
            assert block.type is BlockType.TEXT
            assert block.bbox is not None
            assert len(block.bbox) == 4
            assert block.text_anonymized.strip()


def test_empty_page_yields_no_blocks(tmp_path: Path):
    doc = fitz.open()
    doc.new_page()  # entirely blank page
    path = tmp_path / "blank.pdf"
    doc.save(path)
    doc.close()

    raw = parse_pdf(
        path,
        anonymizer=_make_anonymizer(),
        document_id="DOC1",
        company_id="C1",
        fiscal_year=2023,
    )
    assert len(raw.pages) == 1
    assert raw.pages[0].blocks == []


def test_source_filename_defaults_to_path_name(tmp_path: Path):
    pdf = _make_pdf(tmp_path, [[(72, 72, "Anhang")]])
    raw = parse_pdf(
        pdf,
        anonymizer=_make_anonymizer(),
        document_id="DOC1",
        company_id="C1",
        fiscal_year=2023,
    )
    assert raw.source_filename == "synthetic.pdf"


# --------------------------------------------------------------------------- #
# Table-cell helper (deterministic, no find_tables() reliance)
# --------------------------------------------------------------------------- #


def test_anonymize_cells_replaces_none_and_anonymises():
    anonymizer = _make_anonymizer()
    rows = [
        ["Position", "Muster Maschinenbau GmbH", None],
        [None, "info@example.com", "Summe"],
    ]

    grid = _anonymize_cells(rows, anonymizer)

    assert grid[0][0] == "Position"
    assert grid[0][1] == "[UNTERNEHMEN_1]"
    assert grid[0][2] == ""  # None -> ""
    assert grid[1][0] == ""  # None -> ""
    assert grid[1][1] == "[EMAIL_1]"
    assert grid[1][2] == "Summe"


def test_table_mapping_via_fake_table():
    """Exercise PyMuPDFParser._parse_tables with a fake find_tables() result."""

    class _FakeTable:
        bbox = (10.0, 20.0, 110.0, 220.0)

        def extract(self):
            return [["MMG", None], ["Umsatz", "1000"]]

    class _FakeFinder:
        tables = [_FakeTable()]

    class _FakePage:
        def find_tables(self):
            return _FakeFinder()

    parser = PyMuPDFParser(_make_anonymizer())
    tables = parser._parse_tables(_FakePage(), page_no=3)

    assert len(tables) == 1
    t = tables[0]
    assert t.table_id == "T_3_01"
    assert t.caption_anonymized is None
    assert t.bbox == (10.0, 20.0, 110.0, 220.0)
    assert t.cells == [["[UNTERNEHMEN_1]", ""], ["Umsatz", "1000"]]


def test_geometry_reconstruction_is_primary_table_source(tmp_path: Path):
    # The geometry reconstruction recovers a structured row x value-column grid
    # (and keeps numeric values verbatim, never anonymised), so RawDocument
    # tables are queryable — unlike find_tables() on dense statement layouts.
    # Equal-width, right-aligned figures (as in a real statement) so the value
    # column is detected geometrically.
    pdf = _make_pdf(
        tmp_path,
        [[
            (72, 100, "Umsatzerlöse"), (400, 100, "1.234"),
            (72, 120, "Materialaufwand"), (400, 120, "5.678"),
        ]],
    )
    raw = parse_pdf(
        pdf, anonymizer=_make_anonymizer(),
        document_id="D", company_id="C", fiscal_year=2023,
    )
    tables = raw.pages[0].tables
    assert tables, "geometry reconstruction should produce a table"
    rows = {r[0]: r[1:] for t in tables for r in t.cells}
    assert rows["Umsatzerlöse"] == ["1234"]
    assert rows["Materialaufwand"] == ["5678"]


# --------------------------------------------------------------------------- #
# Cross-page consistency
# --------------------------------------------------------------------------- #


def test_same_company_collapses_to_one_token_across_pages(tmp_path: Path):
    pdf = _make_pdf(
        tmp_path,
        [
            [(72, 72, "Bericht der Muster Maschinenbau GmbH")],
            [(72, 72, "Anhang der MMG zum Geschaeftsjahr")],
        ],
    )

    raw = parse_pdf(
        pdf,
        anonymizer=_make_anonymizer(),
        document_id="DOC1",
        company_id="C1",
        fiscal_year=2023,
    )

    text = _all_block_text(raw)
    # Both aliases map to the same single token, and no [UNTERNEHMEN_2] appears.
    assert "[UNTERNEHMEN_1]" in text
    assert "[UNTERNEHMEN_2]" not in text
    assert "Muster Maschinenbau GmbH" not in text
    assert "MMG" not in text
    # Token appears on both pages.
    page1_text = " ".join(b.text_anonymized for b in raw.pages[0].blocks)
    page2_text = " ".join(b.text_anonymized for b in raw.pages[1].blocks)
    assert "[UNTERNEHMEN_1]" in page1_text
    assert "[UNTERNEHMEN_1]" in page2_text
