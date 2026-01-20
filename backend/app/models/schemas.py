from pydantic import BaseModel, EmailStr, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from enum import Enum


# =============================================================================
# Enums
# =============================================================================

class UserRole(str, Enum):
    analyst = "analyst"
    management = "management"
    admin = "admin"


class AlertSeverity(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class AlertStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    auto_approved = "auto_approved"


# =============================================================================
# Module 1: Auth & RBAC
# =============================================================================

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.analyst


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    mfa_enabled: bool
    created_at: datetime

    class Config:
        orm_mode = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    mfa_code: Optional[str] = None


# =============================================================================
# Module 2: Instrument Master + Mapping
# =============================================================================

class InstrumentCreate(BaseModel):
    name: str
    instrument_type: str  # stock, etf, bond, re_fund, pharma, reinsurer, etc.
    isin: Optional[str] = None
    wkn: Optional[str] = None
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = "EUR"
    sector: Optional[str] = None
    region: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class InstrumentResponse(BaseModel):
    id: int
    name: str
    instrument_type: str
    isin: Optional[str]
    wkn: Optional[str]
    ticker: Optional[str]
    exchange: Optional[str]
    currency: Optional[str]
    sector: Optional[str]
    region: Optional[str]
    metadata: Optional[Dict[str, Any]]
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True


class InstrumentMappingRequest(BaseModel):
    source_name: str
    source_identifier: Optional[str] = None
    instrument_id: int


class InstrumentSearchRequest(BaseModel):
    query: str
    instrument_type: Optional[str] = None


# =============================================================================
# Module 3: Portfolio Math Engine (Index Units)
# =============================================================================

class HoldingCreate(BaseModel):
    instrument_id: int
    baseline_weight_pct: float
    baseline_units: float
    baseline_date: date


class HoldingResponse(BaseModel):
    id: int
    portfolio_id: int
    instrument_id: int
    instrument_name: Optional[str] = None  # Joined data
    baseline_weight_pct: float
    baseline_units: float
    baseline_date: date
    is_active: bool

    class Config:
        orm_mode = True


class PortfolioCreate(BaseModel):
    name: str
    strategy_profile_id: int
    currency: str = "EUR"
    is_paper_only: bool = False
    baseline_date: Optional[date] = None
    holdings: List[HoldingCreate] = []


class PortfolioResponse(BaseModel):
    id: int
    name: str
    owner_id: Optional[int]
    strategy_profile_id: int
    strategy_profile_name: Optional[str] = None
    currency: str
    is_paper_only: bool
    baseline_date: Optional[date]
    created_at: datetime

    class Config:
        orm_mode = True


class PositionAggregateResponse(BaseModel):
    portfolio_id: int
    instrument_id: int
    instrument_name: Optional[str]
    as_of_date: date
    current_units: float
    current_weight_pct: float
    drift_pp: Optional[float]
    units_return_since_baseline: Optional[float]
    contributed_return_pp: Optional[float]

    class Config:
        orm_mode = True


class PortfolioAnalyticsResponse(BaseModel):
    portfolio_id: int
    as_of_date: date
    positions: List[PositionAggregateResponse]
    total_drift: float
    top_contributors: List[Dict[str, Any]]
    top_detractors: List[Dict[str, Any]]


# =============================================================================
# Module 4: Market Data
# =============================================================================

class PriceDataCreate(BaseModel):
    instrument_id: int
    price_date: date
    close_price: float
    volume: Optional[int] = None
    source: str = "manual"


class PriceDataResponse(BaseModel):
    id: int
    instrument_id: int
    price_date: date
    close_price: float
    volume: Optional[int]
    source: str

    class Config:
        orm_mode = True


# =============================================================================
# Module 5: News + Filings Ingestion
# =============================================================================

class DocumentCreate(BaseModel):
    source_id: int
    document_type: str  # news, filing, earnings_call
    title: str
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    author: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DocumentResponse(BaseModel):
    id: int
    source_id: int
    document_type: str
    title: str
    url: Optional[str]
    published_at: Optional[datetime]
    text_preview: Optional[str]
    is_processed: bool
    created_at: datetime
    linked_instruments: Optional[List[int]] = []

    class Config:
        orm_mode = True


# =============================================================================
# Module 6: Vectorization & Hybrid Retrieval
# =============================================================================

class HybridSearchRequest(BaseModel):
    query: str
    instrument_ids: Optional[List[int]] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    limit: int = 10


class SearchResultItem(BaseModel):
    document_id: int
    chunk_id: int
    chunk_text: str
    score: float
    document_title: Optional[str]
    document_url: Optional[str]
    published_at: Optional[datetime]


class HybridSearchResponse(BaseModel):
    results: List[SearchResultItem]
    total_count: int


# =============================================================================
# Module 7: Alert Engine
# =============================================================================

class AlertResponse(BaseModel):
    id: int
    portfolio_id: Optional[int]
    instrument_id: Optional[int]
    instrument_name: Optional[str]
    alert_type: str
    severity: str
    category: Optional[str]
    title: str
    summary: str
    evidence_links: Optional[List[Dict[str, Any]]]
    llm_analysis: Optional[Dict[str, Any]]
    rule_matches: Optional[Dict[str, Any]]
    status: str
    triggered_at: datetime
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class AlertApprovalRequest(BaseModel):
    action: str  # approve or reject
    notes: Optional[str] = None


class AlertListRequest(BaseModel):
    portfolio_id: Optional[int] = None
    severity: Optional[AlertSeverity] = None
    status: Optional[AlertStatus] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    limit: int = 50


# =============================================================================
# Module 8: Report Generation
# =============================================================================

class ReportGenerationRequest(BaseModel):
    portfolio_id: int
    report_type: str  # monthly, quarterly, annual_ideas, weekly_digest
    period_start: date
    period_end: date


class ReportResponse(BaseModel):
    id: int
    portfolio_id: int
    report_type: str
    report_period_start: date
    report_period_end: date
    strategy_profile_id: Optional[int]
    content_markdown: str
    validation_passed: bool
    validation_errors: Optional[Dict[str, Any]]
    created_at: datetime

    class Config:
        orm_mode = True


class ReportListRequest(BaseModel):
    portfolio_id: Optional[int] = None
    report_type: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    limit: int = 20


# =============================================================================
# Strategy Profiles
# =============================================================================

class StrategyProfileResponse(BaseModel):
    id: int
    name: str
    policy_json: Dict[str, Any]
    is_active: bool
    created_at: datetime

    class Config:
        orm_mode = True
