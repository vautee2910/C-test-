"""Geometry-based reconstruction of tabular line items from word coordinates.

This is the **generalised** core: it turns a flat list of positioned words (as
any PDF text layer yields) into rows of *(label, values-per-column)*, with **no**
hard-coded coordinates, page numbers, or document-specific labels. It is what
makes the pipeline scale across many different annual statements.

The approach mirrors how a human reads a German balance sheet:

1. **Rows** — cluster words by vertical position.
2. **Panels** — many statements print two tables side by side (AKTIVA | PASSIVA).
   The vertical gutter between them is found by *consensus* across body rows, so
   a heading that happens to span the gutter does not defeat the split.
3. **Columns** — value figures are right-aligned, so their right edges cluster
   into columns (e.g. "Geschäftsjahr" / "Vorjahr"). Each row's remaining text is
   its label.

Mapping a label like "Sachanlagen" to a canonical HGB concept is intentionally
*out of scope* here — that needs the shared HGB knowledge base (a later, also
generalised, layer), not geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import re

from .numbers import is_bare_integer, is_de_number, parse_de_number, parse_number_token


@dataclass(frozen=True)
class Word:
    """A positioned word from a PDF text layer."""

    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class LineItem:
    """One reconstructed row: a label plus one value per detected column."""

    label: str
    values: list[Optional[float]]
    y: float

    @property
    def has_values(self) -> bool:
        return any(v is not None for v in self.values)


@dataclass
class ReconstructedTable:
    """A panel's worth of line items sharing the same value columns."""

    n_columns: int
    items: list[LineItem] = field(default_factory=list)
    x_range: Optional[tuple[float, float]] = None


# Pieces of a German number split by a space acting as thousands separator:
# a grouped integer head ("550", "1.381") followed by a 3-digit group with an
# optional ",dd" tail and optional trailing minus ("415,00", "423,24", "96-").
_NUM_HEAD = re.compile(r"^-?\d{1,3}(?:\.\d{3})*$")
_NUM_TAIL = re.compile(r"^\d{3}(?:,\d+)?-?$")


def merge_number_fragments(row: list[Word], max_gap: float = 6.0) -> list[Word]:
    """Re-join numbers split into separate words by a space thousands separator.

    Some statements (notably Anlagenspiegel exports / OCR) render ``550.415,00``
    as two tokens ``550`` and ``415,00``. When a grouped-integer head is followed
    within ``max_gap`` px by a 3-digit tail, they are merged back into one word.
    Column spacing is far larger than ``max_gap``, so genuine adjacent columns
    are never merged.
    """
    out: list[Word] = []
    for w in sorted(row, key=lambda w: w.x0):
        if (
            out
            and _NUM_HEAD.match(out[-1].text)
            and _NUM_TAIL.match(w.text)
            and (w.x0 - out[-1].x1) <= max_gap
        ):
            p = out.pop()
            out.append(Word(p.x0, p.y0, w.x1, w.y1, f"{p.text}.{w.text}"))
        else:
            out.append(w)
    return out


# --------------------------------------------------------------------------- #
# 1. Rows
# --------------------------------------------------------------------------- #


def cluster_rows(words: list[Word], y_tol: float = 3.0) -> list[list[Word]]:
    """Group words into visual rows by vertical centre, sorted top-to-bottom.

    Words whose vertical centre lies within ``y_tol`` of the running row centre
    join that row. Each returned row is sorted left-to-right.
    """
    rows: list[list[Word]] = []
    centres: list[float] = []
    for w in sorted(words, key=lambda w: w.cy):
        placed = False
        for i, c in enumerate(centres):
            if abs(w.cy - c) <= y_tol:
                rows[i].append(w)
                # running mean keeps the centre stable as the row grows
                centres[i] = (c * (len(rows[i]) - 1) + w.cy) / len(rows[i])
                placed = True
                break
        if not placed:
            rows.append([w])
            centres.append(w.cy)
    order = sorted(range(len(rows)), key=lambda i: centres[i])
    return [sorted(rows[i], key=lambda w: w.x0) for i in order]


# --------------------------------------------------------------------------- #
# 2. Panels (vertical gutters)
# --------------------------------------------------------------------------- #


