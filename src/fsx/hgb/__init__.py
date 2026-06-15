"""HGB concept knowledge base and Level-2 fact generation (shared, generalised)."""

from __future__ import annotations

from .concepts import (
    DEFAULT_HGB_CONCEPTS,
    Concept,
    ConceptMatch,
    ConceptMatcher,
    classify_document_family,
    classify_segments,
    concept_paths_for_family,
    load_concepts,
    normalise_label,
)
from .families import REGISTRY, Family, FamilyRegistry, load_registry
from .anlagenspiegel import (
    Anlagenspiegel,
    AnlagenRow,
    MovementColumn,
    anlagenspiegel_facts,
    classify_column,
    extract_anlagenspiegel,
    reconstruct_anlagenspiegel,
)
from .facts import facts_from_pdf, facts_from_tables, split_period_values
from .reconcile import (
    DEFAULT_IDENTITIES,
    IdentityCheck,
    ReconciliationIssue,
    reconcile_facts,
)

__all__ = [
    "DEFAULT_HGB_CONCEPTS",
    "Concept",
    "ConceptMatch",
    "ConceptMatcher",
    "classify_document_family",
    "classify_segments",
    "concept_paths_for_family",
    "load_concepts",
    "normalise_label",
    "REGISTRY",
    "Family",
    "FamilyRegistry",
    "load_registry",
    "facts_from_tables",
    "facts_from_pdf",
    "split_period_values",
    "Anlagenspiegel",
    "AnlagenRow",
    "MovementColumn",
    "classify_column",
    "reconstruct_anlagenspiegel",
    "extract_anlagenspiegel",
    "anlagenspiegel_facts",
    "DEFAULT_IDENTITIES",
    "IdentityCheck",
    "ReconciliationIssue",
    "reconcile_facts",
]
