"""Definitions of derived HGB metrics and ratios — shared, generalised.

These are standard accounting aggregates/ratios (not per company). Each carries
the recipe to *compute* it from component concepts, used only when the value is
not already reported in the statement (see :mod:`fsx.analysis.features` for the
reported-else-computed resolution).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DerivedMetric:
    """An aggregate computed by summing component concepts.

    ``reported_concept`` is the concept key under which the statement may already
    report this aggregate directly; if a fact with that concept exists it is
    preferred over computing. ``required`` components must all be present to
    compute; ``optional`` ones are added when present.
    """

    name: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    reported_concept: str | None = None


@dataclass(frozen=True)
class Ratio:
    """A ratio numerator / denominator, by metric or concept name."""

    name: str
    numerator: str
    denominator: str
    use_abs: bool = True


# Standard German HGB aggregates.
DEFAULT_DERIVED: tuple[DerivedMetric, ...] = (
    DerivedMetric(
        name="bilanzsumme",
        required=("summe_anlagevermoegen", "summe_umlaufvermoegen"),
        optional=("rechnungsabgrenzungsposten_aktiv",),
        reported_concept="bilanzsumme",
    ),
    DerivedMetric(
        name="personalaufwand",
        required=("loehne_gehaelter", "soziale_abgaben"),
        reported_concept="personalaufwand",
    ),
    DerivedMetric(
        name="materialaufwand",
        required=("aufwand_rhb", "aufwand_bezogene_leistungen"),
        reported_concept="materialaufwand",
    ),
)

# Standard German HGB ratios (Kennzahlen).
DEFAULT_RATIOS: tuple[Ratio, ...] = (
    Ratio("eigenkapitalquote", "summe_eigenkapital", "bilanzsumme"),
    Ratio("anlagenintensitaet", "summe_anlagevermoegen", "bilanzsumme"),
    Ratio("personalaufwandsquote", "personalaufwand", "gesamtleistung"),
    Ratio("materialaufwandsquote", "materialaufwand", "gesamtleistung"),
)


@dataclass(frozen=True)
class AnalysisConfig:
    """Thresholds for year-over-year flagging.

    ``stable_band``: |relative change| below this counts as STABLE.
    ``anomaly_threshold``: |relative change| at/above this is flagged ANOMALY.
    Changes are measured on magnitudes, so a growing cost item flags as INCREASE
    just like growing revenue — which is what the "hidden costs" review wants.
    """

    stable_band: float = 0.02
    anomaly_threshold: float = 0.30
