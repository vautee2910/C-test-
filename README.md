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
| `cas-server.xethub.hf.co` | **HF Xet CAS reconstruction API** — the control endpoint that resolves a file into its content chunks. Required *before* any weight bytes flow. |
| `us.aws.cdn.hf.co` | **HF Xet data CDN** (the `xet-bridge-us` backend) that actually serves the weight bytes. Both this and `cas-server` must be reachable or `snapshot_download` 403s. |
| `cas-bridge.xethub.hf.co`, `transfer.xethub.hf.co` | Other Xet hosts seen in HF docs. Reachable here (they answer with a CloudFront origin 403 on bare-root requests), but on this account/region the weights resolve through `cas-server` + `us.aws.cdn.hf.co` above, so those two are the ones that matter. |

> **Verified 2026-06-13 (this environment):** a literal allowlist of
> `cas-bridge`/`transfer.xethub.hf.co` is **not sufficient** — Docling's weights
> resolve through `cas-server.xethub.hf.co` → `us.aws.cdn.hf.co`, and both were
> blocked (HTTP 403 with header `x-deny-reason: host_not_allowed`, the egress
> proxy's block signature, vs. a `server: CloudFront` origin 403 which means
> *reachable*). The `*.hf.co` / `*.xethub.hf.co` wildcards were **not honoured** —
> only literal hostnames took effect. Allowlist `cas-server.xethub.hf.co` and
> `us.aws.cdn.hf.co` explicitly (in addition to the wildcards).
>
> **Note:** the legacy `cdn-lfs*.hf.co` LFS hosts are also blocked here, so
> `HF_HUB_DISABLE_XET=1` does **not** provide a working fallback in this
> environment (it redirects to `us.aws.cdn.hf.co`, which is blocked too).

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
