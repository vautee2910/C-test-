"""Portfolio routes for Module 3"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.db import get_db
from app.models.schemas import (
    PortfolioCreate,
    PortfolioResponse,
    HoldingResponse,
    PositionAggregateResponse,
    StrategyProfileResponse
)
from app.services.portfolio_service import PortfolioService

router = APIRouter()


@router.post("/", response_model=PortfolioResponse, status_code=201)
def create_portfolio(portfolio: PortfolioCreate, db: Session = Depends(get_db)):
    """Create a new portfolio with holdings."""
    # Create portfolio
    new_portfolio = PortfolioService.create_portfolio(
        db,
        name=portfolio.name,
        strategy_profile_id=portfolio.strategy_profile_id,
        owner_id=1,  # Would use actual user ID
        currency=portfolio.currency,
        is_paper_only=portfolio.is_paper_only,
        baseline_date=portfolio.baseline_date
    )

    # Add holdings
    for holding in portfolio.holdings:
        PortfolioService.add_holding(
            db,
            portfolio_id=new_portfolio.id,
            instrument_id=holding.instrument_id,
            baseline_weight_pct=holding.baseline_weight_pct,
            baseline_units=holding.baseline_units,
            baseline_date=holding.baseline_date
        )

    return new_portfolio


@router.get("/{portfolio_id}", response_model=PortfolioResponse)
def get_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    """Get portfolio by ID."""
    portfolio = PortfolioService.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


@router.get("/{portfolio_id}/holdings")
def get_holdings(portfolio_id: int, db: Session = Depends(get_db)):
    """Get all holdings for a portfolio."""
    holdings = PortfolioService.get_holdings(db, portfolio_id)
    return {"holdings": [dict(h._mapping) for h in holdings]}


@router.get("/{portfolio_id}/positions")
def get_positions(
    portfolio_id: int,
    as_of_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """Get current positions for a portfolio."""
    positions = PortfolioService.get_position_aggregates(db, portfolio_id, as_of_date)

    if not positions:
        return {"message": "No position data available. Run recompute task."}

    return {"positions": [dict(p._mapping) for p in positions]}


@router.post("/{portfolio_id}/recompute")
def recompute_positions(
    portfolio_id: int,
    as_of_date: date = Query(..., description="Date to recompute positions"),
    db: Session = Depends(get_db)
):
    """Manually trigger position recomputation."""
    results = PortfolioService.recompute_positions(db, portfolio_id, as_of_date)
    return {
        "status": "completed",
        "portfolio_id": portfolio_id,
        "as_of_date": as_of_date,
        "positions_computed": len(results)
    }


@router.get("/strategy-profiles/", response_model=list)
def list_strategy_profiles(db: Session = Depends(get_db)):
    """List all strategy profiles."""
    profiles = PortfolioService.list_strategy_profiles(db)
    return [dict(p._mapping) for p in profiles]


@router.get("/strategy-profiles/{profile_id}")
def get_strategy_profile(profile_id: int, db: Session = Depends(get_db)):
    """Get strategy profile by ID."""
    profile = PortfolioService.get_strategy_profile(db, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Strategy profile not found")
    return dict(profile._mapping)
