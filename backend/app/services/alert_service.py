"""
Module 7: Alert Engine (Rules + LLM + Approval Workflow)
Implements Stage A rule-based filtering and Stage B LLM analysis.
"""
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date, timedelta
import json

from app.core.config import settings


class AlertService:
    """Handles alert generation, approval workflow, and rule-based filtering."""

    @staticmethod
    def get_keyword_taxonomy(db: Session, instrument_type: str = "all"):
        """Get keyword taxonomy for an instrument type."""
        query = text("""
            SELECT category, severity, keywords, description
            FROM keyword_taxonomy
            WHERE instrument_type IN ('all', :instrument_type)
            ORDER BY severity DESC
        """)
        result = db.execute(query, {"instrument_type": instrument_type})
        return result.fetchall()

    @staticmethod
    def check_keywords_in_text(text: str, keywords: List[str]) -> List[str]:
        """Check if any keywords appear in text (case-insensitive)."""
        text_lower = text.lower()
        matches = []
        for keyword in keywords:
            if keyword.lower() in text_lower:
                matches.append(keyword)
        return matches

    @staticmethod
    def stage_a_rule_based_filter(
        db: Session,
        document_id: int,
        document_text: str,
        instrument_id: int,
        instrument_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Stage A: Rule-based filtering using keyword taxonomy.
        Returns None if no keywords match, otherwise returns alert metadata.
        """
        # Get taxonomy for this instrument type
        taxonomy = AlertService.get_keyword_taxonomy(db, instrument_type)

        best_match = None
        best_severity = None
        all_matches = []

        severity_order = {"high": 3, "medium": 2, "low": 1}

        for rule in taxonomy:
            keywords = rule.keywords
            category = rule.category
            severity = rule.severity

            # Check for keyword matches
            matched_keywords = AlertService.check_keywords_in_text(document_text, keywords)

            if matched_keywords:
                match_info = {
                    "category": category,
                    "severity": severity,
                    "matched_keywords": matched_keywords,
                    "description": rule.description
                }
                all_matches.append(match_info)

                # Track highest severity match
                if not best_severity or severity_order.get(severity, 0) > severity_order.get(best_severity, 0):
                    best_match = match_info
                    best_severity = severity

        if best_match:
            return {
                "primary_match": best_match,
                "all_matches": all_matches,
                "total_keywords_matched": sum(len(m["matched_keywords"]) for m in all_matches)
            }

        return None

    @staticmethod
    def create_alert(
        db: Session,
        portfolio_id: Optional[int],
        instrument_id: Optional[int],
        alert_type: str,
        severity: str,
        category: Optional[str],
        title: str,
        summary: str,
        evidence_links: Optional[List[Dict[str, Any]]] = None,
        llm_analysis: Optional[Dict[str, Any]] = None,
        rule_matches: Optional[Dict[str, Any]] = None,
        status: str = "pending"
    ):
        """Create a new alert."""
        query = text("""
            INSERT INTO alerts
            (portfolio_id, instrument_id, alert_type, severity, category, title, summary,
             evidence_links, llm_analysis, rule_matches, status, triggered_at)
            VALUES
            (:portfolio_id, :instrument_id, :alert_type, :severity, :category, :title, :summary,
             :evidence_links::jsonb, :llm_analysis::jsonb, :rule_matches::jsonb, :status, NOW())
            RETURNING id, triggered_at
        """)

        result = db.execute(query, {
            "portfolio_id": portfolio_id,
            "instrument_id": instrument_id,
            "alert_type": alert_type,
            "severity": severity,
            "category": category,
            "title": title,
            "summary": summary,
            "evidence_links": json.dumps(evidence_links) if evidence_links else None,
            "llm_analysis": json.dumps(llm_analysis) if llm_analysis else None,
            "rule_matches": json.dumps(rule_matches) if rule_matches else None,
            "status": status
        })
        db.commit()
        return result.fetchone()

    @staticmethod
    def get_strategy_policy(db: Session, portfolio_id: int) -> Dict[str, Any]:
        """Get the strategy policy JSON for a portfolio."""
        query = text("""
            SELECT sp.policy_json
            FROM portfolios p
            JOIN strategy_profiles sp ON p.strategy_profile_id = sp.id
            WHERE p.id = :portfolio_id
        """)
        result = db.execute(query, {"portfolio_id": portfolio_id})
        row = result.fetchone()
        return row.policy_json if row else {}

    @staticmethod
    def should_require_approval(policy: Dict[str, Any], severity: str, alert_count: int) -> bool:
        """
        Check if alert requires human approval based on strategy policy.
        """
        alert_policy = policy.get("alert_policy", {})

        if severity == "high":
            if alert_policy.get("human_approval_required_for_high", True):
                # Check if we've exceeded the max alerts per week
                max_high_per_week = alert_policy.get("max_high_alerts_per_week", 2)
                if alert_count >= max_high_per_week:
                    return True
                return True
            return False

        return False

    @staticmethod
    def approve_alert(db: Session, alert_id: int, approved_by: int, action: str):
        """Approve or reject an alert."""
        status = "approved" if action == "approve" else "rejected"

        query = text("""
            UPDATE alerts
            SET status = :status, approved_by = :approved_by, approved_at = NOW()
            WHERE id = :alert_id
            RETURNING id, status
        """)

        result = db.execute(query, {
            "alert_id": alert_id,
            "status": status,
            "approved_by": approved_by
        })
        db.commit()
        return result.fetchone()

    @staticmethod
    def list_alerts(
        db: Session,
        portfolio_id: Optional[int] = None,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 50
    ):
        """List alerts with filters."""
        conditions = []
        params = {"limit": limit}

        if portfolio_id:
            conditions.append("a.portfolio_id = :portfolio_id")
            params["portfolio_id"] = portfolio_id

        if severity:
            conditions.append("a.severity = :severity")
            params["severity"] = severity

        if status:
            conditions.append("a.status = :status")
            params["status"] = status

        if date_from:
            conditions.append("a.triggered_at >= :date_from")
            params["date_from"] = date_from

        if date_to:
            conditions.append("a.triggered_at <= :date_to")
            params["date_to"] = date_to

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = text(f"""
            SELECT a.id, a.portfolio_id, a.instrument_id, a.alert_type, a.severity,
                   a.category, a.title, a.summary, a.evidence_links, a.llm_analysis,
                   a.rule_matches, a.status, a.triggered_at, a.approved_by, a.approved_at,
                   i.name as instrument_name
            FROM alerts a
            LEFT JOIN instruments i ON a.instrument_id = i.id
            {where_clause}
            ORDER BY a.triggered_at DESC
            LIMIT :limit
        """)

        result = db.execute(query, params)
        return result.fetchall()

    @staticmethod
    def generate_alert_from_document(
        db: Session,
        document_id: int,
        portfolio_id: int
    ):
        """
        Generate alerts from a document for all instruments in a portfolio.
        Implements Stage A (keyword filtering).
        Stage B (LLM analysis) would be called separately.
        """
        # Get document text (simplified - would fetch from chunks in reality)
        doc_query = text("""
            SELECT d.id, d.title, d.url, d.published_at,
                   STRING_AGG(dc.chunk_text, ' ') as full_text
            FROM documents d
            LEFT JOIN document_chunks dc ON d.id = dc.document_id
            WHERE d.id = :document_id
            GROUP BY d.id, d.title, d.url, d.published_at
        """)
        doc = db.execute(doc_query, {"document_id": document_id}).fetchone()

        if not doc or not doc.full_text:
            return []

        # Get instruments linked to this document
        link_query = text("""
            SELECT di.instrument_id, i.name, i.instrument_type
            FROM document_instruments di
            JOIN instruments i ON di.instrument_id = i.id
            WHERE di.document_id = :document_id
        """)
        linked_instruments = db.execute(link_query, {"document_id": document_id}).fetchall()

        alerts_created = []

        for instrument in linked_instruments:
            # Stage A: Rule-based filtering
            rule_result = AlertService.stage_a_rule_based_filter(
                db,
                document_id,
                doc.full_text,
                instrument.instrument_id,
                instrument.instrument_type
            )

            if rule_result:
                primary_match = rule_result["primary_match"]

                # Create alert
                alert = AlertService.create_alert(
                    db,
                    portfolio_id=portfolio_id,
                    instrument_id=instrument.instrument_id,
                    alert_type="news",
                    severity=primary_match["severity"],
                    category=primary_match["category"],
                    title=f"{primary_match['category'].replace('_', ' ').title()}: {instrument.name}",
                    summary=doc.title,
                    evidence_links=[{
                        "document_id": document_id,
                        "url": doc.url,
                        "title": doc.title,
                        "published_at": str(doc.published_at) if doc.published_at else None
                    }],
                    rule_matches=rule_result,
                    status="pending"
                )
                alerts_created.append(alert)

        return alerts_created

    @staticmethod
    def get_alert_count_recent(
        db: Session,
        portfolio_id: int,
        severity: str,
        days: int = 7
    ) -> int:
        """Get count of alerts for a portfolio in recent days."""
        query = text("""
            SELECT COUNT(*)
            FROM alerts
            WHERE portfolio_id = :portfolio_id
              AND severity = :severity
              AND triggered_at >= NOW() - INTERVAL ':days days'
        """)
        result = db.execute(query, {
            "portfolio_id": portfolio_id,
            "severity": severity,
            "days": days
        })
        return result.scalar()
