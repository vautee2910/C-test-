"""Turn reconstructed line items into Level-2 :class:`~fsx.schemas.Fact` objects.

Generalised: the period/value rule below follows the standard German nested
column convention, not this one document.

Column convention (per :mod:`fsx.extract`): figures are right-aligned and the
**rightmost** column is always the prior year. Within the remaining (current
year) columns, German reports place a line's own amount in the *inner* column
and a group subtotal in the *outer* column on the group's last sub-item. Taking
the *first* non-empty current-year column therefore yields the line's own value
(not a group subtotal that merely shares the row).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..schemas import Fact, PeriodType, StatementType
from .concepts import DEFAULT_HGB_CONCEPTS, ConceptMatcher, has_leading_enumerator

_STATEMENT_MAP = {
    "bilanz": StatementType.BILANZ,
    "guv": StatementType.GUV,
    "anlagenspiegel": StatementType.ANLAGENSPIEGEL,
    "anhang": StatementType.ANHANG,
}

# Result concepts that can be either a surplus or a deficit. In the Bilanz a
# deficit is printed as a *positive* equity-reducing amount (and the prior year
# of a "Jahresfehlbetrag" row as negative when it was actually a surplus), so
# when the line label says Fehlbetrag/Verlust the printed value's economic sign
# is flipped to make a loss negative and a surplus positive.
_RESULT_CONCEPTS = {"jahresueberschuss", "bilanzgewinn"}


def _is_loss_label(label: str) -> bool:
    low = label.lower()
    return "fehlbetrag" in low or "verlust" in low


def _panel_section(table, panel_index: int, statement: Optional[str], n_panels: int) -> Optional[str]:
    """Infer a Bilanz panel's section (aktiva / passiva).

    Prefers an explicit AKTIVA/PASSIVA marker in the panel's labels; otherwise
    falls back to the German convention (left panel = Aktiva) for a 2-panel
    balance sheet. Returns ``None`` for non-Bilanz statements.
    """
    if statement != "bilanz":
        return None
    blob = " ".join(it.label for it in table.items).lower()
    if "passiva" in blob:
        return "passiva"
    if "aktiva" in blob:
        return "aktiva"
    if n_panels >= 2:
        return "aktiva" if panel_index == 0 else "passiva"
    return None


def split_period_values(values: list[Optional[float]]) -> tuple[Optional[float], Optional[float]]:
    """Return ``(current_year, prior_year)`` from a row's column values.

    Rightmost column = prior year; current year = first non-empty among the rest
    (the line's own amount rather than a group subtotal sharing the row).
    """
    if not values:
        return (None, None)
    if len(values) == 1:
        return (values[0], None)
    prior = values[-1]
    current = next((v for v in values[:-1] if v is not None), None)
    return (current, prior)


def facts_from_tables(
    tables_by_page: dict[int, list],
    *,
    company_id: str,
    fiscal_year: int,
    matcher: ConceptMatcher,
    currency: str = "EUR",
    emit_prior_year: bool = True,
    statement_by_page: Optional[dict[int, str]] = None,
    scale_by_page: Optional[dict[int, int]] = None,
    min_confidence: float = 0.5,
) -> list[Fact]:
    """Map reconstructed tables to Facts for the current (and prior) year.

    Labels that wrap across two reconstruction rows (a label-only row followed
    by a *continuation* row) are rejoined before matching, so e.g.
    "Kassenbestand und Guthaben bei" + "Kreditinstituten" still resolves. A row
    starting with its own enumerator (``a) Raumkosten``) is a new sub-item, not
    a continuation, and is never merged. ``statement_by_page`` restricts matching
    to a page's statement to avoid cross-statement false matches.
    """
    statement_by_page = statement_by_page or {}
    scale_by_page = scale_by_page or {}
    facts: list[Fact] = []
    counter = 0
    for page in sorted(tables_by_page):
        statement = statement_by_page.get(page)
        scale = scale_by_page.get(page, 1)
        panels = tables_by_page[page]
        for ti, table in enumerate(panels):
            section = _panel_section(table, ti, statement, len(panels))
            pending_label: Optional[str] = None
            for item in table.items:
                if not item.has_values:
                    if item.label:
                        pending_label = item.label
                    continue

                label = item.label
                match = matcher.match(label, statement=statement, section=section)
                if match is None and pending_label and not has_leading_enumerator(item.label):
                    combined = f"{pending_label} {item.label}".strip()
                    found = matcher.match(combined, statement=statement, section=section)
                    if found is not None:
                        match, label = found, combined
                pending_label = None
                if match is None or match.confidence < min_confidence:
                    continue

                current, prior = split_period_values(item.values)
                periods = [(fiscal_year, current)]
                if emit_prior_year:
                    periods.append((fiscal_year - 1, prior))

                flip_sign = match.concept in _RESULT_CONCEPTS and _is_loss_label(label)

                for year, value in periods:
                    if value is None:
                        continue
                    if flip_sign:
                        value = -value
                    counter += 1
                    facts.append(
                        Fact(
                            fact_id=f"{company_id}_{year}_{match.concept}_{counter}",
                            company_id=company_id,
                            fiscal_year=year,
                            period_type=PeriodType.YEAR,
                            statement=_STATEMENT_MAP.get(match.statement, StatementType.UNKNOWN),
                            section=match.section,
                            line_item_original_anonymized=label,
                            concept=match.concept,
                            value=value,
                            currency=currency,
                            scale=scale,
                            sign=-1 if value < 0 else 1,
                            source_page=page,
                            source_table=f"P{page}_T{ti}",
                            confidence=match.confidence,
                        )
                    )
    return facts


# Statement title phrases -> canonical statement key. Matched after lower-casing
# and folding hyphens/whitespace to single spaces, so "Gewinn-und-Verlust-
# Rechnung" and "Gewinn- und Verlustrechnung" both hit. "Aktivseite"/
# "Passivseite" catch multi-page balance sheets whose only "Bilanz" title sits on
# an earlier page. Order: most specific first.
_STATEMENT_TITLES = [
    ("guv", ("gewinn und verlust",)),
    ("anlagenspiegel", ("anlagenspiegel", "entwicklung des anlagevermögens")),
    ("bilanz", ("bilanz", "aktivseite", "passivseite")),
    ("anhang", ("anhang",)),
]


def detect_statement(page_text: str) -> Optional[str]:
    """Infer a page's statement from its heading text, or ``None``."""
    text = re.sub(r"[\s\-]+", " ", page_text.lower())
    for statement, phrases in _STATEMENT_TITLES:
        if any(p in text for p in phrases):
            return statement
    return None


