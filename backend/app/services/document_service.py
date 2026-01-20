"""
Module 5: News + Filings Ingestion + Document Processing
Module 6: Vectorization & Hybrid Retrieval
Combined: document ingestion, processing, chunking, embedding, and search.
"""
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date
import hashlib
import json
import tiktoken
from minio import Minio
from minio.error import S3Error

from app.core.config import settings


class DocumentService:
    """Handles document ingestion, processing, chunking, and search."""

    def __init__(self):
        """Initialize MinIO client."""
        self.minio_client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure
        )
        self._ensure_buckets()

    def _ensure_buckets(self):
        """Ensure MinIO buckets exist."""
        for bucket in [settings.minio_bucket_raw, settings.minio_bucket_text, settings.minio_bucket_chunks]:
            try:
                if not self.minio_client.bucket_exists(bucket):
                    self.minio_client.make_bucket(bucket)
            except S3Error:
                pass  # Bucket might already exist

    @staticmethod
    def create_dedupe_hash(title: str, domain: str, published_at: datetime) -> str:
        """Create deduplication hash from normalized title + domain + date."""
        normalized = f"{title.lower().strip()}|{domain.lower()}|{published_at.date()}"
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def ingest_document(
        db: Session,
        source_id: int,
        document_type: str,
        title: str,
        url: Optional[str] = None,
        published_at: Optional[datetime] = None,
        author: Optional[str] = None,
        raw_content: Optional[str] = None,
        metadata: Optional[dict] = None
    ):
        """
        Ingest a document (news article, filing, etc.).
        Deduplicates by hash of (title + domain + date).
        """
        # Create dedupe hash
        from urllib.parse import urlparse
        domain = urlparse(url).netloc if url else "unknown"
        dedupe_hash = DocumentService.create_dedupe_hash(
            title, domain, published_at or datetime.now()
        )

        # Check if already exists
        check_query = text("SELECT id FROM documents WHERE dedupe_hash = :dedupe_hash")
        existing = db.execute(check_query, {"dedupe_hash": dedupe_hash}).fetchone()

        if existing:
            return existing.id  # Already ingested

        # Insert document
        insert_query = text("""
            INSERT INTO documents
            (source_id, document_type, title, url, published_at, author, dedupe_hash,
             text_preview, metadata, is_processed)
            VALUES
            (:source_id, :document_type, :title, :url, :published_at, :author, :dedupe_hash,
             :text_preview, :metadata::jsonb, FALSE)
            RETURNING id
        """)

        text_preview = raw_content[:500] if raw_content else None

        result = db.execute(insert_query, {
            "source_id": source_id,
            "document_type": document_type,
            "title": title,
            "url": url,
            "published_at": published_at,
            "author": author,
            "dedupe_hash": dedupe_hash,
            "text_preview": text_preview,
            "metadata": json.dumps(metadata) if metadata else None
        })
        db.commit()

        document_id = result.fetchone().id

        # Store raw content in MinIO if provided
        if raw_content:
            # Will be implemented in actual storage logic
            pass

        return document_id

    @staticmethod
    def link_document_to_instruments(
        db: Session,
        document_id: int,
        instrument_ids: List[int],
        match_method: str = "manual",
        confidence: float = 1.0
    ):
        """Link a document to one or more instruments."""
        for instrument_id in instrument_ids:
            query = text("""
                INSERT INTO document_instruments
                (document_id, instrument_id, confidence, match_method)
                VALUES (:document_id, :instrument_id, :confidence, :match_method)
                ON CONFLICT (document_id, instrument_id) DO NOTHING
            """)
            db.execute(query, {
                "document_id": document_id,
                "instrument_id": instrument_id,
                "confidence": confidence,
                "match_method": match_method
            })
        db.commit()

    @staticmethod
    def auto_link_document_to_instruments(db: Session, document_id: int, document_text: str):
        """
        Automatically link document to instruments by detecting:
        - ISIN mentions
        - Ticker mentions
        - Company name fuzzy matches
        """
        from app.services.instrument_service import InstrumentService
        import re

        linked_instruments = set()

        # Pattern 1: ISIN (e.g., DE0005190003, US0378331005)
        isin_pattern = r'\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b'
        isins = re.findall(isin_pattern, document_text)
        for isin in isins:
            instrument_id = InstrumentService.resolve_instrument(db, isin=isin)
            if instrument_id:
                linked_instruments.add((instrument_id, "isin_match", 1.0))

        # Pattern 2: Get all instrument names and fuzzy match (simplified)
        # In production, use a more sophisticated NER approach
        query = text("SELECT id, name, ticker FROM instruments WHERE is_active = TRUE")
        instruments = db.execute(query).fetchall()

        for instrument in instruments:
            # Exact name match (case insensitive)
            if instrument.name.lower() in document_text.lower():
                linked_instruments.add((instrument.id, "name_exact", 0.9))
            # Ticker match (uppercase)
            elif instrument.ticker and f" {instrument.ticker} " in f" {document_text.upper()} ":
                linked_instruments.add((instrument.id, "ticker_match", 0.95))

        # Link all found instruments
        for instrument_id, match_method, confidence in linked_instruments:
            DocumentService.link_document_to_instruments(
                db, document_id, [instrument_id], match_method, confidence
            )

    @staticmethod
    def chunk_document(text: str, chunk_size: int = 600, overlap: int = 100) -> List[str]:
        """
        Chunk document text into smaller pieces for embedding.
        Uses token-based chunking with overlap.
        """
        encoding = tiktoken.get_encoding("cl100k_base")  # GPT-4 encoding
        tokens = encoding.encode(text)

        chunks = []
        start = 0
        while start < len(tokens):
            end = start + chunk_size
            chunk_tokens = tokens[start:end]
            chunk_text = encoding.decode(chunk_tokens)
            chunks.append(chunk_text)
            start += (chunk_size - overlap)

        return chunks

    @staticmethod
    def create_chunks_for_document(
        db: Session,
        document_id: int,
        full_text: str
    ):
        """
        Create and store chunks for a document.
        Note: Embeddings will be generated separately (requires OpenAI API).
        """
        chunks = DocumentService.chunk_document(
            full_text,
            settings.chunk_size_tokens,
            settings.chunk_overlap_tokens
        )

        for idx, chunk_text in enumerate(chunks):
            # Calculate token count
            encoding = tiktoken.get_encoding("cl100k_base")
            chunk_tokens = len(encoding.encode(chunk_text))

            # Create tsvector for full-text search
            query = text("""
                INSERT INTO document_chunks
                (document_id, chunk_index, chunk_text, chunk_tokens, tsvector_col)
                VALUES (:document_id, :chunk_index, :chunk_text, :chunk_tokens,
                        to_tsvector('english', :chunk_text))
                RETURNING id
            """)

            db.execute(query, {
                "document_id": document_id,
                "chunk_index": idx,
                "chunk_text": chunk_text,
                "chunk_tokens": chunk_tokens
            })

        db.commit()

        # Mark document as processed
        update_query = text("""
            UPDATE documents SET is_processed = TRUE WHERE id = :document_id
        """)
        db.execute(update_query, {"document_id": document_id})
        db.commit()

    @staticmethod
    def hybrid_search(
        db: Session,
        query: str,
        instrument_ids: Optional[List[int]] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 10
    ):
        """
        Hybrid search: BM25 full-text + vector similarity.
        For now, implements BM25 only (vector search requires embeddings).
        """
        # Build query conditions
        conditions = []
        params = {"query": query, "limit": limit}

        if instrument_ids:
            conditions.append("d.id IN (SELECT document_id FROM document_instruments WHERE instrument_id = ANY(:instrument_ids))")
            params["instrument_ids"] = instrument_ids

        if date_from:
            conditions.append("d.published_at >= :date_from")
            params["date_from"] = date_from

        if date_to:
            conditions.append("d.published_at <= :date_to")
            params["date_to"] = date_to

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # BM25 full-text search
        search_query = text(f"""
            SELECT
                dc.id as chunk_id,
                dc.document_id,
                dc.chunk_text,
                d.title as document_title,
                d.url as document_url,
                d.published_at,
                ts_rank_cd(dc.tsvector_col, plainto_tsquery('english', :query)) as score
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            {where_clause}
            AND dc.tsvector_col @@ plainto_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT :limit
        """)

        result = db.execute(search_query, params)
        return result.fetchall()

    @staticmethod
    def get_documents_for_instrument(
        db: Session,
        instrument_id: int,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 50
    ):
        """Get all documents linked to an instrument."""
        conditions = ["di.instrument_id = :instrument_id"]
        params = {"instrument_id": instrument_id, "limit": limit}

        if date_from:
            conditions.append("d.published_at >= :date_from")
            params["date_from"] = date_from

        if date_to:
            conditions.append("d.published_at <= :date_to")
            params["date_to"] = date_to

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT d.id, d.title, d.url, d.published_at, d.document_type,
                   d.text_preview, di.confidence, di.match_method
            FROM documents d
            JOIN document_instruments di ON d.id = di.document_id
            WHERE {where_clause}
            ORDER BY d.published_at DESC
            LIMIT :limit
        """)

        result = db.execute(query, params)
        return result.fetchall()
