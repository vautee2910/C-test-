"""Config loader / anonymizer-builder tests, including the shipped example."""

from __future__ import annotations

from pathlib import Path

from fsx.config import build_anonymizer, load_anonymizer

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "config" / "known_entities.example.yaml"


def test_build_from_dict_groups_company_aliases():
    cfg = {
        "company_aliases": ["Muster Maschinenbau GmbH", "MMG"],
        "people": ["Max Mustermann"],
    }
    eng = build_anonymizer(cfg)
    res = eng.anonymize("Die Muster Maschinenbau GmbH (MMG); GF Max Mustermann")
    assert res.text.count("[UNTERNEHMEN_1]") == 2
    assert "[PERSON_1]" in res.text


def test_subsidiary_gets_next_company_number():
    cfg = {"company_aliases": ["Mutter AG"], "subsidiaries": ["Tochter GmbH"]}
    eng = build_anonymizer(cfg)
    res = eng.anonymize("Mutter AG hält Tochter GmbH")
    assert "[UNTERNEHMEN_1]" in res.text
    assert "[UNTERNEHMEN_2]" in res.text


def test_replacement_policy_override():
    cfg = {
        "company_aliases": ["Muster GmbH"],
        "replacement_policy": {"company": "[FIRMA_{n}]"},
    }
    eng = build_anonymizer(cfg)
    res = eng.anonymize("Muster GmbH")
    assert res.text == "[FIRMA_1]"


def test_regex_enabled_labels_narrowing():
    cfg = {"regex": {"enabled_labels": ["EMAIL"]}}
    eng = build_anonymizer(cfg)
    res = eng.anonymize("DE123456789 und info@x.de")
    assert "[EMAIL_1]" in res.text
    assert "DE123456789" in res.text  # VAT not enabled


def test_empty_config_still_runs_default_regex():
    eng = build_anonymizer({})
    res = eng.anonymize("Kontakt: info@muster.de")
    assert "[EMAIL_1]" in res.text


def test_default_build_keeps_reporting_dates():
    # DATE is excluded from the default regex set: a Bilanzstichtag stays intact.
    eng = build_anonymizer({})
    res = eng.anonymize("Bilanz zum 31.12.2024")
    assert "31.12.2024" in res.text
    assert "[DATUM_1]" not in res.text


def test_example_yaml_loads_and_anonymises():
    eng = load_anonymizer(EXAMPLE)
    res = eng.anonymize(
        "Die Muster Maschinenbau GmbH (MMG) in München, GF Max Mustermann, "
        "Web muster-maschinenbau.de"
    )
    assert "Muster Maschinenbau GmbH" not in res.text
    assert "Max Mustermann" not in res.text
    assert "München" not in res.text
    assert "[UNTERNEHMEN_1]" in res.text
