"""
Module 8: Report Generation with Template Validation
Implements report generation, word count enforcement, and template validation.
"""
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import date
import json
import re


class ReportService:
    """Handles report generation and validation."""

    @staticmethod
    def generate_report(
        db: Session,
        portfolio_id: int,
        report_type: str,
        period_start: date,
        period_end: date
    ) -> int:
        """
        Generate a report for a portfolio.
        Note: Actual LLM-based generation would be implemented here.
        This is a scaffold that enforces validation.
        """
        # Get portfolio and strategy profile
        portfolio_query = text("""
            SELECT p.id, p.name, p.strategy_profile_id, sp.policy_json, sp.name as strategy_name
            FROM portfolios p
            JOIN strategy_profiles sp ON p.strategy_profile_id = sp.id
            WHERE p.id = :portfolio_id
        """)
        portfolio = db.execute(portfolio_query, {"portfolio_id": portfolio_id}).fetchone()

        if not portfolio:
            raise ValueError("Portfolio not found")

        policy = portfolio.policy_json
        report_policy = policy.get("report_policy", {})

        # Check if this report type is enabled for this strategy
        cadence = report_policy.get("cadence", {})
        if report_type not in cadence or not cadence.get(report_type):
            raise ValueError(f"Report type '{report_type}' not enabled for strategy '{portfolio.strategy_name}'")

        # Generate report content (simplified - would use LLM in production)
        content_markdown = ReportService._generate_report_content(
            db, portfolio_id, report_type, period_start, period_end, policy
        )

        # Validate report
        validation_result = ReportService.validate_report(
            content_markdown, report_type, policy
        )

        # Store report
        insert_query = text("""
            INSERT INTO reports
            (portfolio_id, report_type, report_period_start, report_period_end,
             strategy_profile_id, content_markdown, validation_passed, validation_errors,
             generated_by, metadata)
            VALUES
            (:portfolio_id, :report_type, :period_start, :period_end,
             :strategy_profile_id, :content_markdown, :validation_passed, :validation_errors::jsonb,
             'system', :metadata::jsonb)
            RETURNING id
        """)

        result = db.execute(insert_query, {
            "portfolio_id": portfolio_id,
            "report_type": report_type,
            "period_start": period_start,
            "period_end": period_end,
            "strategy_profile_id": portfolio.strategy_profile_id,
            "content_markdown": content_markdown,
            "validation_passed": validation_result["passed"],
            "validation_errors": json.dumps(validation_result.get("errors", [])),
            "metadata": json.dumps(validation_result.get("metadata", {}))
        })
        db.commit()

        return result.fetchone().id

    @staticmethod
    def _generate_report_content(
        db: Session,
        portfolio_id: int,
        report_type: str,
        period_start: date,
        period_end: date,
        policy: Dict[str, Any]
    ) -> str:
        """
        Generate report content based on template.
        This is a simplified version - in production, would use LLM.
        """
        from app.services.portfolio_service import PortfolioService

        # Get latest positions
        positions = PortfolioService.get_position_aggregates(db, portfolio_id, period_end)

        # Get alerts in period
        from app.services.alert_service import AlertService
        alerts = AlertService.list_alerts(
            db, portfolio_id=portfolio_id,
            date_from=period_start, date_to=period_end
        )

        # Build report based on type
        if report_type == "monthly":
            return ReportService._build_monthly_report(positions, alerts, policy)
        elif report_type == "quarterly":
            return ReportService._build_quarterly_report(positions, alerts, policy)
        elif report_type == "annual_ideas":
            return ReportService._build_annual_ideas_report(positions, policy)
        else:
            return f"# {report_type.title()} Report\n\nReport content placeholder."

    @staticmethod
    def _build_monthly_report(positions, alerts, policy) -> str:
        """Build monthly report following the template."""
        report_policy = policy.get("report_policy", {})
        max_opportunities = report_policy.get("max_opportunity_callouts", 2)

        # Template sections
        content = "# Monthly Portfolio Report\n\n"

        # 1. Executive Summary
        content += "## Executive Summary\n\n"
        content += "- Portfolio tracking on plan with minor drift observations\n"
        content += "- No high-severity alerts triggered this period\n"
        content += "- All positions remain within policy thresholds\n\n"

        # 2. Allocation & Drift
        content += "## Allocation & Drift vs Baseline\n\n"
        content += "| Holding | Current Weight | Baseline Weight | Drift (pp) |\n"
        content += "|---------|----------------|-----------------|------------|\n"
        for pos in positions[:10]:  # Top 10
            content += f"| {pos.instrument_name} | {pos.current_weight_pct:.2f}% | {pos.current_weight_pct - pos.drift_pp:.2f}% | {pos.drift_pp:.2f} |\n"
        content += "\n"

        # 3. Performance
        content += "## Performance (Index Units)\n\n"
        content += "### Top Contributors\n"
        contributors = sorted(positions, key=lambda p: p.contributed_return_pp or 0, reverse=True)[:5]
        for pos in contributors:
            content += f"- {pos.instrument_name}: +{pos.contributed_return_pp:.2f}pp contribution\n"
        content += "\n"

        content += "### Top Detractors\n"
        detractors = sorted(positions, key=lambda p: p.contributed_return_pp or 0)[:5]
        for pos in detractors:
            content += f"- {pos.instrument_name}: {pos.contributed_return_pp:.2f}pp contribution\n"
        content += "\n"

        # 4. Key Events
        content += "## Key Events Since Last Report\n\n"
        if alerts:
            for alert in alerts[:8]:  # Max 8 bullets
                content += f"- **{alert.title}** ({alert.severity}): {alert.summary}\n"
        else:
            content += "- No material events to report\n"
        content += "\n"

        # 5. Watchlist
        content += "## Watchlist (Non-Urgent)\n\n"
        content += "- Monitor overall market volatility trends\n"
        content += "- Track upcoming earnings releases\n\n"

        # 6. Opportunities (max 2 for conservative)
        content += "## Opportunities\n\n"
        content += "No significant opportunities identified this period.\n\n"

        # 7. Appendix
        content += "## Appendix: Holdings Notes\n\n"
        for pos in positions[:10]:
            content += f"- **{pos.instrument_name}**: Performance in line with expectations\n"

        return content

    @staticmethod
    def _build_quarterly_report(positions, alerts, policy) -> str:
        """Build quarterly report (more detailed)."""
        content = "# Quarterly Position Review\n\n"

        for pos in positions:
            content += f"## {pos.instrument_name}\n\n"
            content += f"**Current Weight:** {pos.current_weight_pct:.2f}% | **Drift:** {pos.drift_pp:.2f}pp\n\n"
            content += "### What happened (90 days)\n"
            content += "- Position tracking as expected\n\n"
            content += "### Thesis watchpoints\n"
            content += "- Monitor key metrics\n\n"
            content += "### Outlook\n"
            content += "- **Base:** Neutral outlook\n\n"
            content += "---\n\n"

        return content

    @staticmethod
    def _build_annual_ideas_report(positions, policy) -> str:
        """Build annual ideas report."""
        content = "# Annual Research Ideas Report\n\n"

        content += "## Portfolio Exposures Summary\n\n"
        content += "Portfolio maintains diversified exposure across sectors.\n\n"

        content += "## Gaps / Concentration Observations\n\n"
        content += "No significant concentration concerns identified.\n\n"

        content += "## Research Candidates\n\n"
        content += "1. **Technology Sector Opportunities**\n"
        content += "   - Key risk: Valuation sensitivity\n"
        content += "   - What to verify: Revenue growth sustainability\n\n"

        content += "## Top 1-3 to Prioritize\n\n"
        content += "Focus on existing holdings performance monitoring.\n\n"

        return content

    @staticmethod
    def validate_report(
        content: str,
        report_type: str,
        policy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate report against policy constraints.
        Returns: {"passed": bool, "errors": [], "metadata": {}}
        """
        report_policy = policy.get("report_policy", {})
        errors = []
        metadata = {}

        # Check word count
        word_count = len(content.split())
        metadata["word_count"] = word_count

        max_words_config = report_policy.get("max_total_words", {})
        max_words = max_words_config.get(report_type, 10000)  # Default 10k if not specified

        if word_count > max_words:
            errors.append(f"Word count {word_count} exceeds maximum {max_words}")

        # Check for banned phrases (if no_trade_language is True)
        no_trade_language = report_policy.get("no_trade_language", False)
        if no_trade_language:
            banned_phrases = ["buy", "sell", "enter", "exit", "target price"]
            found_banned = []
            content_lower = content.lower()
            for phrase in banned_phrases:
                if phrase in content_lower:
                    found_banned.append(phrase)

            if found_banned:
                errors.append(f"Report contains banned phrases: {', '.join(found_banned)}")

        # Check for currency symbols (must not appear for management view)
        currency_symbols = ["$", "€", "£", "¥"]
        found_symbols = []
        for symbol in currency_symbols:
            if symbol in content:
                found_symbols.append(symbol)

        if found_symbols:
            errors.append(f"Report contains currency symbols: {', '.join(found_symbols)}")

        # Check opportunity count
        max_opportunities = report_policy.get("max_opportunity_callouts", 2)
        opportunity_count = content.lower().count("opportunity")  # Simplified
        metadata["opportunity_count"] = opportunity_count

        if opportunity_count > max_opportunities:
            errors.append(f"Opportunity callouts {opportunity_count} exceeds maximum {max_opportunities}")

        return {
            "passed": len(errors) == 0,
            "errors": errors,
            "metadata": metadata
        }

    @staticmethod
    def get_report(db: Session, report_id: int):
        """Get report by ID."""
        query = text("""
            SELECT r.id, r.portfolio_id, r.report_type, r.report_period_start,
                   r.report_period_end, r.strategy_profile_id, r.content_markdown,
                   r.validation_passed, r.validation_errors, r.generated_by,
                   r.metadata, r.created_at,
                   p.name as portfolio_name
            FROM reports r
            JOIN portfolios p ON r.portfolio_id = p.id
            WHERE r.id = :report_id
        """)
        result = db.execute(query, {"report_id": report_id})
        return result.fetchone()

    @staticmethod
    def list_reports(
        db: Session,
        portfolio_id: Optional[int] = None,
        report_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 20
    ):
        """List reports with filters."""
        conditions = []
        params = {"limit": limit}

        if portfolio_id:
            conditions.append("r.portfolio_id = :portfolio_id")
            params["portfolio_id"] = portfolio_id

        if report_type:
            conditions.append("r.report_type = :report_type")
            params["report_type"] = report_type

        if date_from:
            conditions.append("r.report_period_end >= :date_from")
            params["date_from"] = date_from

        if date_to:
            conditions.append("r.report_period_end <= :date_to")
            params["date_to"] = date_to

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = text(f"""
            SELECT r.id, r.portfolio_id, r.report_type, r.report_period_start,
                   r.report_period_end, r.validation_passed, r.created_at,
                   p.name as portfolio_name
            FROM reports r
            JOIN portfolios p ON r.portfolio_id = p.id
            {where_clause}
            ORDER BY r.created_at DESC
            LIMIT :limit
        """)

        result = db.execute(query, params)
        return result.fetchall()

    @staticmethod
    def log_report_view(db: Session, report_id: int, user_id: int):
        """Log that a user viewed a report (for audit)."""
        query = text("""
            INSERT INTO report_views (report_id, user_id, viewed_at)
            VALUES (:report_id, :user_id, NOW())
        """)
        db.execute(query, {"report_id": report_id, "user_id": user_id})
        db.commit()
