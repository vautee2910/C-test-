"""Statement-heading vocabulary and HGB sign conventions, loaded from config.

The German heading phrases and the few sign rules are *data*
(``config/statements.yaml``); the detection and sign-application *logic* that
uses them stays in ``facts.py``. Shared across families — a family-specific
override can be layered later if a statement type ever needs different titles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..schemas import StatementType
from .concepts import _CONFIG_DIR

DEFAULT_STATEMENTS = _CONFIG_DIR / "statements.yaml"

# Heading text is folded to single-spaced lower case before phrase matching.
_FOLD = re.compile(r"[\s\-]+")


@dataclass(frozen=True)
class SignRule:
    """When ``concept`` and a ``flip_when`` keyword (but no ``not_when``) appear in
    the label, the printed value's economic sign is flipped."""

    concepts: frozenset[str]
    flip_when: tuple[str, ...]
    not_when: tuple[str, ...] = ()

    def applies(self, concept: str, label_low: str) -> bool:
        return (
            concept in self.concepts
            and any(k in label_low for k in self.flip_when)
            and not any(k in label_low for k in self.not_when)
        )


@dataclass(frozen=True)
class StatementRules:
    """Title phrases, key→enum binding, section bands and sign rules."""

    titles: tuple[tuple[str, tuple[str, ...]], ...]  # (key, phrases) most-specific first
    types: dict[str, StatementType]
    section_bands: dict[str, str]
    sign_rules: tuple[SignRule, ...]

    def detect(self, heading_text: str) -> str | None:
        """Infer a page's statement key from its heading text, or ``None``."""
        text = _FOLD.sub(" ", heading_text.lower())
        for key, phrases in self.titles:
            if any(p in text for p in phrases):
                return key
        return None

    def statement_type(self, key: str | None) -> StatementType:
        return self.types.get(key, StatementType.UNKNOWN)

    def flip_sign(self, concept: str, label: str) -> bool:
        low = label.lower()
        return any(r.applies(concept, low) for r in self.sign_rules)


def load_statement_rules(path: str | Path = DEFAULT_STATEMENTS) -> StatementRules:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    titles: list[tuple[str, tuple[str, ...]]] = []
    types: dict[str, StatementType] = {}
    for entry in data.get("statements", []):
        key = entry["key"]
        titles.append((key, tuple(_FOLD.sub(" ", t.lower()) for t in entry.get("titles", []))))
        types[key] = StatementType[entry.get("type", "UNKNOWN")]
    sign_rules = tuple(
        SignRule(
            concepts=frozenset(r.get("concepts", [])),
            flip_when=tuple(k.lower() for k in r.get("flip_when", [])),
            not_when=tuple(k.lower() for k in r.get("not_when", [])),
        )
        for r in data.get("sign_rules", [])
    )
    return StatementRules(
        titles=tuple(titles),
        types=types,
        section_bands=dict(data.get("section_bands", {})),
        sign_rules=sign_rules,
    )


# Process-wide rules (the YAML is small and static).
RULES = load_statement_rules()
