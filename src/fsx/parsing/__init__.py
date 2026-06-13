"""Parsing adapters that turn source PDFs into Level-1 ``RawDocument`` objects.

Currently ships the PyMuPDF (``fitz``) backend. Adapters always anonymise text
on the way out, so a :class:`~fsx.schemas.RawDocument` never carries raw,
re-identifiable content.
"""

from __future__ import annotations

from .pymupdf_parser import (
    PyMuPDFParser,
    parse_pdf,
    parse_pdf_with_config,
)

__all__ = ["PyMuPDFParser", "parse_pdf", "parse_pdf_with_config"]
