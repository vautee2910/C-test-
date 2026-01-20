from celery import Celery
from datetime import datetime, date, timedelta
from sqlalchemy import text

from app.core.config import settings
from app.db.connection import get_db_context
from app.services.portfolio_service import PortfolioService
from app.services.report_service import ReportService
from app.services.document_service import DocumentService
from app.services.alert_service import AlertService

celery_app = Celery("worker", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "ingest-news-hourly": {
        "task": "app.tasks.ingest_news",
        "schedule": 60 * 60,
    },
    "daily-prices-fx": {
        "task": "app.tasks.ingest_prices_fx",
        "schedule": 60 * 60 * 24,
    },
    "daily-filings": {
        "task": "app.tasks.ingest_filings",
        "schedule": 60 * 60 * 24,
    },
    "daily-recompute-positions": {
        "task": "app.tasks.recompute_positions_daily",
        "schedule": 60 * 60 * 24,
    },
    "weekly-reports": {
        "task": "app.tasks.generate_weekly_reports",
        "schedule": 60 * 60 * 24 * 7,
    },
    "monthly-reports": {
        "task": "app.tasks.generate_monthly_reports",
        "schedule": 60 * 60 * 24 * 30,
    },
    "monthly-lookthrough": {
        "task": "app.tasks.update_lookthrough",
        "schedule": 60 * 60 * 24 * 30,
    },
    "quarterly-reviews": {
        "task": "app.tasks.generate_quarterly_reviews",
        "schedule": 60 * 60 * 24 * 90,
    },
    "annual-ideas": {
        "task": "app.tasks.generate_annual_ideas",
        "schedule": 60 * 60 * 24 * 365,
    },
}


@celery_app.task(name="app.tasks.ingest_news")
def ingest_news() -> dict:
    """
    Hourly task: Ingest news from configured sources.
    Implementation would:
    1. Fetch from RSS feeds / news APIs
    2. Deduplicate
    3. Store in MinIO
    4. Extract text
    5. Chunk and embed
    6. Link to instruments
    7. Generate alerts
    """
    with get_db_context() as db:
        # Placeholder - would integrate with actual news sources
        # For now, just log that task ran
        return {
            "status": "completed",
            "task": "ingest_news",
            "timestamp": datetime.utcnow().isoformat(),
            "documents_ingested": 0,
            "note": "Placeholder - integrate with news APIs (e.g., NewsAPI, RSS feeds)"
        }


@celery_app.task(name="app.tasks.ingest_prices_fx")
def ingest_prices_fx() -> dict:
    """
    Daily task: Ingest price and FX data.
    Implementation would:
    1. Fetch prices for all active instruments
    2. Fetch FX rates
    3. Store in price_data and fx_rates tables
    4. Check for missing data and alert
    """
    with get_db_context() as db:
        # Get all active instruments
        query = text("SELECT id, ticker, isin FROM instruments WHERE is_active = TRUE")
        instruments = db.execute(query).fetchall()

        # Placeholder - would integrate with market data providers
        # (e.g., yfinance, Alpha Vantage free tier, or manual uploads)

        return {
            "status": "completed",
            "task": "ingest_prices_fx",
            "timestamp": datetime.utcnow().isoformat(),
            "instruments_checked": len(instruments),
            "prices_fetched": 0,
            "note": "Placeholder - integrate with market data API (e.g., yfinance, Alpha Vantage)"
        }


@celery_app.task(name="app.tasks.ingest_filings")
def ingest_filings() -> dict:
    """
    Daily task: Ingest regulatory filings (SEC EDGAR, etc.).
    Implementation would:
    1. Check for new filings for tracked instruments
    2. Download PDFs/HTML
    3. Extract text
    4. Chunk and embed
    5. Link to instruments
    """
    with get_db_context() as db:
        return {
            "status": "completed",
            "task": "ingest_filings",
            "timestamp": datetime.utcnow().isoformat(),
            "filings_ingested": 0,
            "note": "Placeholder - integrate with SEC EDGAR, ESEF, etc."
        }


@celery_app.task(name="app.tasks.recompute_positions_daily")
def recompute_positions_daily() -> dict:
    """
    Daily task: Recompute position aggregates for all portfolios.
    Uses the Index Units math engine.
    """
    with get_db_context() as db:
        # Get all portfolios
        query = text("SELECT id, name FROM portfolios")
        portfolios = db.execute(query).fetchall()

        today = date.today()
        results = []

        for portfolio in portfolios:
            try:
                positions = PortfolioService.recompute_positions(
                    db, portfolio.id, today
                )
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "positions_computed": len(positions),
                    "status": "success"
                })
            except Exception as e:
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "status": "error",
                    "error": str(e)
                })

        return {
            "status": "completed",
            "task": "recompute_positions_daily",
            "timestamp": datetime.utcnow().isoformat(),
            "portfolios_processed": len(results),
            "results": results
        }


