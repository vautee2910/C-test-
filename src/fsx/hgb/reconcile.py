"""Reconciliation / plausibility checks over Level-2 :class:`~fsx.schemas.Fact`.

Generic, document-agnostic sanity checks that surface *internal inconsistencies*
in extracted facts — the kind OCR digit errors and mis-extraction produce — so a
human can review them. These checks **never mutate** facts; they only report.

Two families:

* **Conflicting values** — the same concept for the same year extracted more than
  once (e.g. on a detail page *and* a summary page) with materially different
  values. The Level-3 resolver keeps the first and silently drops the rest
  (:mod:`fsx.analysis.features`), so without this a single mis-read digit would
  pass unnoticed (e.g. ``7.516,95`` read as ``7.316,95``).
* **Broken accounting identities** — a reported aggregate that does not equal the
  sum of its reported components (Bilanzsumme = Σ Anlage-/Umlaufvermögen + RAP,
  Gesamtleistung = Umsatz + Bestandsveränderung, Personal-/Materialaufwand).
  Evaluated only when the aggregate *and* enough components are present, so the
  check never invents a complaint from data that simply was not extracted.
* **Bilanz does not balance** — Aktiva total != Passiva total, summed from the
  section subtotals (so a missing or mis-read position surfaces). Checked only
  when both sides are anchored by their subtotals.

All amounts are compared at their effective scale (``value * scale``) with a
combined relative/absolute tolerance, so genuine rounding never trips a flag.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel

from ..schemas import Fact


@dataclass(frozen=True)
class IdentityCheck:
    """A reported aggregate that should equal the sum of its components."""

    total: str
    components: tuple[str, ...]
    min_components: int = 2


# Standard HGB additive identities. Each fires only when the ``total`` concept is
# present and at least ``min_components`` of its components are; the sum uses the
# signed values so cost/expense signs are respected.
DEFAULT_IDENTITIES: tuple[IdentityCheck, ...] = (
    IdentityCheck(
        "bilanzsumme",
        ("summe_anlagevermoegen", "summe_umlaufvermoegen", "rechnungsabgrenzungsposten_aktiv"),
        min_components=2,
    ),
    # Requires *both* operands: when only Umsatz is present the line may hide a
    # Bestandsveränderung (esp. a "Verminderung"/decrease) we did not capture, so
    # Gesamtleistung != Umsatz is then expected, not an error. Only flag when both
    # are known and still disagree.
    IdentityCheck("gesamtleistung", ("umsatzerloese", "bestandsveraenderung"), min_components=2),
    IdentityCheck("personalaufwand", ("loehne_gehaelter", "soziale_abgaben"), min_components=1),
    IdentityCheck("materialaufwand", ("aufwand_rhb", "aufwand_bezogene_leistungen"), min_components=1),
)

# Bank statements (RechKredV) report no HGB-style section subtotals, so the
# additive HGB identities never apply. Their balance is instead enforced by the
# *dual* bilanzsumme: "Summe der Aktiva" and "Summe der Passiva" both normalise to
# the ``bilanzsumme`` concept, so the generic conflicting-value check already
# flags a sheet whose two sides disagree. We deliberately do NOT sum the
# individual asset/liability positions — one missed position would raise a false
# imbalance (precision over recall).
BANK_IDENTITIES: tuple[IdentityCheck, ...] = ()

# Concepts that occur only on bank sheets; their presence marks a fact set as a
# bank statement. Excludes positions an industrial sheet also reports
# (verbindlichkeiten_kreditinstitute is an HGB passiva component; Zinsen appear in
# any GuV) so an industrial fact set is never mistaken for a bank one.
_BANK_CONCEPTS = frozenset({
    "barreserve", "forderungen_kreditinstitute", "forderungen_kunden",
    "verbindlichkeiten_kunden", "fonds_bankrisiken",
})


def family_from_facts(facts: list[Fact]) -> str:
    """``"bank"`` if any bank-specific concept is present, else ``"hgb"``."""
    return "bank" if any(f.concept in _BANK_CONCEPTS for f in facts) else "hgb"


class ReconciliationIssue(BaseModel):
    """One flagged inconsistency. Advisory — facts are never changed."""

    kind: str  # "conflicting_value" | "broken_identity" | "low_confidence"
    severity: str  # "error" | "warning" | "info"
    company_id: str
    fiscal_year: int
    concept: str
    message: str
    values: list[float] = []
    pages: list[int] = []


# Sort order so the most actionable issues surface first.
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _effective(fact: Fact) -> float:
    return fact.value * fact.scale


def _differ(a: float, b: float, rel_tol: float, abs_tol: float) -> bool:
    return abs(a - b) > max(abs_tol, rel_tol * max(abs(a), abs(b)))


def _conflicting_values(
    facts: list[Fact], rel_tol: float, abs_tol: float
) -> list[ReconciliationIssue]:
    groups: dict[tuple[str, int, str], list[Fact]] = defaultdict(list)
    for f in facts:
        groups[(f.company_id, f.fiscal_year, f.concept)].append(f)

    issues: list[ReconciliationIssue] = []
    for (company_id, year, concept), fs in groups.items():
        vals = [_effective(f) for f in fs]
        if not _differ(min(vals), max(vals), rel_tol, abs_tol):
            continue
        # Keep one representative value per distinct page so the message reads
        # cleanly even when a page repeats a value.
        seen: dict[int, float] = {}
        for f in fs:
            if f.source_page is not None:
                seen.setdefault(f.source_page, _effective(f))
        detail = ", ".join(
            f"{v:,.2f} (p{p})" for p, v in sorted(seen.items())
        ) or ", ".join(f"{v:,.2f}" for v in vals)
        issues.append(
            ReconciliationIssue(
                kind="conflicting_value",
                severity="error",
                company_id=company_id,
                fiscal_year=year,
                concept=concept,
                message=f"{concept} ({year}) extracted with conflicting values: {detail}",
                values=sorted({round(v, 2) for v in vals}),
                pages=sorted(seen),
            )
        )
    return issues


def _broken_identities(
    facts: list[Fact],
    identities: tuple[IdentityCheck, ...],
    rel_tol: float,
    abs_tol: float,
) -> list[ReconciliationIssue]:
    # company -> year -> concept -> (value, page); first fact wins, matching the
    # Level-3 resolver so the check sees the same numbers analysis would use.
    by: dict[tuple[str, int], dict[str, tuple[float, Optional[int]]]] = defaultdict(dict)
    for f in facts:
        by[(f.company_id, f.fiscal_year)].setdefault(f.concept, (_effective(f), f.source_page))

    issues: list[ReconciliationIssue] = []
    for (company_id, year), values in by.items():
        for ident in identities:
            if ident.total not in values:
                continue
            present = [c for c in ident.components if c in values]
            if len(present) < ident.min_components:
                continue
            total = values[ident.total][0]
            computed = sum(values[c][0] for c in present)
            if not _differ(total, computed, rel_tol, abs_tol):
                continue
            pages = sorted(
                {values[c][1] for c in [ident.total, *present] if values[c][1] is not None}
            )
            issues.append(
                ReconciliationIssue(
                    kind="broken_identity",
                    severity="warning",
                    company_id=company_id,
                    fiscal_year=year,
                    concept=ident.total,
                    message=(
                        f"{ident.total} ({year}) = {total:,.2f} does not match "
                        f"{' + '.join(present)} = {computed:,.2f}"
                    ),
                    values=[round(total, 2), round(computed, 2)],
                    pages=pages,
                )
            )
    return issues


# A balance sheet must satisfy Aktiva = Passiva. Both sides are summed from their
# *section subtotals*, not every line, to avoid double-counting a group total and
# its components. For the two passiva groups that may be reported either as one
# total or as individual positions, the group total wins when present, else the
# components are summed (mirrors the reported-else-computed rule in analysis).
_AKTIVA_TOTAL = ("summe_anlagevermoegen", "summe_umlaufvermoegen")
_AKTIVA_EXTRA = ("rechnungsabgrenzungsposten_aktiv",)
_PASSIVA_EXTRA = ("summe_eigenkapital", "sonderposten", "rechnungsabgrenzungsposten_passiv")
_RUECKSTELLUNGEN = (
    "rueckstellungen",
    ("pensionsrueckstellungen", "steuerrueckstellungen", "sonstige_rueckstellungen"),
)
_VERBINDLICHKEITEN = (
    "verbindlichkeiten",
    ("verbindlichkeiten_kreditinstitute", "erhaltene_anzahlungen",
     "verbindlichkeiten_lul", "sonstige_verbindlichkeiten"),
)


def _resolve_group(vals: dict[str, float], total: str, components: tuple[str, ...]) -> float:
    """Group total if reported, else the sum of whatever components are present."""
    if total in vals:
        return vals[total]
    return sum(vals[c] for c in components if c in vals)


def _bilanz_balance(
    facts: list[Fact], rel_tol: float, abs_tol: float
) -> list[ReconciliationIssue]:
    by: dict[tuple[str, int], dict[str, float]] = defaultdict(dict)
    for f in facts:
        by[(f.company_id, f.fiscal_year)].setdefault(f.concept, _effective(f))

    issues: list[ReconciliationIssue] = []
    for (company_id, year), vals in by.items():
        # Only check when both sides are anchored by their subtotals; otherwise an
        # absent subtotal would make a complete sheet look unbalanced.
        if not all(c in vals for c in (*_AKTIVA_TOTAL, "summe_eigenkapital")):
            continue
        aktiva = sum(vals[c] for c in _AKTIVA_TOTAL) + sum(vals.get(c, 0.0) for c in _AKTIVA_EXTRA)
        passiva = (
            sum(vals.get(c, 0.0) for c in _PASSIVA_EXTRA)
            + _resolve_group(vals, *_RUECKSTELLUNGEN)
            + _resolve_group(vals, *_VERBINDLICHKEITEN)
        )
        if not _differ(aktiva, passiva, rel_tol, abs_tol):
            continue
        issues.append(
            ReconciliationIssue(
                kind="bilanz_imbalance",
                severity="warning",
                company_id=company_id,
                fiscal_year=year,
                concept="bilanzsumme",
                message=(
                    f"Bilanz ({year}) does not balance: Aktiva {aktiva:,.2f} "
                    f"!= Passiva {passiva:,.2f} (Δ {aktiva - passiva:,.2f}) — "
                    f"a position is likely missing or mis-read."
                ),
                values=[round(aktiva, 2), round(passiva, 2)],
            )
        )
    return issues


def _low_confidence(
    facts: list[Fact], review_confidence: float
) -> list[ReconciliationIssue]:
    issues: list[ReconciliationIssue] = []
    for f in facts:
        if f.confidence >= review_confidence:
            continue
        page = f"p{f.source_page}" if f.source_page is not None else "?"
        issues.append(
            ReconciliationIssue(
                kind="low_confidence",
                severity="info",
                company_id=f.company_id,
                fiscal_year=f.fiscal_year,
                concept=f.concept,
                message=(
                    f"{f.concept} ({f.fiscal_year}) = {_effective(f):,.2f} matched "
                    f"with low confidence {f.confidence:.2f} on {page} — review."
                ),
                values=[round(_effective(f), 2)],
                pages=[f.source_page] if f.source_page is not None else [],
            )
        )
    return issues


def reconcile_facts(
    facts: list[Fact],
    *,
    rel_tol: float = 0.005,
    abs_tol: float = 1.0,
    review_confidence: float = 0.7,
    identities: Optional[tuple[IdentityCheck, ...]] = None,
) -> list[ReconciliationIssue]:
    """Return inconsistencies found across a company's extracted Facts.

    ``rel_tol`` / ``abs_tol`` set the match tolerance (an amount differs only if
    it is off by more than both ``abs_tol`` and ``rel_tol`` of the larger value).
    ``review_confidence`` surfaces facts matched below that confidence as
    ``info`` issues — a partial guard against OCR/extraction errors that do *not*
    happen to duplicate elsewhere (set to ``0`` to disable). The result is empty
    when everything reconciles, ordered by severity, then year and concept.

    The rule set adapts to the document family: bank statements (RechKredV) use
    the bank identities and skip the HGB section-subtotal balance check, which
    references concepts a bank sheet never reports. Pass ``identities`` explicitly
    to override the family default.
    """
    family = family_from_facts(facts)
    if identities is None:
        identities = BANK_IDENTITIES if family == "bank" else DEFAULT_IDENTITIES
    issues = _conflicting_values(facts, rel_tol, abs_tol)
    issues += _broken_identities(facts, identities, rel_tol, abs_tol)
    if family != "bank":
        issues += _bilanz_balance(facts, rel_tol, abs_tol)
    if review_confidence > 0:
        issues += _low_confidence(facts, review_confidence)
    issues.sort(key=lambda i: (_SEVERITY_RANK.get(i.severity, 9), i.fiscal_year, i.concept))
    return issues
