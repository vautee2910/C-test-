from fastapi import APIRouter

from .auth import router as auth_router
from .instruments import router as instruments_router
from .portfolios import router as portfolios_router
from .alerts import router as alerts_router
from .reports import router as reports_router
from .documents import router as documents_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(instruments_router, prefix="/instruments", tags=["instruments"])
api_router.include_router(portfolios_router, prefix="/portfolios", tags=["portfolios"])
api_router.include_router(alerts_router, prefix="/alerts", tags=["alerts"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])

__all__ = ["api_router"]
