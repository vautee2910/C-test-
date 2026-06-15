"""Tests for the config-driven statement titles and sign rules."""

from __future__ import annotations

from fsx.hgb.statements import RULES, load_statement_rules
from fsx.schemas import StatementType


def test_detect_statement_from_config_titles():
    assert RULES.detect("Gewinn-und-Verlust-Rechnung") == "guv"
    assert RULES.detect("Aktivseite  Mio €") == "bilanz"
    assert RULES.detect("KONTENNACHWEIS zur Bilanz") == "kontennachweis"
    assert RULES.detect("Entwicklung des Anlagevermögens") == "anlagenspiegel"
    assert RULES.detect("Allgemeine Auftragsbedingungen") is None


def test_statement_type_binding():
    assert RULES.statement_type("bilanz") == StatementType.BILANZ
    assert RULES.statement_type("kontennachweis") == StatementType.UNKNOWN
    assert RULES.statement_type(None) == StatementType.UNKNOWN


def test_sign_rules_from_config():
    # Result concept: flipped only for the loss variant.
    assert RULES.flip_sign("jahresueberschuss", "Jahresfehlbetrag") is True
    assert RULES.flip_sign("jahresueberschuss", "Jahresüberschuss") is False
    # Bestandsveränderung: decrease flips, but the combined caption is left as is.
    assert RULES.flip_sign("bestandsveraenderung", "Verminderung des Bestands") is True
    assert RULES.flip_sign("bestandsveraenderung", "Erhöhung oder Verminderung") is False
    # A concept with no sign rule is never flipped.
    assert RULES.flip_sign("umsatzerloese", "Verlust") is False


def test_rules_reloadable_from_yaml():
    fresh = load_statement_rules()
    assert {k for k, _ in fresh.titles} == {k for k, _ in RULES.titles}
    assert fresh.section_bands == RULES.section_bands
