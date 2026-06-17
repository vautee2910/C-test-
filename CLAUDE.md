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
  single-column balance sheets. `_dominant_heading` ignores letter-free spans
  (an OCR rule/underscore can render larger than the title and mask it); the GuV
  title set includes the OCR-jitter-robust `verlustrechnung` (the small `und` of
  "GEWINN- UND VERLUSTRECHNUNG" can drop out of the font band). A scanned GuV
  summary page is recognised even when it also has a Kontennachweis — the two
  then cross-validate, and reconciliation flags a real OCR digit error between
  them (precision over recall).
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
  verbatim, so no PII regex can corrupt a figure into a token. Value columns are
  named (`Table.column_headers` / `ReconstructedTable.column_headers`) **only**
  for unambiguous *period* headers (a year/date row above the body); generic
  geometric header→column mapping is unreliable on heterogeneous layouts (it
  mislabels caption/title fragments), so per precision-over-recall everything
  else stays positional (`[]`) and the host names columns itself. Document-type
  header semantics belong in a tuned extractor (cf. `anlagenspiegel`).
- **Anonymiser number integrity & phone coverage**: the PHONE regex (`PHONE_RE`
  in `detectors.py`) is two alternatives — an explicit `+49`/`0049` (optionally
  `(0)`) international trunk with flexible 1+-digit grouping incl. thin/no-break
  space separators ("+49 (0) 611 / 75 24 05"), and a deliberately strict domestic
  `0…` form. The domestic form carries a second lookbehind `(?<!\d\s)` so a
  space-separated thousands continuation ("2 076 909" → "076 909") is not eaten
  as a phone — it kept corrupting figures in number-dense statistics tables. On
  the Jahrbuch front matter the anonymiser (regex-only) catches 6/8 PII (3
  phone/fax, 2 addresses, 1 email); the 2 personal names need the opt-in spaCy
  NER / known-entities dictionary (regex cannot find names by design).
- Modularity: `extract` + `anonymize` standalone & guarded; Anlagenspiegel moved
  to `hgb/`.
- Anonymisation: dictionary + regex core, plus two optional, injectable model
  detectors in `anonymize/model_detectors.py` — `SpacyNerDetector` (ORG/person/
  location; with structural + injected stopword filtering so it stops redacting
  statement vocabulary) and `PrivacyFilterDetector` (openai/privacy-filter ONNX,
  person/contact PII, no ORG). Both off by default, enabled via the `models`
  config section. The anonymiser targets *all* document types, not only
  statements. Validated on the Jahrbuch front matter: with the privacy-filter
  on, the pipeline reaches 8/8 PII (adds the 2 personal names the regex cannot
  find). The model is context-sensitive — it misses names when fed a whole page
  but catches them when fed per Level-1 block (which is how the pipeline runs);
  its subword tokens could tag part of a word ("Ers" of "Erschienen"), so a
  word-boundary guard (`_cuts_word`) drops spans that slice a word. Validated on
  the e.V. Erstellungsbericht: it recovers every real person name (Steuerberater
  + full Vorstand) but over-redacts statement structure as PERSON/ADDRESS. Two
  more domain-free guards keep precision: `_stopword_match` folds a leading
  enumerator ("B. Umlaufvermögen") and trailing punctuation ("Abschr.") before
  the stopword test so one bare stopword covers the decorated forms, and an
  all-lowercase PERSON/ORG/LOCATION span ("dabei", a wrapped "gesetzli chen") is
  dropped (a German proper noun is capitalised); the default NER stopwords gained
  the Anlagenspiegel/Kontennachweis vocabulary (immaterielle, AHK, Abschr., GWG,
  Buchwert, …). Residual hits are only open-ended Kontennachweis asset names,
  where conservative over-redaction is the safe direction for an anonymiser.
  **Performance vs precision (opt-in)**: the model does per-call inference, so on
  table-heavy pages scanning every cell dominates the cost. The **default is
  precise** — the model scans table cells too (`PyMuPDFParser` /
  `parse_pdf(..., model_on_tables=True)`), so a name appearing only in a cell is
  still redacted. Pass `model_on_tables=False` to opt into the faster path: the
  model then runs on prose text blocks only, and table cells (geometry-recon­structed
  and `find_tables`) are anonymised by the dictionary + regex layers via
  `Anonymizer.anonymize(text, use_models=False)` — those cells are dense, low-PII
  concept labels already present in the text blocks. Measured ~2.8× faster on
  table-heavy pages (140→49.5 s; the shared token mapping keeps pseudonyms
  consistent either way). Trade-off of the fast path: a name only ever in a table
  cell is then caught by the dictionary/regex layers, not the model.
