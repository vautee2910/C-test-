"""PII spans and overlap resolution.

A :class:`PiiSpan` is a single detected mention: a character range in the source
text plus its canonical label and provenance. Detectors emit spans; the engine
merges them (resolving overlaps) before replacement.
"""

from __future__ import annotations

from dataclasses import dataclass

from .labels import Label


@dataclass(frozen=True)
class PiiSpan:
    """A detected entity mention in a piece of text.

    Attributes:
        start, end: character offsets, ``text[start:end]`` is the match.
        label: canonical :class:`Label`.
        text: the matched substring (kept for the audit mapping).
        source: which detector produced it ("regex", "dictionary", …).
        entity_id: groups mentions of the *same* entity so they share a token.
            For dictionary hits this is the configured entity id (all aliases of
            one company share it); for regex hits it defaults to the normalised
            match (so the same IBAN maps to the same token).
        priority: higher wins when two spans overlap and are the same length.
    """

    start: int
    end: int
    label: Label
    text: str
    source: str
    entity_id: str
    priority: int = 0

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "PiiSpan") -> bool:
        return self.start < other.end and other.start < self.end


def merge_spans(spans: list[PiiSpan]) -> list[PiiSpan]:
    """Resolve overlaps, returning a non-overlapping list sorted by position.

    Resolution order when spans overlap: prefer the **longer** span, then the
    higher **priority**, then the earlier start. This lets a multi-word
    dictionary match (e.g. a full company name) win over a shorter regex hit
    sitting inside it, while structured-id regexes still win ties via priority.
    """
    # Consider the strongest spans first (longest, then highest priority,
    # then earliest) so a longer match wins over any shorter span it overlaps,
    # regardless of which one starts earlier.
    ordered = sorted(spans, key=lambda s: (-s.length, -s.priority, s.start))

    accepted: list[PiiSpan] = []
    for span in ordered:
        if span.start >= span.end:
            continue  # skip empty
        if any(span.overlaps(a) for a in accepted):
            continue
        accepted.append(span)

    accepted.sort(key=lambda s: s.start)
    return accepted