@celery_app.task(name="app.tasks.generate_weekly_reports")
def generate_weekly_reports() -> dict:
    """
    Weekly task: Generate weekly reports for trading/YOLO portfolios.
    """
    with get_db_context() as db:
        # Get portfolios with weekly reporting enabled
        query = text("""
            SELECT p.id, p.name, sp.policy_json
            FROM portfolios p
            JOIN strategy_profiles sp ON p.strategy_profile_id = sp.id
            WHERE sp.policy_json->'report_policy'->'cadence'->>'weekly' = 'true'
        """)
        portfolios = db.execute(query).fetchall()

        end_date = date.today()
        start_date = end_date - timedelta(days=7)
        results = []

        for portfolio in portfolios:
            try:
                report_id = ReportService.generate_report(
                    db, portfolio.id, "weekly", start_date, end_date
                )
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "report_id": report_id,
                    "status": "success"
                })
            except Exception as e:
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "status": "error",
                    "error": str(e)
                })

        return {
            "status": "completed",
            "task": "generate_weekly_reports",
            "timestamp": datetime.utcnow().isoformat(),
            "reports_generated": len([r for r in results if r["status"] == "success"]),
            "results": results
        }


@celery_app.task(name="app.tasks.generate_monthly_reports")
def generate_monthly_reports() -> dict:
    """
    Monthly task: Generate monthly reports for all portfolios with monthly reporting enabled.
    """
    with get_db_context() as db:
        # Get portfolios with monthly reporting enabled
        query = text("""
            SELECT p.id, p.name, sp.policy_json
            FROM portfolios p
            JOIN strategy_profiles sp ON p.strategy_profile_id = sp.id
            WHERE sp.policy_json->'report_policy'->'cadence'->>'monthly' = 'true'
        """)
        portfolios = db.execute(query).fetchall()

        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        results = []

        for portfolio in portfolios:
            try:
                report_id = ReportService.generate_report(
                    db, portfolio.id, "monthly", start_date, end_date
                )
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "report_id": report_id,
                    "status": "success"
                })
            except Exception as e:
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "status": "error",
                    "error": str(e)
                })

        return {
            "status": "completed",
            "task": "generate_monthly_reports",
            "timestamp": datetime.utcnow().isoformat(),
            "reports_generated": len([r for r in results if r["status"] == "success"]),
            "results": results
        }


@celery_app.task(name="app.tasks.update_lookthrough")
def update_lookthrough() -> dict:
    """
    Monthly task: Update look-through exposures for funds/ETFs.
    Implementation would:
    1. Fetch current holdings of ETFs/funds
    2. Calculate look-through weights
    3. Store in position_aggregates with aggregated sector/region exposures
    """
    with get_db_context() as db:
        return {
            "status": "completed",
            "task": "update_lookthrough",
            "timestamp": datetime.utcnow().isoformat(),
            "note": "Placeholder - implement look-through calculation for ETF/fund holdings"
        }


@celery_app.task(name="app.tasks.generate_quarterly_reviews")
def generate_quarterly_reviews() -> dict:
    """
    Quarterly task: Generate quarterly position reviews.
    """
    with get_db_context() as db:
        # Get portfolios with quarterly reporting enabled
        query = text("""
            SELECT p.id, p.name, sp.policy_json
            FROM portfolios p
            JOIN strategy_profiles sp ON p.strategy_profile_id = sp.id
            WHERE sp.policy_json->'report_policy'->'cadence'->>'quarterly' = 'true'
        """)
        portfolios = db.execute(query).fetchall()

        end_date = date.today()
        start_date = end_date - timedelta(days=90)
        results = []

        for portfolio in portfolios:
            try:
                report_id = ReportService.generate_report(
                    db, portfolio.id, "quarterly", start_date, end_date
                )
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "report_id": report_id,
                    "status": "success"
                })
            except Exception as e:
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "status": "error",
                    "error": str(e)
                })

        return {
            "status": "completed",
            "task": "generate_quarterly_reviews",
            "timestamp": datetime.utcnow().isoformat(),
            "reports_generated": len([r for r in results if r["status"] == "success"]),
            "results": results
        }


@celery_app.task(name="app.tasks.generate_annual_ideas")
def generate_annual_ideas() -> dict:
    """
    Annual task: Generate annual research ideas reports.
    """
    with get_db_context() as db:
        # Get portfolios with annual reporting enabled
        query = text("""
            SELECT p.id, p.name, sp.policy_json
            FROM portfolios p
            JOIN strategy_profiles sp ON p.strategy_profile_id = sp.id
            WHERE sp.policy_json->'report_policy'->'cadence'->>'annual' = 'true'
        """)
        portfolios = db.execute(query).fetchall()

        end_date = date.today()
        start_date = end_date - timedelta(days=365)
        results = []

        for portfolio in portfolios:
            try:
                report_id = ReportService.generate_report(
                    db, portfolio.id, "annual_ideas", start_date, end_date
                )
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "report_id": report_id,
                    "status": "success"
                })
            except Exception as e:
                results.append({
                    "portfolio_id": portfolio.id,
                    "portfolio_name": portfolio.name,
                    "status": "error",
                    "error": str(e)
                })

        return {
            "status": "completed",
            "task": "generate_annual_ideas",
            "timestamp": datetime.utcnow().isoformat(),
            "reports_generated": len([r for r in results if r["status"] == "success"]),
            "results": results
        }
