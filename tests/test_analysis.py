"""Level-3 analysis-feature tests."""

from __future__ import annotations

import pytest

from fsx.analysis.features import build_features
from fsx.analysis.metrics import AnalysisConfig
from fsx.schemas import Fact, FeatureFlag


def _fact(concept, year, value):
    return Fact(
        fact_id=f"{concept}_{year}", company_id="C1", fiscal_year=year,
        concept=concept, value=value,
    )


def _by(features, metric, year):
    return next(f for f in features if f.metric == metric and f.year == year)


def test_year_over_year_delta_on_raw_concept():
    facts = [_fact("umsatzerloese", 2022, 1000.0), _fact("umsatzerloese", 2023, 1100.0)]
    feats = build_features(facts)
    cur = _by(feats, "umsatzerloese", 2023)
    assert cur.delta_abs_vs_prev_year == pytest.approx(100.0)
    assert cur.delta_pct_vs_prev_year == pytest.approx(0.1)
    assert cur.flag == FeatureFlag.INCREASE
    # The earliest year has no prior -> no delta.
    assert _by(feats, "umsatzerloese", 2022).flag is None


def test_computed_aggregate_when_not_reported():
    facts = [
        _fact("loehne_gehaelter", 2023, -600.0),
        _fact("soziale_abgaben", 2023, -60.0),
    ]
    feats = build_features(facts)
    pa = _by(feats, "personalaufwand", 2023)
    assert pa.value == pytest.approx(-660.0)
    assert pa.formula == "loehne_gehaelter + soziale_abgaben"


def test_reported_aggregate_wins_over_computed():
    # If the statement already reports personalaufwand, use it verbatim.
    facts = [
        _fact("personalaufwand", 2023, -662921.90),
        _fact("loehne_gehaelter", 2023, -600000.0),
        _fact("soziale_abgaben", 2023, -62921.90),
    ]
    feats = build_features(facts)
    pa = _by(feats, "personalaufwand", 2023)
    assert pa.value == pytest.approx(-662921.90)
    assert pa.formula == "reported"


def test_bilanzsumme_includes_optional_component():
    facts = [
        _fact("summe_anlagevermoegen", 2023, 2116685.83),
        _fact("summe_umlaufvermoegen", 2023, 599202.40),
        _fact("rechnungsabgrenzungsposten_aktiv", 2023, 24596.40),
    ]
    feats = build_features(facts)
    bs = _by(feats, "bilanzsumme", 2023)
    assert bs.value == pytest.approx(2740484.63)


def test_eigenkapitalquote_ratio():
    facts = [
        _fact("summe_eigenkapital", 2023, 2014879.12),
        _fact("summe_anlagevermoegen", 2023, 2116685.83),
        _fact("summe_umlaufvermoegen", 2023, 599202.40),
        _fact("rechnungsabgrenzungsposten_aktiv", 2023, 24596.40),
    ]
    feats = build_features(facts)
    ekq = _by(feats, "eigenkapitalquote", 2023)
    assert ekq.value == pytest.approx(2014879.12 / 2740484.63, rel=1e-6)
    assert ekq.formula == "summe_eigenkapital / bilanzsumme"


def test_cost_growth_flags_as_increase_even_though_negative():
    # A cost item growing in magnitude (more negative) is INCREASE, not DECREASE.
    facts = [_fact("materialaufwand", 2022, -100.0), _fact("materialaufwand", 2023, -150.0)]
    feats = build_features(facts)
    cur = _by(feats, "materialaufwand", 2023)
    assert cur.flag == FeatureFlag.ANOMALY  # +50% magnitude
    assert cur.delta_abs_vs_prev_year == pytest.approx(-50.0)


def test_stable_flag_within_band():
    facts = [_fact("umsatzerloese", 2022, 1000.0), _fact("umsatzerloese", 2023, 1010.0)]
    feats = build_features(facts)
    assert _by(feats, "umsatzerloese", 2023).flag == FeatureFlag.STABLE


def test_anomaly_threshold_configurable():
    facts = [_fact("umsatzerloese", 2022, 1000.0), _fact("umsatzerloese", 2023, 1200.0)]
    feats = build_features(facts, config=AnalysisConfig(anomaly_threshold=0.5))
    # +20% is below a 50% anomaly threshold -> just INCREASE.
    assert _by(feats, "umsatzerloese", 2023).flag == FeatureFlag.INCREASE


def test_empty_facts_yield_no_features():
    assert build_features([]) == []
