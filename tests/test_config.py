"""Config loader / anonymizer-builder tests, including the shipped example."""

from __future__ import annotations

from pathlib import Path

from fsx.anonymize.labels import Label
from fsx.anonymize.model_detectors import PrivacyFilterDetector, SpacyNerDetector
from fsx.config import build_anonymizer, load_anonymizer

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "config" / "known_entities.example.yaml"


class _FakeNlp:
    """Minimal spaCy stand-in: locates 'Globex SE' and yields one ORG entity."""

    def __call__(self, text):  # noqa: D401 - tiny fake
        start = text.find("Globex SE")
        ents = []
        if start >= 0:
            ents.append(
                type(
                    "Ent",
                    (),
                    {
                        "text": "Globex SE",
                        "label_": "ORG",
                        "start_char": start,
                        "end_char": start + len("Globex SE"),
                    },
                )()
            )
        return type("Doc", (), {"ents": ents})()


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


def test_models_disabled_by_default_adds_no_detector():
    # No 'models' section -> only dictionary + regex (2 detectors), and a name
    # not in the dictionary survives because no NER layer is wired in.
    eng = build_anonymizer({"company_aliases": ["Muster GmbH"]})
    assert len(eng.detectors) == 2
    res = eng.anonymize("Globex SE expandiert")
    assert "Globex SE" in res.text


def test_spacy_detector_wired_when_enabled():
    captured = {}

    def fake_loader(model, *, enabled_labels=None, min_length=2, stopwords=None):
        captured["model"] = model
        captured["labels"] = enabled_labels
        captured["min_length"] = min_length
        captured["stopwords"] = stopwords
        return SpacyNerDetector(_FakeNlp(), enabled_labels=enabled_labels, stopwords=stopwords)

    cfg = {
        "models": {
            "spacy": {
                "enabled": True,
                "model": "de_core_news_lg",
                "labels": ["COMPANY"],
                "min_length": 3,
            }
        }
    }
    eng = build_anonymizer(cfg, spacy_loader=fake_loader)

    assert captured["model"] == "de_core_news_lg"
    assert captured["labels"] == {Label.COMPANY}
    assert captured["min_length"] == 3
    # Domain stopwords are injected so the NER never redacts statement headings.
    assert "bilanz" in captured["stopwords"] and "aktiva" in captured["stopwords"]
    assert len(eng.detectors) == 3  # dict + regex + spacy

    res = eng.anonymize("Globex SE expandiert")
    assert "[UNTERNEHMEN_1]" in res.text
    assert "Globex SE" not in res.text


def test_spacy_loader_not_called_when_disabled():
    def boom(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("loader should not be called when disabled")

    cfg = {"models": {"spacy": {"enabled": False}}}
    eng = build_anonymizer(cfg, spacy_loader=boom)
    assert len(eng.detectors) == 2


def test_privacy_filter_wired_when_enabled():
    captured = {}

    def fake_loader(*, variant="q4f16", enabled_labels=None, stopwords=None, repo=None):
        captured.update(variant=variant, labels=enabled_labels, repo=repo)
        # A fixed predictor: one person token, exercised below.
        return PrivacyFilterDetector(
            lambda text: [("S-private_person", 0, 3)], enabled_labels=enabled_labels
        )

    cfg = {"models": {"privacy_filter": {"enabled": True, "variant": "q4", "labels": ["PERSON"]}}}
    eng = build_anonymizer(cfg, privacy_loader=fake_loader)

    assert captured["variant"] == "q4"
    assert captured["labels"] == {Label.PERSON}
    assert len(eng.detectors) == 3  # dict + regex + privacy-filter
    res = eng.anonymize("Max wohnt hier")
    assert res.text.startswith("[PERSON_1]")


def test_both_model_detectors_can_be_enabled_together():
    spacy_calls, pf_calls = [], []

    def fake_spacy(model, **k):
        spacy_calls.append(model)
        return SpacyNerDetector(lambda t: type("D", (), {"ents": []})())

    def fake_pf(**k):
        pf_calls.append(k.get("variant"))
        return PrivacyFilterDetector(lambda t: [])

    cfg = {"models": {"spacy": {"enabled": True}, "privacy_filter": {"enabled": True}}}
    eng = build_anonymizer(cfg, spacy_loader=fake_spacy, privacy_loader=fake_pf)
    assert len(eng.detectors) == 4  # dict + regex + spacy + privacy-filter
    assert spacy_calls and pf_calls


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
