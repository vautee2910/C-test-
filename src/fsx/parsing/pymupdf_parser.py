"""PyMuPDF (``fitz``) parsing adapter producing a Level-1 ``RawDocument``.

This backend opens a PDF, walks every page, and extracts:

* **text blocks** via ``page.get_text("blocks")`` — each block is a tuple
  ``(x0, y0, x1, y1, text, block_no, block_type)``;
* **tables** via the geometry reconstruction in :mod:`fsx.extract` (primary;
  recovers the row × value-column grid of dense financial / statistics tables),
  falling back to ``page.find_tables()`` only when reconstruction is empty.

Every piece of human-readable text — block text and table cells alike — is run
through the **same** :class:`~fsx.anonymize.engine.Anonymizer` instance so that
pseudonyms stay consistent across the whole document (one company collapses to
one ``[UNTERNEHMEN_n]`` token regardless of which page it appears on). The raw,
non-anonymised text never enters the resulting :class:`RawDocument`.

The caller owns the ``Anonymizer`` (built from the engagement config); this
adapter uses the passed-in instance directly so consistency holds.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

import fitz

from ..anonymize.engine import Anonymizer
from ..schemas import BBox, BlockType, Page, RawDocument, Table, TextBlock

# Trailing dotted-leader artifacts of statement layouts: the run of dots between
# a line label and its value renders (in many embedded fonts) as replacement
# chars / control glyphs. Strip them so the cell label is a clean SQL key.
_LEADER_RE = re.compile("[\\s. \u0008\u2008\ufffd]+$")


def _clean_label(label: str) -> str:
    return _LEADER_RE.sub("", label)


def _format_value(value: Optional[float]) -> str:
    """Render a reconstructed numeric value as a clean cell string.

    Integers print without a trailing ``.0`` so a host can ``CAST`` them
    directly; ``None`` (empty column) becomes ``""``.
    """
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return repr(value)


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
    *,
    use_models: bool = True,
) -> list[list[str]]:
    """Anonymise a row-major grid of (possibly ``None``) cell strings.

    ``None`` cells become empty strings; every non-empty string is passed
    through ``anonymizer`` so pseudonyms stay consistent with the rest of the
    document. Factored out so table mapping can be tested without a real PDF.

    ``use_models`` defaults to ``True`` (the precise default): the statistical
    model also scans table cells, so a name that appears only in a cell is still
    caught. Pass ``False`` to opt into the faster path that runs only the
    dictionary + regex layers on cells (the model is slow per-cell and the cells
    are dense, low-PII concept labels already present in the page's text blocks).
    """
    grid: list[list[str]] = []
    for row in rows:
        out_row: list[str] = []
        for cell in row:
            if cell is None:
                out_row.append("")
            else:
                out_row.append(anonymizer.anonymize(cell, use_models=use_models).text)
        grid.append(out_row)
    return grid


def _bbox_of(raw: Any) -> Optional[BBox]:
    """Coerce a 4-tuple / ``fitz.Rect``-like object into a ``BBox`` or ``None``."""
    if raw is None:
        return None
    x0, y0, x1, y1 = raw[0], raw[1], raw[2], raw[3]
    return (float(x0), float(y0), float(x1), float(y1))


class PyMuPDFParser:
    """Parse a PDF into an anonymised Level-1 :class:`RawDocument` using fitz.

    ``model_on_tables`` (default ``True``) keeps the precise behaviour: the
    statistical-model detectors scan table cells as well as prose blocks, so a
    name that appears only in a cell is still redacted by the model. Set it to
    ``False`` to opt into the faster path — the model then runs on prose text
    blocks only, and table cells are anonymised by the dictionary + regex layers
    alone (~2.8× faster on table-heavy pages; a cell-only name is then caught by
    those layers, not the model). Either way the shared token mapping keeps
    pseudonyms consistent across blocks and cells.
    """

    def __init__(self, anonymizer: Anonymizer, *, model_on_tables: bool = True) -> None:
        self.anonymizer = anonymizer
        self.model_on_tables = model_on_tables

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

    def _parse_tables_geometry(self, page: Any, page_no: int) -> list[Table]:
        """Reconstruct tables from word geometry — the primary table source.

        Uses the same geometry reconstruction as the fact pipeline
        (:mod:`fsx.extract`), which is far more robust than PyMuPDF
        ``find_tables()`` on dense financial / statistics tables: it recovers the
        row × value-column grid instead of collapsing a page into one text blob
        or missing the body entirely. Only the *labels* pass through the
        anonymiser; numeric values stay untouched, so a downstream SQL store gets
        the figures verbatim (no PII regex can corrupt a number into a token).

        Returns ``[]`` when the page has no reconstructable rows, so the caller
        can fall back to ``find_tables()``.
        """
        from ..extract.pdf_words import words_from_page
        from ..extract.tables import reconstruct_tables

        tables: list[Table] = []
        for i, panel in enumerate(reconstruct_tables(words_from_page(page)), start=1):
            cells: list[list[str]] = []
            for item in panel.items:
                # The model scans cells by default (precise); model_on_tables=False
                # opts into the faster dictionary+regex-only path. See __init__.
                label = (
                    self.anonymizer.anonymize(
                        item.label, use_models=self.model_on_tables
                    ).text
                    if item.label else ""
                )
                cells.append([_clean_label(label)] + [_format_value(v) for v in item.values])
            if not cells:
                continue
            headers = [
                self.anonymizer.anonymize(h, use_models=self.model_on_tables).text if h else ""
                for h in panel.column_headers
            ]
            tables.append(
                Table(
                    table_id=f"T_{page_no}_{i:02d}",
                    caption_anonymized=None,
                    cells=cells,
                    column_headers=headers,
                    bbox=None,
                )
            )
        return tables

    def _parse_tables(self, page: Any, page_no: int) -> list[Table]:
        tables: list[Table] = []
        found = page.find_tables()
        # find_tables() returns a TableFinder; the tables live on .tables.
        table_objs = getattr(found, "tables", found)
        for i, table in enumerate(table_objs, start=1):
            cells = _anonymize_cells(
                table.extract(), self.anonymizer, use_models=self.model_on_tables
            )
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
                # Geometry reconstruction is the primary table source; fall back
                # to PyMuPDF find_tables() only when it yields nothing.
                tables = self._parse_tables_geometry(page, index) or self._parse_tables(
                    page, index
                )
                pages.append(
                    Page(
                        page=index,
                        blocks=self._parse_blocks(page),
                        tables=tables,
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
    model_on_tables: bool = True,
) -> RawDocument:
    """Parse a PDF into an anonymised Level-1 :class:`RawDocument`.

    The caller builds and owns ``anonymizer`` (typically from the engagement
    config); the passed-in instance is used directly so its token counters and
    entity→token mapping stay shared across every block and table of the
    document. ``source_filename`` defaults to the file's name when omitted.

    ``model_on_tables`` defaults to ``True`` — the precise path, where the
    statistical model scans table cells too. Pass ``False`` to opt into the
    faster blocks-only path (see :class:`PyMuPDFParser`).
    """
    return PyMuPDFParser(anonymizer, model_on_tables=model_on_tables).parse(
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
    model_on_tables: bool = True,
) -> RawDocument:
    """Parse a PDF, transparently OCR-ing it first **if** it is a scan.

    A born-digital statement already has a text layer, so it is parsed directly
    with no OCR (see :func:`fsx.parsing.ocr.ensure_searchable_pdf`). A scanned
    statement is run through the OCR backend (OCRmyPDF/Tesseract by default) to
    produce a searchable PDF, which is then parsed by the *same* PyMuPDF adapter
    — the rest of the chain is unchanged.

    ``source_filename`` defaults to the **original** file's name (not the
    intermediate ``.ocr.pdf``), so provenance points at the real input.
    ``model_on_tables`` is forwarded to :func:`parse_pdf` (precise by default).
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
        model_on_tables=model_on_tables,
    )


def parse_pdf_with_config(
    path: str | Path,
    config_path: str | Path,
    *,
    document_id: str,
    company_id: str,
    fiscal_year: int,
    model_on_tables: bool = True,
) -> RawDocument:
    """Build an :class:`Anonymizer` from a YAML config and parse ``path``.

    Thin convenience wrapper around :func:`parse_pdf` for callers that have a
    config file rather than a pre-built anonymizer. ``model_on_tables`` is
    forwarded (precise by default).
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
        model_on_tables=model_on_tables,
    )
