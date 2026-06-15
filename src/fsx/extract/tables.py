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
    # One header phrase per value column (left→right), or empty when the column
    # headers could not be resolved geometrically. Lets a host name the columns
    # (e.g. period years, statistics breakdown dimensions) for SQL.
    column_headers: list[str] = field(default_factory=list)


# Pieces of a German number split by a space acting as thousands separator:
# a grouped integer head ("550", "1.381") followed by a 3-digit group with an
# optional ",dd" tail and optional trailing minus ("415,00", "423,24", "96-").
_NUM_HEAD = re.compile(r"^-?\d{1,3}(?:\.\d{3})*$")
_NUM_TAIL = re.compile(r"^\d{3}(?:,\d+)?-?$")
# Lone dash tokens used as a leading minus sign (bank reports use an en dash).
_DASHES = {"-", "‐", "‑", "‒", "–", "—", "−"}
# At least one (Unicode) letter — a real panel label, not a dash placeholder
# ("-,--", "( -)") or a bare figure. Used to qualify a panel-gutter candidate.
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def merge_number_fragments(row: list[Word], max_gap: float = 6.0) -> list[Word]:
    """Re-join numbers split into separate words, and attach detached minus signs.

    Some statements (Anlagenspiegel exports, bank "Mio €" sheets, OCR) render
    ``550.415,00`` as ``550`` + ``415,00`` and a negative ``-10.658`` as a lone
    dash ``–`` then ``10`` ``658``. Grouped-integer heads followed within
    ``max_gap`` px by a 3-digit tail are merged; a lone leading dash before a
    number becomes its sign. Column spacing is far larger than ``max_gap``, so
    genuine adjacent columns are never merged.
    """
    # Phase 1: join space-split thousands groups.
    joined: list[Word] = []
    for w in sorted(row, key=lambda w: w.x0):
        if (
            joined
            and _NUM_HEAD.match(joined[-1].text)
            and _NUM_TAIL.match(w.text)
            and (w.x0 - joined[-1].x1) <= max_gap
        ):
            p = joined.pop()
            joined.append(Word(p.x0, p.y0, w.x1, w.y1, f"{p.text}.{w.text}"))
        else:
            joined.append(w)

    # Phase 2: attach a lone leading dash to the number that follows it.
    out: list[Word] = []
    for w in joined:
        if (
            out
            and out[-1].text in _DASHES
            and (w.x0 - out[-1].x1) <= max_gap
            and (is_de_number(w.text) or is_bare_integer(w.text))
        ):
            d = out.pop()
            out.append(Word(d.x0, d.y0, w.x1, w.y1, f"-{w.text}"))
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
    min_panel_support: int = 2,
) -> list[float]:
    """Find x-positions of vertical gutters separating side-by-side panels.

    A panel gutter is distinguished from an ordinary label-to-value gap by what
    sits on either side: across a true gutter the left word is the *end of a
    value column* (a number) and the right word is the *start of the next
    panel's label* — real text *with a letter*, not a dash placeholder (``-,--``,
    ``( -)``) or a bare figure, so a lone prior-year value column (common on bank
    sheets, separated by dashes) is never mistaken for a second panel. A
    label-to-value gap is the opposite (text then number), so it is ignored —
    which also means single-column pages are never split. A gutter is accepted only if this pattern appears (at roughly the
    same x) in at least ``max(min_support_count, min_support * n_rows)`` rows —
    by consensus — so a single heading bridging the gutter does not hide it, nor
    a couple of stray gaps invent one. The absolute floor matters because many
    rows (totals, headers) are legitimately single-panel and never cross the
    gutter, so a pure fraction-of-all-rows threshold would be too strict.

    Real two-up balance sheets often print AKTIVA and PASSIVA with a *different*
    number of lines, so the two sides drift vertically and few rows carry the
    number-then-label pair at the same x — the consensus floor would then miss
    an obvious gutter. As a fallback, a smaller cluster (``min_panel_support``)
    is still accepted when it is *flanked by value columns on both sides* (a
    number right-aligned to its left **and** a number starting to its right):
    that two-group-of-figures structure only occurs between genuine panels, not
    within a single column, so it cannot split a label from its values nor two
    value columns of one panel (whose gap is number-then-number, never a
    candidate).
    """
    if not rows:
        return []

    candidates: list[float] = []
    for row in rows:
        for a, b in zip(row, row[1:]):
            gap = b.x0 - a.x1
            if (
                gap >= min_gap
                and is_de_number(a.text)
                and not is_de_number(b.text)
                and _HAS_LETTER.search(b.text)
            ):
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

    # Right edges / left edges of every numeric word, to confirm that a weak
    # cluster sits between two genuine columns of figures.
    num_edges = [w.x1 for row in rows for w in row if is_de_number(w.text)]
    num_starts = [w.x0 for row in rows for w in row if is_de_number(w.text)]

    threshold = max(min_support_count, int(min_support * len(rows)))
    gutters: list[float] = []
    for cl in clusters:
        centre = sum(cl) / len(cl)
        if len(cl) >= threshold:
            gutters.append(centre)
        elif len(cl) >= min_panel_support:
            flanked_left = any(e <= centre - min_gap for e in num_edges)
            flanked_right = any(s >= centre + min_gap for s in num_starts)
            if flanked_left and flanked_right:
                gutters.append(centre)
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


