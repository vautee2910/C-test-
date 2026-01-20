"""Document routes for Modules 5 & 6"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.db import get_db
from app.models.schemas import DocumentCreate, HybridSearchRequest
from app.services.document_service import DocumentService

router = APIRouter()


@router.post("/ingest", status_code=201)
def ingest_document(document: DocumentCreate, db: Session = Depends(get_db)):
    """Ingest a new document."""
    doc_service = DocumentService()
    document_id = doc_service.ingest_document(
        db,
        source_id=document.source_id,
        document_type=document.document_type,
        title=document.title,
        url=document.url,
        published_at=document.published_at,
        author=document.author,
        metadata=document.metadata
    )
    return {"status": "ingested", "document_id": document_id}


@router.post("/search")
def hybrid_search(request: HybridSearchRequest, db: Session = Depends(get_db)):
    """Perform hybrid search (BM25 + vector)."""
    doc_service = DocumentService()
    results = doc_service.hybrid_search(
        db,
        query=request.query,
        instrument_ids=request.instrument_ids,
        date_from=request.date_from,
        date_to=request.date_to,
        limit=request.limit
    )

    return {
        "results": [dict(r._mapping) for r in results],
        "total_count": len(results)
    }


@router.get("/instrument/{instrument_id}")
def get_documents_for_instrument(
    instrument_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    """Get all documents for an instrument."""
    doc_service = DocumentService()
    documents = doc_service.get_documents_for_instrument(
        db, instrument_id, date_from, date_to, limit
    )
    return {"documents": [dict(d._mapping) for d in documents]}
