"""Reusable, domain-agnostic extraction of tables from PDF word coordinates.

This package is deliberately free of any financial-statement (HGB) knowledge, so
it can be lifted into another application unchanged. It contains only generic
machinery:

* :mod:`fsx.extract.tables` — turn positioned words into rows / panels / value
  columns (no document-specific constants);
* :mod:`fsx.extract.numbers` — German number parsing;
* :mod:`fsx.extract.pdf_words` — the PyMuPDF adapter (rotation-normalised words,
  optional label anonymisation).

Mapping a reconstructed table to *meaning* (HGB concepts, the Anlagenspiegel,
Facts) lives in :mod:`fsx.hgb`, never here. Only external dependency: PyMuPDF
(``fitz``), and only in :mod:`~fsx.extract.pdf_words`.
"""

from __future__ import annotations

from .numbers import is_de_number, parse_de_number
from .tables import (
    LineItem,
    ReconstructedTable,
    Word,
    cluster_rows,
    detect_value_columns,
    find_column_gutters,
    merge_number_fragments,
    reconstruct_tables,
)

__all__ = [
    "is_de_number",
    "parse_de_number",
    "Word",
    "LineItem",
    "ReconstructedTable",
    "cluster_rows",
    "find_column_gutters",
    "detect_value_columns",
    "merge_number_fragments",
    "reconstruct_tables",
]
