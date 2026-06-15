# CLAUDE.md

Guidance for AI agents working in this repository. Read this first — it captures
the architecture, the invariants that must not be broken, and the current state
so work carries across sessions.

## What this is

`fsx` — an **on-premise pipeline** that extracts German annual financial
statements (Jahresabschlüsse) from PDFs, anonymises them locally, normalises the
numbers into canonical HGB **facts**, reconciles them, and builds a
multi-year analysis. The point: only a minimised, **anonymised** fact pack ever
leaves the machine, never the original PDF.

Everything is local and CPU-only. The core has light dependencies (PyMuPDF for
PDFs, Pydantic for contracts); OCR (OCRmyPDF/Tesseract) and the statistical NER
detector (spaCy) are optional add-ons.

## Architecture (data flows top → bottom)

```
PDF
 └─ parsing/         OCR gate + PyMuPDF parsing      (parsing/ocr.py, text_layer.py, pymupdf_parser.py)
 └─ anonymize/       detectors → span merge → pseudonyms   [REUSABLE, domain-free]
 └─ extract/         words → rows → panels → value columns [REUSABLE, domain-free]
 └─ hgb/             concepts, facts, anlagenspiegel, reconcile   [DOMAIN]
 └─ analysis/        derived metrics, ratios, YoY, report         [DOMAIN]
```

Three data contracts (`fsx/schemas.py`, all Pydantic):
- **Level 1** `RawDocument` — anonymised raw extraction with provenance.
- **Level 2** `Fact` — one canonical HGB concept + value/sign/scale/source.
- **Level 3** `AnalysisFeature` / `AnalysisReport` — metrics + reconciliation.

End-to-end entry points (each callable one layer lower too):
- `fsx.parsing.parse_pdf_with_ocr(...)  -> RawDocument`
- `fsx.hgb.facts.facts_from_pdf(...)    -> list[Fact]`
- `fsx.analysis.analyze_pdf(...)        -> AnalysisReport`  (features + reconcile)

## Invariants — do NOT break these

1. **`extract/` and `anonymize/` stay reusable and domain-free.** They must not
   import `fsx.hgb`, `fsx.analysis`, or `fsx.schemas` (and `extract` must not
   import `anonymize` — the anonymiser is passed in, duck-typed, or `None`).
   Enforced by `tests/test_modularity.py`. These two packages are meant to be
   lifted into other applications; keep that property.
2. **Geometry is document-agnostic.** `extract/tables.py` has no hard-coded
   coordinates, page numbers, or document-specific labels. Keep it that way;
   document-specific knowledge belongs in `hgb/` and `config/*.yaml`.
3. **Precision over recall.** Better to emit no fact than a wrong one. When a
   value can't be derived reliably (e.g. OCR-garbled nested subtotals), suppress
   rather than guess.
4. **Reconciliation flags, never mutates.** `hgb/reconcile.py` reports issues;
   it does not change facts.
5. **No persistence in the core.** The pipeline returns Pydantic objects; the
   *host engine* owns SQL/storage. `fact_id` is deterministic and content-based
   (hash of company/year/statement/section/concept/source_table/label, **not**
   value) so the host can upsert idempotently. Don't add a DB dependency to the
   core.
6. **Anonymise before anything domain-specific.** Labels are pseudonymised at
   the `extract`/parsing boundary; the same `Anonymizer` is shared across a
   document for consistent pseudonyms.

## Key files

- `src/fsx/extract/tables.py` — row clustering, panel gutters (incl. the
  flanked-by-value-columns fallback for vertically misaligned two-up sheets),
  value-column detection. Pure stdlib.
- `src/fsx/extract/pdf_words.py` — the only PyMuPDF use; **rotation-normalises**
  words via `page.rotation_matrix` (landscape `/Rotate 90` balance sheets).
- `src/fsx/hgb/concepts.py` + `config/hgb_concepts.yaml` — shared HGB concept
  synonyms / matcher (exact → prefix → optional fuzzy).
- `src/fsx/hgb/families.py` + `config/families.yaml` — data-driven document-family
  registry. Each family declares marker phrases, concept file(s) and a reconcile
  set; classification scores markers, highest-`priority` qualifier wins (bank over
  the generic hgb base), no match → `unknown` (base concepts, flagged). Add a new
  document type as YAML, no code. `concepts.classify_document_family` /
  `concept_paths_for_family` are thin wrappers over the registry.
- `src/fsx/hgb/statements.py` + `config/statements.yaml` — statement-title
  vocabulary (heading → statement key + `StatementType`), AKTIVA/PASSIVA section
  bands and the HGB sign rules, all as data; `detect_statement` / sign-flip logic
  in `facts.py` read it through `RULES`.
- `src/fsx/hgb/facts.py` — tables → `Fact`s: statement/section context, wrapped
  & hyphenated label rejoin, prior-year column rule, sign rules
  (Jahresfehlbetrag, Bestandsveränderung), Übertrag skip, orphan subtotals,
  nested sub-group suppression, deterministic `fact_id`.
- `src/fsx/hgb/reconcile.py` — conflicting values, broken accounting identities,
  low-confidence flags.
- `src/fsx/analysis/features.py` (pure transform) + `report.py`
  (`analyze_facts` / `analyze_pdf`, tags features touched by an issue).
