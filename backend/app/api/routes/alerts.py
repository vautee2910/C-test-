"""Alert routes for Module 7"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.db import get_db
from app.models.schemas import AlertResponse, AlertApprovalRequest, AlertListRequest
from app.services.alert_service import AlertService

router = APIRouter()


@router.get("/")
def list_alerts(
    portfolio_id: Optional[int] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    """List alerts with filters."""
    alerts = AlertService.list_alerts(
        db, portfolio_id, severity, status, date_from, date_to, limit
    )
    return {"alerts": [dict(a._mapping) for a in alerts]}


@router.post("/{alert_id}/approve")
def approve_alert(
    alert_id: int,
    approval: AlertApprovalRequest,
    db: Session = Depends(get_db)
):
    """Approve or reject an alert."""
    result = AlertService.approve_alert(
        db, alert_id, approved_by=1, action=approval.action  # Would use actual user ID
    )

    if not result:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Log audit event
    from app.services.auth_service import AuthService
    AuthService.log_audit_event(
        db, 1, f"alert_{approval.action}", "alert", alert_id,
        details={"notes": approval.notes}
    )

    return {"status": "success", "alert": dict(result._mapping)}


@router.get("/keyword-taxonomy")
def get_keyword_taxonomy(
    instrument_type: str = Query("all"),
    db: Session = Depends(get_db)
):
    """Get keyword taxonomy for an instrument type."""
    taxonomy = AlertService.get_keyword_taxonomy(db, instrument_type)
    return {"taxonomy": [dict(t._mapping) for t in taxonomy]}
