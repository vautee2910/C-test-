"""Functional proof that the reusable pipelines work *standalone*.

Unlike ``test_modularity.py`` (which guards imports), these exercise each
capability end to end using **only** its own package — no domain layer, and for
the extractor, no anonymiser either — on inputs that have nothing to do with
financial statements. This is what "lift it into another app" looks like.
"""

from __future__ import annotations

from pathlib import Path

import fitz

# Reusable package #1 — anonymisation — imported on its own.
from fsx.anonymize import (
    Anonymizer,
    DictionaryDetector,
    DictionaryEntity,
    Label,
    RegexDetector,
)

# Reusable package #2 — table extraction — imported on its own.
from fsx.extract import Word, reconstruct_tables
from fsx.extract.pdf_words import extract_tables


# --------------------------------------------------------------------------- #
# Anonymisation pipeline, standalone, on arbitrary (non-financial) text
# --------------------------------------------------------------------------- #


def test_anonymize_pipeline_standalone_on_generic_text():
    anon = Anonymizer(
        detectors=[
            DictionaryDetector([
                DictionaryEntity("p1", Label.PERSON, ["Erika Mustermann"]),
            ]),
            RegexDetector(),  # structured identifiers: email, IBAN, phone, ...
        ]
    )
    text = (
        "Hi, this is Erika Mustermann. Reach me at erika@example.com, "
        "transfer to DE89370400440532013000. Regards, Erika Mustermann."
    )
    result = anon.anonymize(text)

    # PII is gone from the output...
    assert "Erika Mustermann" not in result.text
    assert "erika@example.com" not in result.text
    assert "DE89370400440532013000" not in result.text
    # ...replaced by stable, typed pseudonyms (same entity -> same token twice).
    assert result.text.count("[PERSON_1]") == 2
    assert "[EMAIL_1]" in result.text and "[IBAN_1]" in result.text
    # ...and reversible via the mapping.
    assert result.mapping["[EMAIL_1]"] == "erika@example.com"


def test_anonymizer_pseudonyms_are_consistent_across_calls():
    anon = Anonymizer(detectors=[RegexDetector()])
    first = anon.anonymize("Mail an a@b.com")
    second = anon.anonymize("Nochmal a@b.com")
    # The same source value keeps the same token across documents.
    assert first.text.split()[-1] == second.text.split()[-1]


# --------------------------------------------------------------------------- #
# Extraction pipeline, standalone, with no anonymiser and no domain layer
# --------------------------------------------------------------------------- #


def _w(x0, x1, y, text):
    return Word(x0=x0, y0=y, x1=x1, y1=y + 10, text=text)


def test_reconstruct_tables_standalone_pure_geometry():
    # A generic two-column numeric table — nothing financial about it.
    words = [
        _w(50, 120, 100, "Population"),
        _w(300, 360, 100, "1.000.000"), _w(420, 480, 100, "950.000"),
        _w(50, 120, 120, "Households"),
        _w(300, 360, 120, "400.000"), _w(420, 480, 120, "380.000"),
    ]
    tables = reconstruct_tables(words)
    assert len(tables) == 1
    pop = next(it for it in tables[0].items if "Population" in it.label)
    assert pop.values == [1_000_000.0, 950_000.0]


def test_extract_tables_standalone_without_anonymizer(tmp_path: Path):
    # Build a tiny PDF with a right-aligned numeric table, then extract it with
    # no anonymiser (anonymizer=None) and no domain code in sight.
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Widgets")
    page.insert_text((300, 100), "12.345")
    pdf = tmp_path / "generic.pdf"
    doc.save(pdf)
    doc.close()

    tables = extract_tables(pdf)  # anonymizer defaults to None
    items = [it for panel in tables.get(1, []) for it in panel.items]
    assert any(it.label == "Widgets" for it in items)
    assert any(12345.0 in it.values for it in items if it.has_values)
