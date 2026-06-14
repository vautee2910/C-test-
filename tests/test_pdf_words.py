"""Tests for the PyMuPDF word adapter feeding the geometric reconstructor.

The key behaviour is rotation normalisation: landscape balance sheets are often
bound into a portrait report as ``/Rotate 90`` pages, on which PyMuPDF returns
word boxes in the unrotated content space (glyphs advancing vertically). Without
mapping them into visual reading orientation, the row-clustering reconstructor
scrambles the table. Upright pages must be left untouched.
"""

from __future__ import annotations

import fitz
import pytest

from fsx.extract.pdf_words import words_from_page


def _new_page(rotation: int = 0):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((100, 120), "Aktiva")
    page.insert_text((300, 120), "1.234,56")
    if rotation:
        page.set_rotation(rotation)
    return doc, page


def test_upright_page_coordinates_are_unchanged():
    # rotation == 0 -> rotation_matrix is the identity; born-digital portrait
    # statements must pass through byte-for-byte.
    _doc, page = _new_page(rotation=0)
    got = {w.text: w for w in words_from_page(page)}
    raw = {r[4]: r for r in page.get_text("words") if r[4].strip()}
    for text, w in got.items():
        x0, y0, x1, y1 = raw[text][:4]
        assert (w.x0, w.y0, w.x1, w.y1) == pytest.approx((x0, y0, x1, y1))


def test_rotated_page_words_mapped_to_reading_orientation():
    # On a /Rotate 90 page the words must be transformed by the page's rotation
    # matrix, not returned in raw content space.
    _doc, page = _new_page(rotation=90)
    mat = page.rotation_matrix
    got = {w.text: w for w in words_from_page(page)}
    for raw in page.get_text("words"):
        x0, y0, x1, y1, text, *_ = raw
        if not text.strip():
            continue
        r = fitz.Rect(x0, y0, x1, y1) * mat
        r.normalize()
        w = got[text]
        assert (w.x0, w.y0, w.x1, w.y1) == pytest.approx((r.x0, r.y0, r.x1, r.y1))


def test_rotated_output_differs_from_raw():
    # Guard against silently dropping the rotation mapping.
    _doc, page = _new_page(rotation=90)
    got = {w.text: w for w in words_from_page(page)}
    raw = {r[4]: r for r in page.get_text("words") if r[4].strip()}
    label = got["Aktiva"]
    rx0, ry0 = raw["Aktiva"][0], raw["Aktiva"][1]
    assert (label.x0, label.y0) != pytest.approx((rx0, ry0))
