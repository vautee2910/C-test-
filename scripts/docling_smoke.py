#!/usr/bin/env python3
"""Minimal Docling smoke test: convert a PDF and print structure summary.

Usage:
    python scripts/docling_smoke.py path/to/statement.pdf [out_dir]

On first run Docling downloads its layout + table models from HuggingFace,
so the initial invocation is slower and needs huggingface.co allowlisted.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    pdf = Path(sys.argv[1])
    if not pdf.is_file():
        print(f"ERROR: no such file: {pdf}")
        return 1
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)

    from docling.document_converter import DocumentConverter

    print(f"Converting {pdf} ...")
    result = DocumentConverter().convert(str(pdf))
    doc = result.document

    n_tables = len(getattr(doc, "tables", []) or [])
    n_pages = len(getattr(doc, "pages", {}) or {})
    print(f"  pages : {n_pages}")
    print(f"  tables: {n_tables}")

    md_path = out_dir / (pdf.stem + ".md")
    md_path.write_text(doc.export_to_markdown(), encoding="utf-8")
    print(f"  markdown -> {md_path}")

    json_path = out_dir / (pdf.stem + ".json")
    try:
        import json

        json_path.write_text(
            json.dumps(doc.export_to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  json     -> {json_path}")
    except Exception as exc:  # pragma: no cover - best-effort dump
        print(f"  (json export skipped: {exc})")

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
