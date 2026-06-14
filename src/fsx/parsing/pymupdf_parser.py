"""PyMuPDF (``fitz``) parsing adapter producing a Level-1 ``RawDocument``.

This backend opens a PDF, walks every page, and extracts:

* **text blocks** via ``page.get_text("blocks")`` — each block is a tuple
  ``(x0, y0, x1, y1, text, block_no, block_type)``;
* **tables** via ``page.find_tables()`` — each found table exposes
  ``.extract()`` (a row-major grid of ``str | None``) and ``.bbox``.

Every piece of human-readable text — block text and table cells alike — is run
through the **same** :class:`~fsx.anonymize.engine.Anonymizer` instance so that
pseudonyms stay consistent across the whole document (one company collapses to
one ``[UNTERNEHMEN_n]`` token regardless of which page it appears on). The raw,
non-anonymised text never enters the resulting :class:`RawDocument`.

The caller owns the ``Anonymizer`` (built from the engagement config); this
adapter uses the passed-in instance directly so consistency holds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

import fitz

from ..anonymize.engine import Anonymizer
from ..schemas import BBox, BlockType, Page, RawDocument, Table, TextBlock


class _TableLike(Protocol):
    """Structural type for the tables returned by ``page.find_tables()``.

    Declared so the cell-anonymisation helper can be unit-tested with a small
    fake instead of a real PyMuPDF table object.
    """

    bbox: Any

    def extract(self) -> list[list[Optional[str]]]:  # pragma: no cover - protocol
        ...


def _anonymize_cells(
    rows: Iterable[Iterable[Optional[str]]],
    anonymizer: Anonymizer,
) -> list[list[str]]:
    """Anonymise a row-major grid of (possibly ``None``) cell strings.

    ``None`` cells become empty strings; every non-empty string is passed
    through ``anonymizer`` so pseudonyms stay consistent with the rest of the
    document. Factored out so table mapping can be tested without a real PDF.
    """
    grid: list[list[str]] = []
    for row in rows:
        out_row: list[str] = []
        for cell in row:
            if cell is None:
                out_row.append("")
            else:
                out_row.append(anonymizer.anonymize(cell).text)
        grid.append(out_row)
    return grid


def _bbox_of(raw: Any) -> Optional[BBox]:
    """Coerce a 4-tuple / ``fitz.Rect``-like object into a ``BBox`` or ``None``."""
    if raw is None:
        return None
    x0, y0, x1, y1 = raw[0], raw[1], raw[2], raw[3]
    return (float(x0), float(y0), float(x1), float(y1))


class PyMuPDFParser:
    """Parse a PDF into an anonymised Level-1 :class:`RawDocument` using fitz."""

    def __init__(self, anonymizer: Anonymizer) -> None:
        self.anonymizer = anonymizer

    def _parse_blocks(self, page: Any) -> list[TextBlock]:
        blocks: list[TextBlock] = []
        for raw in page.get_text("blocks"):
            x0, y0, x1, y1, text = raw[0], raw[1], raw[2], raw[3], raw[4]
            text = text.rstrip("\n")
            if not text.strip():
                continue
            anonymized = self.anonymizer.anonymize(text).text
            blocks.append(
                TextBlock(
                    type=BlockType.TEXT,
                    text_anonymized=anonymized,
                    bbox=(float(x0), float(y0), float(x1), float(y1)),
                )
            )
        return blocks

    def _parse_tables(self, page: Any, page_no: int) -> list[Table]:
        tables: list[Table] = []
        found = page.find_tables()
        # find_tables() returns a TableFinder; the tables live on .tables.
        table_objs = getattr(found, "tables", found)
        for i, table in enumerate(table_objs, start=1):
            cells = _anonymize_cells(table.extract(), self.anonymizer)
            tables.append(
                Table(
                    table_id=f"T_{page_no}_{i:02d}",
                    caption_anonymized=None,
                    cells=cells,
                    bbox=_bbox_of(getattr(table, "bbox", None)),
                )
            )
        return tables

    def parse(
        self,
        path: str | Path,
        *,
        document_id: str,
        company_id: str,
        fiscal_year: int,
        source_filename: str | None = None,
    ) -> RawDocument:
        """Open ``path`` and return its fully anonymised :class:`RawDocument`."""
        path = Path(path)
        pages: list[Page] = []
        with fitz.open(path) as doc:
            for index, page in enumerate(doc, start=1):
                pages.append(
                    Page(
                        page=index,
                        blocks=self._parse_blocks(page),
                        tables=self._parse_tables(page, index),
                    )
                )
        return RawDocument(
            document_id=document_id,
            company_id=company_id,
            fiscal_year=fiscal_year,
            source_filename=source_filename if source_filename is not None else path.name,
            pages=pages,
        )


def parse_pdf(
    path: str | Path,
    *,
    anonymizer: Anonymizer,
    document_id: str,
    company_id: str,
    fiscal_year: int,
    source_filename: str | None = None,
) -> RawDocument:
    """Parse a PDF into an anonymised Level-1 :class:`RawDocument`.

    The caller builds and owns ``anonymizer`` (typically from the engagement
    config); the passed-in instance is used directly so its token counters and
    entity→token mapping stay shared across every block and table of the
    document. ``source_filename`` defaults to the file's name when omitted.
    """
    return PyMuPDFParser(anonymizer).parse(
        path,
        document_id=document_id,
        company_id=company_id,
        fiscal_year=fiscal_year,
        source_filename=source_filename,
    )


def parse_pdf_with_ocr(
    path: str | Path,
    *,
    anonymizer: Anonymizer,
    document_id: str,
    company_id: str,
    fiscal_year: int,
    source_filename: str | None = None,
    backend: "Any | None" = None,
    force_ocr: bool = False,
    ocr_output_path: str | Path | None = None,
) -> RawDocument:
    """Parse a PDF, transparently OCR-ing it first **if** it is a scan.

    A born-digital statement already has a text layer, so it is parsed directly
    with no OCR (see :func:`fsx.parsing.ocr.ensure_searchable_pdf`). A scanned
    statement is run through the OCR backend (OCRmyPDF/Tesseract by default) to
    produce a searchable PDF, which is then parsed by the *same* PyMuPDF adapter
    — the rest of the chain is unchanged.

    ``source_filename`` defaults to the **original** file's name (not the
    intermediate ``.ocr.pdf``), so provenance points at the real input.
    """
    # Lazy import keeps the OCRmyPDF dependency optional for callers that never
    # touch scanned documents.
    from .ocr import ensure_searchable_pdf

    path = Path(path)
    outcome = ensure_searchable_pdf(
        path,
        backend=backend,
        output_path=ocr_output_path,
        force=force_ocr,
    )
    return parse_pdf(
        outcome.pdf_path,
        anonymizer=anonymizer,
        document_id=document_id,
        company_id=company_id,
        fiscal_year=fiscal_year,
        source_filename=source_filename if source_filename is not None else path.name,
    )


def parse_pdf_with_config(
    path: str | Path,
    config_path: str | Path,
    *,
    document_id: str,
    company_id: str,
    fiscal_year: int,
) -> RawDocument:
    """Build an :class:`Anonymizer` from a YAML config and parse ``path``.

    Thin convenience wrapper around :func:`parse_pdf` for callers that have a
    config file rather than a pre-built anonymizer.
    """
    # Imported lazily to keep the anonymisation core import-light.
    from ..config import load_anonymizer

    anonymizer = load_anonymizer(config_path)
    return parse_pdf(
        path,
        anonymizer=anonymizer,
        document_id=document_id,
        company_id=company_id,
        fiscal_year=fiscal_year,
    )
