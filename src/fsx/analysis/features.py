"""Build Level-3 :class:`~fsx.schemas.AnalysisFeature` objects from Facts.

Produces, per metric and year:

* the **value** — taken from the statement if reported, otherwise computed from
  components (the ``formula`` field records which: ``"reported"`` or the recipe);
* the **year-over-year delta** (absolute and relative);
* an **anomaly flag** based on the magnitude change.

Raw line-item concepts get year-over-year features too, so the multi-year
comparison covers both individual positions and the derived Kennzahlen.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Optional

from ..schemas import AnalysisFeature, Fact, FeatureFlag
from .metrics import (
    DEFAULT_DERIVED,
    DEFAULT_RATIOS,
    AnalysisConfig,
    DerivedMetric,
    Ratio,
)

# name -> year -> (value, formula)
_ValueMap = dict[str, dict[int, tuple[float, str]]]


def _delta_and_flag(
    cur: float, prev: Optional[float], cfg: AnalysisConfig
) -> tuple[Optional[float], Optional[float], Optional[FeatureFlag]]:
    if prev is None:
        return (None, None, None)
    delta_abs = cur - prev
    if prev == 0:
        flag = FeatureFlag.ANOMALY if cur != 0 else FeatureFlag.STABLE
        return (delta_abs, None, flag)
    delta_pct = (cur - prev) / abs(prev)
    growth = (abs(cur) - abs(prev)) / abs(prev)
    if abs(growth) >= cfg.anomaly_threshold:
        flag = FeatureFlag.ANOMALY
    elif growth > cfg.stable_band:
        flag = FeatureFlag.INCREASE
    elif growth < -cfg.stable_band:
        flag = FeatureFlag.DECREASE
    else:
        flag = FeatureFlag.STABLE
    return (delta_abs, round(delta_pct, 6), flag)


def _resolve_values(
    facts: list[Fact],
    derived: tuple[DerivedMetric, ...],
    ratios: tuple[Ratio, ...],
) -> tuple[_ValueMap, list[int]]:
    values: _ValueMap = defaultdict(dict)
    for f in facts:
        # First fact for a (concept, year) wins; statements don't restate.
        values[f.concept].setdefault(f.fiscal_year, (f.value, "reported"))

    years = sorted({f.fiscal_year for f in facts})

    # Derived aggregates: reported value wins, else sum the present components
    # (at least min_present of them).
    for m in derived:
        for year in years:
            if year in values.get(m.name, {}):
                continue  # already reported
            present = [c for c in m.components if year in values.get(c, {})]
            if len(present) < m.min_present:
                continue
            total = sum(values[c][year][0] for c in present)
            values[m.name][year] = (total, " + ".join(present))

    # Ratios reference concepts or derived metrics resolved above.
    for r in ratios:
        for year in years:
            num = values.get(r.numerator, {}).get(year)
            den = values.get(r.denominator, {}).get(year)
            if num is None or den is None:
                continue
            n = abs(num[0]) if r.use_abs else num[0]
            d = abs(den[0]) if r.use_abs else den[0]
            if d == 0:
                continue
            values[r.name][year] = (n / d, f"{r.numerator} / {r.denominator}")

    return values, years


def build_features(
    facts: list[Fact],
    *,
    company_id: Optional[str] = None,
    derived: tuple[DerivedMetric, ...] = DEFAULT_DERIVED,
    ratios: tuple[Ratio, ...] = DEFAULT_RATIOS,
    config: Optional[AnalysisConfig] = None,
) -> list[AnalysisFeature]:
    """Turn a multi-year list of Facts into AnalysisFeatures."""
    if not facts:
        return []
    config = config or AnalysisConfig()
    company_id = company_id or facts[0].company_id

    values, _years = _resolve_values(facts, derived, ratios)

    features: list[AnalysisFeature] = []
    for name, by_year in values.items():
        for year in sorted(by_year):
            value, formula = by_year[year]
            prev = by_year.get(year - 1)
            delta_abs, delta_pct, flag = _delta_and_flag(
                value, prev[0] if prev else None, config
            )
            features.append(
                AnalysisFeature(
                    company_id=company_id,
                    metric=name,
                    year=year,
                    value=value,
                    formula=formula,
                    delta_abs_vs_prev_year=delta_abs,
                    delta_pct_vs_prev_year=delta_pct,
                    flag=flag,
                )
            )
    return features


def features_from_pdf(
    path: str | Path,
    *,
    anonymizer,
    company_id: str,
    fiscal_year: int,
    pages: Optional[list[int]] = None,
    config: Optional[AnalysisConfig] = None,
) -> list[AnalysisFeature]:
    """Convenience: PDF -> Facts -> AnalysisFeatures in one call."""
    from ..hgb.facts import facts_from_pdf

    facts = facts_from_pdf(
        path, anonymizer=anonymizer, company_id=company_id,
        fiscal_year=fiscal_year, pages=pages,
    )
    return build_features(facts, company_id=company_id, config=config)
