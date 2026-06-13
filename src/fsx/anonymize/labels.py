"""Canonical PII / entity labels and their default replacement tokens.

The label taxonomy is a superset that covers both the German annual-statement
needs (company, auditor, commercial register, VAT id, …) and the generic PII
categories a later model layer (spaCy / Presidio / OpenAI Privacy Filter) would
emit. Keeping one canonical enum means every detector — regardless of source —
merges into the same vocabulary.

Each label has a default token *template* with an ``{n}`` placeholder. The
engine fills ``{n}`` with a per-label, per-entity counter so the *same* entity
always maps to the *same* token within a document (e.g. every mention of one
company becomes ``[UNTERNEHMEN_1]``), which keeps the anonymised text usable for
analysis.
"""

from __future__ import annotations

from enum import Enum


class Label(str, Enum):
    # Organisation / people / place (typically dictionary-driven)
    COMPANY = "COMPANY"
    PERSON = "PERSON"
    LOCATION = "LOCATION"
    AUDITOR = "AUDITOR"
    TAX_ADVISOR = "TAX_ADVISOR"

    # German register / tax / bank identifiers (regex-driven)
    COMMERCIAL_REGISTER = "COMMERCIAL_REGISTER"  # HRB / HRA
    VAT_ID = "VAT_ID"  # USt-IdNr.
    TAX_NUMBER = "TAX_NUMBER"  # Steuernummer
    IBAN = "IBAN"
    BIC = "BIC"
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"

    # Contact / web (regex-driven)
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    URL = "URL"
    DOMAIN = "DOMAIN"
    ADDRESS = "ADDRESS"  # PLZ + Ort

    # Other
    DATE = "DATE"
    SECRET = "SECRET"


# Default token templates. ``{n}`` is replaced by a stable per-entity counter.
DEFAULT_TOKENS: dict[Label, str] = {
    Label.COMPANY: "[UNTERNEHMEN_{n}]",
    Label.PERSON: "[PERSON_{n}]",
    Label.LOCATION: "[ORT_{n}]",
    Label.AUDITOR: "[PRUEFER_{n}]",
    Label.TAX_ADVISOR: "[STEUERBERATER_{n}]",
    Label.COMMERCIAL_REGISTER: "[REGISTER_{n}]",
    Label.VAT_ID: "[USTID_{n}]",
    Label.TAX_NUMBER: "[STEUERNR_{n}]",
    Label.IBAN: "[IBAN_{n}]",
    Label.BIC: "[BIC_{n}]",
    Label.ACCOUNT_NUMBER: "[KONTO_{n}]",
    Label.EMAIL: "[EMAIL_{n}]",
    Label.PHONE: "[TELEFON_{n}]",
    Label.URL: "[URL_{n}]",
    Label.DOMAIN: "[DOMAIN_{n}]",
    Label.ADDRESS: "[ADRESSE_{n}]",
    Label.DATE: "[DATUM_{n}]",
    Label.SECRET: "[SECRET_{n}]",
}


def token_template(label: Label, overrides: dict[Label, str] | None = None) -> str:
    """Return the token template for ``label``, honouring policy overrides."""
    if overrides and label in overrides:
        return overrides[label]
    return DEFAULT_TOKENS[label]