- **Anonymised PDF output** (`parsing/redact.py`, `write_anonymized_pdf`; opt-in
  `parse_pdf(..., redacted_pdf_path=...)`): emits the *same* PDF — layout, fonts,
  figures, every non-PII glyph untouched — with each detected PII surface replaced
  in place by the pipeline's pseudonym token. Built on PyMuPDF redaction
  annotations, so the text is genuinely removed from the content stream (and with
  `images=PIXELS` the covered pixels of a page image, so a *scanned* name is
  erased from the image, not just the OCR layer). It also scrubs the info-dict +
  XMP metadata and embedded files (real docs carry an author / internal title)
  and removes signature stamps (the signer's name lives in the widget appearance,
  invisible to `search_for`). Surface matching is longest-first with overlap-skip;
  a surface that does not match as one contiguous run falls back to per-word boxes
  (over-redact rather than leak). Validated on the e.V. (born-digital, *signed*)
  and the scan: layout 1:1, metadata cleared, tokens in place. **Recall equals
  detector recall** — the privacy filter is person/contact only, so company/ORG
  and bare city names need the dictionary (the engagement knows the client) or
  spaCy NER; the integrated path reuses the run's already-detected surfaces
  (`detect=False`), so there is no second model pass. Surface matching is
  whole-word (consecutive `get_text("words")` runs), not substring — a short or
  mis-detected surface ("Jah" from a hyphenated "Jah-resabschluss") can no longer
  blank the inside of "Jahresabschluss"/"Geschäftsjahr". **Image limit**: a firm
  letterhead (logo, footer address/phone/email) and a round signature stamp are
  embedded *raster images* — `get_text` returns nothing for them, so no text
  detector (nor the `RawDocument`) sees that PII. Opt-in `remove_images=True`
  blanks every embedded image (in a statement that is letterhead, not data); off
  by default since it also drops legitimate figures.

Known/deferred (be honest about these):
- **OCR digit errors** on scans are mitigated (reconciliation flags, low-conf
  surfacing) but not eliminated — the planned fix is a **remote GPU-OCR backend**
  plugged in behind the `OcrBackend` protocol.
- **Table-extraction backends**: the geometry reconstruction is the precise CPU
  default. `parsing/table_backends.py` adds a `TableExtractor` protocol (mirrors
  `OcrBackend`) + a scorer (precision/recall/F1 vs a ground-truth cell set) and
  `scripts/bench_tables.py` so an alternative (docling/camelot/VLM) is *measured*
  before adoption, never swapped into the core. Benchmarked head-to-head on a
  **real born-digital Bilanz**: geometry 14/14 values (100%, instant) vs
  **docling 10/14 (71%, ~19 s)** — docling caught the subtotals but dropped
  individual line items, so on the *target* documents the lightweight geometry
  pass is both more complete and far faster. Getting docling to run at all
  exposed its cost (the point of the seam): a torchvision matched to torch (else
  a `torchvision::nms` import error), a transformers it agrees with, and
  `do_ocr=False` (its default pipeline pulls a RapidOCR model from a blocked host
  even for born-digital PDFs). Keep it an *optional* backend for hard layouts,
  not a core dep. A cloud VLM is ruled out (raw page image would leave the host,
  breaking anonymise-before-egress). `DoclingTableExtractor(do_ocr=True)` adds a
  scan path (reports `name="docling-ocr"`) so docling can be measured end-to-end
  on an image-only PDF, not only born-digital. **Re-benchmarked on the real scan**
  (Smart Site Solutions, Bilanz p21/22 + GuV p23, value-recall vs hand-verified
  figures): geometry on the OCRmyPDF layer **70/79 = 88.6% (instant)** vs
  **docling-OCR 67/79 = 84.8% (~196 s for 3 pages)** — so docling-OCR does *not*
  catch up on real scans; it is both slower and slightly less complete. Both miss
  the same closing grand totals (Bilanzsumme) and GuV group subtotals (handled in
  the fact layer, not raw reconstruction); docling additionally drops a few line
  items the geometry pass recovers. Geometry stays the default; docling stays an
  optional, measured backend.
- **Scans / OCR validated end-to-end**: a 34-page image-only scan OCRs in ~27 s
  (OCRmyPDF + Tesseract `deu`) and yields 49 facts at good digit quality;
  reconciliation flags the review items — the documented safety net. It first
  raised a spurious `bilanz_imbalance`; the root cause was **not** the 3-column
  layout (inner amount + Geschäftsjahr + Vorjahr, which parses correctly) but an
  **OCR stray trailing dot**: a last sub-item's figure rendered as `11.156,85.`
  failed money detection and was absorbed into the label, so the line inherited
  its group subtotal and inflated the Passiva. Fixed in `extract/numbers.py`
  (`_strip_ocr_trailing_dot`: tolerate one trailing `.` only when a decimal comma
  is present, so dates/enumerators stay rejected); the scan now balances exactly
  and the two figures are recovered.
- **Nested GuV sub-group totals** are *suppressed* rather than summed, because
  garbled OCR makes the sum unreliable; with clean OCR this becomes a sum.
- **Persistence** is intentionally absent — the host engine writes SQL using the
  Pydantic contracts and the stable `fact_id`.
- A `fsx.store` reference adapter is intentionally **not** built (host owns it).

When in doubt, measure on the real `.scratch/` PDFs (if present), keep the
reusable boundary clean, and prefer precision.
