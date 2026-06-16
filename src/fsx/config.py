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

    models:                 # optional, off by default — statistical NER recall
      spacy:
        enabled: true
        model: de_core_news_lg          # local spaCy package / cache
        labels: [PERSON, COMPANY, LOCATION]   # optional canonical-label filter
        min_length: 2
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml

from .anonymize.detectors import REGEX_RULES, DictionaryDetector, DictionaryEntity, RegexDetector
from .anonymize.engine import Anonymizer
from .anonymize.labels import Label
from .anonymize.model_detectors import PrivacyFilterDetector, SpacyNerDetector

# Signature of a model-detector loader; injectable so config wiring is testable
# without the multi-hundred-MB models. Default to the respective ``.load``.
SpacyLoader = Callable[..., Any]
PrivacyLoader = Callable[..., Any]

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


def _parse_labels(values: Any) -> set[Label] | None:
    """Parse a list of canonical label names into a set, or ``None`` if absent."""
    if not values:
        return None
    labels: set[Label] = set()
    for name in values:
        try:
            labels.add(Label(str(name).upper()))
        except ValueError:
            continue
    return labels or None


# Financial-statement vocabulary that a German NER model routinely mis-tags as a
# company, person or location (statement/section headings, structural words,
# units). Injected into the spaCy detector so it never redacts these — keeping
# the generic anonymiser free of domain knowledge. Matched on the whole entity
# surface (case/whitespace-insensitive), so a real company name that merely
# *contains* one of these words is unaffected.
_DEFAULT_NER_STOPWORDS: frozenset[str] = frozenset({
    # statements / sections
    "bilanz", "aktiva", "passiva", "aktivseite", "passivseite",
    "gewinn- und verlustrechnung", "gewinn und verlustrechnung", "guv",
    "anlagenspiegel", "entwicklung des anlagevermögens", "jahresabschluss",
    "jahresabschlussauswertungen", "anhang", "lagebericht", "kontennachweis",
    "bescheinigung", "vermerk", "kapitalflussrechnung", "eigenkapitalspiegel",
    "inhaltsverzeichnis", "auftrag", "anlagen",
    # balance-sheet / P&L positions
    "anlagevermögen", "umlaufvermögen", "eigenkapital", "verbindlichkeiten",
    "rückstellungen", "rechnungsabgrenzungsposten", "gesamtleistung",
    "umsatzerlöse", "jahresüberschuss", "jahresfehlbetrag", "bilanzgewinn",
    "bilanzsumme", "sachanlagen", "finanzanlagen", "immaterielle",
    "immaterielle vermögensgegenstände",
    # Anlagenspiegel column/abbreviation vocabulary (mis-tagged on the
    # Kontennachweis / Entwicklung des Anlagevermögens pages)
    "ahk", "abschr", "abschreibung", "abschreibungen", "buchwert", "zugang",
    "abgang", "umbuchung", "zuschreibung", "gwg", "gwg-sofort",
    # structural words / units
    "blatt", "seite", "summe", "übertrag", "davon", "vortrag",
    "geschäftsjahr", "vorjahr", "eur", "euro", "tsd", "mio",
})


def _ner_stopwords(spacy_cfg: dict[str, Any]) -> set[str]:
    extra = spacy_cfg.get("stopwords") or []
    return set(_DEFAULT_NER_STOPWORDS) | {str(w) for w in extra}


def _build_model_detectors(
    config: dict[str, Any],
    *,
    spacy_loader: SpacyLoader | None = None,
    privacy_loader: PrivacyLoader | None = None,
) -> list[Any]:
    """Build opt-in statistical NER detectors from the ``models`` config section.

    Returns an empty list unless ``models.spacy.enabled`` is true. The spaCy
    model is loaded via ``spacy_loader`` (defaults to
    :meth:`SpacyNerDetector.load`); inject a fake to test wiring without the
    real model. A loader error (missing package/model) propagates, since the
    detector was explicitly requested.
    """
    models = config.get("models") or {}
    detectors: list[Any] = []

    spacy_cfg = models.get("spacy") or {}
    if spacy_cfg.get("enabled", False):
        loader = spacy_loader if spacy_loader is not None else SpacyNerDetector.load
        detectors.append(loader(
            spacy_cfg.get("model", "de_core_news_lg"),
            enabled_labels=_parse_labels(spacy_cfg.get("labels")),
            min_length=int(spacy_cfg.get("min_length", 2)),
            stopwords=_ner_stopwords(spacy_cfg),
        ))

    pf_cfg = models.get("privacy_filter") or {}
    if pf_cfg.get("enabled", False):
        loader = privacy_loader if privacy_loader is not None else PrivacyFilterDetector.load
        kwargs: dict[str, Any] = {
            "variant": pf_cfg.get("variant", "q4f16"),
            "enabled_labels": _parse_labels(pf_cfg.get("labels")),
            "stopwords": _ner_stopwords(pf_cfg),
        }
        if pf_cfg.get("repo"):
            kwargs["repo"] = pf_cfg["repo"]
        detectors.append(loader(**kwargs))

    return detectors


def build_anonymizer(
    config: dict[str, Any],
    *,
    spacy_loader: SpacyLoader | None = None,
    privacy_loader: PrivacyLoader | None = None,
) -> Anonymizer:
    """Construct an :class:`Anonymizer` from a parsed config dict.

    Model-based detectors are appended *after* the dictionary and regex layers
    so the precise, curated layers are considered first on overlaps.
    """
    entities = _build_entities(config)
    regex_labels = _build_regex_labels(config)
    detectors: list[Any] = [
        DictionaryDetector(entities),
        RegexDetector(enabled_labels=regex_labels),
    ]
    detectors.extend(_build_model_detectors(
        config, spacy_loader=spacy_loader, privacy_loader=privacy_loader,
    ))
    return Anonymizer(detectors, token_overrides=_build_token_overrides(config))


def load_anonymizer(
    path: str | Path,
    *,
    spacy_loader: SpacyLoader | None = None,
    privacy_loader: PrivacyLoader | None = None,
) -> Anonymizer:
    """Convenience: load a YAML config from ``path`` and build the engine."""
    return build_anonymizer(
        load_config(path), spacy_loader=spacy_loader, privacy_loader=privacy_loader,
    )
