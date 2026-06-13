"""Data contracts for the three pipeline levels.

These Pydantic models are the backbone of the pipeline. Every stage reads from
and writes to one of these levels:

* **Level 1 — raw extraction** (:class:`RawDocument`): everything that came out
  of the PDF, *already anonymised*, with page/coordinate provenance.
* **Level 2 — normalised facts** (:class:`Fact`): canonical HGB concepts with
  values, signs, scale and source references — the core for analysis.
* **Level 3 — analysis features** (:class:`AnalysisFeature`): derived metrics,
  ratios and year-over-year deltas with anomaly flags.

The models are intentionally permissive about optional provenance fields so a
parsing adapter can fill in what it has and leave the rest ``None``.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Shared enums
# --------------------------------------------------------------------------- #


class StatementType(str, Enum):
    """Sections of a German annual financial statement (Jahresabschluss)."""

    BILANZ = "bilanz"
    GUV = "guv"
    KAPITALFLUSSRECHNUNG = "kapitalflussrechnung"
    EIGENKAPITALSPIEGEL = "eigenkapitalspiegel"
    ANHANG = "anhang"
    ANLAGENSPIEGEL = "anlagenspiegel"
    VERBINDLICHKEITENSPIEGEL = "verbindlichkeitenspiegel"
    RUECKSTELLUNGSSPIEGEL = "rueckstellungsspiegel"
    LAGEBERICHT = "lagebericht"
    UNKNOWN = "unknown"


class PeriodType(str, Enum):
    YEAR = "year"
    QUARTER = "quarter"
    HALF_YEAR = "half_year"


class BlockType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    HEADING = "heading"
    FIGURE = "figure"


# A bounding box in PDF points: (x0, y0, x1, y1).
BBox = tuple[float, float, float, float]


# --------------------------------------------------------------------------- #
# Level 1 — raw extraction (anonymised)
# --------------------------------------------------------------------------- #


class TextBlock(BaseModel):
    """A block of text from the PDF, already anonymised."""

    type: BlockType = BlockType.TEXT
    text_anonymized: str
    bbox: Optional[BBox] = None


class Table(BaseModel):
    """A table extracted from the PDF.

    ``cells`` is a row-major grid of anonymised cell strings; richer cell
    metadata (spans, coordinates) can be layered on later without breaking this
    contract.
    """

    table_id: str
    caption_anonymized: Optional[str] = None
    cells: list[list[str]] = Field(default_factory=list)
    bbox: Optional[BBox] = None


class Page(BaseModel):
    page: int
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)


class RawDocument(BaseModel):
    """Level 1: the full anonymised extraction of one source PDF."""

    document_id: str
    company_id: str
    fiscal_year: int
    source_filename: Optional[str] = None
    pages: list[Page] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Level 2 — normalised facts
# --------------------------------------------------------------------------- #


class Fact(BaseModel):
    """Level 2: one normalised financial fact mapped to a canonical concept."""

    fact_id: str
    company_id: str
    fiscal_year: int
    period_type: PeriodType = PeriodType.YEAR
    statement: StatementType = StatementType.UNKNOWN
    section: Optional[str] = None
    line_item_original_anonymized: Optional[str] = None
    concept: str
    value: float
    currency: str = "EUR"
    scale: int = 1
    sign: int = 1
    source_page: Optional[int] = None
    source_table: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# --------------------------------------------------------------------------- #
# Level 3 — analysis features
# --------------------------------------------------------------------------- #


class FeatureFlag(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    STABLE = "stable"
    ANOMALY = "anomaly"


class AnalysisFeature(BaseModel):
    """Level 3: a derived comparison metric for one company/year."""

    company_id: str
    metric: str
    year: int
    value: Optional[float] = None
    formula: Optional[str] = None
    delta_abs_vs_prev_year: Optional[float] = None
    delta_pct_vs_prev_year: Optional[float] = None
    flag: Optional[FeatureFlag] = None