def _dominant_heading(page) -> str:
    """Return the largest-font text in the top of a PyMuPDF page.

    The statement title is set in a much larger font than body text or the nav
    breadcrumb, so the dominant heading isolates it reliably.
    """
    data = page.get_text("dict")
    height = page.rect.height
    spans: list[tuple[float, float, str]] = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span["text"].strip()
                if text and span["bbox"][1] < height * 0.55:
                    spans.append((round(span["size"], 1), span["bbox"][1], text))
    if not spans:
        return ""
    max_size = max(s[0] for s in spans)
    return " ".join(t for size, _y, t in sorted(spans, key=lambda s: s[1]) if size >= max_size - 0.5)


def detect_scale(page_text: str) -> int:
    """Infer the monetary scale from a page's unit header.

    "in Millionen €" / "Mio. €" -> 1_000_000; "in Tausend" / "T€" -> 1_000;
    otherwise 1. Carried onto ``Fact.scale`` (values stay as printed).
    """
    t = page_text.lower()
    if "mio" in t or "million" in t:
        return 1_000_000
    if "tsd" in t or "tausend" in t or "t€" in t or "t €" in t:
        return 1_000
    return 1


def facts_from_pdf(
    path: str | Path,
    *,
    anonymizer,
    company_id: str,
    fiscal_year: int,
    pages: Optional[list[int]] = None,
    concepts_path: str | Path = DEFAULT_HGB_CONCEPTS,
    matcher: Optional[ConceptMatcher] = None,
) -> list[Fact]:
    """Convenience: PDF -> reconstructed tables -> Facts, in one call.

    Detects each page's statement (Bilanz / GuV / …) from its heading and uses
    it to keep concept matching within the right statement.
    """
    # Lazy import keeps the HGB layer free of the fitz dependency unless used.
    import fitz

    from ..extract.pdf_words import extract_tables

    if matcher is None:
        matcher = ConceptMatcher.from_yaml(concepts_path)

    # Detect each page's statement from its dominant (largest-font) heading, not
    # from arbitrary text — many reports repeat a nav breadcrumb listing every
    # statement on every page. Carry the last seen statement forward so multi-
    # page statements (Bilanz Aktiv-/Passivseite) inherit it on continuation
    # pages that have no heading of their own.
    statement_by_page: dict[int, Optional[str]] = {}
    scale_by_page: dict[int, int] = {}
    current: Optional[str] = None
    with fitz.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            heading_stmt = detect_statement(_dominant_heading(page))
            if heading_stmt is not None:
                current = heading_stmt
            statement_by_page[index] = current
            scale_by_page[index] = detect_scale(page.get_text("text"))

    tables = extract_tables(path, anonymizer=anonymizer, pages=pages)
    return facts_from_tables(
        tables,
        company_id=company_id,
        fiscal_year=fiscal_year,
        matcher=matcher,
        statement_by_page=statement_by_page,
        scale_by_page=scale_by_page,
    )