# A period column header: a 4-digit year (optionally a range "2015/17") or a
# full date. Used to gate column naming to the unambiguous statement case.
_PERIOD_HEADER_RE = re.compile(r"(?:19|20)\d{2}|\d{1,2}\.\d{1,2}\.\d{2,4}")


def _column_header_phrases(
    header_words: list[Word], anchors: list[float]
) -> list[str]:
    """Bind label-only header words above the body to their value column.

    Generalises the Anlagenspiegel column-header reading: value figures are
    right-aligned at each ``anchor`` (their ``x1``), so a header sits slightly to
    the *left* of and above its column. Each header word is assigned to the
    nearest anchor within an asymmetric band scaled to the column spacing; words
    far to the left (a row label, a page title) fall outside every band and are
    dropped. Multi-line headers stack top→bottom, left→right. Returns one phrase
    per column (``""`` where nothing mapped), or ``[]`` if nothing mapped at all.
    """
    if not anchors or not header_words:
        return []
    if len(anchors) > 1:
        gap = min(anchors[i + 1] - anchors[i] for i in range(len(anchors) - 1))
    else:
        gap = 80.0
    left_tol, right_tol = 0.85 * gap, 0.30 * gap
    buckets: list[list[Word]] = [[] for _ in anchors]
    for w in header_words:
        i = min(range(len(anchors)), key=lambda k: abs(anchors[k] - w.cx))
        if anchors[i] - left_tol <= w.cx <= anchors[i] + right_tol:
            buckets[i].append(w)
    phrases = [
        " ".join(w.text for w in sorted(b, key=lambda w: (round(w.cy, 1), w.x0))).strip()
        for b in buckets
    ]
    nonempty = [p for p in phrases if p]
    if not nonempty:
        return []
    # Precision guard: geometry alone cannot tell a real column header from a
    # caption / section phrase that merely sits in the band, so naming is
    # restricted to the one unambiguous, genuinely useful case for statements —
    # *period* headers. Accept only when most named columns look like a year or
    # date (a Geschäftsjahr/Vorjahr row); statistics breakdowns (sector names)
    # and prose fragments then correctly stay positional ([]).
    period_like = sum(1 for p in nonempty if _PERIOD_HEADER_RE.search(p))
    if period_like < 0.6 * len(nonempty):
        return []
    return phrases


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
        # Column headers: the label-only rows in the band immediately above the
        # body. Walk upward from the first valued row and stop at the first large
        # vertical gap — that blank band separates the column-header rows from the
        # page title, so the title's words do not leak into the headers.
        first_value_y = min((it.y for it in items if it.has_values), default=None)
        header_words: list[Word] = []
        if first_value_y is not None:
            seg_ys = sorted(
                {sum(w.cy for w in s) / len(s) for s in segments if s}
            )
            diffs = [b - a for a, b in zip(seg_ys, seg_ys[1:]) if b - a > 0]
            pitch = sorted(diffs)[len(diffs) // 2] if diffs else 12.0
            # Only the single label-only row directly above the body — a one-line
            # period/date header. A multi-line band invariably drags in caption /
            # title prose, producing wrong column names, so it is not trusted.
            above = sorted(
                (
                    s
                    for s in segments
                    if s
                    and 0 < first_value_y - sum(w.cy for w in s) / len(s) <= 1.6 * pitch
                    and not any(is_de_number(w.text) for w in s)
                ),
                key=lambda s: -sum(w.cy for w in s) / len(s),
            )
            if above:
                header_words = above[0]
        xs = [w.x0 for w in panel_words] + [w.x1 for w in panel_words]
        tables.append(
            ReconstructedTable(
                n_columns=len(anchors),
                items=items,
                x_range=(min(xs), max(xs)),
                column_headers=_column_header_phrases(header_words, anchors),
            )
        )
    return tables
