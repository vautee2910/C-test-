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


# openai/privacy-filter PII categories -> canonical labels. Person/contact PII
# only — the model has no organisation class, so it complements (does not
# replace) the dictionary/ORG layers.
DEFAULT_PRIVACY_LABEL_MAP: dict[str, Label] = {
    "private_person": Label.PERSON,
    "private_address": Label.ADDRESS,
    "private_email": Label.EMAIL,
    "private_phone": Label.PHONE,
    "private_url": Label.URL,
    "private_date": Label.DATE,
    "account_number": Label.ACCOUNT_NUMBER,
    "secret": Label.SECRET,
}


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


def _cuts_word(text: str, start: int, end: int) -> bool:
    """True if ``[start:end)`` slices through a word (a sub-word fragment).

    Subword-token models can tag only part of a word — e.g. labelling "Ers" of
    "Erschienen" as a person, which would rewrite it to "[PERSON]chienen". A real
    entity is bounded by non-letters, so reject a span whose immediate neighbour
    on either side is a letter (precision over recall).
    """
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return before.isalpha() or after.isalpha()


# A leading structural enumerator ("B.", "I.", "1.", "a)") + trailing punctuation.
# A NER model often tags a heading *with* its enumerator ("B. Umlaufvermögen") or
# an abbreviation *with* its dot ("Abschr."), which a plain stopword equality test
# misses. Folding these structural decorations away — shape only, no vocabulary —
# lets one bare stopword ("umlaufvermögen") cover those forms too.
_LEADING_ENUM = re.compile(r"^(?:[ivxlcdm]+|[a-z]|\d+)[.):\]]+\s+", re.IGNORECASE)
_TRAILING_PUNCT = re.compile(r"[.,;:]+$")

# Labels whose value is a proper noun — always capitalised in German. A span with
# no uppercase letter cannot be one; it is general-language NER noise ("dabei", a
# line-wrapped "gesetzli chen"), so drop it (precision over recall).
_PROPER_NOUN_LABELS = frozenset({Label.PERSON, Label.COMPANY, Label.LOCATION})


def _stopword_match(surface: str, stopwords: set[str]) -> bool:
    """True if ``surface`` — or its enumerator/punctuation-stripped form — is a stopword.

    Domain vocabulary is injected as bare words; this folds the structural
    decorations a model tends to glue on (leading enumerator, trailing
    punctuation) so a single bare stopword still matches. Purely structural, so
    the detector stays domain-free.
    """
    if not stopwords:
        return False
    norm = re.sub(r"\s+", " ", surface).strip().casefold()
    stripped = re.sub(r"\s+", " ", _LEADING_ENUM.sub("", surface)).strip().casefold()
    candidates = {
        norm, _TRAILING_PUNCT.sub("", norm),
        stripped, _TRAILING_PUNCT.sub("", stripped),
    }
    return bool(candidates & stopwords)


def _lacks_uppercase(surface: str) -> bool:
    """True for an alphabetic surface that carries no uppercase letter."""
    return any(c.isalpha() for c in surface) and not any(c.isupper() for c in surface)


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

    # Statistical model layer: heavy (per-call inference) and recall-oriented.
    # The engine can skip it on a per-call basis (e.g. on dense table cells).
    is_model = True

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
            if label in _PROPER_NOUN_LABELS and _lacks_uppercase(surface):
                continue
            if _stopword_match(surface, self.stopwords):
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


# --------------------------------------------------------------------------- #
# openai/privacy-filter — purpose-built PII token classifier (BIOES tags)
# --------------------------------------------------------------------------- #


def _privacy_spans(
    raw_labels: list[str], offsets: list[tuple[int, int]], text: str
) -> list[tuple[str, int, int]]:
    """Decode per-token BIOES labels into ``(category, start, end)`` char spans.

    Pure and model-free so it is unit-testable. ``B``/``S`` (or a category
    change) starts a new span; ``I``/``E`` of the same category extend it; ``O``
    and zero-width tokens (special tokens) close it. Leading/trailing whitespace
    is trimmed off each span.
    """
    spans: list[tuple[str, int, int]] = []
    cur: tuple[str, int, int] | None = None

    def flush() -> None:
        nonlocal cur
        if cur is None:
            return
        cat, s, e = cur
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if s < e:
            spans.append((cat, s, e))
        cur = None

    for lab, (s, e) in zip(raw_labels, offsets):
        if e <= s:  # special token (empty offset)
            flush()
            continue
        if lab == "O":
            flush()
            continue
        prefix, _, cat = lab.partition("-")
        if cat == "":  # label had no BIOES prefix
            prefix, cat = "B", lab
        if prefix in ("B", "S") or cur is None or cur[0] != cat:
            flush()
            cur = (cat, s, e)
        else:
            cur = (cat, cur[1], e)
    flush()
    return spans


