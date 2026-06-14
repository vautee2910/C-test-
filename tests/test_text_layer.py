"""Tests for text-layer detection (the OCR gate).

Synthetic PDFs are generated at runtime with ``fitz``: a born-digital page that
carries a text layer, and a "scanned" page that is a rasterised image with no
extractable text. No binary fixtures are committed.
"""

from __future__ import annotations

from pathlib import Path

import fitz

from fsx.parsing.text_layer import (
    TextLayerStats,
    has_text_layer,
    needs_ocr,
    page_text_lengths,
    text_layer_stats,
)


# --------------------------------------------------------------------------- #
# Helpers — build digital vs. scanned-style PDFs
# --------------------------------------------------------------------------- #


def _make_text_pdf(tmp_path: Path, pages: list[str], name: str = "digital.pdf") -> Path:
    """A born-digital PDF: each page gets a block of real, selectable text."""
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), body)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def _make_scanned_pdf(tmp_path: Path, pages: list[str], name: str = "scanned.pdf") -> Path:
    """A scanned-style PDF: each page is a rasterised image, no text layer.

    The text is first rendered on a throwaway page, that page is rasterised to a
    pixmap, and the pixmap is stamped into a fresh page as an image — exactly the
    shape PyMuPDF sees for a real scan.
    """
    out = fitz.open()
    for body in pages:
        tmp = fitz.open()
        tpage = tmp.new_page()
        tpage.insert_text((72, 144), body, fontsize=18)
        pix = tpage.get_pixmap(dpi=150)
        tmp.close()

        page = out.new_page()
        page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / name
    out.save(path)
    out.close()
    return path


# --------------------------------------------------------------------------- #
# Digital PDFs are recognised as having a text layer
# --------------------------------------------------------------------------- #


def test_digital_pdf_has_text_layer(tmp_path: Path):
    pdf = _make_text_pdf(tmp_path, ["Bilanz zum 31.12.2023\nAktiva ... Passiva ..."])
    assert has_text_layer(pdf) is True
    assert needs_ocr(pdf) is False


def test_digital_pdf_stats(tmp_path: Path):
    pdf = _make_text_pdf(tmp_path, ["Gewinn- und Verlustrechnung " * 5, "Anhang " * 10])
    stats = text_layer_stats(pdf)
    assert stats.page_count == 2
    assert stats.pages_with_text == 2
    assert stats.coverage == 1.0
    assert stats.total_chars > 0
    assert stats.avg_chars_per_page > stats.min_chars_per_page


# --------------------------------------------------------------------------- #
# Scanned PDFs are recognised as needing OCR
# --------------------------------------------------------------------------- #


def test_scanned_pdf_needs_ocr(tmp_path: Path):
    pdf = _make_scanned_pdf(tmp_path, ["Bilanz zum 31.12.2023"])
    # An image-only page extracts essentially no text.
    assert page_text_lengths(pdf)[0] < 16
    assert has_text_layer(pdf) is False
    assert needs_ocr(pdf) is True


def test_scanned_pdf_stats_show_no_coverage(tmp_path: Path):
    pdf = _make_scanned_pdf(tmp_path, ["Seite eins", "Seite zwei"])
    stats = text_layer_stats(pdf)
    assert stats.page_count == 2
    assert stats.pages_with_text == 0
    assert stats.coverage == 0.0


# --------------------------------------------------------------------------- #
# Mixed and edge cases
# --------------------------------------------------------------------------- #


def test_mixed_document_below_coverage_needs_ocr(tmp_path: Path):
    """One digital page, three scanned pages -> coverage 0.25 < 0.5 -> OCR."""
    doc = fitz.open()
    # page 1: real text
    doc.new_page().insert_text((72, 72), "Lagebericht des Vorstands " * 4)
    # pages 2-4: rasterised images
    for body in ("A", "B", "C"):
        tmp = fitz.open()
        tp = tmp.new_page()
        tp.insert_text((72, 144), body, fontsize=18)
        pix = tp.get_pixmap(dpi=150)
        tmp.close()
        doc.new_page().insert_image(doc[-1].rect, pixmap=pix)
    path = tmp_path / "mixed.pdf"
    doc.save(path)
    doc.close()

    stats = text_layer_stats(path)
    assert stats.pages_with_text == 1
    assert stats.page_count == 4
    assert needs_ocr(path) is True
    # Loosening the coverage threshold flips the decision.
    assert has_text_layer(path, min_page_coverage=0.2) is True


def test_zero_page_stats_are_safe():
    """A page-less document divides by zero nowhere and counts as no text layer.

    (PyMuPDF refuses to *save* a zero-page PDF, so the empty case is exercised on
    the stats type directly — that is the branch the file-based callers hit.)
    """
    stats = TextLayerStats(
        page_count=0, pages_with_text=0, total_chars=0, min_chars_per_page=16
    )
    assert stats.coverage == 0.0
    assert stats.avg_chars_per_page == 0.0
