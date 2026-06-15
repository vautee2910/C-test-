"""Level-3 analysis *with* a quality view: features plus reconciliation.

:func:`build_features` stays a pure transform (facts -> features). This module
adds the run-level quality layer on top: it runs the Level-2 reconciliation
checks (:mod:`fsx.hgb.reconcile`) alongside feature building, tags each feature
that an issue touches, and returns both together in an :class:`AnalysisReport` so
a caller sees the metrics *and* whether to trust them in one object.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..hgb.reconcile import ReconciliationIssue, reconcile_facts
from ..schemas import AnalysisFeature, Fact
from .features import build_features
from .metrics import AnalysisConfig


class AnalysisReport(BaseModel):
    """Level-3 result: derived features plus the reconciliation findings."""

    company_id: str
    features: list[AnalysisFeature] = Field(default_factory=list)
    issues: list[ReconciliationIssue] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def ok(self) -> bool:
        """True when nothing reconciled badly (no error- or warning-level issue)."""
        return not any(i.severity in ("error", "warning") for i in self.issues)


def analyze_facts(
    facts: list[Fact],
    *,
    company_id: Optional[str] = None,
    config: Optional[AnalysisConfig] = None,
    rel_tol: float = 0.005,
    abs_tol: float = 1.0,
    review_confidence: float = 0.7,
) -> AnalysisReport:
    """Build features and reconcile, tagging features that an issue touches."""
    company_id = company_id or (facts[0].company_id if facts else "")
    features = build_features(facts, company_id=company_id, config=config)
    issues = reconcile_facts(
        facts, rel_tol=rel_tol, abs_tol=abs_tol, review_confidence=review_confidence
    )

    # Map a (concept, year) to the most severe issue message touching it, so the
    # feature carrying that concept can advertise the concern.
    by_key: dict[tuple[str, int], ReconciliationIssue] = {}
    for issue in issues:  # issues arrive most-severe first
        by_key.setdefault((issue.concept, issue.fiscal_year), issue)
    for feature in features:
        issue = by_key.get((feature.metric, feature.year))
        if issue is not None:
            feature.quality_issue = f"{issue.severity}: {issue.message}"

    return AnalysisReport(company_id=company_id, features=features, issues=issues)


def analyze_pdf(
    path: str | Path,
    *,
    anonymizer,
    company_id: str,
    fiscal_year: int,
    pages: Optional[list[int]] = None,
    config: Optional[AnalysisConfig] = None,
) -> AnalysisReport:
    """Convenience: PDF -> Facts -> features + reconciliation in one call."""
    from ..hgb.facts import facts_from_pdf

    facts = facts_from_pdf(
        path, anonymizer=anonymizer, company_id=company_id,
        fiscal_year=fiscal_year, pages=pages,
    )
    return analyze_facts(facts, company_id=company_id, config=config)