def find_column_gutters(
    rows: list[list[Word]],
    min_gap: float = 18.0,
    min_support: float = 0.1,
    min_support_count: int = 3,
    cluster_tol: float = 20.0,
) -> list[float]:
    """Find x-positions of vertical gutters separating side-by-side panels.

    A panel gutter is distinguished from an ordinary label-to-value gap by what
    sits on either side: across a true gutter the left word is the *end of a
    value column* (a number) and the right word is the *start of the next
    panel's label* (text). A label-to-value gap is the opposite (text then
    number), so it is ignored — which also means single-column pages are never
    split. A gutter is accepted only if this pattern appears (at roughly the
    same x) in at least ``max(min_support_count, min_support * n_rows)`` rows —
    by consensus — so a single heading bridging the gutter does not hide it, nor
    a couple of stray gaps invent one. The absolute floor matters because many
    rows (totals, headers) are legitimately single-panel and never cross the
    gutter, so a pure fraction-of-all-rows threshold would be too strict.
    """
    if not rows:
        return []

    candidates: list[float] = []
    for row in rows:
        for a, b in zip(row, row[1:]):
            gap = b.x0 - a.x1
            if gap >= min_gap and is_de_number(a.text) and not is_de_number(b.text):
                candidates.append((a.x1 + b.x0) / 2)

    if not candidates:
        return []

    # Cluster candidate gap centres that fall within cluster_tol of each other.
    candidates.sort()
    clusters: list[list[float]] = [[candidates[0]]]
    for c in candidates[1:]:
        if c - clusters[-1][-1] <= cluster_tol:
            clusters[-1].append(c)
        else:
            clusters.append([c])

    threshold = max(min_support_count, int(min_support * len(rows)))
    gutters = [sum(cl) / len(cl) for cl in clusters if len(cl) >= threshold]
    return sorted(gutters)


def split_row_by_gutters(row: list[Word], gutters: list[float]) -> list[list[Word]]:
    """Split one row into panel segments using gutter x-positions."""
    if not gutters:
        return [row]
    segments: list[list[Word]] = [[] for _ in range(len(gutters) + 1)]
    for w in row:
        panel = 0
        for g in gutters:
            if w.cx > g:
                panel += 1
            else:
                break
        segments[panel].append(w)
    return segments


# --------------------------------------------------------------------------- #
# 3. Columns + line items
# --------------------------------------------------------------------------- #


def detect_value_columns(words: list[Word], gap_tol: float = 14.0) -> list[float]:
    """Cluster the right edges of numeric words into value-column anchors.

    German value figures are right-aligned, so their right edges (``x1``) line
    up per column. Returns the column anchor x-positions, left to right.
    """
    edges = sorted(w.x1 for w in words if is_de_number(w.text))
    if not edges:
        return []
    clusters: list[list[float]] = [[edges[0]]]
    for e in edges[1:]:
        if e - clusters[-1][-1] <= gap_tol:
            clusters[-1].append(e)
        else:
            clusters.append([e])
    return [sum(cl) / len(cl) for cl in clusters]


def _nearest_column(x1: float, anchors: list[float]) -> int:
    return min(range(len(anchors)), key=lambda i: abs(anchors[i] - x1))


def _build_line_item(
    row: list[Word], anchors: list[float], y: float, align_tol: float = 9.0
) -> LineItem:
    values: list[Optional[float]] = [None] * len(anchors)
    label_parts: list[str] = []
    for w in row:
        if is_de_number(w.text):
            values[_nearest_column(w.x1, anchors)] = parse_de_number(w.text)
        elif anchors and is_bare_integer(w.text):
            # A bare integer (e.g. a "Mio €" value like 15 / -770) counts only if
            # it right-aligns to a column established by the strong numbers; this
            # keeps note refs and stray digits out of the values.
            col = _nearest_column(w.x1, anchors)
            if abs(w.x1 - anchors[col]) <= align_tol:
                values[col] = parse_number_token(w.text)
            else:
                label_parts.append(w.text)
        else:
            label_parts.append(w.text)
    return LineItem(label=" ".join(label_parts).strip(), values=values, y=y)


def reconstruct_tables(
    words: list[Word],
    *,
    y_tol: float = 3.0,
    min_gap: float = 18.0,
) -> list[ReconstructedTable]:
    """Reconstruct one :class:`ReconstructedTable` per side-by-side panel.

    Fully geometric and document-agnostic. Rows with neither label nor value
    are dropped; label-only rows (section headers) are kept so hierarchy stays
    visible — callers wanting facts can filter on :attr:`LineItem.has_values`.
    """
    rows = cluster_rows(words, y_tol=y_tol)
    if not rows:
        return []
    # Re-join numbers split by a space thousands separator (e.g. bank "Mio €"
    # reports render 20.717 as "20" + "717") before any column analysis.
    rows = [merge_number_fragments(r) for r in rows]
    gutters = find_column_gutters(rows, min_gap=min_gap)

    # Collect, per panel, the list of word-segments (one per visual row).
    n_panels = len(gutters) + 1
    panel_rows: list[list[list[Word]]] = [[] for _ in range(n_panels)]
    for row in rows:
        for p, seg in enumerate(split_row_by_gutters(row, gutters)):
            panel_rows[p].append(seg)

    tables: list[ReconstructedTable] = []
    for segments in panel_rows:
        panel_words = [w for seg in segments for w in seg]
        if not panel_words:
            continue
        anchors = detect_value_columns(panel_words)
        items: list[LineItem] = []
        for seg in segments:
            if not seg:
                continue
            y = sum(w.cy for w in seg) / len(seg)
            item = _build_line_item(seg, anchors, y)
            if item.label or item.has_values:
                items.append(item)
        if not items:
            continue
        xs = [w.x0 for w in panel_words] + [w.x1 for w in panel_words]
        tables.append(
            ReconstructedTable(
                n_columns=len(anchors),
                items=items,
                x_range=(min(xs), max(xs)),
            )
        )
    return tables
