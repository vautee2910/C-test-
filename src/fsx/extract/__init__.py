"""Geometric extraction of tabular line items from PDF word coordinates.

The geometry (:mod:`fsx.extract.tables`) and number parsing
(:mod:`fsx.extract.numbers`) are fully generalised — no document-specific
constants. :mod:`fsx.extract.pdf_words` is the PyMuPDF adapter that sources
words from a real PDF and anonymises labels.
"""

from __future__ import annotations

from .anlagenspiegel import (
    Anlagenspiegel,
    AnlagenRow,
    MovementColumn,
    anlagenspiegel_facts,
    classify_column,
    extract_anlagenspiegel,
    reconstruct_anlagenspiegel,
)
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
    "Anlagenspiegel",
    "AnlagenRow",
    "MovementColumn",
    "classify_column",
    "reconstruct_anlagenspiegel",
    "extract_anlagenspiegel",
    "anlagenspiegel_facts",
]
