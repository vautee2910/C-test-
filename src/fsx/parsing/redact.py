"""Write an anonymised *copy* of a PDF — same layout, PII replaced in place.

This is the optional, document-shaped output of the anonymisation pipeline: the
original PDF with every detected PII surface replaced, in situ, by the **same**
pseudonym token the rest of the pipeline uses (``[PERSON_1]`` …), and with the
document metadata scrubbed. Everything else — fonts, geometry, figures, every
non-PII glyph — is left byte-for-byte where it was.

It is built on PyMuPDF *redaction annotations*, not a cosmetic overlay:
``apply_redactions()`` genuinely removes the covered text from the content
stream (and, with the default ``images=PIXELS``, blanks the covered pixels of a
page image — so a scanned name is erased from the *image*, not merely from the
invisible OCR layer). The result is safe to hand out, consistent with the
"anonymise before egress" principle.

Detection reuses the engagement :class:`~fsx.anonymize.engine.Anonymizer`, so a
name becomes the same token here as in the Level-1 ``RawDocument`` / fact pack
when the *same* instance is shared. Precision-over-recall holds: redaction is
driven by the full detector set over the page text (high recall), longest
surfaces first, and a surface that does not match as one contiguous run falls
back to per-word boxes (over-redact rather than leak).

Limit (be honest): redaction is driven by *detected text*. PII baked into a
raster logo as pixels (no text, no detection box) is not found automatically;
that is a property of any detection-driven redaction, not of this code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from ..anonymize.engine import Anonymizer

# A surface must have at least this many characters to be searched/redacted —
# a lone letter would match half the page.
_MIN_SURFACE = 2


@dataclass(frozen=True)
class RedactionSummary:
    """What :func:`write_anonymized_pdf` did, for logging / a host audit."""

    output_path: str
    pages: int
    entities: int  # distinct PII surfaces redacted
    boxes: int     # redaction boxes applied across all pages
    metadata_scrubbed: bool


def _fit_fontsize(rect: "fitz.Rect", token: str) -> float:
    """A font size that keeps ``token`` inside its original box.

    Helvetica averages ~0.5 em per glyph; fit by width and cap by the box
    height, clamped to a legible range so the token stays readable.
    """
    by_width = rect.width / (0.5 * max(len(token), 1))
    return max(4.0, min(rect.height * 0.85, by_width, 11.0))


def _surfaces_by_token(doc: "fitz.Document", anonymizer: Anonymizer, use_models: bool) -> dict[str, str]:
    """Run the detectors over every page's text; return ``{surface: token}``.

    ``page.get_text("blocks")`` yields the full visible text (prose *and* table
    content), so feeding the blocks to the anonymiser detects all text PII at the
    pipeline's recall. The cumulative token→surface mapping is inverted; because
    it spans the whole document, a surface first seen on page 1 is also redacted
    where it recurs on a later page (consistent pseudonyms).
    """
    for page in doc:
        for block in page.get_text("blocks"):
            text = block[4]
            if text and text.strip():
                anonymizer.anonymize(text, use_models=use_models)
    return {surface: token for token, surface in anonymizer.mapping.items()}


def _mostly_covered(rect: "fitz.Rect", placed: list["fitz.Rect"]) -> bool:
    """True if ``rect`` is already (mostly) inside a scheduled redaction box.

    Stops a shorter substring surface ("Muster") double-boxing a longer one
    ("Muster GmbH") that was redacted first.
    """
    area = abs(rect.get_area())
    if area == 0:
        return True
    for p in placed:
        inter = fitz.Rect(rect)
        inter.intersect(p)
        if not inter.is_empty and abs(inter.get_area()) > 0.6 * area:
            return True
    return False


_EDGE_PUNCT = " \t\r\n.,;:!?()[]{}\"'`/\\„“”»«…-"


def _norm(text: str) -> str:
    """Whitespace-collapsed, edge-punctuation-stripped, case-folded comparison key."""
    return " ".join(text.split()).strip(_EDGE_PUNCT).casefold()


def _match_word_rects(words: list[tuple[str, "fitz.Rect"]], surface: str) -> list["fitz.Rect"]:
    """Rects of every *whole-word* run of ``words`` whose text equals ``surface``.

    Matching is by consecutive word windows, not substring: this is what keeps a
    short or mis-detected surface ("Jah" from a hyphenated "Jah-resabschluss")
    from blanking the inside of every "Jahresabschluss"/"Geschäftsjahr" — only a
    standalone word matches. It also rejoins a surface that wrapped across lines
    (the words list is line-agnostic), so multi-word names/addresses still match.
    """
    target = _norm(surface)
    if not target:
        return []
    n_words = len(target.split())
    rects: list[fitz.Rect] = []
    for i in range(len(words) - n_words + 1):
        window = words[i:i + n_words]
        if _norm(" ".join(t for t, _ in window)) == target:
            r = fitz.Rect(window[0][1])
            for _, rr in window[1:]:
                r |= rr
            rects.append(r)
    return rects


def _redact_surface(
    page, words: list[tuple[str, "fitz.Rect"]], surface: str, token: str,
    placed: list["fitz.Rect"],
) -> int:
    """Add a token redaction box over every whole-word match of ``surface``."""
    n = 0
    for r in _match_word_rects(words, surface):
        if _mostly_covered(r, placed):
            continue
        page.add_redact_annot(
            r, text=token, fontsize=_fit_fontsize(r, token),
            align=fitz.TEXT_ALIGN_LEFT, fill=(1, 1, 1), text_color=(0, 0, 0),
        )
        placed.append(r)
        n += 1
    return n


def _scrub_document(doc: "fitz.Document") -> None:
    """Strip the document info dict, XMP metadata and embedded/attached files.

    The info dict routinely carries an author / internal title (and XMP mirrors
    it); both are cleared via ``set_metadata({})`` / ``del_xml_metadata``, and
    embedded/attached files are deleted by name. These reliable calls are used
    instead of ``doc.scrub`` — scrub's full xref walk raises on real-world PDFs
    with an irregular xref, and the metadata is the part that matters here.
    """
    doc.set_metadata({})
    try:
        doc.del_xml_metadata()
    except Exception:  # pragma: no cover - older bindings
        pass
    try:
        for name in list(doc.embfile_names()):
            doc.embfile_del(name)
    except Exception:  # pragma: no cover - none embedded
        pass


def _redact_widgets_and_annots(page, surfaces: list[str], sig_index: list[int]) -> int:
    """Redact signature stamps and PII-bearing annotations on ``page``.

    ``page.search_for`` only scans the content stream, so text rendered inside a
    *signature widget* appearance (the signer's name/stamp) or a free-text/stamp
    annotation is invisible to the main loop. A signature stamp is inherently
    identifying, so every Signature widget is redacted and removed; other
    annotations are redacted only when their text carries a detected PII surface.
    Removing the widget drops its appearance; the redaction box blanks the area.
    """
    n = 0
    for w in list(page.widgets() or []):
        rect_text = page.get_textbox(w.rect) or ""
        is_signature = (w.field_type_string or "").lower() == "signature"
        if is_signature or any(s in rect_text for s in surfaces):
            sig_index[0] += 1
            token = f"[SIGNATUR_{sig_index[0]}]"
            page.add_redact_annot(
                w.rect, text=token, fontsize=_fit_fontsize(w.rect, token),
                align=fitz.TEXT_ALIGN_LEFT, fill=(1, 1, 1), text_color=(0, 0, 0),
            )
            try:
                page.delete_widget(w)
            except Exception:  # pragma: no cover - binding/version dependent
                pass
            n += 1
    for a in list(page.annots() or []):
        # Skip the redaction annotations the text loop just added (their rect
        # still covers the original PII text, which would otherwise match here
        # and get a second, token-erasing black box on top).
        if a.type[0] == fitz.PDF_ANNOT_REDACT:
            continue
        blob = (a.info.get("content") or "") + " " + (page.get_textbox(a.rect) or "")
        if any(s in blob for s in surfaces):
            page.add_redact_annot(a.rect, fill=(0, 0, 0))
            try:
                page.delete_annot(a)
            except Exception:  # pragma: no cover - binding/version dependent
                pass
            n += 1
    return n


def write_anonymized_pdf(
    src: str | Path,
    dst: str | Path,
    *,
    anonymizer: Anonymizer,
    use_models: bool = True,
    scrub_metadata: bool = True,
    redact_signatures: bool = True,
    detect: bool = True,
) -> RedactionSummary:
    """Write an anonymised copy of ``src`` to ``dst`` and return a summary.

    Pass the *same* ``anonymizer`` used to build the document's ``RawDocument``
    so the tokens match across artifacts. ``use_models`` keeps the statistical
    model in the detection (default, max recall); set it ``False`` for the fast
    dictionary+regex-only path. ``scrub_metadata`` clears the document info-dict,
    XMP metadata and embedded/attached files — PDF metadata routinely carries an
    author / internal title. ``redact_signatures`` removes visible signature
    stamps (the signer's name lives in the widget appearance, which the text loop
    cannot see) and PII-bearing annotations. ``detect`` re-runs the detectors over
    the page text to find PII surfaces; pass ``False`` to reuse the surfaces the
    given ``anonymizer`` already collected (e.g. during a preceding ``parse_pdf``),
    avoiding a second, costly model pass.
    """
    src, dst = Path(src), Path(dst)
    doc = fitz.open(src)
    if detect:
        surfaces = _surfaces_by_token(doc, anonymizer, use_models)
    else:
        surfaces = {surface: token for token, surface in anonymizer.mapping.items()}
    # Longest surfaces first: redact "Muster Maschinenbau GmbH" before "Muster".
    ordered = sorted(
        ((s.strip(), t) for s, t in surfaces.items() if len(s.strip()) >= _MIN_SURFACE),
        key=lambda kv: len(kv[0]), reverse=True,
    )
    surface_keys = [s for s, _ in ordered]
    sig_index = [0]
    boxes = 0
    for page in doc:
        words = [(w[4], fitz.Rect(w[:4])) for w in page.get_text("words")]
        placed: list[fitz.Rect] = []
        for surface, token in ordered:
            boxes += _redact_surface(page, words, surface, token, placed)
        if redact_signatures:
            boxes += _redact_widgets_and_annots(page, surface_keys, sig_index)
        # images=PIXELS (default) blanks the covered pixels of a page image too,
        # so a scanned name is erased from the image, not just the OCR text layer.
        page.apply_redactions()

    if scrub_metadata:
        _scrub_document(doc)

    pages = doc.page_count
    doc.save(dst, garbage=4, deflate=True)
    doc.close()
    return RedactionSummary(
        output_path=str(dst),
        pages=pages,
        entities=len(ordered),
        boxes=boxes,
        metadata_scrubbed=scrub_metadata,
    )
