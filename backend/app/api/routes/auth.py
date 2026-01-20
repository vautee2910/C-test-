"""Auth routes for Module 1"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.schemas import UserCreate, UserResponse, Token, LoginRequest
from app.services.auth_service import AuthService

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user."""
    try:
        user = AuthService.create_user(
            db,
            email=user_data.email,
            password=user_data.password,
            full_name=user_data.full_name,
            role=user_data.role
        )
        return user
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=Token)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and get access token."""
    user = AuthService.authenticate_user(db, login_data.email, login_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # Create access token
    access_token = AuthService.create_access_token(
        data={"sub": user.email, "user_id": user.id, "role": user.role}
    )

    # Log audit event
    AuthService.log_audit_event(
        db, user.id, "user_login", "user", user.id
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def get_current_user(db: Session = Depends(get_db)):
    """Get current user info (simplified - would use auth dependency in production)."""
    # In production, extract user from JWT token
    # For now, return a placeholder
    return UserResponse(
        id=1,
        email="analyst@example.com",
        full_name="Analyst User",
        role="analyst",
        is_active=True,
        mfa_enabled=False,
        created_at="2024-01-01T00:00:00"
    )
