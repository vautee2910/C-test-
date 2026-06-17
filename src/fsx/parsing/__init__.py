"""Parsing adapters that turn source PDFs into Level-1 ``RawDocument`` objects.

Currently ships the PyMuPDF (``fitz``) backend. Adapters always anonymise text
on the way out, so a :class:`~fsx.schemas.RawDocument` never carries raw,
re-identifiable content.
"""

from __future__ import annotations

from .ocr import (
    OcrBackend,
    OcrError,
    OcrMyPdfBackend,
    OcrOutcome,
    ensure_searchable_pdf,
)
from .pymupdf_parser import (
    PyMuPDFParser,
    parse_pdf,
    parse_pdf_with_config,
    parse_pdf_with_ocr,
)
from .redact import RedactionSummary, write_anonymized_pdf
from .text_layer import has_text_layer, needs_ocr, text_layer_stats

__all__ = [
    "PyMuPDFParser",
    "parse_pdf",
    "parse_pdf_with_config",
    "parse_pdf_with_ocr",
    # anonymised-PDF output
    "write_anonymized_pdf",
    "RedactionSummary",
    # OCR front-stage
    "OcrBackend",
    "OcrError",
    "OcrMyPdfBackend",
    "OcrOutcome",
    "ensure_searchable_pdf",
    "has_text_layer",
    "needs_ocr",
    "text_layer_stats",
]
