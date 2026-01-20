"""
Module 3: Portfolio Math Engine (Index Units)
Implements portfolio tracking, index units math, drift calculation.
"""
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date
import json


class PortfolioService:
    """Handles portfolio creation, holdings, and position calculations."""

    @staticmethod
    def create_portfolio(
        db: Session,
        name: str,
        strategy_profile_id: int,
        owner_id: Optional[int] = None,
        currency: str = "EUR",
        is_paper_only: bool = False,
        baseline_date: Optional[date] = None
    ):
        """Create a new portfolio."""
        query = text("""
            INSERT INTO portfolios
            (name, owner_id, strategy_profile_id, currency, is_paper_only, baseline_date)
            VALUES (:name, :owner_id, :strategy_profile_id, :currency, :is_paper_only, :baseline_date)
            RETURNING id, name, owner_id, strategy_profile_id, currency, is_paper_only, baseline_date, created_at
        """)
        result = db.execute(query, {
            "name": name,
            "owner_id": owner_id,
            "strategy_profile_id": strategy_profile_id,
            "currency": currency,
            "is_paper_only": is_paper_only,
            "baseline_date": baseline_date
        })
        db.commit()
        return result.fetchone()

    @staticmethod
    def add_holding(
        db: Session,
        portfolio_id: int,
        instrument_id: int,
        baseline_weight_pct: float,
        baseline_units: float,
        baseline_date: date
    ):
        """Add a holding to a portfolio."""
        query = text("""
            INSERT INTO holdings
            (portfolio_id, instrument_id, baseline_weight_pct, baseline_units, baseline_date, is_active)
            VALUES (:portfolio_id, :instrument_id, :baseline_weight_pct, :baseline_units, :baseline_date, TRUE)
            RETURNING id, portfolio_id, instrument_id, baseline_weight_pct, baseline_units, baseline_date
        """)
        result = db.execute(query, {
            "portfolio_id": portfolio_id,
            "instrument_id": instrument_id,
            "baseline_weight_pct": baseline_weight_pct,
            "baseline_units": baseline_units,
            "baseline_date": baseline_date
        })
        db.commit()
        return result.fetchone()

    @staticmethod
    def get_portfolio(db: Session, portfolio_id: int):
        """Get portfolio by ID with strategy profile info."""
        query = text("""
            SELECT p.id, p.name, p.owner_id, p.strategy_profile_id, p.currency,
                   p.is_paper_only, p.baseline_date, p.created_at,
                   sp.name as strategy_profile_name
            FROM portfolios p
            LEFT JOIN strategy_profiles sp ON p.strategy_profile_id = sp.id
            WHERE p.id = :portfolio_id
        """)
        result = db.execute(query, {"portfolio_id": portfolio_id})
        return result.fetchone()

    @staticmethod
    def get_holdings(db: Session, portfolio_id: int):
        """Get all active holdings for a portfolio."""
        query = text("""
            SELECT h.id, h.portfolio_id, h.instrument_id, h.baseline_weight_pct,
                   h.baseline_units, h.baseline_date, h.is_active,
                   i.name as instrument_name, i.instrument_type, i.currency
            FROM holdings h
            JOIN instruments i ON h.instrument_id = i.id
            WHERE h.portfolio_id = :portfolio_id AND h.is_active = TRUE
            ORDER BY h.baseline_weight_pct DESC
        """)
        result = db.execute(query, {"portfolio_id": portfolio_id})
        return result.fetchall()

    @staticmethod
    def recompute_positions(
        db: Session,
        portfolio_id: int,
        as_of_date: date
    ):
        """
        Recompute position aggregates for a portfolio as of a given date.
        Uses index units math: current_units = baseline_units * (1 + cumulative_return)
        """
        # Get baseline holdings
        holdings = PortfolioService.get_holdings(db, portfolio_id)

        if not holdings:
            return []

        results = []
        total_current_value = 0.0  # For weight calculation

        # First pass: calculate current units and values
        for holding in holdings:
            instrument_id = holding.instrument_id
            baseline_units = holding.baseline_units
            baseline_date = holding.baseline_date

            # Get price at baseline
            baseline_price = PortfolioService._get_price(db, instrument_id, baseline_date)
            # Get price as of date
            current_price = PortfolioService._get_price(db, instrument_id, as_of_date)

            if baseline_price and current_price and baseline_price > 0:
                # Calculate return
                cumulative_return = (current_price - baseline_price) / baseline_price
                current_units = baseline_units * (1 + cumulative_return)
                current_value = current_units  # In index units
            else:
                # No price data, assume no change
                current_units = baseline_units
                current_value = baseline_units

            total_current_value += current_value

            results.append({
                "instrument_id": instrument_id,
                "instrument_name": holding.instrument_name,
                "baseline_units": baseline_units,
                "current_units": current_units,
                "current_value": current_value,
                "baseline_weight_pct": holding.baseline_weight_pct
            })

        # Second pass: calculate weights and drift
        for item in results:
            if total_current_value > 0:
                item["current_weight_pct"] = (item["current_value"] / total_current_value) * 100
                item["drift_pp"] = item["current_weight_pct"] - item["baseline_weight_pct"]
                item["units_return_since_baseline"] = ((item["current_units"] / item["baseline_units"]) - 1) * 100 if item["baseline_units"] > 0 else 0
                item["contributed_return_pp"] = (item["current_value"] - item["baseline_units"]) / 100  # Approximate contribution
            else:
                item["current_weight_pct"] = 0
                item["drift_pp"] = 0
                item["units_return_since_baseline"] = 0
                item["contributed_return_pp"] = 0

            # Store in database
            PortfolioService._upsert_position_aggregate(
                db,
                portfolio_id,
                item["instrument_id"],
                as_of_date,
                item["current_units"],
                item["current_weight_pct"],
                item["drift_pp"],
                item["units_return_since_baseline"],
                item["contributed_return_pp"]
            )

        db.commit()
        return results

    @staticmethod
    def _get_price(db: Session, instrument_id: int, price_date: date) -> Optional[float]:
        """Get price for an instrument on a specific date (or closest prior)."""
        query = text("""
            SELECT close_price
            FROM price_data
            WHERE instrument_id = :instrument_id AND price_date <= :price_date
            ORDER BY price_date DESC
            LIMIT 1
        """)
        result = db.execute(query, {"instrument_id": instrument_id, "price_date": price_date})
        row = result.fetchone()
        return row.close_price if row else None

    @staticmethod
    def _upsert_position_aggregate(
        db: Session,
        portfolio_id: int,
        instrument_id: int,
        as_of_date: date,
        current_units: float,
        current_weight_pct: float,
        drift_pp: float,
        units_return_since_baseline: float,
        contributed_return_pp: float
    ):
        """Insert or update position aggregate."""
        query = text("""
            INSERT INTO position_aggregates
            (portfolio_id, instrument_id, as_of_date, current_units, current_weight_pct,
             drift_pp, units_return_since_baseline, contributed_return_pp)
            VALUES (:portfolio_id, :instrument_id, :as_of_date, :current_units, :current_weight_pct,
                    :drift_pp, :units_return_since_baseline, :contributed_return_pp)
            ON CONFLICT (portfolio_id, instrument_id, as_of_date)
            DO UPDATE SET
                current_units = EXCLUDED.current_units,
                current_weight_pct = EXCLUDED.current_weight_pct,
                drift_pp = EXCLUDED.drift_pp,
                units_return_since_baseline = EXCLUDED.units_return_since_baseline,
                contributed_return_pp = EXCLUDED.contributed_return_pp,
                created_at = NOW()
        """)
        db.execute(query, {
            "portfolio_id": portfolio_id,
            "instrument_id": instrument_id,
            "as_of_date": as_of_date,
            "current_units": current_units,
            "current_weight_pct": current_weight_pct,
            "drift_pp": drift_pp,
            "units_return_since_baseline": units_return_since_baseline,
            "contributed_return_pp": contributed_return_pp
        })

    @staticmethod
    def get_position_aggregates(
        db: Session,
        portfolio_id: int,
        as_of_date: Optional[date] = None
    ):
        """Get position aggregates for a portfolio as of date."""
        if not as_of_date:
            # Get latest
            query = text("""
                SELECT pa.portfolio_id, pa.instrument_id, pa.as_of_date,
                       pa.current_units, pa.current_weight_pct, pa.drift_pp,
                       pa.units_return_since_baseline, pa.contributed_return_pp,
                       i.name as instrument_name
                FROM position_aggregates pa
                JOIN instruments i ON pa.instrument_id = i.id
                WHERE pa.portfolio_id = :portfolio_id
                  AND pa.as_of_date = (
                      SELECT MAX(as_of_date)
                      FROM position_aggregates
                      WHERE portfolio_id = :portfolio_id
                  )
                ORDER BY pa.current_weight_pct DESC
            """)
        else:
            query = text("""
                SELECT pa.portfolio_id, pa.instrument_id, pa.as_of_date,
                       pa.current_units, pa.current_weight_pct, pa.drift_pp,
                       pa.units_return_since_baseline, pa.contributed_return_pp,
                       i.name as instrument_name
                FROM position_aggregates pa
                JOIN instruments i ON pa.instrument_id = i.id
                WHERE pa.portfolio_id = :portfolio_id AND pa.as_of_date = :as_of_date
                ORDER BY pa.current_weight_pct DESC
            """)

        result = db.execute(query, {"portfolio_id": portfolio_id, "as_of_date": as_of_date})
        return result.fetchall()

    @staticmethod
    def get_strategy_profile(db: Session, profile_id: int):
        """Get strategy profile by ID."""
        query = text("""
            SELECT id, name, policy_json, is_active, created_at
            FROM strategy_profiles
            WHERE id = :profile_id
        """)
        result = db.execute(query, {"profile_id": profile_id})
        return result.fetchone()

    @staticmethod
    def list_strategy_profiles(db: Session):
        """List all active strategy profiles."""
        query = text("""
            SELECT id, name, policy_json, is_active, created_at
            FROM strategy_profiles
            WHERE is_active = TRUE
            ORDER BY name
        """)
        result = db.execute(query)
        return result.fetchall()
