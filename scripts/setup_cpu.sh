#!/usr/bin/env bash
#
# Sets up a CPU-only Python environment for the financial-statement pipeline.
#
# Why two pip steps?
#   The PyPI torch wheels for Linux pull the full CUDA stack (~7-9 GB).
#   We force the lean CPU build (~200 MB) from PyTorch's CPU index FIRST,
#   then install the rest. Because torch is already satisfied, the second
#   step won't try to upgrade it back to the CUDA wheel.
#
# Prerequisite (network policy): both download.pytorch.org (the wheel index)
# AND download-r2.pytorch.org (the CDN that serves the wheel bytes) must be
# reachable. See README.md → "Network requirements".

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${REPO_ROOT}/.venv"
CPU_INDEX="https://download.pytorch.org/whl/cpu"

echo "==> Repo:  ${REPO_ROOT}"
echo "==> Venv:  ${VENV}"

# 1. venv
if [ ! -d "${VENV}" ]; then
  python3 -m venv "${VENV}"
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

python -m pip install --upgrade pip wheel setuptools

# 2. Preflight reachability — two layers.
#
#    The wheel *index* (an HTML listing on download.pytorch.org) and the *CDN
#    backend* that serves the actual wheel bytes are DIFFERENT hosts: file
#    downloads redirect to download-r2.pytorch.org. A network policy can
#    allowlist the index while still blocking the CDN, in which case the index
#    returns 200 but the install 403s mid-download. So we probe a real wheel
#    object too, not just the listing.
echo "==> Checking index ${CPU_INDEX}/torch/ reachability ..."
idx_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "${CPU_INDEX}/torch/" || true)"
if [ "${idx_code}" != "200" ]; then
  echo "ERROR: index ${CPU_INDEX}/torch/ returned HTTP ${idx_code} (expected 200)."
  echo "       The PyTorch CPU index is not reachable from this environment."
  echo "       Allowlist download.pytorch.org in the network policy, then re-run."
  exit 1
fi

echo "==> Checking the wheel CDN backend is reachable (not just the index) ..."
href="$(curl -sS --max-time 20 "${CPU_INDEX}/torch/" 2>/dev/null \
  | grep -oE 'href="[^"]*torch-[^"#]*\.whl[^"]*"' \
  | sed -E 's/^href="//; s/"$//' \
  | head -n1 || true)"
if [ -z "${href}" ]; then
  echo "WARN: could not parse a wheel URL from the index; skipping CDN probe."
else
  case "${href}" in
    http*) wheel_url="${href}" ;;
    /*)    wheel_url="https://download.pytorch.org${href}" ;;
    *)     wheel_url="${CPU_INDEX}/torch/${href}" ;;
  esac
  wheel_url="${wheel_url%%#*}"
  # The wheel bytes redirect to the CDN; pip's download is what 403s when that
  # host is blocked. HEAD the actual .whl (following redirects) so the probe is
  # version-agnostic — using the ".metadata" sidecar would 404 on older wheels
  # that predate PEP 658, even when the CDN is perfectly reachable.
  cdn_code="$(curl -sIL -o /dev/null --max-time 30 -w '%{http_code}' "${wheel_url}" || true)"
  case "${cdn_code}" in
    200|206) ;;  # reachable
    *)
      cdn_host="$(curl -sIL -o /dev/null -w '%{url_effective}' --max-time 30 "${wheel_url}" 2>/dev/null \
        | sed -E 's#^https?://([^/]+)/.*#\1#' || true)"
      echo "ERROR: the wheel CDN returned HTTP ${cdn_code} for the actual download"
      echo "       (the index returned 200, so this is a CDN-only block)."
      echo "       Blocked host: ${cdn_host:-download-r2.pytorch.org}"
      echo "       The torch/torchvision wheels are served from this CDN, NOT from"
      echo "       download.pytorch.org. Allowlist it (download-r2.pytorch.org) in"
      echo "       the network policy, then re-run."
      exit 1
      ;;
  esac
fi

# 3. Lean CPU torch first.
echo "==> Installing CPU torch + torchvision ..."
pip install --index-url "${CPU_INDEX}" torch torchvision

# 4. Everything else (torch already satisfied -> stays CPU).
echo "==> Installing pipeline requirements ..."
pip install -r "${REPO_ROOT}/requirements-cpu.txt"

# 5. Sanity check.
echo "==> Verifying install ..."
python - <<'PY'
import torch
from docling.document_converter import DocumentConverter  # noqa: F401
print(f"torch      : {torch.__version__}  (cuda build: {torch.version.cuda})")
print(f"cuda avail : {torch.cuda.is_available()}")
print(f"threads    : {torch.get_num_threads()}")
import docling
print(f"docling    : {docling.__version__}")
print("OK: docling + CPU torch import cleanly.")
PY

echo "==> Done. Activate with: source ${VENV}/bin/activate"
