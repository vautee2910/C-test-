# Local financial-statement extraction & anonymisation pipeline

On-premise pipeline to extract German annual financial statements
(Jahresabschlüsse) from PDFs, anonymise them locally, store normalised
financial facts, and compare year-over-year — so that only a **minimised,
anonymised** data pack is ever sent to an external LLM, never the original PDF.

```
PDF 2022 / 2023 / 2024
        ↓  local PDF / OCR / layout extraction   (Docling, PyMuPDF, pdfplumber, Camelot, OCRmyPDF)
text blocks + tables + page/coordinate refs
        ↓  local entity detection & anonymisation (Presidio + spaCy de + regex + dictionaries)
normalised statement structure                  (JSON + Parquet, SQLite/DuckDB)
        ↓
comparison · ratios · anomaly flags · LLM analysis (only on anonymised facts)
```

## Status

Bootstrapping the **document-parsing layer** with [Docling](https://github.com/docling-project/docling),
CPU-only.

## Network requirements (Claude Code on the web)

This runs in an ephemeral cloud container whose outbound access is governed by
the environment's **network policy**. For the CPU install + model downloads,
these hosts must be allowlisted:

| Host | Why |
| --- | --- |
| `pypi.org`, `files.pythonhosted.org` | Python packages (usually already allowed) |
| `download.pytorch.org` | Wheel **index** (HTML listing) for the lean CPU torch build. |
| `download-r2.pytorch.org` | **CDN that serves the actual wheel bytes** (~200 MB). The index redirects downloads here — allowlisting only `download.pytorch.org` makes the index return 200 while the install still 403s mid-download. Without the CPU wheel, PyPI pulls the full CUDA stack ≈ 7–9 GB. |
| `huggingface.co`, `*.hf.co` | HF API + small files for Docling layout / TableFormer models. |
| `cas-bridge.xethub.hf.co`, `transfer.xethub.hf.co` (or `*.xethub.hf.co`) | **HF Xet LFS backend** that serves the large model weights. Same trap as above: `huggingface.co` can return 200 while weight downloads 403. |

> **Note:** the legacy `cdn-lfs*.huggingface.co` LFS hosts no longer resolve
> here — HF serves LFS objects via the Xet backend above. Keep Xet enabled and
> allowlist `*.xethub.hf.co`. Only if Xet is unavailable, set
> `HF_HUB_DISABLE_XET=1` to fall back to plain HTTPS downloads (which then need
> whatever `cdn-lfs` host HF redirects to allowlisted).

> The network policy is fixed when the environment is created. To change it,
> recreate the web environment with the hosts above allowlisted.
> See https://code.claude.com/docs/en/claude-code-on-the-web

## Setup (CPU-only)

```bash
./scripts/setup_cpu.sh
```

The script preflight-checks that `download.pytorch.org` is reachable, installs
the **CPU** torch wheel first, then the rest of `requirements-cpu.txt`, and
runs an import sanity check. Manual equivalent:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
pip install -r requirements-cpu.txt
```

## Smoke test

```bash
source .venv/bin/activate
python scripts/docling_smoke.py path/to/statement.pdf
```

## OCR & model-based anonymisation (optional, local)

Two optional, fully local stages — see
[docs/ocr-and-model-detectors.md](docs/ocr-and-model-detectors.md):

- **OCR front-stage** for *scanned* PDFs. A born-digital statement is parsed
  directly; a scan is transparently made searchable first (OCRmyPDF/Tesseract)
  and then flows through the unchanged PyMuPDF adapter. Gate: *text layer
  present → no OCR*. Needs the OS binaries plus the pip package:

  ```bash
  apt-get install -y tesseract-ocr tesseract-ocr-deu ghostscript
  pip install ocrmypdf
  python -c "from fsx.parsing import parse_pdf_with_ocr"   # drop-in entry point
  ```

- **Statistical NER detector** (German spaCy) as an extra anonymisation layer to
  catch names not in the dictionary. Off by default; enable via the
  `models.spacy` config section. Inference is local; only the model download
  needs egress.

  ```bash
  pip install spacy
  python -m spacy download de_core_news_lg
  ```

## Notes on hardware

Sized for the current container (4 vCPU / 16 GB RAM / 30 GB disk). Docling runs
on CPU; expect a few seconds to tens of seconds per page depending on layout
complexity and whether OCR is needed. Cap CPU threads via `OMP_NUM_THREADS` /
`torch.set_num_threads()` if running alongside other work.
