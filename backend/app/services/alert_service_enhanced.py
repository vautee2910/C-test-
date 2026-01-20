"""
Enhanced Alert Service - P0.3 Fix
Implements hard gates for alert eligibility:
- Minimum source count enforcement
- Source reliability checks
- Hard caps on high alerts per period
- Deduplication across syndicated sources
"""
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date, timedelta
import hashlib

from app.services.alert_service import AlertService as BaseAlertService


class EnhancedAlertService(BaseAlertService):
    """Alert service with hard gate enforcement."""

    @staticmethod
    def check_alert_eligibility(
        db: Session,
        portfolio_id: int,
        severity: str,
        category: str,
        source_ids: List[int],
        policy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Hard gates to check if alert is eligible to be created.

        Returns:
            {
                "eligible": bool,
                "reason": str (if not eligible),
                "downgraded_severity": str (if downgraded)
            }
        """
        alert_policy = policy.get("alert_policy", {})

        # Gate 1: Check source count requirement for high severity
        if severity == "high":
            min_sources = alert_policy.get("min_sources_for_high", 2)
            unique_sources = len(set(source_ids))

            if unique_sources < min_sources:
                return {
                    "eligible": False,
                    "reason": f"High alerts require >= {min_sources} independent sources (found {unique_sources})",
                    "downgraded_severity": "medium"
                }

        # Gate 2: Check source reliability for high severity
        if severity == "high":
            required_reliability = alert_policy.get("reliability_required_for_high", "high")
            reliability_map = {"low": 0.3, "medium": 0.6, "high": 0.8}
            required_score = reliability_map.get(required_reliability, 0.8)

            source_reliabilities = EnhancedAlertService._get_source_reliabilities(db, source_ids)
            min_reliability = min(source_reliabilities) if source_reliabilities else 0.0

            if min_reliability < required_score:
                return {
                    "eligible": False,
                    "reason": f"High alerts require reliability >= {required_reliability} (min found: {min_reliability:.2f})",
                    "downgraded_severity": "medium"
                }

        # Gate 3: Check high alert caps (per week/day)
        if severity == "high":
            # Check weekly cap
            if "max_high_alerts_per_week" in alert_policy:
                max_weekly = alert_policy["max_high_alerts_per_week"]
                current_week_count = EnhancedAlertService._get_high_alert_count(
                    db, portfolio_id, days=7
                )
                if current_week_count >= max_weekly:
                    return {
                        "eligible": False,
                        "reason": f"Weekly high alert cap reached ({current_week_count}/{max_weekly})",
                        "downgraded_severity": "medium"
                    }

            # Check daily cap (for trading strategies)
            if "max_high_alerts_per_day" in alert_policy:
                max_daily = alert_policy["max_high_alerts_per_day"]
                current_day_count = EnhancedAlertService._get_high_alert_count(
                    db, portfolio_id, days=1
                )
                if current_day_count >= max_daily:
                    return {
                        "eligible": False,
                        "reason": f"Daily high alert cap reached ({current_day_count}/{max_daily})",
                        "downgraded_severity": "medium"
                    }

        # Gate 4: "Ignore if only price move" check
        ignore_price_only = alert_policy.get("ignore_if_only_price_move", False)
        if ignore_price_only and category in ["price_volatility", "price_move"]:
            # Check if there's actual news content beyond price discussion
            # This would need document analysis - simplified here
            return {
                "eligible": False,
                "reason": "Policy ignores price-only moves without substantive news",
                "downgraded_severity": None  # Don't create at all
            }

        # All gates passed
        return {
            "eligible": True,
            "reason": None,
            "downgraded_severity": None
        }

    @staticmethod
    def _get_source_reliabilities(db: Session, source_ids: List[int]) -> List[float]:
        """Get reliability scores for sources."""
        if not source_ids:
            return []

        query = text("""
            SELECT reliability_score
            FROM sources
            WHERE id = ANY(:source_ids)
        """)

        result = db.execute(query, {"source_ids": source_ids})
        return [row.reliability_score for row in result]

    @staticmethod
    def _get_high_alert_count(db: Session, portfolio_id: int, days: int) -> int:
        """Get count of high severity alerts in recent days."""
        query = text("""
            SELECT COUNT(*)
            FROM alerts
            WHERE portfolio_id = :portfolio_id
              AND severity = 'high'
              AND triggered_at >= NOW() - INTERVAL ':days days'
              AND status != 'rejected'
        """)

        result = db.execute(query, {"portfolio_id": portfolio_id, "days": days})
        return result.scalar() or 0

    @staticmethod
    def deduplicate_sources(
        db: Session,
        source_ids: List[int],
        document_titles: List[str]
    ) -> List[int]:
        """
        Deduplicate sources that are likely syndicated copies.
        Uses title similarity hashing.

        Returns: List of unique source IDs
        """
        if len(source_ids) <= 1:
            return source_ids

        # Create normalized title hashes
        title_hashes = {}
        for source_id, title in zip(source_ids, document_titles):
            # Normalize title (lowercase, remove punctuation, etc.)
            normalized = ''.join(c.lower() for c in title if c.isalnum() or c.isspace())
            normalized = ' '.join(normalized.split())  # Normalize whitespace

            # Create hash
            title_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]

            if title_hash not in title_hashes:
                title_hashes[title_hash] = source_id

        # Return unique source IDs
        return list(title_hashes.values())

    @staticmethod
    def create_alert_with_gates(
        db: Session,
        portfolio_id: Optional[int],
        instrument_id: Optional[int],
        alert_type: str,
        severity: str,
        category: Optional[str],
        title: str,
        summary: str,
        source_ids: List[int],
        evidence_links: Optional[List[Dict[str, Any]]] = None,
        llm_analysis: Optional[Dict[str, Any]] = None,
        rule_matches: Optional[Dict[str, Any]] = None
    ):
        """
        Create alert with hard gate enforcement.

        Returns:
            {
                "status": "created" | "downgraded" | "rejected",
                "alert_id": int (if created),
                "reason": str (if downgraded/rejected),
                "final_severity": str
            }
        """
        if not portfolio_id:
            # Can't check policy without portfolio
            return BaseAlertService.create_alert(
                db, portfolio_id, instrument_id, alert_type, severity,
                category, title, summary, evidence_links, llm_analysis, rule_matches
            )

        # Get strategy policy
        policy = BaseAlertService.get_strategy_policy(db, portfolio_id)

        # Deduplicate sources
        document_titles = [link.get("title", "") for link in evidence_links] if evidence_links else []
        unique_source_ids = EnhancedAlertService.deduplicate_sources(db, source_ids, document_titles)

        # Check eligibility gates
        eligibility = EnhancedAlertService.check_alert_eligibility(
            db, portfolio_id, severity, category, unique_source_ids, policy
        )

        if not eligibility["eligible"]:
            # Not eligible
            downgraded_severity = eligibility["downgraded_severity"]

            if downgraded_severity is None:
                # Don't create at all
                return {
                    "status": "rejected",
                    "alert_id": None,
                    "reason": eligibility["reason"],
                    "final_severity": None
                }
            else:
                # Downgrade severity and create
                severity = downgraded_severity
                status_result = {
                    "status": "downgraded",
                    "reason": eligibility["reason"],
                    "final_severity": severity
                }

        else:
            status_result = {
                "status": "created",
                "reason": None,
                "final_severity": severity
            }

        # Determine initial status based on approval requirements
        approval_required = BaseAlertService.should_require_approval(
            policy, severity, len(unique_source_ids)
        )
        initial_status = "pending" if approval_required else "auto_approved"

        # Create alert with source metrics
        alert = BaseAlertService.create_alert(
            db, portfolio_id, instrument_id, alert_type, severity,
            category, title, summary, evidence_links, llm_analysis, rule_matches,
            status=initial_status
        )

        # Update source count and reliability metrics
        if alert:
            min_reliability = min(EnhancedAlertService._get_source_reliabilities(db, unique_source_ids)) if unique_source_ids else 0.0

            update_query = text("""
                UPDATE alerts
                SET source_count = :source_count,
                    min_source_reliability = :min_reliability
                WHERE id = :alert_id
            """)

            db.execute(update_query, {
                "alert_id": alert.id,
                "source_count": len(unique_source_ids),
                "min_reliability": min_reliability
            })
            db.commit()

            status_result["alert_id"] = alert.id

        return status_result

    @staticmethod
    def set_source_reliability(
        db: Session,
        source_id: int,
        reliability_score: float,
        is_verified: bool = False
    ):
        """
        Set reliability score for a source (admin function).
        Score: 0.0-0.3 = low, 0.4-0.7 = medium, 0.8-1.0 = high
        """
        query = text("""
            UPDATE sources
            SET reliability_score = :reliability_score,
                is_verified = :is_verified
            WHERE id = :source_id
        """)

        db.execute(query, {
            "source_id": source_id,
            "reliability_score": max(0.0, min(1.0, reliability_score)),
            "is_verified": is_verified
        })
        db.commit()
