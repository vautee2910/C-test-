"""Tests for the pluggable table-extraction backends and the scorer."""

from __future__ import annotations

from pathlib import Path

import fitz

from fsx.parsing.table_backends import (
    DoclingTableExtractor,
    GeometryTableExtractor,
    flatten_cells,
    score_extraction,
)


def _statement_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((400, 80), "2023")
    page.insert_text((470, 80), "2022")
    for i, (label, cur, prior) in enumerate(
        [("Umsatzerlöse", "1.234", "1.100"), ("Materialaufwand", "5.678", "5.000")]
    ):
        y = 110 + i * 20
        page.insert_text((72, y), label)
        page.insert_text((400, y), cur)
        page.insert_text((470, y), prior)
    path = tmp_path / "stmt.pdf"
    doc.save(path)
    doc.close()
    return path


def test_geometry_backend_returns_reconstructed_cells(tmp_path: Path):
    pdf = _statement_pdf(tmp_path)
    cells = flatten_cells(GeometryTableExtractor().extract(pdf))
    assert cells[(1, "umsatzerlöse", 0)] == 1234.0
    assert cells[(1, "umsatzerlöse", 1)] == 1100.0
    assert cells[(1, "materialaufwand", 0)] == 5678.0


def test_geometry_backend_is_always_available():
    assert GeometryTableExtractor().is_available() is True


def test_docling_backend_availability_is_boolean_and_optional():
    # Optional heavy dep: must self-report without importing torch eagerly.
    assert isinstance(DoclingTableExtractor().is_available(), bool)


def test_docling_ocr_mode_reports_a_distinct_name():
    # do_ocr toggles docling's OCR stage for scans; the name must differ so a
    # scorer keeps the born-digital and OCR runs apart. Neither construction
    # imports the heavy dep (only extract() does).
    assert DoclingTableExtractor().name == "docling"
    assert DoclingTableExtractor(do_ocr=False).name == "docling"
    assert DoclingTableExtractor(do_ocr=True).name == "docling-ocr"


def test_score_counts_only_exact_cell_matches():
    truth = {(1, "a", 0): 100.0, (1, "b", 0): 200.0, (1, "c", 0): 300.0}
    extracted = {
        (1, "a", 0): 100.0,   # correct
        (1, "b", 0): 999.0,   # wrong value -> miss (precision over recall)
        (1, "d", 0): 400.0,   # spurious -> hurts precision
        # "c" missing -> hurts recall
    }
    s = score_extraction("x", extracted, truth)
    assert s.correct == 1
    assert s.expected == 3
    assert s.extracted == 3
    assert s.recall == 1 / 3
    assert s.precision == 1 / 3


def test_score_rel_tol_allows_rounding():
    truth = {(1, "a", 0): 1000.0}
    extracted = {(1, "a", 0): 1001.0}
    assert score_extraction("x", extracted, truth).correct == 0
    assert score_extraction("x", extracted, truth, rel_tol=0.01).correct == 1
