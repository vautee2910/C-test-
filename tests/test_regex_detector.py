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


@pytest.mark.parametrize(
    "phone",
    [
        "0911 1234567",
        "+49 911 1234567",
        "0049 911 1234567",
        "0231/9096-0",
        "030 12345678",
    ],
)
def test_real_phone_numbers_detected(phone):
    found = _labels(f"Tel. {phone} erreichbar")
    assert any(lbl == Label.PHONE for lbl, _ in found), phone


@pytest.mark.parametrize(
    "text",
    [
        # Regression: number columns from a real DATEV Kontennachweis that the
        # old phone regex wrongly captured (separators spanning newlines, or
        # contiguous account numbers).
        "Konto 023\n31 Saldo",
        "Position 0\n1549",
        "0690-98\n96",
        "0\n1400",
        "01400",
        "Betrag 0123456789 ",
        # Regression: thousands-grouped figures must not be eaten via the "0"
        # that follows a thousands separator.
        "Summe Eigenkapital 2.014.879,12",
        "2.083.667,31",
        "9.097.683",
        "Betrag 0,00 EUR",
        # Regression: space-grouped figures whose interior group starts with a
        # "0" (statistics tables, e.g. Destatis Jahrbuch) — "2 076 909" must not
        # have its "076 909" tail captured as a phone number.
        "Beschäftigte 2 076 909",
        "Anlagevermögen 1 093 098",
        "dar. weiblich 1 048 546",
    ],
)
def test_account_numbers_not_flagged_as_phone(text):
    found = _labels(text)
    assert not any(lbl == Label.PHONE for lbl, _ in found), text


def test_bare_domain_not_regex_detected():
    # "stpfl.EU" and friends must not be flagged; bare domains are dictionary-only.
    found = _labels("Der stpfl.EU Hinweis und and.EU Text")
    assert not any(lbl == Label.DOMAIN for lbl, _ in found)


def test_same_iban_shares_entity_id():
    det = RegexDetector()
    spans = det.detect("DE89370400440532013000 ... DE89 3704 0044 0532 0130 00")
    ibans = [s for s in spans if s.label == Label.IBAN]
    assert len(ibans) == 2
    # Differently formatted but identical IBAN -> same entity id (same token).
    assert ibans[0].entity_id == ibans[1].entity_id
