"""Regex detector tests for German register / tax / bank / contact data."""

from __future__ import annotations

import pytest

from fsx.anonymize.detectors import RegexDetector
from fsx.anonymize.labels import Label


def _labels(text, **kw):
    det = RegexDetector(**kw)
    return {(s.label, s.text) for s in det.detect(text)}


@pytest.mark.parametrize(
    "text, label, match",
    [
        ("eingetragen im HRB 12345 beim", Label.COMMERCIAL_REGISTER, "HRB 12345"),
        ("Register HRA 987", Label.COMMERCIAL_REGISTER, "HRA 987"),
        ("USt-IdNr. DE123456789 gilt", Label.VAT_ID, "DE123456789"),
        ("Steuernummer 143/567/89012 ", Label.TAX_NUMBER, "143/567/89012"),
        ("Konto DE89370400440532013000 bei", Label.IBAN, "DE89370400440532013000"),
        ("Mail an info@muster-gmbh.de bitte", Label.EMAIL, "info@muster-gmbh.de"),
        ("Sitz: 80331 München, Deutschland", Label.ADDRESS, "80331 München"),
    ],
)
def test_detects_expected_identifier(text, label, match):
    assert (label, match) in _labels(text)


def test_url_detected():
    found = _labels("Siehe https://www.muster-maschinenbau.de/ir für Details")
    assert any(lbl == Label.URL for lbl, _ in found)


def test_date_excluded_when_not_in_enabled_labels():
    # The system default omits DATE; emulate that allowlist here.
    enabled = {Label.VAT_ID, Label.IBAN, Label.EMAIL}
    found = _labels("zum 31.12.2024 betrug", enabled_labels=enabled)
    assert not any(lbl == Label.DATE for lbl, _ in found)


def test_date_detected_when_enabled():
    found = _labels(
        "Stichtag 31.12.2024 sowie 15. März 2024",
        enabled_labels={Label.DATE},
    )
    dates = {t for lbl, t in found if lbl == Label.DATE}
    assert "31.12.2024" in dates
    assert "15. März 2024" in dates


def test_enabled_labels_filters_others_out():
    found = _labels("DE123456789 und info@x.de", enabled_labels={Label.EMAIL})
    assert all(lbl == Label.EMAIL for lbl, _ in found)


def test_same_iban_shares_entity_id():
    det = RegexDetector()
    spans = det.detect("DE89370400440532013000 ... DE89 3704 0044 0532 0130 00")
    ibans = [s for s in spans if s.label == Label.IBAN]
    assert len(ibans) == 2
    # Differently formatted but identical IBAN -> same entity id (same token).
    assert ibans[0].entity_id == ibans[1].entity_id
