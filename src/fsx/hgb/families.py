"""Document-family registry: classify a document and pick its concept set.

Data-driven (``config/families.yaml``) so new families — insurance (RechVersV),
associations (e.V.), IFRS, cooperatives … — are added as *data*: marker phrases,
concept file(s) and a reconciliation set, with no code change. See
``config/families.yaml`` for the scoring rules.

Anonymisation is universal and runs before classification; only *domain*
extraction is family-specific. A document that matches no family is the special
``unknown`` family: extracted best-effort with the base concepts and flagged
(``name == "unknown"``) so a host can route or review it rather than trust it as
a statement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .concepts import _CONFIG_DIR, normalise_label

DEFAULT_FAMILIES = _CONFIG_DIR / "families.yaml"


@dataclass(frozen=True)
class Family:
    """One document family and everything the pipeline needs to handle it."""

    name: str
    concept_paths: tuple[Path, ...]
    reconcile: str = "hgb"
    priority: int = 0
    min_markers: int = 1
    markers: tuple[str, ...] = ()  # normalised marker phrases
    signature_concepts: frozenset[str] = frozenset()

    def marker_hits(self, folded_text: str) -> int:
        """How many of this family's markers occur in the folded document text."""
        return sum(1 for m in self.markers if m and m in folded_text)


@dataclass(frozen=True)
class FamilyRegistry:
    """All families plus the default/unknown handling."""

    families: tuple[Family, ...]
    default: str
    unknown: Family

    def classify_text(self, text: str) -> Family:
        """Highest-priority family meeting its ``min_markers``, else ``unknown``.

        Ties on priority are broken by marker-hit count, so the most specific and
        best-supported family wins (a bank sheet over the generic HGB base).
        """
        folded = normalise_label(text)
        scored = [
            (f.priority, f.marker_hits(folded), f)
            for f in self.families
            if f.marker_hits(folded) >= f.min_markers
        ]
        if not scored:
            return self.unknown
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return scored[0][2]

    def classify_with_scores(self, text: str) -> tuple[Family, dict[str, int]]:
        """Like :meth:`classify_text` but also return raw per-family marker hits.

        The hit map is the unfiltered evidence (every family's marker count,
        whether or not it met ``min_markers``), so a host doing hybrid /
        per-segment routing can see *why* a segment was (not) classified — e.g. a
        page that scores 1 marker just below the threshold. Returns the chosen
        family (``unknown`` when nothing qualifies) and ``{family_name: hits}``.
        """
        folded = normalise_label(text)
        hits = {f.name: f.marker_hits(folded) for f in self.families}
        qualifying = [
            (f.priority, hits[f.name], f)
            for f in self.families
            if hits[f.name] >= f.min_markers
        ]
        if not qualifying:
            return self.unknown, hits
        qualifying.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return qualifying[0][2], hits

    def by_name(self, name: str) -> Family:
        if name == self.unknown.name:
            return self.unknown
        for f in self.families:
            if f.name == name:
                return f
        return self.unknown

    def from_concepts(self, concepts) -> Family:
        """Identify the family from a set of extracted concept keys.

        Used by reconciliation, which sees facts but not the document text. Picks
        the highest-priority family whose ``signature_concepts`` are present; with
        none matching the base ``default`` family (its HGB rules) applies.
        """
        present = set(concepts)
        matches = [f for f in self.families if f.signature_concepts & present]
        if matches:
            return max(matches, key=lambda f: f.priority)
        return self.by_name(self.default)


def load_registry(path: str | Path = DEFAULT_FAMILIES) -> FamilyRegistry:
    """Load the family registry from YAML, resolving concept paths to the config dir."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    def _paths(names) -> tuple[Path, ...]:
        return tuple(_CONFIG_DIR / n for n in names)

    families = tuple(
        Family(
            name=e["name"],
            concept_paths=_paths(e.get("concepts", [])),
            reconcile=e.get("reconcile", "hgb"),
            priority=int(e.get("priority", 0)),
            min_markers=int(e.get("min_markers", 1)),
            markers=tuple(normalise_label(m) for m in e.get("markers", [])),
            signature_concepts=frozenset(e.get("signature_concepts", [])),
        )
        for e in data.get("families", [])
    )
    unknown = Family(
        name="unknown",
        concept_paths=_paths(data.get("unknown_concepts", ["hgb_concepts.yaml"])),
        reconcile="hgb",
    )
    return FamilyRegistry(families=families, default=data.get("default", "hgb"), unknown=unknown)


# Process-wide registry (the YAML is small and static).
REGISTRY = load_registry()
