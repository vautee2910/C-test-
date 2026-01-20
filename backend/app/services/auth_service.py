"""
Module 1: Auth + RBAC + Audit
Implements authentication, role-based access control, and audit logging.
"""
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """Handles authentication, authorization, and audit logging."""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt."""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create a JWT access token."""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(
                minutes=settings.access_token_expire_minutes
            )
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
        return encoded_jwt

    @staticmethod
    def decode_access_token(token: str) -> Optional[dict]:
        """Decode and validate a JWT access token."""
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
            return payload
        except JWTError:
            return None

    @staticmethod
    def create_user(db: Session, email: str, password: str, full_name: str = None, role: str = "analyst"):
        """Create a new user."""
        hashed_password = AuthService.hash_password(password)
        query = text("""
            INSERT INTO users (email, hashed_password, full_name, role, is_active)
            VALUES (:email, :hashed_password, :full_name, :role, :is_active)
            RETURNING id, email, full_name, role, is_active, created_at
        """)
        result = db.execute(query, {
            "email": email,
            "hashed_password": hashed_password,
            "full_name": full_name,
            "role": role,
            "is_active": True
        })
        db.commit()
        return result.fetchone()

    @staticmethod
    def authenticate_user(db: Session, email: str, password: str):
        """Authenticate a user by email and password."""
        query = text("""
            SELECT id, email, hashed_password, full_name, role, is_active, mfa_enabled
            FROM users
            WHERE email = :email AND is_active = TRUE
        """)
        result = db.execute(query, {"email": email})
        user = result.fetchone()

        if not user:
            return None

        if not AuthService.verify_password(password, user.hashed_password):
            return None

        return user

    @staticmethod
    def get_user_by_id(db: Session, user_id: int):
        """Get user by ID."""
        query = text("""
            SELECT id, email, full_name, role, is_active, mfa_enabled, created_at
            FROM users
            WHERE id = :user_id
        """)
        result = db.execute(query, {"user_id": user_id})
        return result.fetchone()

    @staticmethod
    def log_audit_event(
        db: Session,
        user_id: Optional[int],
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[int] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None
    ):
        """Log an audit event."""
        import json
        query = text("""
            INSERT INTO audit_log (user_id, action, resource_type, resource_id, details, ip_address)
            VALUES (:user_id, :action, :resource_type, :resource_id, :details::jsonb, :ip_address)
        """)
        db.execute(query, {
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": json.dumps(details) if details else None,
            "ip_address": ip_address
        })
        db.commit()

    @staticmethod
    def check_permission(user_role: str, required_role: str) -> bool:
        """
        Check if user has required permission.
        Role hierarchy: admin > analyst > management
        Management has restricted access (no currency symbols, no market values)
        """
        role_hierarchy = {
            "admin": 3,
            "analyst": 2,
            "management": 1
        }
        return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0)
