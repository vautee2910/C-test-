from celery import Celery

from app.core.config import settings

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
    return {"status": "queued", "task": "ingest_news"}


@celery_app.task(name="app.tasks.ingest_prices_fx")
def ingest_prices_fx() -> dict:
    return {"status": "queued", "task": "ingest_prices_fx"}


@celery_app.task(name="app.tasks.ingest_filings")
def ingest_filings() -> dict:
    return {"status": "queued", "task": "ingest_filings"}


@celery_app.task(name="app.tasks.recompute_positions_daily")
def recompute_positions_daily() -> dict:
    return {"status": "queued", "task": "recompute_positions_daily"}


@celery_app.task(name="app.tasks.generate_weekly_reports")
def generate_weekly_reports() -> dict:
    return {"status": "queued", "task": "generate_weekly_reports"}


@celery_app.task(name="app.tasks.generate_monthly_reports")
def generate_monthly_reports() -> dict:
    return {"status": "queued", "task": "generate_monthly_reports"}


@celery_app.task(name="app.tasks.update_lookthrough")
def update_lookthrough() -> dict:
    return {"status": "queued", "task": "update_lookthrough"}


@celery_app.task(name="app.tasks.generate_quarterly_reviews")
def generate_quarterly_reviews() -> dict:
    return {"status": "queued", "task": "generate_quarterly_reviews"}


@celery_app.task(name="app.tasks.generate_annual_ideas")
def generate_annual_ideas() -> dict:
    return {"status": "queued", "task": "generate_annual_ideas"}
