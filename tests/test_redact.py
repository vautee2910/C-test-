"""Tests for the anonymised-PDF writer (redaction + metadata scrub)."""

from __future__ import annotations

from pathlib import Path

import fitz

from fsx.config import build_anonymizer
from fsx.parsing.redact import write_anonymized_pdf

_CONFIG = {
    "company_aliases": ["Muster Maschinenbau GmbH"],
    "replacement_policy": {"company": "[UNTERNEHMEN_{n}]"},
}


def _make_pdf(tmp_path: Path, lines: list[tuple[float, float, str]], *, metadata=None) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=11)
    if metadata:
        doc.set_metadata(metadata)
    path = tmp_path / "in.pdf"
    doc.save(path)
    doc.close()
    return path


def test_pii_text_is_removed_and_replaced_by_token(tmp_path: Path):
    src = _make_pdf(tmp_path, [
        (72, 100, "Rechnung an Muster Maschinenbau GmbH"),
        (72, 130, "Umsatzerloese 1.234,00"),
    ])
    dst = tmp_path / "out.pdf"
    summary = write_anonymized_pdf(src, dst, anonymizer=build_anonymizer(_CONFIG), use_models=False)

    doc = fitz.open(dst)
    text = "\n".join(p.get_text("text") for p in doc)
    # original PII text genuinely gone; token in its place; figures untouched.
    assert "Muster Maschinenbau GmbH" not in text
    assert "[UNTERNEHMEN_1]" in text
    assert "1.234,00" in text
    assert summary.boxes >= 1
    assert summary.entities >= 1


def test_layout_is_preserved(tmp_path: Path):
    src = _make_pdf(tmp_path, [(72, 100, "Muster Maschinenbau GmbH")])
    dst = tmp_path / "out.pdf"
    write_anonymized_pdf(src, dst, anonymizer=build_anonymizer(_CONFIG), use_models=False)
    orig, red = fitz.open(src), fitz.open(dst)
    assert orig.page_count == red.page_count
    assert tuple(round(c) for c in orig[0].rect) == tuple(round(c) for c in red[0].rect)


def test_metadata_is_scrubbed(tmp_path: Path):
    src = _make_pdf(
        tmp_path, [(72, 100, "Muster Maschinenbau GmbH")],
        metadata={"author": "Ursel Beckmann", "title": "internal-123", "producer": "X"},
    )
    dst = tmp_path / "out.pdf"
    summary = write_anonymized_pdf(src, dst, anonymizer=build_anonymizer(_CONFIG), use_models=False)
    red = fitz.open(dst)
    assert not red.metadata.get("author")
    assert not red.metadata.get("title")
    assert red.get_xml_metadata() == ""
    assert summary.metadata_scrubbed is True


def test_metadata_kept_when_scrub_disabled(tmp_path: Path):
    src = _make_pdf(
        tmp_path, [(72, 100, "Muster Maschinenbau GmbH")],
        metadata={"author": "Ursel Beckmann"},
    )
    dst = tmp_path / "out.pdf"
    write_anonymized_pdf(
        src, dst, anonymizer=build_anonymizer(_CONFIG), use_models=False, scrub_metadata=False
    )
    assert fitz.open(dst).metadata.get("author") == "Ursel Beckmann"


def test_parse_pdf_emits_redacted_copy(tmp_path: Path):
    # The pipeline writes the anonymised PDF as a side output, reusing the same
    # anonymiser so the RawDocument and the PDF carry the same token.
    import fitz
    from fsx.parsing import parse_pdf

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Kunde: Muster Maschinenbau GmbH", fontsize=11)
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()

    out = tmp_path / "redacted.pdf"
    anon = build_anonymizer(_CONFIG)
    raw = parse_pdf(
        src, anonymizer=anon, document_id="d", company_id="c", fiscal_year=2024,
        redacted_pdf_path=out,
    )
    assert out.exists()
    pdf_text = "\n".join(p.get_text("text") for p in fitz.open(out))
    assert "Muster Maschinenbau GmbH" not in pdf_text
    assert "[UNTERNEHMEN_1]" in pdf_text
    # same token as the Level-1 RawDocument
    raw_text = " ".join(b.text_anonymized for pg in raw.pages for b in pg.blocks)
    assert "[UNTERNEHMEN_1]" in raw_text


def test_short_surface_does_not_redact_inside_longer_word(tmp_path: Path):
    # A short/mis-detected surface ("Jah") must not blank the inside of
    # "Jahresabschluss" — redaction matches whole words, not substrings.
    cfg = {"company_aliases": ["Jah"], "replacement_policy": {"company": "[X_{n}]"}}
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Jah und der Jahresabschluss 2024", fontsize=11)
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()
    dst = tmp_path / "out.pdf"
    write_anonymized_pdf(src, dst, anonymizer=build_anonymizer(cfg), use_models=False)
    text = fitz.open(dst)[0].get_text("text")
    assert "Jahresabschluss" in text   # the long word is untouched
    assert "[X_1]" in text             # the standalone short word is redacted


def test_multiword_surface_redacted_as_one_run(tmp_path: Path):
    cfg = {"people": ["Max Mustermann"], "replacement_policy": {"person": "[PERSON_{n}]"}}
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Sachbearbeiter Max Mustermann hat geprueft", fontsize=11)
    src = tmp_path / "in.pdf"
    doc.save(src)
    doc.close()
    dst = tmp_path / "out.pdf"
    write_anonymized_pdf(src, dst, anonymizer=build_anonymizer(cfg), use_models=False)
    text = fitz.open(dst)[0].get_text("text")
    assert "Mustermann" not in text and "Max " not in text
    assert "[PERSON_1]" in text
