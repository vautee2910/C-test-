"""
API Dependencies for authentication, authorization, and common utilities.
"""
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.connection import get_db
from app.services.auth_service import AuthService

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
):
    """
    Extract and validate JWT token, return user info.
    Sets request.state.user_role for RBAC middleware.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Decode token
    payload = AuthService.decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    # Get user from database
    user = AuthService.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    # Set user role in request state for RBAC middleware
    request.state.user_role = user.role
    request.state.user_id = user.id

    return user


async def get_current_active_user(
    current_user = Depends(get_current_user)
):
    """Ensure user is active."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def require_role(required_role: str):
    """
    Dependency factory for role-based access control.
    Usage: @app.get("/admin", dependencies=[Depends(require_role("admin"))])
    """
    async def role_checker(current_user = Depends(get_current_active_user)):
        if not AuthService.check_permission(current_user.role, required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role}"
            )
        return current_user
    return role_checker


# Convenience dependencies for common roles
require_admin = require_role("admin")
require_analyst = require_role("analyst")
