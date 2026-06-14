"""Tests for the OCR front-stage.

The gate logic (text-layer present -> skip OCR; scanned -> OCR) is exercised with
a fake backend so it runs offline and fast. A separate, availability-guarded test
drives the real OCRmyPDF/Tesseract backend end-to-end on a synthetic scan.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from fsx.parsing.ocr import (
    OcrError,
    OcrMyPdfBackend,
    OcrOutcome,
    ensure_searchable_pdf,
)
from fsx.parsing.text_layer import has_text_layer


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_text_pdf(tmp_path: Path, body: str, name: str = "digital.pdf") -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), body)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def _make_scanned_pdf(tmp_path: Path, body: str, name: str = "scanned.pdf") -> Path:
    tmp = fitz.open()
    tp = tmp.new_page()
    tp.insert_text((72, 144), body, fontsize=18)
    pix = tp.get_pixmap(dpi=200)
    tmp.close()

    out = fitz.open()
    page = out.new_page()
    page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / name
    out.save(path)
    out.close()
    return path


class _FakeBackend:
    """Records whether OCR ran and writes a marker file as its 'output'."""

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.calls: list[tuple[Path, Path]] = []

    def is_available(self) -> bool:
        return self._available

    def ocr_to_pdf(self, src: Path, dst: Path) -> Path:
        self.calls.append((Path(src), Path(dst)))
        Path(dst).write_bytes(b"%PDF-fake-ocr-output")
        return Path(dst)


# --------------------------------------------------------------------------- #
# Gate: text layer present -> no OCR
# --------------------------------------------------------------------------- #


def test_digital_pdf_skips_ocr(tmp_path: Path):
    pdf = _make_text_pdf(tmp_path, "Bilanz zum 31.12.2023\nAktiva ... Passiva ...")
    backend = _FakeBackend()

    outcome = ensure_searchable_pdf(pdf, backend=backend)

    assert isinstance(outcome, OcrOutcome)
    assert outcome.ocr_applied is False
    assert outcome.pdf_path == pdf
    assert outcome.reason == "text-layer-present"
    assert backend.calls == []  # backend was never invoked


# --------------------------------------------------------------------------- #
# Gate: scanned -> OCR runs
# --------------------------------------------------------------------------- #


def test_scanned_pdf_triggers_ocr(tmp_path: Path):
    pdf = _make_scanned_pdf(tmp_path, "Gewinn und Verlust")
    backend = _FakeBackend()

    outcome = ensure_searchable_pdf(pdf, backend=backend)

    assert outcome.ocr_applied is True
    assert outcome.reason == "no-text-layer"
    assert outcome.pdf_path == pdf.with_suffix(".ocr.pdf")
    assert outcome.pdf_path.exists()
    assert len(backend.calls) == 1
    assert backend.calls[0][0] == pdf


def test_custom_output_path_is_honoured(tmp_path: Path):
    pdf = _make_scanned_pdf(tmp_path, "Anhang")
    backend = _FakeBackend()
    dst = tmp_path / "sub" / "searchable.pdf"

    outcome = ensure_searchable_pdf(pdf, backend=backend, output_path=dst)

    assert outcome.pdf_path == dst
    assert dst.exists()


def test_force_runs_ocr_even_with_text_layer(tmp_path: Path):
    pdf = _make_text_pdf(tmp_path, "Bilanz zum 31.12.2023 " * 4)
    backend = _FakeBackend()

    outcome = ensure_searchable_pdf(pdf, backend=backend, force=True)

    assert outcome.ocr_applied is True
    assert outcome.reason == "forced-ocr"
    assert len(backend.calls) == 1


# --------------------------------------------------------------------------- #
# Backend unavailable
# --------------------------------------------------------------------------- #


def test_unavailable_backend_on_scan_raises(tmp_path: Path):
    pdf = _make_scanned_pdf(tmp_path, "Lagebericht")
    backend = _FakeBackend(available=False)

    with pytest.raises(OcrError):
        ensure_searchable_pdf(pdf, backend=backend)


def test_unavailable_backend_with_text_layer_is_fine(tmp_path: Path):
    """A digital PDF must never need the backend, so availability is irrelevant."""
    pdf = _make_text_pdf(tmp_path, "Kapitalflussrechnung " * 5)
    backend = _FakeBackend(available=False)

    outcome = ensure_searchable_pdf(pdf, backend=backend)
    assert outcome.ocr_applied is False


# --------------------------------------------------------------------------- #
# Real end-to-end OCR (only when OCRmyPDF + Tesseract are installed)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not OcrMyPdfBackend().is_available(),
    reason="OCRmyPDF/Tesseract not installed",
)
def test_real_ocr_makes_scan_searchable(tmp_path: Path):
    phrase = "Jahresabschluss Bilanz Summe"
    pdf = _make_scanned_pdf(tmp_path, phrase, name="real_scan.pdf")
    assert has_text_layer(pdf) is False  # starts as a pure image

    outcome = ensure_searchable_pdf(pdf, backend=OcrMyPdfBackend())

    assert outcome.ocr_applied is True
    assert has_text_layer(outcome.pdf_path) is True
    # The OCR'd text layer should contain at least one of our words.
    text = "".join(p.get_text() for p in fitz.open(outcome.pdf_path)).lower()
    assert "bilanz" in text or "summe" in text or "jahresabschluss" in text
