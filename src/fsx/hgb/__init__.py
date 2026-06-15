"""HGB concept knowledge base and Level-2 fact generation (shared, generalised)."""

from __future__ import annotations

from .concepts import (
    DEFAULT_HGB_CONCEPTS,
    Concept,
    ConceptMatch,
    ConceptMatcher,
    load_concepts,
    normalise_label,
)
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
    "load_concepts",
    "normalise_label",
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
