"""Pluggable PII/entity detectors.

A detector takes raw text and returns :class:`PiiSpan` objects. The engine runs
all configured detectors and merges their output, so new layers (spaCy,
Presidio, the OpenAI Privacy Filter) only need to implement :class:`Detector`
and emit spans in the same canonical vocabulary.

This module ships the two network-free layers that form the reliable core for
German annual statements:

* :class:`DictionaryDetector` — project-specific known entities (company names,
  people, auditors, locations, domains). Usually the *most* reliable layer.
* :class:`RegexDetector` — structured German register / tax / bank / contact
  identifiers (HRB, USt-IdNr., IBAN, e-mail, …).
"""

from __future__ import annotations

import re
from typing import Iterable, Protocol

from .labels import Label
from .spans import PiiSpan

# Detector priorities used for overlap tie-breaking (higher wins on equal
# length). Structured-id regexes are trusted over a generic dictionary hit of
# the same length; multi-word dictionary names win on length anyway.
PRIORITY_REGEX = 2
PRIORITY_DICTIONARY = 1


class Detector(Protocol):
    """Anything that can find PII spans in text."""

    def detect(self, text: str) -> list[PiiSpan]:  # pragma: no cover - protocol
        ...


# --------------------------------------------------------------------------- #
# Dictionary detector
# --------------------------------------------------------------------------- #


class DictionaryEntity:
    """One real-world entity and the surface forms (aliases) that name it.

    All aliases of one entity share an ``entity_id`` so every mention collapses
    to the *same* pseudonym token.
    """

    def __init__(self, entity_id: str, label: Label, aliases: Iterable[str]) -> None:
        self.entity_id = entity_id
        self.label = label
        # De-duplicate, drop blanks, longest first so "Muster Maschinenbau GmbH"
        # is tried before "Muster Maschinenbau".
        self.aliases = sorted(
            {a.strip() for a in aliases if a and a.strip()},
            key=len,
            reverse=True,
        )


class DictionaryDetector:
    """Match configured known entities, case-insensitively, on word boundaries."""

    def __init__(self, entities: Iterable[DictionaryEntity]) -> None:
        self._compiled: list[tuple[DictionaryEntity, str, re.Pattern[str]]] = []
        for entity in entities:
            for alias in entity.aliases:
                # \b is unreliable next to non-word chars (e.g. domains), so use
                # lookarounds that treat any word char as a boundary breaker.
                pattern = re.compile(
                    rf"(?<!\w){re.escape(alias)}(?!\w)",
                    re.IGNORECASE,
                )
                self._compiled.append((entity, alias, pattern))

    def detect(self, text: str) -> list[PiiSpan]:
        spans: list[PiiSpan] = []
        for entity, _alias, pattern in self._compiled:
            for m in pattern.finditer(text):
                spans.append(
                    PiiSpan(
                        start=m.start(),
                        end=m.end(),
                        label=entity.label,
                        text=m.group(0),
                        source="dictionary",
                        entity_id=entity.entity_id,
                        priority=PRIORITY_DICTIONARY,
                    )
                )
        return spans


# --------------------------------------------------------------------------- #
# Regex detector
# --------------------------------------------------------------------------- #

MONTHS_DE = (
    "Januar|Februar|März|April|Mai|Juni|Juli|August|"
    "September|Oktober|November|Dezember"
)

# Order matters only for readability; overlaps are resolved by the engine.
REGEX_RULES: list[tuple[Label, re.Pattern[str]]] = [
    # HRB / HRA commercial register numbers.
    (Label.COMMERCIAL_REGISTER, re.compile(r"\bHR[AB]\s?\d{1,6}\b")),
    # German VAT id: DE + 9 digits.
    (Label.VAT_ID, re.compile(r"\bDE\s?\d{9}\b")),
    # German Steuernummer, e.g. 12/345/67890 or 123/456/78901.
    (Label.TAX_NUMBER, re.compile(r"\b\d{2,3}/\d{3}/\d{4,5}\b")),
    # IBAN: country + 2 check digits + 11..30 alnum (grouped in 4s or not).
    (Label.IBAN, re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,3})?\b")),
    # E-mail.
    (Label.EMAIL, re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # Full URL.
    (Label.URL, re.compile(r"\bhttps?://[^\s<>()\"]+", re.IGNORECASE)),
    # German phone numbers (+49 / 0 prefix, separators, extensions).
    (Label.PHONE, re.compile(r"(?:\+49|0)[\s/\-]?(?:\(?\d{2,5}\)?[\s/\-]?)\d{2,}(?:[\s/\-]?\d{1,6})*")),
    # PLZ + Ort (5-digit postal code followed by a capitalised place name).
    (Label.ADDRESS, re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\-]+(?:\s[A-ZÄÖÜ][A-Za-zÄÖÜäöüß.\-]+){0,2}")),
    # Long German date, e.g. "15. März 2024".
    (Label.DATE, re.compile(rf"\b\d{{1,2}}\.\s?(?:{MONTHS_DE})\s?\d{{4}}\b")),
    # Numeric date, e.g. 31.12.2024 (note: often a meaningful Bilanzstichtag —
    # disabled by default, see Anonymizer config).
    (Label.DATE, re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")),
    # Bare domain (lower priority; full URL/email win on length).
    (Label.DOMAIN, re.compile(r"\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+(?:de|com|org|net|eu|at|ch|io|gmbh)\b", re.IGNORECASE)),
]


def _normalise(text: str) -> str:
    """Strip whitespace+case so the same id formatted two ways shares a token.

    Used only to derive a regex span's ``entity_id`` (its token group), e.g. so
    ``DE89 3704 ...`` and ``DE89370400...`` collapse to one ``[IBAN_1]``.
    """
    return re.sub(r"\s+", "", text).upper()


class RegexDetector:
    """Detect structured German identifiers and contact data via regex.

    ``enabled_labels`` lets the caller switch categories off. ``None`` runs every
    rule. The system-wide default (see :data:`fsx.config._DEFAULT_REGEX_LABELS`)
    excludes ``DATE``, since in financial statements most dates are meaningful
    reporting dates rather than PII — but this low-level detector itself stays
    neutral and only filters when given an explicit ``enabled_labels`` set.
    """

    def __init__(self, enabled_labels: set[Label] | None = None) -> None:
        self.enabled_labels = enabled_labels

    def detect(self, text: str) -> list[PiiSpan]:
        spans: list[PiiSpan] = []
        for label, pattern in REGEX_RULES:
            if self.enabled_labels is not None and label not in self.enabled_labels:
                continue
            for m in pattern.finditer(text):
                matched = m.group(0)
                spans.append(
                    PiiSpan(
                        start=m.start(),
                        end=m.end(),
                        label=label,
                        text=matched,
                        source="regex",
                        entity_id=f"{label.value}:{_normalise(matched)}",
                        priority=PRIORITY_REGEX,
                    )
                )
        return spans
