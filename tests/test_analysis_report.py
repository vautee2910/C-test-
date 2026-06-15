"""Tests for the Level-3 analysis report (features + reconciliation)."""

from __future__ import annotations

from fsx.analysis.report import AnalysisReport, analyze_facts
from fsx.schemas import Fact, StatementType


def _fact(concept, value, *, year=2024, page=1, company="C1", confidence=1.0,
          statement=StatementType.GUV):
    return Fact(
        fact_id=f"{company}_{year}_{concept}_{page}",
        company_id=company,
        fiscal_year=year,
        statement=statement,
        concept=concept,
        value=value,
        source_page=page,
        confidence=confidence,
    )


def test_clean_facts_report_is_ok():
    report = analyze_facts([
        _fact("umsatzerloese", 1000.0, year=2024),
        _fact("umsatzerloese", 1100.0, year=2025),
    ])
    assert isinstance(report, AnalysisReport)
    assert report.features  # built as usual
    assert report.issues == []
    assert report.ok and not report.has_errors
    assert all(f.quality_issue is None for f in report.features)


def test_conflicting_value_tags_the_feature_and_sets_error():
    report = analyze_facts([
        _fact("abschreibungen", 7516.95, page=16),
        _fact("abschreibungen", 7316.95, page=23),
    ])
    assert report.has_errors and not report.ok
    feat = next(f for f in report.features if f.metric == "abschreibungen" and f.year == 2024)
    assert feat.quality_issue is not None
    assert feat.quality_issue.startswith("error:")


def test_low_confidence_fact_surfaces_as_info_and_tags_feature():
    report = analyze_facts([_fact("soziale_abgaben", 147868.33, confidence=0.64)])
    kinds = {i.kind for i in report.issues}
    assert "low_confidence" in kinds
    # info-level alone does not make the run "not ok" (no error/warning).
    assert report.ok
    feat = next(f for f in report.features if f.metric == "soziale_abgaben")
    assert feat.quality_issue.startswith("info:")


def test_high_confidence_facts_are_not_flagged():
    report = analyze_facts([_fact("umsatzerloese", 1000.0, confidence=0.95)])
    assert all(i.kind != "low_confidence" for i in report.issues)
