"""Load the project-specific known-entities YAML and build an Anonymizer.

The config is the single most important anonymisation input for German annual
statements: re-identification usually runs via company names, subsidiaries,
register data, auditors and locations rather than classic PII. Keeping it in a
local, gitignored YAML lets each engagement ship its own dictionary without
touching code.

Supported shape (all keys optional)::

    company_aliases:        # aliases of the ONE main company -> one token
      - "Muster Maschinenbau GmbH"
      - "MMG"
    subsidiaries:           # each entry is its own company entity
      - "Muster Tochter GmbH"
    people:                 # each entry its own person
      - "Max Mustermann"
    locations: [...]
    auditors: [...]
    tax_advisors: [...]
    domains: [...]

    replacement_policy:     # optional token overrides, {n} = stable counter
      company: "[UNTERNEHMEN_{n}]"
      person:  "[PERSON_{n}]"

    regex:
      enabled_labels: [VAT_ID, IBAN, EMAIL, ...]   # optional allowlist
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .anonymize.detectors import REGEX_RULES, DictionaryDetector, DictionaryEntity, RegexDetector
from .anonymize.engine import Anonymizer
from .anonymize.labels import Label

# Dictionary category -> (canonical label, grouped?).
# "grouped" means all entries are aliases of ONE entity (share a token);
# otherwise each entry is its own entity.
_DICT_CATEGORIES: dict[str, tuple[Label, bool]] = {
    "company_aliases": (Label.COMPANY, True),
    "subsidiaries": (Label.COMPANY, False),
    "people": (Label.PERSON, False),
    "locations": (Label.LOCATION, False),
    "auditors": (Label.AUDITOR, False),
    "tax_advisors": (Label.TAX_ADVISOR, False),
    "domains": (Label.DOMAIN, False),
}

# Short policy keys -> canonical labels.
_POLICY_KEY_TO_LABEL: dict[str, Label] = {label.value.lower(): label for label in Label}
_POLICY_KEY_TO_LABEL.update(
    {
        "company": Label.COMPANY,
        "person": Label.PERSON,
        "location": Label.LOCATION,
        "auditor": Label.AUDITOR,
        "tax_advisor": Label.TAX_ADVISOR,
    }
)

# Regex labels enabled unless the config narrows them. DATE is excluded by
# default: in financial statements most dates are meaningful reporting dates.
_DEFAULT_REGEX_LABELS: set[Label] = {label for label, _ in REGEX_RULES} - {Label.DATE}


def load_config(path: str | Path) -> dict[str, Any]:
    """Read and parse the YAML config file (returns {} for an empty file)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data or {}


def _build_entities(config: dict[str, Any]) -> list[DictionaryEntity]:
    entities: list[DictionaryEntity] = []
    for category, (label, grouped) in _DICT_CATEGORIES.items():
        values = config.get(category) or []
        if not values:
            continue
        if grouped:
            entities.append(DictionaryEntity(f"{category}:0", label, values))
        else:
            for i, value in enumerate(values):
                entities.append(DictionaryEntity(f"{category}:{i}", label, [value]))
    return entities


def _build_token_overrides(config: dict[str, Any]) -> dict[Label, str]:
    overrides: dict[Label, str] = {}
    for key, template in (config.get("replacement_policy") or {}).items():
        label = _POLICY_KEY_TO_LABEL.get(str(key).lower())
        if label is not None:
            overrides[label] = template
    return overrides


def _build_regex_labels(config: dict[str, Any]) -> set[Label]:
    regex_cfg = config.get("regex") or {}
    enabled = regex_cfg.get("enabled_labels")
    if not enabled:
        return set(_DEFAULT_REGEX_LABELS)
    labels: set[Label] = set()
    for name in enabled:
        try:
            labels.add(Label(str(name).upper()))
        except ValueError:
            continue
    return labels


def build_anonymizer(config: dict[str, Any]) -> Anonymizer:
    """Construct an :class:`Anonymizer` from a parsed config dict."""
    entities = _build_entities(config)
    regex_labels = _build_regex_labels(config)
    detectors = [
        DictionaryDetector(entities),
        RegexDetector(enabled_labels=regex_labels),
    ]
    return Anonymizer(detectors, token_overrides=_build_token_overrides(config))


def load_anonymizer(path: str | Path) -> Anonymizer:
    """Convenience: load a YAML config from ``path`` and build the engine."""
    return build_anonymizer(load_config(path))
