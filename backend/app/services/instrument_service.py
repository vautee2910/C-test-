"""
Module 2: Instrument Master + Mapping
Implements instrument resolution, fuzzy matching, and alias management.
"""
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
from fuzzywuzzy import fuzz
import json


class InstrumentService:
    """Handles instrument master data and mapping resolution."""

    @staticmethod
    def create_instrument(
        db: Session,
        name: str,
        instrument_type: str,
        isin: Optional[str] = None,
        wkn: Optional[str] = None,
        ticker: Optional[str] = None,
        exchange: Optional[str] = None,
        currency: str = "EUR",
        sector: Optional[str] = None,
        region: Optional[str] = None,
        metadata: Optional[dict] = None
    ):
        """Create a new instrument."""
        query = text("""
            INSERT INTO instruments
            (name, instrument_type, isin, wkn, ticker, exchange, currency, sector, region, metadata, is_active)
            VALUES
            (:name, :instrument_type, :isin, :wkn, :ticker, :exchange, :currency, :sector, :region, :metadata::jsonb, :is_active)
            RETURNING id, name, instrument_type, isin, wkn, ticker, exchange, currency, sector, region, metadata, is_active, created_at
        """)
        result = db.execute(query, {
            "name": name,
            "instrument_type": instrument_type,
            "isin": isin,
            "wkn": wkn,
            "ticker": ticker,
            "exchange": exchange,
            "currency": currency,
            "sector": sector,
            "region": region,
            "metadata": json.dumps(metadata) if metadata else None,
            "is_active": True
        })
        db.commit()
        return result.fetchone()

    @staticmethod
    def resolve_instrument(
        db: Session,
        isin: Optional[str] = None,
        wkn: Optional[str] = None,
        ticker: Optional[str] = None,
        name: Optional[str] = None
    ) -> Optional[int]:
        """
        Resolve instrument by priority: ISIN > WKN > ticker+exchange > alias fuzzy match.
        Returns instrument_id if found, None otherwise.
        """
        # Priority 1: ISIN (exact match)
        if isin:
            query = text("SELECT id FROM instruments WHERE isin = :isin AND is_active = TRUE LIMIT 1")
            result = db.execute(query, {"isin": isin}).fetchone()
            if result:
                return result.id

        # Priority 2: WKN (exact match)
        if wkn:
            query = text("SELECT id FROM instruments WHERE wkn = :wkn AND is_active = TRUE LIMIT 1")
            result = db.execute(query, {"wkn": wkn}).fetchone()
            if result:
                return result.id

        # Priority 3: Ticker (exact match)
        if ticker:
            query = text("SELECT id FROM instruments WHERE ticker = :ticker AND is_active = TRUE LIMIT 1")
            result = db.execute(query, {"ticker": ticker}).fetchone()
            if result:
                return result.id

        # Priority 4: Alias exact match
        if name:
            query = text("""
                SELECT instrument_id
                FROM instrument_aliases
                WHERE LOWER(alias_name) = LOWER(:name)
                ORDER BY confidence DESC
                LIMIT 1
            """)
            result = db.execute(query, {"name": name}).fetchone()
            if result:
                return result.instrument_id

        return None

    @staticmethod
    def fuzzy_search_instruments(db: Session, query_name: str, threshold: int = 80) -> List[Tuple]:
        """
        Fuzzy search for instruments by name.
        Returns list of (instrument_id, name, similarity_score).
        """
        # Get all instruments
        query = text("SELECT id, name FROM instruments WHERE is_active = TRUE")
        results = db.execute(query).fetchall()

        # Calculate fuzzy match scores
        matches = []
        for row in results:
            score = fuzz.ratio(query_name.lower(), row.name.lower())
            if score >= threshold:
                matches.append((row.id, row.name, score))

        # Sort by score descending
        matches.sort(key=lambda x: x[2], reverse=True)
        return matches[:10]  # Return top 10

    @staticmethod
    def create_instrument_alias(
        db: Session,
        instrument_id: int,
        alias_name: str,
        alias_type: str = "common_name",
        confidence: float = 1.0,
        created_by: Optional[int] = None
    ):
        """Create an alias for an instrument (for resolving future duplicates)."""
        query = text("""
            INSERT INTO instrument_aliases (instrument_id, alias_name, alias_type, confidence, created_by)
            VALUES (:instrument_id, :alias_name, :alias_type, :confidence, :created_by)
            RETURNING id
        """)
        result = db.execute(query, {
            "instrument_id": instrument_id,
            "alias_name": alias_name,
            "alias_type": alias_type,
            "confidence": confidence,
            "created_by": created_by
        })
        db.commit()
        return result.fetchone()

    @staticmethod
    def create_unresolved_mapping(
        db: Session,
        source_name: str,
        source_identifier: Optional[str] = None,
        suggested_instrument_id: Optional[int] = None,
        confidence_score: Optional[float] = None
    ):
        """Create an unresolved mapping for analyst review."""
        query = text("""
            INSERT INTO unresolved_mappings
            (source_name, source_identifier, suggested_instrument_id, confidence_score, status)
            VALUES (:source_name, :source_identifier, :suggested_instrument_id, :confidence_score, 'pending')
            RETURNING id
        """)
        result = db.execute(query, {
            "source_name": source_name,
            "source_identifier": source_identifier,
            "suggested_instrument_id": suggested_instrument_id,
            "confidence_score": confidence_score
        })
        db.commit()
        return result.fetchone()

    @staticmethod
    def resolve_unresolved_mapping(
        db: Session,
        mapping_id: int,
        instrument_id: int,
        resolved_by: int
    ):
        """Resolve an unresolved mapping and create an alias."""
        # Update mapping status
        update_query = text("""
            UPDATE unresolved_mappings
            SET status = 'resolved', resolved_by = :resolved_by, resolved_at = NOW()
            WHERE id = :mapping_id
            RETURNING source_name
        """)
        result = db.execute(update_query, {
            "mapping_id": mapping_id,
            "resolved_by": resolved_by
        })
        mapping = result.fetchone()

        if mapping:
            # Create alias to prevent future mismatch
            InstrumentService.create_instrument_alias(
                db, instrument_id, mapping.source_name, "import_name", 1.0, resolved_by
            )

        db.commit()
        return mapping

    @staticmethod
    def get_unresolved_mappings(db: Session, status: str = "pending"):
        """Get list of unresolved mappings for analyst review."""
        query = text("""
            SELECT um.id, um.source_name, um.source_identifier,
                   um.suggested_instrument_id, um.confidence_score, um.status,
                   i.name as suggested_instrument_name
            FROM unresolved_mappings um
            LEFT JOIN instruments i ON um.suggested_instrument_id = i.id
            WHERE um.status = :status
            ORDER BY um.created_at DESC
        """)
        result = db.execute(query, {"status": status})
        return result.fetchall()

    @staticmethod
    def get_instrument_by_id(db: Session, instrument_id: int):
        """Get instrument by ID."""
        query = text("""
            SELECT id, name, instrument_type, isin, wkn, ticker, exchange,
                   currency, sector, region, metadata, is_active, created_at
            FROM instruments
            WHERE id = :instrument_id
        """)
        result = db.execute(query, {"instrument_id": instrument_id})
        return result.fetchone()

    @staticmethod
    def search_instruments(
        db: Session,
        query_text: Optional[str] = None,
        instrument_type: Optional[str] = None,
        limit: int = 50
    ):
        """Search instruments with filters."""
        conditions = ["is_active = TRUE"]
        params = {"limit": limit}

        if query_text:
            conditions.append("(LOWER(name) LIKE LOWER(:query) OR ticker LIKE UPPER(:query) OR isin LIKE UPPER(:query))")
            params["query"] = f"%{query_text}%"

        if instrument_type:
            conditions.append("instrument_type = :instrument_type")
            params["instrument_type"] = instrument_type

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT id, name, instrument_type, isin, wkn, ticker, exchange, currency, sector, region
            FROM instruments
            WHERE {where_clause}
            ORDER BY name
            LIMIT :limit
        """)

        result = db.execute(query, params)
        return result.fetchall()
