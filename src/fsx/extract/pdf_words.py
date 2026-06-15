"""PyMuPDF adapter feeding word coordinates into the geometric reconstructor.

Keeps the ``fitz`` dependency isolated (like :mod:`fsx.parsing`). The geometry
in :mod:`fsx.extract.tables` stays pure and testable without a PDF; this module
only sources words from a real document and anonymises the resulting labels.

Values are numbers and pass through untouched; only the human-readable *labels*
are run through the anonymiser (rare, but a Kontennachweis line item can name a
person or related company).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol

import fitz

from .tables import LineItem, ReconstructedTable, Word, reconstruct_tables


class _Anonymized(Protocol):  # pragma: no cover - typing only
    text: str


class LabelAnonymizer(Protocol):  # pragma: no cover - typing only
    """Anything able to anonymise a label string.

    Duck-typed so this generic package never imports :mod:`fsx.anonymize` (or any
    particular anonymiser): pass :class:`fsx.anonymize.Anonymizer`, your own
    engine, or ``None`` to skip anonymisation entirely when reusing this module
    elsewhere.
    """

    def anonymize(self, text: str) -> _Anonymized: ...


def words_from_page(page) -> list[Word]:
    """Extract positioned :class:`Word` objects from a PyMuPDF page.

    Word geometry is mapped through ``page.rotation_matrix`` so coordinates are
    in *visual reading* orientation. Landscape balance sheets are routinely bound
    into a portrait report as ``/Rotate 90`` pages; on those PyMuPDF returns word
    boxes in the unrotated content space, where the glyphs advance vertically, so
    the row-clustering reconstructor would otherwise scramble the table. The
    matrix is the identity for an upright page, so born-digital portrait
    statements are unaffected.
    """
    mat = page.rotation_matrix
    words: list[Word] = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        if text.strip():
            r = fitz.Rect(x0, y0, x1, y1) * mat
            r.normalize()
            words.append(Word(x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1, text=text))
    return words


def _anonymize_table(
    table: ReconstructedTable, anonymizer: Optional[LabelAnonymizer]
) -> ReconstructedTable:
    if anonymizer is None:
        return table
    items = [
        LineItem(
            label=anonymizer.anonymize(it.label).text if it.label else "",
            values=it.values,
            y=it.y,
        )
        for it in table.items
    ]
    return ReconstructedTable(n_columns=table.n_columns, items=items, x_range=table.x_range)


def extract_tables(
    path: str | Path,
    *,
    anonymizer: Optional[LabelAnonymizer] = None,
    pages: Optional[list[int]] = None,
) -> dict[int, list[ReconstructedTable]]:
    """Reconstruct tables per page of a PDF, optionally anonymising labels.

    Returns a mapping of 1-indexed page number -> list of reconstructed panels
    (AKTIVA/PASSIVA etc.). ``pages`` optionally restricts to specific 1-indexed
    pages. Pass an ``anonymizer`` (any object with ``anonymize(str).text``) to
    pseudonymise labels — share the same one across the document so pseudonyms
    stay consistent — or leave it ``None`` to get the raw reconstructed tables.
    """
    result: dict[int, list[ReconstructedTable]] = {}
    with fitz.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            if pages is not None and index not in pages:
                continue
            tables = reconstruct_tables(words_from_page(page))
            result[index] = [_anonymize_table(t, anonymizer) for t in tables]
    return result
