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
from .concepts import DEFAULT_CONCEPTS, ConceptMatcher, has_leading_enumerator

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

# Bestandsveränderung (change in inventory of finished/unfinished goods) is signed
# by direction: a "Verminderung" (decrease) reduces the period's output and is
# negative; an "Erhöhung" (increase) is positive. The combined HGB caption
# "Erhöhung oder Verminderung …" is directionless, so it is left as printed.
_BESTAND_CONCEPT = "bestandsveraenderung"


def _is_bestand_decrease(label: str) -> bool:
    low = label.lower()
    if "erhöhung" in low or "erhohung" in low:
        return False
    return "verminderung" in low or "minderung" in low

# Carry-forward subtotal rows ("Übertrag") repeat a running page total where a
# Bilanz section spills across pages. They are never a reportable line item, so
# they must not be matched or emitted as facts.
_CARRYFORWARD_RE = re.compile(r"übertrag", re.IGNORECASE)

# Bilanz section bands. When one appears as its own row *inside* a single panel,
# it switches the active section: some small-entity balance sheets stack AKTIVA
# above PASSIVA in one column instead of side by side, so the panel-index
# heuristic in :func:`_panel_section` cannot tell them apart — an explicit band
# row in the body can.
_SECTION_BANDS = {"aktiva": "aktiva", "passiva": "passiva"}


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


def split_period_values(
    values: list[Optional[float]], has_prior: bool = True
) -> tuple[Optional[float], Optional[float]]:
    """Return ``(current_year, prior_year)`` from a row's column values.

    With a prior-year column: rightmost = prior year; current = first non-empty
    among the rest (the line's own amount, not a subtotal sharing the row).
    Without one (single-period report, e.g. an "EUR EUR" sub-amount/total
    layout): the rightmost value is the *current* year and there is no prior.
    """
    if not values:
        return (None, None)
    if not has_prior:
        present = [v for v in values if v is not None]
        return (present[-1] if present else None, None)
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
    has_prior_by_page: Optional[dict[int, bool]] = None,
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
    has_prior_by_page = has_prior_by_page or {}
    facts: list[Fact] = []
    counter = 0
    for page in sorted(tables_by_page):
        statement = statement_by_page.get(page)
        scale = scale_by_page.get(page, 1)
        has_prior = has_prior_by_page.get(page, True)
        panels = tables_by_page[page]
        for ti, table in enumerate(panels):
            section = _panel_section(table, ti, statement, len(panels))
            # The active section can be re-pointed mid-panel by an AKTIVA/PASSIVA
            # band row (stacked single-column balance sheets); seed it from the
            # panel-index heuristic.
            current_section = section
            pending_label: Optional[str] = None
            # A matched section header without a value of its own (e.g. bank
            # "FORDERUNGEN AN KREDITINSTITUTE") whose group total appears on a
            # later, label-less subtotal row.
            pending_header: Optional[tuple] = None
            for item in table.items:
                band = (
                    _SECTION_BANDS.get(item.label.strip().lower().rstrip(":"))
                    if item.label
                    else None
                )
                if band is not None and not item.has_values:
                    current_section = band
                    pending_label = None
                    pending_header = None
                    continue
                # Carry-forward subtotals ("Übertrag") are running page totals,
                # not line items — drop them whether or not they carry a value.
                if item.label and _CARRYFORWARD_RE.search(item.label):
                    pending_label = None
                    continue
                if not item.has_values:
                    if item.label:
                        pending_label = item.label
                        header = matcher.match(item.label, statement=statement, section=current_section)
                        if header is not None and header.confidence >= min_confidence:
                            pending_header = (header, item.label)
                    continue

                label = item.label
                match = matcher.match(label, statement=statement, section=current_section) if label else None
                if match is None and pending_label and label and not has_leading_enumerator(label):
                    # Rejoin a wrapped label. German breaks a word with a trailing
                    # hyphen ("... Leis-" / "tungen" -> "Leistungen"), so try the
                    # de-hyphenated join first, then the plain space join; keep the
                    # first that resolves to a concept.
                    pl = pending_label.rstrip()
                    candidates = []
                    if pl.endswith(("-", "‐", "‑")):
                        candidates.append(pl[:-1] + item.label.lstrip())
                    candidates.append(f"{pending_label} {item.label}".strip())
                    for combined in candidates:
                        found = matcher.match(combined, statement=statement, section=current_section)
                        if found is not None:
                            match, label = found, combined
                            break
                # Orphan subtotal: a value row with no usable label inherits the
                # pending section header (the group total it belongs to).
                orphan = False
                if (match is None or match.confidence < min_confidence) and not label.strip() and pending_header:
                    match, label = pending_header[0], pending_header[1]
                    pending_header = None
                    orphan = True
                pending_label = None
                if match is None or match.confidence < min_confidence:
                    continue
                # A labelled line item that itself resolves means the header's
                # children are being captured individually, so any later
                # label-less total is the grand total, not this header's group.
                if not orphan:
                    pending_header = None

                current, prior = split_period_values(item.values, has_prior=has_prior)
                periods = [(fiscal_year, current)]
                if emit_prior_year:
                    periods.append((fiscal_year - 1, prior))

                flip_sign = (
                    match.concept in _RESULT_CONCEPTS and _is_loss_label(label)
                ) or (
                    match.concept == _BESTAND_CONCEPT and _is_bestand_decrease(label)
                )

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
    # Account-level detail pages (Kontennachweis) must not be matched as a
    # summary statement; tagging them with their own key yields no concepts.
    ("kontennachweis", ("kontennachweis",)),
    ("guv", ("gewinn und verlust",)),
    ("anlagenspiegel", ("anlagenspiegel", "entwicklung des anlagevermögens")),
    # Many balance sheets set the AKTIVA/PASSIVA band in a *larger* font than the
    # "Bilanz zum …" title, so the dominant-heading detector sees only the band;
    # treat bare "aktiva"/"passiva" as a Bilanz title too. (Kontennachweis pages
    # also carry these bands but are tagged earlier by their own keyword, so they
    # never reach here.)
    ("bilanz", ("bilanz", "aktivseite", "passivseite", "aktiva", "passiva")),
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


def detect_has_prior_year(page_text: str, fiscal_year: int) -> bool:
    """True if the page shows a prior-year column (a "Vorjahr"/prior-year date).

    Single-period statements (no comparative column) otherwise get their values
    mis-dated to the prior year by the rightmost-is-prior rule.
    """
    t = page_text.lower()
    return ("vorjahr" in t) or (str(fiscal_year - 1) in page_text)


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
    concepts_path: str | Path | tuple = DEFAULT_CONCEPTS,
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
    prior_by_page: dict[int, bool] = {}
    current: Optional[str] = None
    with fitz.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text")
            # A Kontennachweis page overrides the heading regardless of font size
            # (its title is often smaller than the AKTIVA/PASSIVA band).
            if "kontennachweis" in text.lower():
                current = "kontennachweis"
            else:
                heading_stmt = detect_statement(_dominant_heading(page))
                if heading_stmt is not None:
                    current = heading_stmt
            statement_by_page[index] = current
            scale_by_page[index] = detect_scale(text)
            prior_by_page[index] = detect_has_prior_year(text, fiscal_year)

    tables = extract_tables(path, anonymizer=anonymizer, pages=pages)
    return facts_from_tables(
        tables,
        company_id=company_id,
        fiscal_year=fiscal_year,
        matcher=matcher,
        statement_by_page=statement_by_page,
        scale_by_page=scale_by_page,
        has_prior_by_page=prior_by_page,
    )
