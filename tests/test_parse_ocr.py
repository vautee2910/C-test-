"""Tests for ``parse_pdf_with_ocr``: the OCR-aware parsing entry point.

A fake OCR backend that emits a real (text) PDF lets us exercise the full
"scan -> OCR -> parse -> anonymise" wiring offline, without depending on
Tesseract here (the real engine is covered in ``test_ocr.py``).
"""

from __future__ import annotations

from pathlib import Path

import fitz

from fsx.config import build_anonymizer
from fsx.parsing import parse_pdf_with_ocr

_CONFIG = {
    "company_aliases": ["Muster Maschinenbau GmbH", "MMG"],
    "replacement_policy": {"company": "[UNTERNEHMEN_{n}]"},
}


def _anonymizer():
    return build_anonymizer(_CONFIG)


def _make_text_pdf(tmp_path: Path, body: str, name: str) -> Path:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), body)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def _make_scanned_pdf(tmp_path: Path, body: str, name: str) -> Path:
    tmp = fitz.open()
    tp = tmp.new_page()
    tp.insert_text((72, 144), body, fontsize=18)
    pix = tp.get_pixmap(dpi=150)
    tmp.close()
    out = fitz.open()
    page = out.new_page()
    page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / name
    out.save(path)
    out.close()
    return path


class _FakeOcrBackend:
    """Pretends to OCR by writing a digital PDF carrying ``text``."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[Path, Path]] = []

    def is_available(self) -> bool:
        return True

    def ocr_to_pdf(self, src: Path, dst: Path) -> Path:
        self.calls.append((Path(src), Path(dst)))
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), self.text)
        doc.save(dst)
        doc.close()
        return Path(dst)


def _block_text(raw) -> str:
    return "\n".join(b.text_anonymized for p in raw.pages for b in p.blocks)


def test_digital_pdf_parsed_without_ocr(tmp_path: Path):
    pdf = _make_text_pdf(tmp_path, "Bericht der Muster Maschinenbau GmbH", "digital.pdf")
    backend = _FakeOcrBackend("SHOULD-NOT-BE-USED")

    raw = parse_pdf_with_ocr(
        pdf,
        anonymizer=_anonymizer(),
        document_id="DOC1",
        company_id="C1",
        fiscal_year=2023,
        backend=backend,
    )

    assert backend.calls == []  # OCR skipped
    assert "[UNTERNEHMEN_1]" in _block_text(raw)
    assert raw.source_filename == "digital.pdf"


def test_scanned_pdf_is_ocred_then_parsed(tmp_path: Path):
    scan = _make_scanned_pdf(tmp_path, "Platzhalter", "scan.pdf")
    backend = _FakeOcrBackend("Anhang der Muster Maschinenbau GmbH (MMG)")

    raw = parse_pdf_with_ocr(
        scan,
        anonymizer=_anonymizer(),
        document_id="DOC1",
        company_id="C1",
        fiscal_year=2023,
        backend=backend,
    )

    # OCR ran on the scan...
    assert len(backend.calls) == 1
    assert backend.calls[0][0] == scan
    # ...the OCR'd text was parsed and anonymised...
    text = _block_text(raw)
    assert "[UNTERNEHMEN_1]" in text
    assert "Muster Maschinenbau GmbH" not in text
    # ...and provenance still points at the original scanned file.
    assert raw.source_filename == "scan.pdf"
