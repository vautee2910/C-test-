"""Model-based PII detectors (statistical NER) as drop-in :class:`Detector`s.

The regex + dictionary core is precise but only finds *known* or *structured*
entities. A statistical Named-Entity-Recognition model raises **recall** by
catching person / organisation / location names that were never listed in the
engagement dictionary — without any company- or document-specific code.

This module ships a German spaCy NER detector. It is, by design:

* **fully local** — the model is loaded from the on-disk spaCy package / cache;
  inference sends nothing over the network. (Only the one-off model *download*
  needs egress; see ``docs/network-allowlist.md``.)
* **dependency-injectable** — :class:`SpacyNerDetector` takes an already-built
  ``nlp`` callable, so it can be unit-tested with a tiny fake and only imports
  ``spacy`` when you actually call :meth:`SpacyNerDetector.load`.
* **least-trusted on overlap** — model spans carry :data:`PRIORITY_MODEL`
  (below dictionary and regex), so a curated dictionary hit or a structured-id
  regex always wins an equal-length overlap. The model only adds *new* coverage.

Consistency note: model spans group repeated mentions of the same surface form
into one token (e.g. every "Max Mustermann" → ``[PERSON_1]``). An entity that is
*also* in the dictionary is resolved in the dictionary's favour wherever both
fire; the dictionary remains the place to curate shared synonyms.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from .labels import Label
from .spans import PiiSpan

# Model NER is the least trusted layer for equal-length overlaps: curated
# dictionary (1) and structured-id regex (2) outrank it.
PRIORITY_MODEL = 0

# spaCy German models (``de_core_news_*``) tag entities with these coarse types.
# MISC is intentionally dropped: in financial prose it is noisy (statute names,
# product terms) and would hurt precision more than it helps recall.
DEFAULT_SPACY_LABEL_MAP: dict[str, Label] = {
    "PER": Label.PERSON,
    "PERSON": Label.PERSON,
    "ORG": Label.COMPANY,
    "LOC": Label.LOCATION,
    "GPE": Label.LOCATION,
}


def _group_id(label: Label, surface: str) -> str:
    """Stable id grouping repeated mentions of one surface form into one token."""
    norm = re.sub(r"\s+", " ", surface).strip().casefold()
    return f"{label.value}:{norm}"


# A run of at least two letters (Unicode, so umlauts count) — a real word.
_ALPHA_RUN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
# A bare enumerator standing alone: "I.", "II.", "a)", "1." — structural noise
# that German statements are full of and that spaCy loves to mis-tag as a name.
_ENUM_ONLY = re.compile(r"^(?:[ivxlcdm]+|[a-z]|\d+)[.):]*$", re.IGNORECASE)


def _is_structural_noise(surface: str) -> bool:
    """True for surfaces that cannot be a person/org/location name.

    Domain-neutral: drops pure punctuation/numbers and lone enumerators. This is
    about *shape*, not vocabulary — keeping the detector reusable. Vocabulary
    stop-words (e.g. statement headings) are supplied separately by the caller.
    """
    s = surface.strip()
    if not _ALPHA_RUN.search(s):
        return True
    return bool(_ENUM_ONLY.match(s))


class SpacyNerDetector:
    """Emit :class:`PiiSpan`s from a spaCy NER pipeline.

    Args:
        nlp: a callable ``text -> Doc`` exposing ``Doc.ents`` (each entity has
            ``text``, ``label_``, ``start_char``, ``end_char``). In production
            this is a loaded spaCy ``Language``; in tests it is a small fake.
        label_map: spaCy entity type -> canonical :class:`Label`. Defaults to
            :data:`DEFAULT_SPACY_LABEL_MAP`.
        enabled_labels: optional allow-list of canonical labels to keep.
        min_length: discard entity surfaces shorter than this (drops stray
            single-character NER noise).
        stopwords: surfaces to never emit (case/whitespace-insensitive). The
            caller injects domain vocabulary here — e.g. statement headings like
            "Bilanz"/"Aktiva" that the model otherwise mis-tags as a company —
            so the detector itself stays domain-free.
        source: provenance tag recorded on every span.
    """

    def __init__(
        self,
        nlp: Callable[[str], Any],
        *,
        label_map: dict[str, Label] | None = None,
        enabled_labels: Iterable[Label] | None = None,
        min_length: int = 2,
        stopwords: Iterable[str] | None = None,
        source: str = "spacy",
    ) -> None:
        self._nlp = nlp
        self.label_map = dict(label_map) if label_map is not None else dict(DEFAULT_SPACY_LABEL_MAP)
        self.enabled_labels = set(enabled_labels) if enabled_labels is not None else None
        self.min_length = min_length
        self.stopwords = {re.sub(r"\s+", " ", w).strip().casefold() for w in (stopwords or ())}
        self.source = source

    @classmethod
    def load(
        cls,
        model: str = "de_core_news_lg",
        *,
        label_map: dict[str, Label] | None = None,
        enabled_labels: Iterable[Label] | None = None,
        min_length: int = 2,
        stopwords: Iterable[str] | None = None,
        source: str = "spacy",
    ) -> "SpacyNerDetector":
        """Load a local spaCy model and wrap it. Imports ``spacy`` lazily.

        Only the NER components are needed, so the tagger/parser/lemmatizer are
        disabled for speed. Raises a clear error if ``spacy`` or the model is
        missing — both are one-off, network-gated installs.
        """
        try:
            import spacy
        except Exception as exc:  # pragma: no cover - exercised only without dep
            raise RuntimeError(
                "spaCy is not installed; `pip install spacy` and download a "
                "German model (e.g. `python -m spacy download de_core_news_lg`)."
            ) from exc
        try:
            nlp = spacy.load(model, disable=["tagger", "parser", "lemmatizer", "attribute_ruler"])
        except Exception as exc:  # pragma: no cover - exercised only without model
            raise RuntimeError(
                f"spaCy model {model!r} is not available. Download it once with "
                f"`python -m spacy download {model}` (needs egress; see "
                f"docs/network-allowlist.md)."
            ) from exc
        return cls(
            nlp,
            label_map=label_map,
            enabled_labels=enabled_labels,
            min_length=min_length,
            stopwords=stopwords,
            source=source,
        )

    def detect(self, text: str) -> list[PiiSpan]:
        if not text:
            return []
        doc = self._nlp(text)
        spans: list[PiiSpan] = []
        for ent in getattr(doc, "ents", []):
            label = self.label_map.get(ent.label_)
            if label is None:
                continue
            if self.enabled_labels is not None and label not in self.enabled_labels:
                continue
            surface = ent.text.strip()
            if len(surface) < self.min_length:
                continue
            if _is_structural_noise(surface):
                continue
            if re.sub(r"\s+", " ", surface).casefold() in self.stopwords:
                continue
            spans.append(
                PiiSpan(
                    start=ent.start_char,
                    end=ent.end_char,
                    label=label,
                    text=ent.text,
                    source=self.source,
                    entity_id=_group_id(label, surface),
                    priority=PRIORITY_MODEL,
                )
            )
        return spans
