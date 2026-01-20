from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import api_router

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Open-source portfolio research and intelligence platform"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/version")
def version() -> dict:
    """Version information."""
    return {"name": settings.app_name, "version": settings.app_version}


@app.get("/")
def root():
    """Root endpoint with API info."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health"
    }
