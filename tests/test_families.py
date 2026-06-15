"""Tests for the data-driven document-family registry."""

from __future__ import annotations

from fsx.hgb.concepts import DEFAULT_BANK_CONCEPTS, DEFAULT_HGB_CONCEPTS
from fsx.hgb.families import REGISTRY, load_registry


def test_registry_loads_expected_families():
    names = {f.name for f in REGISTRY.families}
    assert {"hgb", "bank"} <= names
    assert REGISTRY.default == "hgb"
    assert REGISTRY.unknown.name == "unknown"


def test_more_specific_family_wins_on_priority():
    # A bank sheet also reads like a generic HGB statement (Bilanz, Umsatzerlöse);
    # the higher-priority bank family must win over the base hgb family.
    text = "Bilanz Umsatzerlöse Barreserve Forderungen an Kreditinstitute"
    fam = REGISTRY.classify_text(text)
    assert fam.name == "bank"
    assert DEFAULT_BANK_CONCEPTS in fam.concept_paths
    assert DEFAULT_HGB_CONCEPTS in fam.concept_paths  # base reused


def test_base_family_matches_plain_hgb_statement():
    fam = REGISTRY.classify_text("Bilanz Gewinn- und Verlustrechnung Umsatzerlöse")
    assert fam.name == "hgb"
    assert fam.concept_paths == (DEFAULT_HGB_CONCEPTS,)


def test_unmatched_document_is_unknown_with_base_concepts():
    fam = REGISTRY.classify_text("Mietvertrag über Wohnraum zwischen den Parteien.")
    assert fam.name == "unknown"
    # Best-effort base concepts, never a specific family's positions.
    assert DEFAULT_BANK_CONCEPTS not in fam.concept_paths


def test_from_concepts_identifies_family_for_reconcile():
    assert REGISTRY.from_concepts({"barreserve", "bilanzsumme"}).name == "bank"
    # No signature concept -> base hgb rules (not "unknown").
    assert REGISTRY.from_concepts({"umsatzerloese"}).name == "hgb"


def test_registry_is_reloadable_from_yaml():
    fresh = load_registry()
    assert {f.name for f in fresh.families} == {f.name for f in REGISTRY.families}
