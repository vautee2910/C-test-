"""The anonymisation engine: run detectors, merge spans, replace consistently.

The engine is detector-agnostic. The network-free core wires up
:class:`~fsx.anonymize.detectors.DictionaryDetector` and
:class:`~fsx.anonymize.detectors.RegexDetector`; later layers (spaCy, Presidio,
the OpenAI Privacy Filter) just append more :class:`Detector` instances.

Replacement is **consistent**: every mention of the same entity becomes the
same token (``[UNTERNEHMEN_1]``), and numbering is assigned per label in order
of first appearance. The reverse mapping (token → original) is returned for a
*local* audit artifact and must never be exported alongside the anonymised text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .detectors import Detector
from .labels import Label, token_template
from .spans import PiiSpan, merge_spans


@dataclass
class AnonymizationResult:
    """Outcome of anonymising one piece of text."""

    text: str
    spans: list[PiiSpan] = field(default_factory=list)
    # token -> original surface text, for the LOCAL audit mapping only.
    mapping: dict[str, str] = field(default_factory=dict)

    @property
    def replaced_count(self) -> int:
        return len(self.spans)


class Anonymizer:
    """Orchestrates detectors and rewrites text with stable pseudonyms.

    A single instance keeps its token counters and entity→token mapping across
    calls, so the same company gets the same token across every page/block of a
    document. Create a fresh ``Anonymizer`` per document to reset numbering.
    """

    def __init__(
        self,
        detectors: list[Detector],
        token_overrides: dict[Label, str] | None = None,
    ) -> None:
        self.detectors = detectors
        self.token_overrides = token_overrides or {}
        # entity_id -> assigned token; and per-label running counter.
        self._entity_tokens: dict[str, str] = {}
        self._label_counters: dict[Label, int] = {}
        self._mapping: dict[str, str] = {}
        # Every *surface form* ever replaced -> its token. Unlike ``_mapping``
        # (token -> one surface), this keeps all spellings of an entity (e.g. a
        # company's long and short name), which a downstream redactor needs to
        # find every mention, not just the first.
        self._surface_tokens: dict[str, str] = {}

    def _token_for(self, span: PiiSpan) -> str:
        """Return the stable token for a span's entity, assigning one if new."""
        if span.entity_id in self._entity_tokens:
            return self._entity_tokens[span.entity_id]
        n = self._label_counters.get(span.label, 0) + 1
        self._label_counters[span.label] = n
        tmpl = token_template(span.label, self.token_overrides)
        # Be forgiving if a policy template forgot the {n} placeholder, so
        # distinct entities still get distinct tokens instead of colliding.
        token = tmpl.format(n=n) if "{n}" in tmpl else f"{tmpl}_{n}"
        self._entity_tokens[span.entity_id] = token
        self._mapping[token] = span.text
        return token

    def anonymize(self, text: str, *, use_models: bool = True) -> AnonymizationResult:
        """Anonymise ``text``, keeping pseudonyms consistent with prior calls.

        ``use_models=False`` skips the heavy statistical-model detectors (those
        flagged ``is_model``) for this call, keeping only the fast, precise
        dictionary + regex layers. The token counters / mapping are shared either
        way, so pseudonyms stay consistent across calls. Callers use this to keep
        the slow, recall-oriented model off dense, low-PII inputs (e.g. statement
        table cells) while still running it on prose blocks.
        """
        if not text:
            return AnonymizationResult(text=text)

        raw_spans: list[PiiSpan] = []
        for detector in self.detectors:
            if not use_models and getattr(detector, "is_model", False):
                continue
            raw_spans.extend(detector.detect(text))
        spans = merge_spans(raw_spans)

        # Rebuild the string left-to-right, swapping each span for its token.
        out: list[str] = []
        cursor = 0
        for span in spans:
            out.append(text[cursor : span.start])
            token = self._token_for(span)
            self._surface_tokens[span.text] = token
            out.append(token)
            cursor = span.end
        out.append(text[cursor:])

        return AnonymizationResult(
            text="".join(out),
            spans=spans,
            mapping=dict(self._mapping),
        )

    @property
    def mapping(self) -> dict[str, str]:
        """Full token → original mapping accumulated so far (audit only)."""
        return dict(self._mapping)

    @property
    def surface_tokens(self) -> dict[str, str]:
        """Every replaced surface form → its token (all spellings of each entity)."""
        return dict(self._surface_tokens)
