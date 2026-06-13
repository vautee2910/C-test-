"""Schema contract tests for the three pipeline levels."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fsx.schemas import (
    AnalysisFeature,
    BlockType,
    Fact,
    FeatureFlag,
    Page,
    RawDocument,
    StatementType,
    Table,
    TextBlock,
)


def test_raw_document_roundtrip():
    doc = RawDocument(
        document_id="DOC_2024_001",
        company_id="COMPANY_001",
        fiscal_year=2024,
        pages=[
            Page(
                page=17,
                blocks=[TextBlock(text_anonymized="Die [UNTERNEHMEN_1] ...", bbox=(72, 130, 520, 180))],
                tables=[Table(table_id="T_17_01", caption_anonymized="GuV", cells=[["a", "b"]])],
            )
        ],
    )
    again = RawDocument.model_validate(doc.model_dump())
    assert again.pages[0].blocks[0].type == BlockType.TEXT
    assert again.pages[0].tables[0].table_id == "T_17_01"


def test_fact_defaults_and_concept():
    f = Fact(
        fact_id="F1",
        company_id="COMPANY_001",
        fiscal_year=2024,
        concept="personnel_expense",
        value=1234000,
    )
    assert f.statement == StatementType.UNKNOWN
    assert f.currency == "EUR"
    assert f.confidence == 1.0


def test_fact_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        Fact(fact_id="F1", company_id="C", fiscal_year=2024, concept="x", value=1, confidence=1.5)


def test_analysis_feature_flag_enum():
    feat = AnalysisFeature(
        company_id="COMPANY_001",
        metric="personalaufwand_quote",
        year=2024,
        value=0.214,
        delta_pct_vs_prev_year=16.9,
        flag=FeatureFlag.INCREASE,
    )
    assert feat.flag == FeatureFlag.INCREASE
