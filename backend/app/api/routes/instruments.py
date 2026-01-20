"""Instrument routes for Module 2"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.db import get_db
from app.models.schemas import InstrumentCreate, InstrumentResponse, InstrumentMappingRequest
from app.services.instrument_service import InstrumentService

router = APIRouter()


@router.post("/", response_model=InstrumentResponse, status_code=201)
def create_instrument(instrument: InstrumentCreate, db: Session = Depends(get_db)):
    """Create a new instrument."""
    result = InstrumentService.create_instrument(
        db,
        name=instrument.name,
        instrument_type=instrument.instrument_type,
        isin=instrument.isin,
        wkn=instrument.wkn,
        ticker=instrument.ticker,
        exchange=instrument.exchange,
        currency=instrument.currency,
        sector=instrument.sector,
        region=instrument.region,
        metadata=instrument.metadata
    )
    return result


@router.get("/search")
def search_instruments(
    q: Optional[str] = Query(None, description="Search query"),
    instrument_type: Optional[str] = Query(None, description="Filter by instrument type"),
    limit: int = Query(50, le=100),
    db: Session = Depends(get_db)
):
    """Search instruments."""
    results = InstrumentService.search_instruments(db, q, instrument_type, limit)
    return {"results": [dict(r._mapping) for r in results]}


@router.get("/{instrument_id}", response_model=InstrumentResponse)
def get_instrument(instrument_id: int, db: Session = Depends(get_db)):
    """Get instrument by ID."""
    instrument = InstrumentService.get_instrument_by_id(db, instrument_id)
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return instrument


@router.get("/resolve/")
def resolve_instrument(
    isin: Optional[str] = None,
    wkn: Optional[str] = None,
    ticker: Optional[str] = None,
    name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Resolve instrument by ISIN/WKN/ticker/name."""
    instrument_id = InstrumentService.resolve_instrument(db, isin, wkn, ticker, name)

    if instrument_id:
        instrument = InstrumentService.get_instrument_by_id(db, instrument_id)
        return {"resolved": True, "instrument": dict(instrument._mapping)}
    else:
        # Try fuzzy search if no exact match
        if name:
            fuzzy_matches = InstrumentService.fuzzy_search_instruments(db, name)
            return {
                "resolved": False,
                "suggestions": [
                    {"id": m[0], "name": m[1], "score": m[2]}
                    for m in fuzzy_matches
                ]
            }
        return {"resolved": False, "suggestions": []}


@router.get("/admin/unresolved-mappings")
def get_unresolved_mappings(status: str = "pending", db: Session = Depends(get_db)):
    """Get unresolved mappings for analyst review."""
    mappings = InstrumentService.get_unresolved_mappings(db, status)
    return {"mappings": [dict(m._mapping) for m in mappings]}


@router.post("/admin/resolve-mapping/{mapping_id}")
def resolve_mapping(
    mapping_id: int,
    mapping: InstrumentMappingRequest,
    db: Session = Depends(get_db)
):
    """Resolve an unresolved mapping."""
    result = InstrumentService.resolve_unresolved_mapping(
        db, mapping_id, mapping.instrument_id, resolved_by=1  # Would use actual user ID
    )
    return {"status": "resolved", "mapping": dict(result._mapping) if result else None}
