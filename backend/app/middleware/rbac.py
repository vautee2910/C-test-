"""
RBAC Field Stripping Middleware
Prevents $ leaks by removing restricted fields based on user role.
"""
from typing import Any, Dict, List, Optional
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response, StreamingResponse
import json
import re


class SafeSerializer:
    """
    Role-based field stripping to prevent sensitive data leaks.
    Management role must never see currency values.
    """

    # Fields that contain currency/market values (forbidden for management)
    RESTRICTED_FIELDS = {
        "management": [
            # Direct currency fields
            "market_value",
            "price",
            "close_price",
            "cost_basis",
            "pnl",
            "profit_loss",
            "cash",
            "amount",
            "total_value",
            "portfolio_value",
            # Derived fields that could reveal values
            "contributed_return_pp",  # Could be reverse-engineered
        ]
    }

    # Currency symbols to redact from any text fields
    CURRENCY_SYMBOLS = ["$", "€", "£", "¥", "₹", "¢"]

    @staticmethod
    def strip_fields(data: Any, user_role: str) -> Any:
        """
        Recursively strip restricted fields from data based on user role.
        """
        if user_role not in SafeSerializer.RESTRICTED_FIELDS:
            return data  # No restrictions for this role

        restricted = SafeSerializer.RESTRICTED_FIELDS[user_role]

        if isinstance(data, dict):
            return {
                k: SafeSerializer.strip_fields(v, user_role)
                for k, v in data.items()
                if k not in restricted
            }
        elif isinstance(data, list):
            return [SafeSerializer.strip_fields(item, user_role) for item in data]
        else:
            return data

    @staticmethod
    def redact_currency_symbols(text: str) -> str:
        """
        Redact currency symbols from text (for management role).
        Replaces symbols with [REDACTED].
        """
        for symbol in SafeSerializer.CURRENCY_SYMBOLS:
            text = text.replace(symbol, "[REDACTED]")
        return text

    @staticmethod
    def sanitize_response(data: Any, user_role: str, redact_symbols: bool = True) -> Any:
        """
        Full sanitization: strip fields + redact symbols in text.
        """
        # First, strip restricted fields
        data = SafeSerializer.strip_fields(data, user_role)

        # Then, redact currency symbols from text fields (if management)
        if user_role == "management" and redact_symbols:
            data = SafeSerializer._redact_text_fields(data)

        return data

    @staticmethod
    def _redact_text_fields(data: Any) -> Any:
        """
        Recursively redact currency symbols from string fields.
        """
        if isinstance(data, dict):
            return {
                k: SafeSerializer._redact_text_fields(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [SafeSerializer._redact_text_fields(item) for item in data]
        elif isinstance(data, str):
            return SafeSerializer.redact_currency_symbols(data)
        else:
            return data


class RBACResponseMiddleware(BaseHTTPMiddleware):
    """
    Middleware that strips restricted fields from all API responses
    based on the authenticated user's role.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Get response from endpoint
        response = await call_next(request)

        # Skip if not JSON response
        if "application/json" not in response.headers.get("content-type", ""):
            return response

        # Get user role from request state (set by auth dependency)
        user_role = getattr(request.state, "user_role", None)

        if not user_role or user_role not in ["management"]:
            # No sanitization needed for admin/analyst roles
            return response

        # Read response body
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            # Parse JSON
            data = json.loads(body.decode())

            # Sanitize based on role
            sanitized = SafeSerializer.sanitize_response(data, user_role)

            # Create new response with sanitized data
            new_body = json.dumps(sanitized).encode()

            return Response(
                content=new_body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="application/json"
            )
        except json.JSONDecodeError:
            # If not valid JSON, return original
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers)
            )


class LoggingRedactionMiddleware(BaseHTTPMiddleware):
    """
    Redacts sensitive values from logs (request/response logging).
    """

    # Patterns to redact from logs
    REDACTION_PATTERNS = [
        (re.compile(r'"price":\s*[\d.]+'), '"price": "[REDACTED]"'),
        (re.compile(r'"market_value":\s*[\d.]+'), '"market_value": "[REDACTED]"'),
        (re.compile(r'"close_price":\s*[\d.]+'), '"close_price": "[REDACTED]"'),
        (re.compile(r'\$[\d,]+\.?\d*'), '[REDACTED]'),
        (re.compile(r'€[\d,]+\.?\d*'), '[REDACTED]'),
        (re.compile(r'£[\d,]+\.?\d*'), '[REDACTED]'),
    ]

    @staticmethod
    def redact_log_message(message: str) -> str:
        """Redact sensitive patterns from log messages."""
        for pattern, replacement in LoggingRedactionMiddleware.REDACTION_PATTERNS:
            message = pattern.sub(replacement, message)
        return message

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Just pass through for now - actual logging happens in logging config
        # This middleware is a placeholder for custom logging redaction
        return await call_next(request)
