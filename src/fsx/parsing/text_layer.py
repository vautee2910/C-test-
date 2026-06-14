"""Detect whether a PDF already carries a usable text layer.

This is the gate in front of the OCR stage. Born-digital German annual
statements expose a rich text layer through PyMuPDF, so they must flow into the
existing :class:`~fsx.parsing.pymupdf_parser.PyMuPDFParser` *unchanged* — no OCR.
Scanned statements (image-only pages) yield essentially no extractable text and
need an OCR pass first.

The decision is a simple, tunable heuristic over per-page character counts so it
stays explainable and free of model dependencies:

* a *page* counts as "has text" when its stripped character count reaches
  ``min_chars_per_page`` (a handful of stray annotation characters on an
  otherwise scanned page should not count as a real text layer);
* the *document* is considered to have a text layer when the fraction of
  text-bearing pages reaches ``min_page_coverage``.

Mixed documents (a scanned cover page in front of a digital statement, or vice
versa) are handled downstream: OCRmyPDF's ``--skip-text`` only OCRs the pages
that lack a text layer and leaves the rest byte-for-byte intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

# Defaults tuned for A4 financial statements. A genuine text page carries
# hundreds of characters; a scanned page typically extracts 0. The thresholds
# sit well clear of both, so stray page numbers or watermark text on a scan do
# not masquerade as a text layer.
DEFAULT_MIN_CHARS_PER_PAGE = 16
DEFAULT_MIN_PAGE_COVERAGE = 0.5


@dataclass(frozen=True)
class TextLayerStats:
    """Per-document summary of extractable text, used to decide on OCR."""

    page_count: int
    pages_with_text: int
    total_chars: int
    min_chars_per_page: int

    @property
    def coverage(self) -> float:
        """Fraction of pages that carry a usable text layer (0.0–1.0)."""
        if self.page_count == 0:
            return 0.0
        return self.pages_with_text / self.page_count

    @property
    def avg_chars_per_page(self) -> float:
        if self.page_count == 0:
            return 0.0
        return self.total_chars / self.page_count


def page_text_lengths(path: str | Path) -> list[int]:
    """Return the stripped character count of each page's text layer."""
    lengths: list[int] = []
    with fitz.open(path) as doc:
        for page in doc:
            lengths.append(len(page.get_text("text").strip()))
    return lengths


def text_layer_stats(
    path: str | Path,
    *,
    min_chars_per_page: int = DEFAULT_MIN_CHARS_PER_PAGE,
) -> TextLayerStats:
    """Summarise the extractable text layer of ``path``."""
    lengths = page_text_lengths(path)
    pages_with_text = sum(1 for n in lengths if n >= min_chars_per_page)
    return TextLayerStats(
        page_count=len(lengths),
        pages_with_text=pages_with_text,
        total_chars=sum(lengths),
        min_chars_per_page=min_chars_per_page,
    )


def has_text_layer(
    path: str | Path,
    *,
    min_chars_per_page: int = DEFAULT_MIN_CHARS_PER_PAGE,
    min_page_coverage: float = DEFAULT_MIN_PAGE_COVERAGE,
) -> bool:
    """Whether ``path`` already has a text layer good enough to skip OCR.

    Returns ``True`` (skip OCR) when the fraction of text-bearing pages reaches
    ``min_page_coverage``. An empty / page-less PDF is treated as having no text
    layer.
    """
    stats = text_layer_stats(path, min_chars_per_page=min_chars_per_page)
    if stats.page_count == 0:
        return False
    return stats.coverage >= min_page_coverage


def needs_ocr(
    path: str | Path,
    *,
    min_chars_per_page: int = DEFAULT_MIN_CHARS_PER_PAGE,
    min_page_coverage: float = DEFAULT_MIN_PAGE_COVERAGE,
) -> bool:
    """Inverse of :func:`has_text_layer`: ``True`` when an OCR pass is needed."""
    return not has_text_layer(
        path,
        min_chars_per_page=min_chars_per_page,
        min_page_coverage=min_page_coverage,
    )
