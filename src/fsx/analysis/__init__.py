"""Level-3 analysis: derived metrics, ratios and year-over-year features."""

from __future__ import annotations

from .features import build_features, features_from_pdf
from .metrics import (
    DEFAULT_DERIVED,
    DEFAULT_RATIOS,
    AnalysisConfig,
    DerivedMetric,
    Ratio,
)
from .report import AnalysisReport, analyze_facts, analyze_pdf

__all__ = [
    "build_features",
    "features_from_pdf",
    "AnalysisConfig",
    "DerivedMetric",
    "Ratio",
    "DEFAULT_DERIVED",
    "DEFAULT_RATIOS",
    "AnalysisReport",
    "analyze_facts",
    "analyze_pdf",
]
