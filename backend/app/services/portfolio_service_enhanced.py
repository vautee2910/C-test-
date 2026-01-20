"""
Enhanced Portfolio Service - P0.2 Fix
Implements proper Index Units math with:
- FX conversion to portfolio currency
- Corporate actions (splits, dividends)
- Missing price handling (carry-forward)
- Multiple portfolio events support
"""
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date, timedelta
from decimal import Decimal

from app.services.portfolio_service import PortfolioService as BasePortfolioService


class EnhancedPortfolioService(BasePortfolioService):
    """Enhanced portfolio service with correct Index Units math."""

    @staticmethod
    def get_fx_rate(
        db: Session,
        from_currency: str,
        to_currency: str,
        as_of_date: date
    ) -> float:
        """
        Get FX rate to convert from_currency to to_currency.
        Returns 1.0 if same currency.
        Uses most recent rate if exact date not available.
        """
        if from_currency == to_currency:
            return 1.0

        query = text("""
            SELECT rate
            FROM fx_rates
            WHERE from_currency = :from_currency
              AND to_currency = :to_currency
              AND rate_date <= :as_of_date
            ORDER BY rate_date DESC
            LIMIT 1
        """)

        result = db.execute(query, {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "as_of_date": as_of_date
        })
        row = result.fetchone()

        if row:
            return row.rate

        # Try inverse rate
        inverse_query = text("""
            SELECT rate
            FROM fx_rates
            WHERE from_currency = :to_currency
              AND to_currency = :from_currency
              AND rate_date <= :as_of_date
            ORDER BY rate_date DESC
            LIMIT 1
        """)

        result = db.execute(inverse_query, {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "as_of_date": as_of_date
        })
        row = result.fetchone()

        if row and row.rate > 0:
            return 1.0 / row.rate

        # No rate found - log warning and return 1.0 (will need manual intervention)
        print(f"WARNING: No FX rate found for {from_currency}/{to_currency} on {as_of_date}")
        return 1.0

    @staticmethod
    def get_price_with_carry_forward(
        db: Session,
        instrument_id: int,
        price_date: date,
        max_lookback_days: int = 30
    ) -> Optional[float]:
        """
        Get price for an instrument on a specific date.
        If exact date not available, carry forward last known price
        (up to max_lookback_days).
        """
        query = text("""
            SELECT close_price, price_date
            FROM price_data
            WHERE instrument_id = :instrument_id
              AND price_date <= :price_date
              AND price_date >= :min_date
            ORDER BY price_date DESC
            LIMIT 1
        """)

        min_date = price_date - timedelta(days=max_lookback_days)

        result = db.execute(query, {
            "instrument_id": instrument_id,
            "price_date": price_date,
            "min_date": min_date
        })
        row = result.fetchone()

        if row:
            if row.price_date < price_date:
                print(f"INFO: Carrying forward price from {row.price_date} to {price_date} for instrument {instrument_id}")
            return row.close_price

        return None

    @staticmethod
    def get_corporate_actions(
        db: Session,
        instrument_id: int,
        from_date: date,
        to_date: date
    ) -> List[Dict]:
        """
        Get all corporate actions for an instrument in date range.
        """
        query = text("""
            SELECT action_type, action_date, ratio, amount, new_instrument_id, description
            FROM corporate_actions
            WHERE instrument_id = :instrument_id
              AND action_date > :from_date
              AND action_date <= :to_date
            ORDER BY action_date ASC
        """)

        result = db.execute(query, {
            "instrument_id": instrument_id,
            "from_date": from_date,
            "to_date": to_date
        })

        return [dict(row._mapping) for row in result]

    @staticmethod
    def apply_corporate_actions(
        units: float,
        price: float,
        actions: List[Dict]
    ) -> tuple[float, float]:
        """
        Apply corporate actions to units and price.
        Returns (adjusted_units, adjusted_price).

        Actions:
        - Split: units *= ratio, price /= ratio
        - Dividend: price stays same, units increase by reinvestment
        - Symbol change: units stay same, price from new instrument
        """
        current_units = units
        current_price = price

        for action in actions:
            action_type = action['action_type']

            if action_type == 'split':
                ratio = action['ratio']  # e.g., 2.0 for 2-for-1 split
                current_units *= ratio
                current_price /= ratio

            elif action_type == 'dividend':
                # Assume dividend reinvestment at current price
                dividend_amount = action['amount']
                if current_price > 0:
                    reinvested_shares = (dividend_amount / current_price) * current_units
                    current_units += reinvested_shares
                # Price doesn't change for dividend

            elif action_type == 'symbol_change':
                # Units stay same, but we'd need new instrument's price
                # This is handled by updating instrument_id in holdings
                pass

        return current_units, current_price

    @staticmethod
    def recompute_positions_enhanced(
        db: Session,
        portfolio_id: int,
        as_of_date: date
    ):
        """
        Enhanced position recompute with:
        - FX conversion to portfolio currency
        - Corporate actions adjustment
        - Missing price carry-forward
        - Proper multi-lot support (if needed)
        """
        # Get portfolio currency
        portfolio = EnhancedPortfolioService.get_portfolio(db, portfolio_id)
        if not portfolio:
            return []

        portfolio_currency = portfolio.currency

        # Get holdings
        holdings = EnhancedPortfolioService.get_holdings(db, portfolio_id)
        if not holdings:
            return []

        results = []
        total_current_value_portfolio_ccy = 0.0

        # First pass: calculate current units and values with FX conversion
        for holding in holdings:
            instrument_id = holding.instrument_id
            instrument_currency = holding.currency or portfolio_currency
            baseline_units = holding.baseline_units
            baseline_date = holding.baseline_date

            # Get baseline price with carry-forward
            baseline_price = EnhancedPortfolioService.get_price_with_carry_forward(
                db, instrument_id, baseline_date, max_lookback_days=30
            )

            # Get current price with carry-forward
            current_price = EnhancedPortfolioService.get_price_with_carry_forward(
                db, instrument_id, as_of_date, max_lookback_days=30
            )

            if not baseline_price or not current_price:
                print(f"WARNING: Missing price for instrument {instrument_id} ({holding.instrument_name})")
                current_units = baseline_units
                current_value_instrument_ccy = baseline_units
            else:
                # Get corporate actions since baseline
                actions = EnhancedPortfolioService.get_corporate_actions(
                    db, instrument_id, baseline_date, as_of_date
                )

                # Apply corporate actions
                adjusted_units, adjusted_current_price = EnhancedPortfolioService.apply_corporate_actions(
                    baseline_units, current_price, actions
                )

                # Calculate return
                cumulative_return = (adjusted_current_price - baseline_price) / baseline_price if baseline_price > 0 else 0
                current_units = adjusted_units * (1 + cumulative_return)
                current_value_instrument_ccy = current_units

            # Convert to portfolio currency
            fx_rate = EnhancedPortfolioService.get_fx_rate(
                db, instrument_currency, portfolio_currency, as_of_date
            )
            current_value_portfolio_ccy = current_value_instrument_ccy * fx_rate

            total_current_value_portfolio_ccy += current_value_portfolio_ccy

            results.append({
                "instrument_id": instrument_id,
                "instrument_name": holding.instrument_name,
                "baseline_units": baseline_units,
                "current_units": current_units,
                "current_value_instrument_ccy": current_value_instrument_ccy,
                "current_value_portfolio_ccy": current_value_portfolio_ccy,
                "fx_rate": fx_rate,
                "instrument_currency": instrument_currency,
                "baseline_weight_pct": holding.baseline_weight_pct
            })

        # Second pass: calculate weights and drift in portfolio currency
        for item in results:
            if total_current_value_portfolio_ccy > 0:
                item["current_weight_pct"] = (item["current_value_portfolio_ccy"] / total_current_value_portfolio_ccy) * 100
                item["drift_pp"] = item["current_weight_pct"] - item["baseline_weight_pct"]
                item["units_return_since_baseline"] = ((item["current_units"] / item["baseline_units"]) - 1) * 100 if item["baseline_units"] > 0 else 0
                # Contribution is in portfolio currency terms
                item["contributed_return_pp"] = (item["current_value_portfolio_ccy"] - item["baseline_units"]) / (total_current_value_portfolio_ccy / 100) if total_current_value_portfolio_ccy > 0 else 0
            else:
                item["current_weight_pct"] = 0
                item["drift_pp"] = 0
                item["units_return_since_baseline"] = 0
                item["contributed_return_pp"] = 0

            # Store in database
            EnhancedPortfolioService._upsert_position_aggregate(
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
    def record_portfolio_event(
        db: Session,
        portfolio_id: int,
        event_type: str,
        event_date: date,
        instrument_id: Optional[int] = None,
        amount: Optional[float] = None,
        details: Optional[Dict] = None,
        created_by: Optional[int] = None
    ):
        """
        Record a portfolio event (baseline reset, deposit, withdrawal, etc.).
        """
        import json

        query = text("""
            INSERT INTO portfolio_events
            (portfolio_id, event_type, event_date, instrument_id, amount, details, created_by)
            VALUES
            (:portfolio_id, :event_type, :event_date, :instrument_id, :amount, :details::jsonb, :created_by)
            RETURNING id
        """)

        result = db.execute(query, {
            "portfolio_id": portfolio_id,
            "event_type": event_type,
            "event_date": event_date,
            "instrument_id": instrument_id,
            "amount": amount,
            "details": json.dumps(details) if details else None,
            "created_by": created_by
        })
        db.commit()
        return result.fetchone()

    @staticmethod
    def record_corporate_action(
        db: Session,
        instrument_id: int,
        action_type: str,
        action_date: date,
        ratio: Optional[float] = None,
        amount: Optional[float] = None,
        new_instrument_id: Optional[int] = None,
        description: Optional[str] = None
    ):
        """
        Record a corporate action for an instrument.
        """
        query = text("""
            INSERT INTO corporate_actions
            (instrument_id, action_type, action_date, ratio, amount, new_instrument_id, description, is_processed)
            VALUES
            (:instrument_id, :action_type, :action_date, :ratio, :amount, :new_instrument_id, :description, FALSE)
            RETURNING id
        """)

        result = db.execute(query, {
            "instrument_id": instrument_id,
            "action_type": action_type,
            "action_date": action_date,
            "ratio": ratio,
            "amount": amount,
            "new_instrument_id": new_instrument_id,
            "description": description
        })
        db.commit()
        return result.fetchone()
