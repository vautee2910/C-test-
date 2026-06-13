"""HGB concept knowledge base loading and label matching.

Generalised and shared across all German HGB statements — *not* per company.
A :class:`ConceptMatcher` maps a (possibly messy) line-item label to a canonical
concept by folding umlauts, stripping enumerators (``I.``, ``1.``, ``a)``), then
trying exact, prefix and fuzzy matches in that order.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# config/hgb_concepts.yaml at the repo root (src/fsx/hgb/concepts.py -> repo).
DEFAULT_HGB_CONCEPTS = Path(__file__).resolve().parents[3] / "config" / "hgb_concepts.yaml"

_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
# Leading enumerators: roman (i., ii.), arabic (1., 2)), single letters (a)).
# The separator may be ".", ")" or "," — some reports (or OCR) use "5," / "8,".
_ENUM_RE = re.compile(r"^\s*(?:[ivxlcdm]+[.,)]|\d+[.,)]|[a-z][.,)])\s+", re.IGNORECASE)


def has_leading_enumerator(label: str) -> bool:
    """True if the label starts with an enumerator like ``a)``, ``1.``, ``II.``.

    Used to tell a genuine wrapped-line continuation ("Kreditinstituten") from a
    new sub-item ("a) Raumkosten") so the two are not wrongly merged.
    """
    return bool(_ENUM_RE.match(label.strip() + " "))


def normalise_label(label: str) -> str:
    """Lowercase, strip enumerators and note refs, fold umlauts, drop punctuation."""
    s = label.strip().lower()
    # Drop parenthesised note references / clarifiers, e.g. "(1)", "(Stammkapital)".
    s = re.sub(r"\([^)]*\)", " ", s)
    # Strip possibly several stacked enumerators, e.g. "1. a) ...".
    while True:
        new = _ENUM_RE.sub("", s).strip()
        if new == s.strip():
            break
        s = new
    for k, v in _UMLAUTS.items():
        s = s.replace(k, v)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass(frozen=True)
class Concept:
    concept: str
    statement: str
    section: Optional[str]
    synonyms: tuple[str, ...]


@dataclass(frozen=True)
class ConceptMatch:
    concept: str
    statement: str
    section: Optional[str]
    confidence: float
    matched_synonym: str


def load_concepts(path: str | Path = DEFAULT_HGB_CONCEPTS) -> list[Concept]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    concepts: list[Concept] = []
    for entry in data.get("concepts", []):
        concepts.append(
            Concept(
                concept=entry["concept"],
                statement=entry.get("statement", "unknown"),
                section=entry.get("section"),
                synonyms=tuple(entry.get("synonyms", [])),
            )
        )
    return concepts


class ConceptMatcher:
    """Match line-item labels to canonical HGB concepts."""

    def __init__(
        self,
        concepts: list[Concept],
        fuzzy_threshold: float = 0.9,
        use_fuzzy: bool = False,
    ) -> None:
        self.concepts = concepts
        self.fuzzy_threshold = fuzzy_threshold
        # Fuzzy matching is off by default: prefix matching already absorbs minor
        # inflections, while loose fuzzy tends to bind sub-items to group
        # concepts. Prefer extending the shared KB synonyms over guessing.
        self.use_fuzzy = use_fuzzy
        # (normalised synonym, concept, original synonym) for each synonym.
        self._normalised: list[tuple[str, Concept, str]] = []
        for c in concepts:
            for syn in c.synonyms:
                norm = normalise_label(syn)
                if norm:
                    self._normalised.append((norm, c, syn))

    @classmethod
    def from_yaml(cls, path: str | Path = DEFAULT_HGB_CONCEPTS, **kw) -> "ConceptMatcher":
        return cls(load_concepts(path), **kw)

    def match(
        self,
        label: str,
        statement: Optional[str] = None,
        section: Optional[str] = None,
    ) -> Optional[ConceptMatch]:
        """Match ``label`` to a concept, optionally restricted to context.

        Passing the page's ``statement`` ("bilanz" / "guv") prevents
        cross-statement false matches (e.g. a GuV line mentioning
        "Anlagevermögens" binding to the Bilanz concept). Passing ``section``
        ("aktiva" / "passiva") disambiguates labels shared across sections, such
        as "Rechnungsabgrenzungsposten" on both Bilanz sides.
        """
        norm = normalise_label(label)
        if not norm:
            return None

        candidates = [
            (n, c, s)
            for (n, c, s) in self._normalised
            if (statement is None or c.statement == statement)
            and (section is None or c.section is None or c.section == section)
        ]

        # 1. Exact normalised match.
        for n, c, syn in candidates:
            if n == norm:
                return ConceptMatch(c.concept, c.statement, c.section, 1.0, syn)

        # 2. Prefix match either direction (handles truncated / inflected
        #    labels), guarded by a minimum length to avoid trivial collisions.
        best_prefix: Optional[tuple[float, Concept, str]] = None
        for n, c, syn in candidates:
            if len(n) < 6:
                continue
            if norm.startswith(n) or n.startswith(norm):
                score = min(len(norm), len(n)) / max(len(norm), len(n))
                cand = (0.9 * score + 0.1, c, syn)
                if best_prefix is None or cand[0] > best_prefix[0]:
                    best_prefix = cand
        if best_prefix is not None:
            _, c, syn = best_prefix
            return ConceptMatch(c.concept, c.statement, c.section, round(best_prefix[0], 3), syn)

        # 3. Optional fuzzy match (off by default).
        if self.use_fuzzy:
            best: Optional[tuple[float, Concept, str]] = None
            for n, c, syn in candidates:
                ratio = difflib.SequenceMatcher(None, norm, n).ratio()
                if best is None or ratio > best[0]:
                    best = (ratio, c, syn)
            if best is not None and best[0] >= self.fuzzy_threshold:
                ratio, c, syn = best
                return ConceptMatch(c.concept, c.statement, c.section, round(ratio, 3), syn)
        return None
