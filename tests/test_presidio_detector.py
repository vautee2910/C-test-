"""Adapter tests for the optional Presidio detector (fake analyzer, deterministic).

These never need the heavy Presidio/spaCy stack: the analysing callable is
injected, so mapping, score thresholding and the shared precision guards are
exercised with a tiny fake. The real-engine comparison lives in
``test_presidio_comparison.py`` (guarded/skipped when Presidio is absent).
"""

from __future__ import annotations

from dataclasses import dataclass

from fsx.anonymize import Anonymizer, PresidioDetector
from fsx.anonymize.labels import Label
from fsx.config import build_anonymizer


@dataclass
class _R:
    """Minimal stand-in for a Presidio RecognizerResult."""
    entity_type: str
    start: int
    end: int
    score: float = 0.9


def _fake(results_for):
    """Build an analyze(text) callable returning the given (type,start,end,score)."""
    def analyze(text):
        return [_R(*r) if not isinstance(r, _R) else r for r in results_for(text)]
    return analyze


def _spans(text, results, **kw):
    det = PresidioDetector(_fake(lambda t: results), **kw)
    return det.detect(text)


def test_maps_presidio_types_to_canonical_labels():
    text = "Acme GmbH zahlt an Max Mustermann"
    results = [("ORGANIZATION", 0, 9, 0.85), ("PERSON", 19, 33, 0.85)]
    spans = _spans(text, results)
    by = {s.text: s.label for s in spans}
    assert by["Acme GmbH"] == Label.COMPANY
    assert by["Max Mustermann"] == Label.PERSON


def test_low_score_results_dropped():
    text = "Vielleicht Acme GmbH"
    spans = _spans(text, [("ORGANIZATION", 11, 20, 0.30)], min_score=0.5)
    assert spans == []


def test_unmapped_entity_type_ignored():
    text = "Server 10.0.0.1 läuft"
    spans = _spans(text, [("IP_ADDRESS", 7, 15, 0.9)])  # not in default map
    assert spans == []


def test_stopword_suppresses_statement_vocabulary():
    text = "Bilanz zum Jahresende"
    spans = _spans(text, [("ORGANIZATION", 0, 6, 0.85)], stopwords=["bilanz"])
    assert spans == []


def test_lowercase_proper_noun_dropped():
    # spaCy/Presidio sometimes tag a lowercase token as ORG/PERSON; a German
    # proper noun is capitalised, so drop it.
    text = "dabei entstand nichts"
    spans = _spans(text, [("PERSON", 0, 5, 0.85)])
    assert spans == []


def test_repeated_mentions_share_entity_id():
    text = "Acme GmbH und nochmal Acme GmbH"
    spans = _spans(text, [("ORGANIZATION", 0, 9, 0.85), ("ORGANIZATION", 22, 31, 0.85)])
    assert len(spans) == 2
    assert spans[0].entity_id == spans[1].entity_id


def test_enabled_labels_filter():
    text = "Acme GmbH und Berlin"
    results = [("ORGANIZATION", 0, 9, 0.85), ("LOCATION", 14, 20, 0.85)]
    spans = _spans(text, results, enabled_labels={Label.LOCATION})
    assert {s.label for s in spans} == {Label.LOCATION}


def test_config_wires_presidio_via_injected_loader():
    # build_anonymizer must accept models.presidio and use the injected loader,
    # so wiring is testable without the heavy engine.
    captured = {}

    def fake_loader(**kwargs):
        captured.update(kwargs)
        return PresidioDetector(_fake(lambda t: [("PERSON", 0, 14, 0.9)]))

    cfg = {"models": {"presidio": {"enabled": True, "min_score": 0.6}},
           "replacement_policy": {"person": "[PERSON_{n}]"}}
    eng = build_anonymizer(cfg, presidio_loader=fake_loader)
    assert captured.get("min_score") == 0.6  # config forwarded
    res = eng.anonymize("Max Mustermann meldet sich")
    assert "[PERSON_1]" in res.text
    assert "Mustermann" not in res.text


def test_disabled_by_default():
    eng = build_anonymizer({})
    # no presidio detector unless models.presidio.enabled
    assert all(getattr(d, "source", "") != "presidio" for d in eng.detectors)
