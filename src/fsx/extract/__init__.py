"""Geometric extraction of tabular line items from PDF word coordinates.

The geometry (:mod:`fsx.extract.tables`) and number parsing
(:mod:`fsx.extract.numbers`) are fully generalised — no document-specific
constants. :mod:`fsx.extract.pdf_words` is the PyMuPDF adapter that sources
words from a real PDF and anonymises labels.
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
    "reconstruct_tables",
]
