"""Local anonymisation engine: detectors → span merge → consistent pseudonyms."""

from __future__ import annotations

from .detectors import (
    DictionaryDetector,
    DictionaryEntity,
    Detector,
    RegexDetector,
)
from .engine import AnonymizationResult, Anonymizer
from .labels import DEFAULT_TOKENS, Label
from .model_detectors import PRIORITY_MODEL, PrivacyFilterDetector, SpacyNerDetector
from .spans import PiiSpan, merge_spans

__all__ = [
    "Anonymizer",
    "AnonymizationResult",
    "Detector",
    "DictionaryDetector",
    "DictionaryEntity",
    "RegexDetector",
    "SpacyNerDetector",
    "PrivacyFilterDetector",
    "PRIORITY_MODEL",
    "PiiSpan",
    "merge_spans",
    "Label",
    "DEFAULT_TOKENS",
]
