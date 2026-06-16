#!/usr/bin/env python
"""Benchmark table-extraction backends against a ground truth.

Runs every *available* backend (geometry default; docling if installed) over a
PDF and reports precision / recall / F1 on a cell set — the honest basis for
choosing a backend. Adoption follows the numbers, not vibes.

Usage:
    # zero external files: generate a synthetic statement + ground truth
    python scripts/bench_tables.py --synthetic

    # a real PDF with a ground-truth JSON: [{"page":1,"label":"Umsatzerlöse",
    #   "col":0,"value":1234.0}, ...]
    python scripts/bench_tables.py --pdf doc.pdf --truth gt.json --pages 1,2
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fsx.parsing.table_backends import (  # noqa: E402
    DoclingTableExtractor,
    GeometryTableExtractor,
    flatten_cells,
    score_extraction,
)

BACKENDS = [GeometryTableExtractor(), DoclingTableExtractor()]


def _make_synthetic(tmp: Path) -> tuple[Path, dict]:
    """A small born-digital statement (year header + 4 rows) with its truth."""
    import fitz

    rows = [
        ("Umsatzerlöse", "1.234", "1.100"),
        ("Materialaufwand", "5.678", "5.000"),
        ("Personalaufwand", "9.012", "8.500"),
        ("Jahresüberschuss", "3.456", "2.900"),
    ]
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((400, 80), "2023")
    page.insert_text((470, 80), "2022")
    y = 110
    for label, cur, prior in rows:
        page.insert_text((72, y), label)
        page.insert_text((400, y), cur)
        page.insert_text((470, y), prior)
        y += 20
    path = tmp / "synthetic_statement.pdf"
    doc.save(path)
    doc.close()
    truth = {}
    for label, cur, prior in rows:
        truth[(1, label, 0)] = float(cur.replace(".", ""))
        truth[(1, label, 1)] = float(prior.replace(".", ""))
    return path, truth


def _truth_from_json(path: Path) -> dict:
    from fsx.parsing.table_backends import _norm_label

    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        (int(r["page"]), _norm_label(r["label"]), int(r["col"])): float(r["value"])
        for r in rows
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--pdf")
    ap.add_argument("--truth")
    ap.add_argument("--pages")
    ap.add_argument("--rel-tol", type=float, default=0.0)
    args = ap.parse_args()

    pages = [int(p) for p in args.pages.split(",")] if args.pages else None

    with tempfile.TemporaryDirectory() as td:
        if args.synthetic:
            from fsx.parsing.table_backends import _norm_label

            pdf, raw_truth = _make_synthetic(Path(td))
            truth = {(p, _norm_label(lbl), c): v for (p, lbl, c), v in raw_truth.items()}
        elif args.pdf and args.truth:
            pdf, truth = Path(args.pdf), _truth_from_json(Path(args.truth))
        else:
            ap.error("pass --synthetic, or both --pdf and --truth")

        print(f"PDF: {pdf}   ground-truth cells: {len(truth)}")
        print(f"{'backend':12s} {'avail':6s} {'prec':>6s} {'recall':>7s} {'f1':>6s} "
              f"{'correct':>8s} {'extracted':>10s}")
        for be in BACKENDS:
            if not be.is_available():
                print(f"{be.name:12s} {'no':6s}    (not installed — skipped)")
                continue
            extracted = flatten_cells(be.extract(pdf, pages=pages))
            s = score_extraction(be.name, extracted, truth, rel_tol=args.rel_tol)
            print(f"{be.name:12s} {'yes':6s} {s.precision:6.2f} {s.recall:7.2f} "
                  f"{s.f1:6.2f} {s.correct:8d} {s.extracted:10d}")


if __name__ == "__main__":
    main()
