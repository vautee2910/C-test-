"""Report routes for Module 8"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.db import get_db
from app.models.schemas import ReportGenerationRequest, ReportResponse, ReportListRequest
from app.services.report_service import ReportService

router = APIRouter()


@router.post("/generate", status_code=201)
def generate_report(request: ReportGenerationRequest, db: Session = Depends(get_db)):
    """Generate a new report."""
    try:
        report_id = ReportService.generate_report(
            db,
            portfolio_id=request.portfolio_id,
            report_type=request.report_type,
            period_start=request.period_start,
            period_end=request.period_end
        )
        return {"status": "generated", "report_id": report_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/")
def list_reports(
    portfolio_id: Optional[int] = None,
    report_type: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db)
):
    """List reports with filters."""
    reports = ReportService.list_reports(
        db, portfolio_id, report_type, date_from, date_to, limit
    )
    return {"reports": [dict(r._mapping) for r in reports]}


@router.get("/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    """Get report by ID."""
    report = ReportService.get_report(db, report_id)

    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Log view
    ReportService.log_report_view(db, report_id, user_id=1)  # Would use actual user ID

    return dict(report._mapping)