class PrivacyFilterDetector:
    """Emit :class:`PiiSpan`s from the openai/privacy-filter ONNX model.

    Like :class:`SpacyNerDetector`, the model is injected: the constructor takes
    a ``predict`` callable ``text -> list[(raw_label, start_char, end_char)]``
    (one entry per token), so the decoding/mapping is unit-testable with a tiny
    fake. :meth:`load` builds the real ``predict`` from the on-disk ONNX session
    and tokenizer (lazy imports, so the dependency is optional).

    Person/contact PII only — there is no organisation class, so pair it with the
    dictionary/spaCy layers when company names matter. Least-trusted on overlap
    (:data:`PRIORITY_MODEL`), like the spaCy detector.
    """

    # Statistical model layer: heavy (per-call inference) and recall-oriented.
    # The engine can skip it on a per-call basis (e.g. on dense table cells).
    is_model = True

    def __init__(
        self,
        predict: Callable[[str], list[tuple[str, int, int]]],
        *,
        label_map: dict[str, Label] | None = None,
        enabled_labels: Iterable[Label] | None = None,
        stopwords: Iterable[str] | None = None,
        source: str = "privacy-filter",
    ) -> None:
        self._predict = predict
        self.label_map = dict(label_map) if label_map is not None else dict(DEFAULT_PRIVACY_LABEL_MAP)
        self.enabled_labels = set(enabled_labels) if enabled_labels is not None else None
        self.stopwords = {re.sub(r"\s+", " ", w).strip().casefold() for w in (stopwords or ())}
        self.source = source

    @classmethod
    def load(
        cls,
        repo: str = "openai/privacy-filter",
        *,
        variant: str = "q4f16",
        label_map: dict[str, Label] | None = None,
        enabled_labels: Iterable[Label] | None = None,
        stopwords: Iterable[str] | None = None,
        source: str = "privacy-filter",
    ) -> "PrivacyFilterDetector":
        """Download + wrap the ONNX model. Imports onnxruntime/tokenizers lazily.

        ``variant`` selects an ONNX precision (``q4f16`` is the smallest, ~0.8 GB);
        the weights are fetched once from the Hugging Face hub (network-gated; see
        ``docs/network-allowlist.md``).
        """
        try:
            import json

            import numpy as np
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer
        except Exception as exc:  # pragma: no cover - exercised only without deps
            raise RuntimeError(
                "privacy-filter needs onnxruntime, tokenizers and huggingface_hub; "
                "`pip install onnxruntime tokenizers huggingface_hub`."
            ) from exc

        onnx_path = hf_hub_download(repo, f"onnx/model_{variant}.onnx")
        hf_hub_download(repo, f"onnx/model_{variant}.onnx_data")  # external weights
        id2label = {
            int(k): v
            for k, v in json.load(open(hf_hub_download(repo, "config.json")))["id2label"].items()
        }
        tok = Tokenizer.from_file(hf_hub_download(repo, "tokenizer.json"))
        sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        input_names = [i.name for i in sess.get_inputs()]

        def predict(text: str) -> list[tuple[str, int, int]]:
            enc = tok.encode(text)
            ids = np.array([enc.ids], dtype=np.int64)
            mask = np.ones_like(ids)
            feed = {n: (mask if "mask" in n else ids) for n in input_names}
            logits = sess.run(None, feed)[0]
            preds = logits[0].argmax(-1)
            return [
                (id2label[int(p)], s, e) for p, (s, e) in zip(preds, enc.offsets)
            ]

        return cls(
            predict,
            label_map=label_map,
            enabled_labels=enabled_labels,
            stopwords=stopwords,
            source=source,
        )

    def detect(self, text: str) -> list[PiiSpan]:
        if not text:
            return []
        tokens = self._predict(text)
        raw_labels = [t[0] for t in tokens]
        offsets = [(t[1], t[2]) for t in tokens]
        spans: list[PiiSpan] = []
        for cat, start, end in _privacy_spans(raw_labels, offsets, text):
            label = self.label_map.get(cat)
            if label is None:
                continue
            if self.enabled_labels is not None and label not in self.enabled_labels:
                continue
            surface = text[start:end]
            if _is_structural_noise(surface) or _cuts_word(text, start, end):
                continue
            if label in _PROPER_NOUN_LABELS and _lacks_uppercase(surface):
                continue
            if _stopword_match(surface, self.stopwords):
                continue
            spans.append(
                PiiSpan(
                    start=start,
                    end=end,
                    label=label,
                    text=surface,
                    source=self.source,
                    entity_id=_group_id(label, surface),
                    priority=PRIORITY_MODEL,
                )
            )
        return spans


# --------------------------------------------------------------------------- #
# Microsoft Presidio — analyzer as an optional Detector source
# --------------------------------------------------------------------------- #

