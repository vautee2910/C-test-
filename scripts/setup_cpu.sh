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
# Prerequisite (network policy): download.pytorch.org must be reachable.
# See README.md → "Network requirements".

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

# 2. Preflight: confirm the CPU index is reachable before we commit to it.
echo "==> Checking ${CPU_INDEX} reachability ..."
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "${CPU_INDEX}/torch/" || true)"
if [ "${code}" != "200" ]; then
  echo "ERROR: ${CPU_INDEX} returned HTTP ${code} (expected 200)."
  echo "       The PyTorch CPU index is not reachable from this environment."
  echo "       Allowlist download.pytorch.org in the network policy, then re-run."
  exit 1
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
