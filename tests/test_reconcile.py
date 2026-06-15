"""Tests for the Level-2 reconciliation / plausibility checks."""

from __future__ import annotations

from fsx.hgb.reconcile import IdentityCheck, reconcile_facts
from fsx.schemas import Fact, StatementType


def _fact(concept, value, *, year=2024, page=1, scale=1, company="C1", statement=StatementType.GUV):
    return Fact(
        fact_id=f"{company}_{year}_{concept}_{page}",
        company_id=company,
        fiscal_year=year,
        statement=statement,
        concept=concept,
        value=value,
        scale=scale,
        source_page=page,
    )


def test_clean_facts_reconcile_without_issues():
    facts = [
        _fact("umsatzerloese", 1000.0),
        _fact("gesamtleistung", 1000.0),
    ]
    assert reconcile_facts(facts) == []


def test_conflicting_values_for_same_concept_flagged():
    # Same concept/year from two pages, one digit off -> error.
    facts = [
        _fact("abschreibungen", 7516.95, page=16),
        _fact("abschreibungen", 7316.95, page=23),
    ]
    issues = reconcile_facts(facts)
    assert len(issues) == 1
    assert issues[0].kind == "conflicting_value"
    assert issues[0].severity == "error"
    assert issues[0].concept == "abschreibungen"
    assert sorted(issues[0].values) == [7316.95, 7516.95]
    assert issues[0].pages == [16, 23]


def test_identical_repeated_values_are_not_conflicts():
    # The Jahresüberschuss legitimately repeats across pages with the same value.
    facts = [
        _fact("jahresueberschuss", 106453.89, page=18, statement=StatementType.GUV),
        _fact("jahresueberschuss", 106453.89, page=22, statement=StatementType.BILANZ),
    ]
    assert reconcile_facts(facts) == []


def test_rounding_within_tolerance_is_not_a_conflict():
    facts = [_fact("umsatzerloese", 1000.00, page=1), _fact("umsatzerloese", 1000.40, page=2)]
    assert reconcile_facts(facts) == []


def test_scale_is_applied_before_comparison():
    # 1000 (scale 1000 -> 1_000_000) vs 1_000_500 (scale 1) -> within tolerance.
    facts = [
        _fact("umsatzerloese", 1000.0, page=1, scale=1000),
        _fact("umsatzerloese", 1_000_500.0, page=2, scale=1),
    ]
    assert reconcile_facts(facts) == []


def test_broken_gesamtleistung_identity_flagged():
    # Both operands present and they still disagree -> flag.
    facts = [
        _fact("umsatzerloese", 1_208_447.55),
        _fact("bestandsveraenderung", 50_000.00),
        _fact("gesamtleistung", 731_476.36),
    ]
    issues = reconcile_facts(facts)
    assert [i.kind for i in issues] == ["broken_identity"]
    assert issues[0].severity == "warning"
    assert issues[0].concept == "gesamtleistung"


def test_gesamtleistung_not_flagged_when_only_umsatz_present():
    # Real case: Gesamtleistung 731.476,36 = Umsatz 1.208.447,55 minus a
    # Bestandsverminderung we did not capture -> must NOT be a false positive.
    facts = [
        _fact("umsatzerloese", 1_208_447.55),
        _fact("gesamtleistung", 731_476.36),
    ]
    assert [i.kind for i in reconcile_facts(facts)] == []


def test_identity_not_checked_when_components_missing():
    # bilanzsumme present but only one of its components -> below min_components.
    facts = [
        _fact("bilanzsumme", 999.0, statement=StatementType.BILANZ),
        _fact("summe_anlagevermoegen", 1.0, statement=StatementType.BILANZ),
    ]
    assert reconcile_facts(facts) == []


def test_satisfied_identity_produces_no_issue():
    facts = [
        _fact("loehne_gehaelter", 400.0),
        _fact("soziale_abgaben", 100.0),
        _fact("personalaufwand", 500.0),
    ]
    assert reconcile_facts(facts) == []


def test_errors_sort_before_warnings():
    facts = [
        _fact("umsatzerloese", 1000.0, page=1),
        _fact("bestandsveraenderung", 100.0, page=1),
        _fact("gesamtleistung", 5000.0, page=1),  # 5000 != 1100 -> warning
        _fact("abschreibungen", 100.0, page=1),
        _fact("abschreibungen", 200.0, page=2),  # conflicting (error)
    ]
    issues = reconcile_facts(facts)
    assert [i.severity for i in issues] == ["error", "warning"]


def test_custom_identity_respected():
    facts = [_fact("a", 10.0), _fact("b", 3.0), _fact("total", 99.0)]
    ident = (IdentityCheck("total", ("a", "b"), min_components=2),)
    issues = reconcile_facts(facts, identities=ident)
    assert [i.concept for i in issues] == ["total"]


def _bfact(concept, value, **kw):
    return _fact(concept, value, statement=StatementType.BILANZ, **kw)


def test_balanced_bilanz_has_no_imbalance_issue():
    facts = [
        _bfact("summe_anlagevermoegen", 1000.0),
        _bfact("summe_umlaufvermoegen", 500.0),
        _bfact("summe_eigenkapital", 900.0),
        _bfact("verbindlichkeiten", 600.0),
    ]  # Aktiva 1500 == Passiva 1500
    assert all(i.kind != "bilanz_imbalance" for i in reconcile_facts(facts))


def test_unbalanced_bilanz_is_flagged():
    facts = [
        _bfact("summe_anlagevermoegen", 1000.0),
        _bfact("summe_umlaufvermoegen", 500.0),
        _bfact("summe_eigenkapital", 900.0),
        _bfact("verbindlichkeiten", 700.0),
    ]  # Aktiva 1500 != Passiva 1600
    issues = [i for i in reconcile_facts(facts) if i.kind == "bilanz_imbalance"]
    assert len(issues) == 1 and issues[0].severity == "warning"
    assert issues[0].values == [1500.0, 1600.0]


def test_balance_check_skipped_when_a_subtotal_is_missing():
    facts = [
        _bfact("summe_anlagevermoegen", 1000.0),  # no summe_umlaufvermoegen
        _bfact("summe_eigenkapital", 900.0),
    ]
    assert all(i.kind != "bilanz_imbalance" for i in reconcile_facts(facts))


def test_balance_uses_group_total_not_double_counting_components():
    facts = [
        _bfact("summe_anlagevermoegen", 1000.0),
        _bfact("summe_umlaufvermoegen", 500.0),
        _bfact("summe_eigenkapital", 900.0),
        _bfact("rueckstellungen", 600.0),          # group total present...
        _bfact("steuerrueckstellungen", 600.0),    # ...so this component is ignored
    ]  # Passiva = 900 + 600 (group) = 1500 == Aktiva 1500
    assert all(i.kind != "bilanz_imbalance" for i in reconcile_facts(facts))


def test_low_confidence_fact_flagged_as_info():
    facts = [
        Fact(fact_id="x", company_id="C1", fiscal_year=2024, concept="soziale_abgaben",
             value=100.0, confidence=0.5, source_page=11),
    ]
    issues = reconcile_facts(facts)
    assert len(issues) == 1
    assert issues[0].kind == "low_confidence"
    assert issues[0].severity == "info"


def test_low_confidence_check_can_be_disabled():
    facts = [
        Fact(fact_id="x", company_id="C1", fiscal_year=2024, concept="umsatzerloese",
             value=100.0, confidence=0.5),
    ]
    assert reconcile_facts(facts, review_confidence=0.0) == []