# Presidio entity type -> canonical label. Presidio's NER (PERSON/ORGANIZATION/
# LOCATION) is its strength; its generic EMAIL/IBAN are reliable too. Its German
# coverage of register/tax ids is poor (it mis-tags "HRB" as LOCATION and a
# Steuernummer as PHONE_NUMBER), so by default we do NOT map PHONE/URL/date —
# the German-tuned RegexDetector owns those.
DEFAULT_PRESIDIO_LABEL_MAP: dict[str, Label] = {
    "PERSON": Label.PERSON,
    "ORGANIZATION": Label.COMPANY,
    "LOCATION": Label.LOCATION,
    "NRP": Label.PERSON,  # nationality/religious/political group, person-ish
    "EMAIL_ADDRESS": Label.EMAIL,
    "IBAN_CODE": Label.IBAN,
}

# Entities to ask the analyzer for. Restricting the set keeps the noisy/wrong
# German recognizers from running at all (and the URL recognizer's network fetch
# of the Public Suffix List — a no-go for an offline pipeline).
DEFAULT_PRESIDIO_ENTITIES: tuple[str, ...] = (
    "PERSON", "ORGANIZATION", "LOCATION", "NRP", "EMAIL_ADDRESS", "IBAN_CODE",
)


class PresidioDetector:
    """Emit :class:`PiiSpan`s from a Microsoft Presidio analyzer (optional).

    Like the other model detectors, the analysing callable is **injected**: the
    constructor takes ``analyze(text) -> list[result]`` where each result has
    ``entity_type``, ``start``, ``end`` and ``score`` — so the mapping/guards are
    unit-testable with a tiny fake. :meth:`load` builds the real callable from a
    Presidio ``AnalyzerEngine`` over a spaCy model (lazy import; heavy/optional).

    Best used for Presidio's strength — PERSON / ORGANIZATION / LOCATION (and the
    reliable EMAIL / IBAN) — while the German register/tax/phone ids stay with the
    precise :class:`~fsx.anonymize.detectors.RegexDetector`. Least-trusted on
    overlap (:data:`PRIORITY_MODEL`), and it reuses the same precision guards as
    the spaCy/privacy detectors (structural noise, stopwords, lowercase, score).
    """

    is_model = True

    def __init__(
        self,
        analyze: Callable[[str], Any],
        *,
        label_map: dict[str, Label] | None = None,
        enabled_labels: Iterable[Label] | None = None,
        min_score: float = 0.5,
        stopwords: Iterable[str] | None = None,
        source: str = "presidio",
    ) -> None:
        self._analyze = analyze
        self.label_map = dict(label_map) if label_map is not None else dict(DEFAULT_PRESIDIO_LABEL_MAP)
        self.enabled_labels = set(enabled_labels) if enabled_labels is not None else None
        self.min_score = min_score
        self.stopwords = {re.sub(r"\s+", " ", w).strip().casefold() for w in (stopwords or ())}
        self.source = source

    @classmethod
    def load(
        cls,
        *,
        language: str = "de",
        model: str = "de_core_news_lg",
        entities: Iterable[str] | None = None,
        label_map: dict[str, Label] | None = None,
        enabled_labels: Iterable[Label] | None = None,
        min_score: float = 0.5,
        stopwords: Iterable[str] | None = None,
        source: str = "presidio",
    ) -> "PresidioDetector":
        """Build a Presidio ``AnalyzerEngine`` over a spaCy model and wrap it.

        Only the requested ``entities`` are analysed (defaults to the NER + email
        + IBAN set), which also stops the URL recognizer from reaching out to the
        Public Suffix List — inference stays local.
        """
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
        except Exception as exc:  # pragma: no cover - exercised only without dep
            raise RuntimeError(
                "presidio is not installed; `pip install presidio-analyzer` and a "
                "spaCy model (e.g. `python -m spacy download de_core_news_lg`)."
            ) from exc
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": language, "model_name": model}],
            }
        ).create_engine()
        engine = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=[language])
        wanted = list(entities) if entities is not None else list(DEFAULT_PRESIDIO_ENTITIES)

        def analyze(text: str) -> Any:
            return engine.analyze(text=text, language=language, entities=wanted)

        return cls(
            analyze,
            label_map=label_map,
            enabled_labels=enabled_labels,
            min_score=min_score,
            stopwords=stopwords,
            source=source,
        )

    def detect(self, text: str) -> list[PiiSpan]:
        if not text:
            return []
        spans: list[PiiSpan] = []
        for r in self._analyze(text):
            label = self.label_map.get(r.entity_type)
            if label is None:
                continue
            if self.enabled_labels is not None and label not in self.enabled_labels:
                continue
            if getattr(r, "score", 1.0) < self.min_score:
                continue
            surface = text[r.start:r.end].strip()
            if len(surface) < 2 or _is_structural_noise(surface):
                continue
            if label in _PROPER_NOUN_LABELS and _lacks_uppercase(surface):
                continue
            if _stopword_match(surface, self.stopwords):
                continue
            spans.append(
                PiiSpan(
                    start=r.start,
                    end=r.end,
                    label=label,
                    text=text[r.start:r.end],
                    source=self.source,
                    entity_id=_group_id(label, surface),
                    priority=PRIORITY_MODEL,
                )
            )
        return spans
