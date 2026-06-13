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
| `download.pytorch.org` | **Lean CPU torch wheel** (~200 MB). Without it, PyPI pulls the full CUDA stack ≈ 7–9 GB. |
| `huggingface.co`, `cdn-lfs.huggingface.co`, `*.hf.co` | Docling layout + TableFormer model weights (downloaded on first run) |

If the xet transfer backend causes issues behind a restrictive policy, set
`HF_HUB_DISABLE_XET=1` to fall back to plain HTTPS downloads.

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

## Notes on hardware

Sized for the current container (4 vCPU / 16 GB RAM / 30 GB disk). Docling runs
on CPU; expect a few seconds to tens of seconds per page depending on layout
complexity and whether OCR is needed. Cap CPU threads via `OMP_NUM_THREADS` /
`torch.set_num_threads()` if running alongside other work.
