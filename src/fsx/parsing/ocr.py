"""OCR front-stage: make scanned PDFs searchable before the rest of the chain.

A scanned annual statement has no text layer, so the geometry-based extractor
downstream sees nothing. This module adds an *optional* pass that produces a
searchable PDF — same pages, same coordinates, plus an invisible text layer —
which then flows into the existing :class:`PyMuPDFParser` **unchanged**.

Design:

* :class:`OcrBackend` is the interface. Any engine (OCRmyPDF/Tesseract today,
  Docling-OCR or another tool later) implements ``is_available`` and
  ``ocr_to_pdf`` and can be swapped in without touching the parser.
* :class:`OcrMyPdfBackend` wraps OCRmyPDF + Tesseract. It is fully local: the
  Tesseract language data ships with the OS package, nothing is sent anywhere.
* :func:`ensure_searchable_pdf` is the orchestrator. It applies the gate from
  :mod:`fsx.parsing.text_layer`: **if a text layer is already present, no OCR is
  run** and the original file is returned untouched. Only image-only / scanned
  documents get an OCR pass.

Everything here is import-light by default; the OCRmyPDF dependency is imported
lazily inside the backend so the parsing package keeps loading without it.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .text_layer import has_text_layer


class OcrError(RuntimeError):
    """Raised when an OCR backend fails or is asked to run while unavailable."""


class OcrBackend(Protocol):
    """Anything that can turn a (scanned) PDF into a searchable PDF."""

    def is_available(self) -> bool:  # pragma: no cover - protocol
        """Whether this backend can actually run in the current environment."""
        ...

    def ocr_to_pdf(self, src: Path, dst: Path) -> Path:  # pragma: no cover - protocol
        """OCR ``src`` and write a searchable PDF to ``dst``; return ``dst``."""
        ...


@dataclass(frozen=True)
class OcrOutcome:
    """Result of the OCR gate.

    Attributes:
        pdf_path: the PDF to feed downstream — the OCR output if a pass ran, else
            the original input.
        ocr_applied: whether an OCR pass actually ran.
        reason: short, human-readable explanation of the decision (for logs).
    """

    pdf_path: Path
    ocr_applied: bool
    reason: str


class OcrMyPdfBackend:
    """OCR backend built on OCRmyPDF + Tesseract — entirely local.

    ``language`` is a Tesseract language spec (``"deu+eng"`` by default: German
    statements occasionally carry English headings).

    Two mutually exclusive page-selection modes (OCRmyPDF forbids combining
    them):

    * ``skip_text=True`` — OCR only the pages that *lack* a text layer and leave
      existing-text pages byte-for-byte intact. Right for **genuinely mixed**
      PDFs (a digital statement with a scanned cover page).
    * ``force_ocr=True`` — rasterise and OCR **every** page, discarding any
      existing text layer. Right once a document-level gate has already decided
      the file is a scan: some scans carry a *phantom* text layer (a few
      invisible / non-Unicode glyphs) that ``skip_text`` treats as "already has
      text" and silently passes through, so those pages reach the parser with no
      usable text. Forcing OCR avoids that data loss. ``force_ocr`` wins if both
      are set.
    """

    def __init__(
        self,
        *,
        language: str = "deu+eng",
        skip_text: bool = True,
        force_ocr: bool = False,
        deskew: bool = False,
        rotate_pages: bool = False,
        optimize: int = 0,
        output_type: str = "pdf",
        progress_bar: bool = False,
    ) -> None:
        self.language = language
        self.skip_text = skip_text
        self.force_ocr = force_ocr
        self.deskew = deskew
        self.rotate_pages = rotate_pages
        self.optimize = optimize
        self.output_type = output_type
        self.progress_bar = progress_bar

    def is_available(self) -> bool:
        """True when both the ``ocrmypdf`` package and the Tesseract binary exist."""
        if shutil.which("tesseract") is None:
            return False
        try:
            import ocrmypdf  # noqa: F401
        except Exception:
            return False
        return True

    def ocr_to_pdf(self, src: Path, dst: Path) -> Path:
        src = Path(src)
        dst = Path(dst)
        try:
            import ocrmypdf
        except Exception as exc:  # pragma: no cover - exercised only without dep
            raise OcrError(
                "OCRmyPDF is not installed; install 'ocrmypdf' and the Tesseract "
                "binary to enable the OCR stage."
            ) from exc

        dst.parent.mkdir(parents=True, exist_ok=True)
        # force_ocr and skip_text are mutually exclusive in OCRmyPDF; pass only
        # the selected one so the call never raises on a conflicting pair.
        page_mode = {"force_ocr": True} if self.force_ocr else {"skip_text": self.skip_text}
        try:
            ocrmypdf.ocr(
                str(src),
                str(dst),
                language=self.language,
                deskew=self.deskew,
                rotate_pages=self.rotate_pages,
                optimize=self.optimize,
                output_type=self.output_type,
                progress_bar=self.progress_bar,
                **page_mode,
            )
        except Exception as exc:  # ocrmypdf raises a family of exceptions
            raise OcrError(f"OCRmyPDF failed on {src.name}: {exc}") from exc
        return dst


def default_backend() -> OcrBackend:
    """Return the project's default OCR backend (OCRmyPDF/Tesseract).

    Uses ``force_ocr=True``: this backend is only ever invoked by
    :func:`ensure_searchable_pdf` *after* the document-level gate has already
    found no usable text layer, so re-OCRing every page is correct and dodges
    the ``skip_text`` phantom-text-layer trap (see :class:`OcrMyPdfBackend`).
    """
    return OcrMyPdfBackend(force_ocr=True)


def ensure_searchable_pdf(
    path: str | Path,
    *,
    backend: OcrBackend | None = None,
    output_path: str | Path | None = None,
    force: bool = False,
    min_chars_per_page: int = 16,
    min_page_coverage: float = 0.5,
) -> OcrOutcome:
    """Return a searchable PDF for ``path``, running OCR only when needed.

    The gate:

    * if ``force`` is false and ``path`` already has a text layer (per
      :func:`~fsx.parsing.text_layer.has_text_layer`), **no OCR runs** and the
      original path is returned;
    * otherwise the ``backend`` (default :class:`OcrMyPdfBackend`) OCRs the file.

    ``output_path`` defaults to a sibling ``<stem>.ocr.pdf`` next to the source.
    Raises :class:`OcrError` if OCR is required but the backend is unavailable.
    """
    path = Path(path)
    backend = backend if backend is not None else default_backend()

    if not force and has_text_layer(
        path,
        min_chars_per_page=min_chars_per_page,
        min_page_coverage=min_page_coverage,
    ):
        return OcrOutcome(pdf_path=path, ocr_applied=False, reason="text-layer-present")

    if not backend.is_available():
        raise OcrError(
            "OCR is required for a scanned PDF but no OCR backend is available "
            "(need the 'ocrmypdf' package and the Tesseract binary on PATH)."
        )

    dst = Path(output_path) if output_path is not None else path.with_suffix(".ocr.pdf")
    dst.parent.mkdir(parents=True, exist_ok=True)
    backend.ocr_to_pdf(path, dst)
    reason = "forced-ocr" if force else "no-text-layer"
    return OcrOutcome(pdf_path=dst, ocr_applied=True, reason=reason)
