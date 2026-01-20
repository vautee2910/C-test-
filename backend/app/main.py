from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.api.routes import api_router
from app.middleware import RBACResponseMiddleware, LoggingRedactionMiddleware

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Open-source portfolio research and intelligence platform"
)

# Security headers middleware (must be first)
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response

# RBAC field stripping middleware (CRITICAL for $ leak protection)
app.add_middleware(RBACResponseMiddleware)

# Logging redaction middleware
app.add_middleware(LoggingRedactionMiddleware)

# CORS middleware - configure allowed origins via environment variable
allowed_origins = settings.cors_allowed_origins if hasattr(settings, 'cors_allowed_origins') else ["http://localhost:3000", "http://localhost:8000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "Content-Range"],
)

# Trusted host middleware (prevents host header injection)
if hasattr(settings, 'trusted_hosts'):
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

# GZip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Session middleware (for MFA flows)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

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
