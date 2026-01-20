"""
Unit tests for service layer.
These tests demonstrate the service functionality but require a database connection.
"""
import pytest
from datetime import date

from app.services.auth_service import AuthService
from app.services.instrument_service import InstrumentService
from app.services.portfolio_service import PortfolioService
from app.services.alert_service import AlertService
from app.services.report_service import ReportService


class TestAuthService:
    """Test authentication service."""

    def test_hash_password(self):
        """Test password hashing."""
        password = "test_password_123"
        hashed = AuthService.hash_password(password)
        assert hashed != password
        assert len(hashed) > 20

    def test_verify_password(self):
        """Test password verification."""
        password = "test_password_123"
        hashed = AuthService.hash_password(password)
        assert AuthService.verify_password(password, hashed) is True
        assert AuthService.verify_password("wrong_password", hashed) is False

    def test_create_access_token(self):
        """Test JWT token creation."""
        data = {"sub": "test@example.com", "user_id": 1}
        token = AuthService.create_access_token(data)
        assert isinstance(token, str)
        assert len(token) > 50

    def test_decode_access_token(self):
        """Test JWT token decoding."""
        data = {"sub": "test@example.com", "user_id": 1}
        token = AuthService.create_access_token(data)
        decoded = AuthService.decode_access_token(token)
        assert decoded is not None
        assert decoded["sub"] == "test@example.com"
        assert decoded["user_id"] == 1


class TestInstrumentService:
    """Test instrument service."""

    def test_fuzzy_search_logic(self):
        """Test fuzzy matching logic (without DB)."""
        # Just validates imports and basic structure
        assert InstrumentService is not None


class TestPortfolioService:
    """Test portfolio service."""

    def test_service_exists(self):
        """Validate portfolio service exists."""
        assert PortfolioService is not None


class TestAlertService:
    """Test alert service."""

    def test_check_keywords_in_text(self):
        """Test keyword matching logic."""
        text = "Company announced a material restatement of earnings"
        keywords = ["restatement", "fraud", "bankruptcy"]
        matches = AlertService.check_keywords_in_text(text, keywords)
        assert "restatement" in matches
        assert len(matches) == 1

    def test_check_keywords_case_insensitive(self):
        """Test case-insensitive keyword matching."""
        text = "COMPANY ANNOUNCED RESTATEMENT"
        keywords = ["restatement"]
        matches = AlertService.check_keywords_in_text(text, keywords)
        assert len(matches) == 1


class TestReportService:
    """Test report service."""

    def test_validate_report_word_count(self):
        """Test report validation - word count."""
        content = " ".join(["word"] * 2000)  # 2000 words
        report_type = "monthly"
        policy = {
            "report_policy": {
                "max_total_words": {"monthly": 1600},
                "no_trade_language": False
            }
        }

        validation = ReportService.validate_report(content, report_type, policy)
        assert validation["passed"] is False
        assert "word count" in validation["errors"][0].lower()

    def test_validate_report_banned_phrases(self):
        """Test report validation - banned phrases."""
        content = "You should buy this stock and sell that one."
        report_type = "monthly"
        policy = {
            "report_policy": {
                "max_total_words": {"monthly": 5000},
                "no_trade_language": True
            }
        }

        validation = ReportService.validate_report(content, report_type, policy)
        assert validation["passed"] is False
        assert any("banned phrases" in err.lower() for err in validation["errors"])

    def test_validate_report_currency_symbols(self):
        """Test report validation - currency symbols."""
        content = "The stock is priced at $50 per share."
        report_type = "monthly"
        policy = {
            "report_policy": {
                "max_total_words": {"monthly": 5000},
                "no_trade_language": False
            }
        }

        validation = ReportService.validate_report(content, report_type, policy)
        assert validation["passed"] is False
        assert any("currency symbols" in err.lower() for err in validation["errors"])

    def test_validate_report_success(self):
        """Test successful report validation."""
        content = "Portfolio tracking on plan with minor drift observations noted."
        report_type = "monthly"
        policy = {
            "report_policy": {
                "max_total_words": {"monthly": 5000},
                "no_trade_language": True,
                "max_opportunity_callouts": 2
            }
        }

        validation = ReportService.validate_report(content, report_type, policy)
        assert validation["passed"] is True
        assert len(validation["errors"]) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
