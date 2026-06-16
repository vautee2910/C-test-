"""Pluggable table-extraction backends + a tiny benchmark harness.

The geometry reconstruction (:mod:`fsx.extract`) is the precise CPU default and
the backbone of Level 1 / the fact pipeline. This module adds a seam — the
:class:`TableExtractor` protocol, mirroring :class:`fsx.parsing.ocr.OcrBackend`
— so an alternative extractor (docling's TableFormer, a camelot pass, a remote
VLM …) can be *measured* against the default on the same PDF without touching
the core. Adoption follows evidence, never the other way round.

All backends return the common, domain-free
:class:`~fsx.extract.tables.ReconstructedTable` form (label + one value per
column, optional period ``column_headers``) so the Level-1 builder and the
scorer treat them uniformly. The scorer compares an extraction to a ground-truth
cell set and reports precision / recall / F1 — the only honest basis for
choosing a backend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from ..extract.tables import LineItem, ReconstructedTable

# A cell key: (1-based page, normalised row label, value-column index).
CellKey = tuple[int, str, int]


class TableExtractor(Protocol):
    """Anything that turns a PDF into reconstructed tables, per page."""

    name: str

    def is_available(self) -> bool:  # pragma: no cover - protocol
        """Whether this backend can run in the current environment."""
        ...

    def extract(
        self, pdf_path: str | Path, pages: Optional[list[int]] = None
    ) -> dict[int, list[ReconstructedTable]]:  # pragma: no cover - protocol
        """Return ``{1-based page: [panels]}`` with raw (un-anonymised) values."""
        ...


class GeometryTableExtractor:
    """The default backend: the pure-stdlib geometry reconstruction."""

    name = "geometry"

    def is_available(self) -> bool:
        return True

    def extract(
        self, pdf_path: str | Path, pages: Optional[list[int]] = None
    ) -> dict[int, list[ReconstructedTable]]:
        from ..extract.pdf_words import extract_tables

        # anonymizer=None: the benchmark needs verbatim values, not pseudonyms.
        return extract_tables(pdf_path, anonymizer=None, pages=pages)


class DoclingTableExtractor:
    """Adapter for docling's TableFormer table-structure model (optional).

    docling is ML-based (layout + table-structure) and handles spanning cells /
    nested headers the geometry pass cannot. It is heavy (pulls torch) and
    downloads models on first use, so it is *opt-in* and self-reports
    availability; the adapter maps docling's cell grid onto the common
    :class:`ReconstructedTable` (first column = label, the rest parsed as values).

    ``do_ocr`` selects docling's own OCR stage. It is off by default — born-digital
    statements already carry a text layer, and docling's default OCR otherwise
    pulls a model from a network host. Turn it **on** to run docling end-to-end on
    a *scan* (image-only PDF), so it can be benchmarked head-to-head against our
    OCRmyPDF→geometry path on the same raw scan. The backend reports its
    :attr:`name` accordingly (``docling`` vs ``docling-ocr``) so the scorer keeps
    the two modes apart.
    """

    def __init__(self, *, do_ocr: bool = False) -> None:
        self._converter = None
        self._do_ocr = do_ocr
        self.name = "docling-ocr" if do_ocr else "docling"

    def is_available(self) -> bool:
        # Probe the actual import path extract() needs, not just the top package:
        # docling can be installed yet fail to import its converter when its heavy
        # transformers / vision deps are version-mismatched (observed with
        # transformers 5.x → the granite-vision stage breaks on AutoProcessor).
        try:  # pragma: no cover - depends on optional heavy dep
            from docling.document_converter import DocumentConverter  # noqa: F401

            return True
        except Exception:
            return False

    def _convert(self, pdf_path: str | Path):  # pragma: no cover - heavy/optional
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        if self._converter is None:
            # Born-digital statements already carry a text layer, so OCR is off by
            # default (docling's default OCR otherwise pulls a model from a network
            # host); keep table-structure (TableFormer) on. For a scan, ``do_ocr``
            # turns the OCR stage on so docling can run end-to-end on the image.
            opts = PdfPipelineOptions(do_ocr=self._do_ocr, do_table_structure=True)
            self._converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
            )
        return self._converter.convert(str(pdf_path)).document

    def extract(
        self, pdf_path: str | Path, pages: Optional[list[int]] = None
    ) -> dict[int, list[ReconstructedTable]]:  # pragma: no cover - heavy/optional
        doc = self._convert(pdf_path)
        out: dict[int, list[ReconstructedTable]] = {}
        for table in getattr(doc, "tables", []):
            grid = table.export_to_dataframe().values.tolist()
            page = _docling_page_no(table)
            if page is None or (pages is not None and page not in pages):
                continue
            items = [
                LineItem(
                    label=str(row[0]).strip() if row else "",
                    values=[_to_float(c) for c in row[1:]],
                    y=float(i),
                )
                for i, row in enumerate(grid)
            ]
            n_cols = max((len(it.values) for it in items), default=0)
            out.setdefault(page, []).append(
                ReconstructedTable(n_columns=n_cols, items=items)
            )
        return out


def _docling_page_no(table) -> Optional[int]:  # pragma: no cover - heavy/optional
    """Best-effort 1-based page number from a docling table's provenance."""
    prov = getattr(table, "prov", None) or []
    if prov and getattr(prov[0], "page_no", None) is not None:
        return int(prov[0].page_no)
    return None


def _to_float(cell: object) -> Optional[float]:
    """Parse a docling cell (German or plain number) to float, else ``None``."""
    from ..extract.numbers import parse_de_number

    s = str(cell).strip()
    if not s:
        return None
    v = parse_de_number(s)
    if v is not None:
        return v
    try:
        return float(s.replace(" ", ""))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Scoring — the honest basis for comparing backends
# --------------------------------------------------------------------------- #

_NORM_RE = re.compile(r"[^0-9a-zäöüß]+")


def _norm_label(label: str) -> str:
    """Fold a row label to a comparison key (case/leader/space-insensitive)."""
    return _NORM_RE.sub(" ", label.lower()).strip()


def flatten_cells(
    tables_by_page: dict[int, list[ReconstructedTable]]
) -> dict[CellKey, float]:
    """Flatten an extraction to ``{(page, label, col): value}`` for scoring."""
    out: dict[CellKey, float] = {}
    for page, panels in tables_by_page.items():
        for table in panels:
            for item in table.items:
                label = _norm_label(item.label)
                if not label:
                    continue
                for col, value in enumerate(item.values):
                    if value is not None:
                        out[(page, label, col)] = value
    return out


@dataclass(frozen=True)
class BackendScore:
    """Precision / recall / F1 of one backend against ground truth."""

    name: str
    correct: int
    extracted: int
    expected: int

    @property
    def precision(self) -> float:
        return self.correct / self.extracted if self.extracted else 0.0

    @property
    def recall(self) -> float:
        return self.correct / self.expected if self.expected else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def score_extraction(
    name: str,
    extracted: dict[CellKey, float],
    truth: dict[CellKey, float],
    *,
    rel_tol: float = 0.0,
) -> BackendScore:
    """Score ``extracted`` cells against ``truth`` (exact value match by default).

    A cell counts as correct only when the *same* (page, label, column) carries a
    matching value — a wrong figure is a miss, not a hit (precision over recall).
    """
    correct = 0
    for key, want in truth.items():
        got = extracted.get(key)
        if got is None:
            continue
        if got == want or (rel_tol and abs(got - want) <= rel_tol * abs(want)):
            correct += 1
    return BackendScore(
        name=name, correct=correct, extracted=len(extracted), expected=len(truth)
    )
