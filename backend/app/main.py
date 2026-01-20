from fastapi import FastAPI

from app.core.config import settings


app = FastAPI(title=settings.app_name, version=settings.app_version)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@app.get("/version")
def version() -> dict:
    return {"name": settings.app_name, "version": settings.app_version}
