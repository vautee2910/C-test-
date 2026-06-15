"""Anlagenspiegel (fixed-asset movement schedule) extraction.

Generalised, document-agnostic. The Anlagenspiegel is a wide table: each asset
class is a row, and the columns track the movement of cost and depreciation over
the year (opening cost, additions, disposals, ..., closing book value). Unlike
the Bilanz, the *columns* carry the semantics, so this module:

1. reconstructs rows (re-joining numbers split by space thousands separators),
2. maps each value column to a canonical *movement* by reading the header words
   sitting above it (headers are multi-line and fragmented, so matching is by
   keyword presence, not exact synonyms),
3. emits Facts per asset-class row x mapped movement.

The headline figures (total additions = capex, total depreciation of the year,
closing book value) reconcile with the Bilanz and GuV, which is the natural
validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..extract.numbers import is_de_number, parse_de_number
from ..extract.tables import Word, cluster_rows, detect_value_columns, merge_number_fragments
from ..schemas import Fact, StatementType
from .concepts import normalise_label

# Canonical movements, in priority order. Each maps to the keywords that must all
# be present in a column's (normalised) header phrase. Order matters: more
# specific patterns first (e.g. buchwert_vorjahr before buchwert_gj).
_MOVEMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("buchwert_vorjahr", ("buchwert", "vorjahr")),
    ("buchwert_gj", ("buchwert",)),
    ("abschreibung_gj", ("abschreibung", "geschaefts")),
    ("abschreibung_kumuliert_ende", ("kumulierte", "abschreibung", "31")),
    ("abschreibung_kumuliert_anfang", ("kumulierte", "abschreibung")),
    ("zuschreibungen", ("zuschreibung",)),
    ("zugaenge", ("zugaenge",)),
    ("abgaenge", ("abgaenge",)),
    ("umbuchungen", ("umbuchung",)),
    ("ahk_ende", ("anschaffung", "31")),
    ("ahk_anfang", ("anschaffung",)),
)


@dataclass(frozen=True)
class MovementColumn:
    index: int
    anchor_x: float
    movement: Optional[str]


@dataclass
class AnlagenRow:
    label: str
    values: list[Optional[float]]
    y: float

    @property
    def has_values(self) -> bool:
        return any(v is not None for v in self.values)


@dataclass
class Anlagenspiegel:
    columns: list[MovementColumn] = field(default_factory=list)
    rows: list[AnlagenRow] = field(default_factory=list)

    def movement_index(self, movement: str) -> Optional[int]:
        for c in self.columns:
            if c.movement == movement:
                return c.index
        return None


def classify_column(header_phrase: str) -> Optional[str]:
    """Map a column's concatenated header text to a canonical movement."""
    norm = normalise_label(header_phrase)
    for movement, keywords in _MOVEMENTS:
        if all(k in norm for k in keywords):
            return movement
    return None


def _map_columns(header_words: list[Word], anchors: list[float]) -> list[MovementColumn]:
    columns: list[MovementColumn] = []
    for i, anchor in enumerate(anchors):
        # Header words sitting above this right-aligned column (slightly left of
        # and up to the right edge).
        near = sorted(
            (w for w in header_words if anchor - 32 < w.cx < anchor + 18),
            key=lambda w: (w.cy, w.x0),
        )
        phrase = " ".join(w.text for w in near)
        columns.append(MovementColumn(index=i, anchor_x=anchor, movement=classify_column(phrase)))
    return columns


def reconstruct_anlagenspiegel(
    words: list[Word],
    *,
    header_y_max: float = 172.0,
    header_y_min: float = 110.0,
    y_tol: float = 4.0,
) -> Anlagenspiegel:
    """Reconstruct an Anlagenspiegel grid with movement-mapped columns.

    ``header_y_min/max`` bound the column-header band (excluding the page title
    and company line above it). Defaults suit a typical portrait/landscape sheet;
    callers can override per layout.
    """
    if not words:
        return Anlagenspiegel()

    header_words = [w for w in words if header_y_min < w.cy < header_y_max]
    data_words = [w for w in words if w.cy >= header_y_max]

    rows = cluster_rows(data_words, y_tol=y_tol)
    merged_rows = [merge_number_fragments(r) for r in rows]
    all_merged = [w for r in merged_rows for w in r]

    anchors = detect_value_columns(all_merged, gap_tol=10.0)
    columns = _map_columns(header_words, anchors)

    out_rows: list[AnlagenRow] = []
    for r in merged_rows:
        if not r:
            continue
        values: list[Optional[float]] = [None] * len(anchors)
        label_parts: list[str] = []
        for w in r:
            if is_de_number(w.text):
                col = min(range(len(anchors)), key=lambda i: abs(anchors[i] - w.x1))
                values[col] = parse_de_number(w.text)
            else:
                label_parts.append(w.text)
        label = " ".join(label_parts).strip()
        if label or any(v is not None for v in values):
            out_rows.append(AnlagenRow(label=label, values=values, y=sum(w.cy for w in r) / len(r)))

    return Anlagenspiegel(columns=columns, rows=out_rows)


def extract_anlagenspiegel(
    path: str | Path,
    *,
    anonymizer,
    page: int,
    **kwargs,
) -> Anlagenspiegel:
    """Reconstruct the Anlagenspiegel on a given 1-indexed PDF page.

    Row labels are anonymised via the shared anonymiser; numeric movements pass
    through unchanged.
    """
    import fitz

    from .pdf_words import words_from_page

    with fitz.open(path) as doc:
        words = words_from_page(doc[page - 1])
    asp = reconstruct_anlagenspiegel(words, **kwargs)
    for row in asp.rows:
        if row.label:
            row.label = anonymizer.anonymize(row.label).text
    return asp


# Movements emitted as Facts and how their year is assigned. Flow movements
# belong to the current year; the closing book value forms a time series, with
# the prior-year column mapped to the previous fiscal year.
_FLOW_MOVEMENTS = ("zugaenge", "abgaenge", "abschreibung_gj", "zuschreibungen")


def anlagenspiegel_facts(
    asp: Anlagenspiegel,
    *,
    company_id: str,
    fiscal_year: int,
    source_page: Optional[int] = None,
) -> list[Fact]:
    """Emit Facts for the analytically useful movements (capex, depreciation,
    book value). Book value yields two years (current + prior column)."""
    facts: list[Fact] = []
    counter = 0
    by_index = {c.index: c.movement for c in asp.columns}
    for row in asp.rows:
        if not row.has_values:
            continue
        for index, value in enumerate(row.values):
            if value is None:
                continue
            movement = by_index.get(index)
            if movement in _FLOW_MOVEMENTS:
                concept, year = movement, fiscal_year
            elif movement == "buchwert_gj":
                concept, year = "buchwert_ende", fiscal_year
            elif movement == "buchwert_vorjahr":
                concept, year = "buchwert_ende", fiscal_year - 1
            else:
                continue
            counter += 1
            facts.append(
                Fact(
                    fact_id=f"{company_id}_{year}_AS_{concept}_{counter}",
                    company_id=company_id,
                    fiscal_year=year,
                    statement=StatementType.ANLAGENSPIEGEL,
                    line_item_original_anonymized=row.label or None,
                    concept=concept,
                    value=value,
                    sign=-1 if value < 0 else 1,
                    source_page=source_page,
                    confidence=0.9,
                )
            )
    return facts