- `src/fsx/parsing/ocr.py` — OCR gate + `OcrMyPdfBackend` (`force_ocr` default;
  opt-in `tessdata_dir`/`tesseract_oem`/`oversample` via env, off by default).

## Commands

```bash
.venv/bin/python -m pytest -q          # full suite (currently 227 tests)
./scripts/setup_cpu.sh                 # CPU-only env setup
```

Tests run offline. The OCR end-to-end test self-skips if Tesseract is absent.
There is no committed sample PDF (the two real validation statements live only
in the gitignored `.scratch/`); reason about new geometry against synthetic
fixtures and the existing tests.

## Conventions

- Match the surrounding style: dense docstrings explaining *why*, generic
  parameters with sensible defaults (never magic coordinates).
- Add/adjust tests for every behavioural change; keep the suite green.
- German financial terms in code/data; docstrings and this file in English.
- Per-statement docs live in `docs/` (German): `level2-extraction.md`,
  `level3-analysis.md`, `ocr-and-model-detectors.md`, `modularity.md`,
  `network-allowlist.md`.

## Current state (validated on real statements: born-digital, scan, and a bank/RechKredV sheet)

Done and tested:
- OCR gate + `force_ocr` (recovers phantom-text-layer scans); page-rotation
  normalisation; two-up panel split for misaligned AKTIVA/PASSIVA.
- Statement/section detection incl. bare AKTIVA/PASSIVA bands and stacked
  single-column balance sheets.
- Fact rules: prior-year split, hyphenated/wrapped label rejoin, Übertrag skip,
  Jahresfehlbetrag & Bestandsveränderung signs, orphan subtotals, nested
  sub-group suppression, deterministic `fact_id`.
- Reconciliation (conflicts / identities / low-confidence) wired into Level-3
  (`AnalysisReport`); **family-aware** — bank sheets use the bank identity set and
  skip the HGB section-subtotal balance (their balance is enforced by the dual
  `bilanzsumme` via the conflicting-value check).
- **Document-family registry** (`families.py` + `config/families.yaml`):
  `facts_from_pdf` classifies the document (`hgb` / `bank` / `unknown`) and loads
  that family's concept set, instead of always merging HGB + bank. Industrial
  sheets no longer see bank positions; bank sheets resolve with no caller config.
  Per-period scale handles bank "Tsd. EUR" prior columns; the dash-separated
  prior column no longer triggers a spurious panel split.
- **Non-statement / heterogeneous documents**: `facts_from_tables` suppresses
  panels with `>= 4` value columns — cross-sectional / multi-year statistics
  matrices (e.g. a Destatis Jahrbuch table by Wirtschaftsbereich) have no
  unambiguous value column, so per precision-over-recall they emit no Fact (the
  dedicated `anlagenspiegel` path keeps handling legitimately-wide statements via
  its column-header → dimension mapping). For hybrid/RAG hosts,
  `concepts.classify_segments(page_texts) -> list[SegmentClassification]` returns
  per-page raw family classification + full marker-hit evidence (a compendium is
  not one family); the host correlates it with Level-1 pages and owns the
  metadata (no persistence in core). `RawDocument` (Level 1) always keeps the
  full anonymised content regardless of Fact suppression — that is the RAG index.
- **Level-1 tables** (`parsing/pymupdf_parser.py`) are built from the geometry
  reconstruction (`fsx.extract`) as the *primary* source, falling back to PyMuPDF
  `find_tables()` only when it yields nothing. `find_tables` collapses dense
  statement / statistics tables into one text blob or misses the body entirely;
  the reconstruction recovers the row × value-column grid, so `RawDocument.tables`
  is queryable (SQL-grade). Only labels are anonymised — numeric values stay
  verbatim, so no PII regex can corrupt a figure into a token.
- **Anonymiser number integrity**: the PHONE regex carries a second lookbehind
  `(?<!\d\s)` so a space-separated thousands continuation ("2 076 909" → "076
  909") is not eaten as a phone number — it kept corrupting figures in
  number-dense statistics tables. Space-separated real phones ("0911 1234567")
  still match.
- Modularity: `extract` + `anonymize` standalone & guarded; Anlagenspiegel moved
  to `hgb/`.
- Anonymisation: dictionary + regex core, plus two optional, injectable model
  detectors in `anonymize/model_detectors.py` — `SpacyNerDetector` (ORG/person/
  location; with structural + injected stopword filtering so it stops redacting
  statement vocabulary) and `PrivacyFilterDetector` (openai/privacy-filter ONNX,
  person/contact PII, no ORG). Both off by default, enabled via the `models`
  config section. The anonymiser targets *all* document types, not only
  statements.

Known/deferred (be honest about these):
- **OCR digit errors** on scans are mitigated (reconciliation flags, low-conf
  surfacing) but not eliminated — the planned fix is a **remote GPU-OCR backend**
  plugged in behind the `OcrBackend` protocol.
- **Nested GuV sub-group totals** are *suppressed* rather than summed, because
  garbled OCR makes the sum unreliable; with clean OCR this becomes a sum.
- **Persistence** is intentionally absent — the host engine writes SQL using the
  Pydantic contracts and the stable `fact_id`.
- A `fsx.store` reference adapter is intentionally **not** built (host owns it).

When in doubt, measure on the real `.scratch/` PDFs (if present), keep the
reusable boundary clean, and prefer precision.
