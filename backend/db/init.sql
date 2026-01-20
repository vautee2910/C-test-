-- Enable pgvector extension for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- MODULE 1: Auth + RBAC + Audit
-- =============================================================================

-- Users table (simple auth, can integrate with Keycloak later)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255),
    full_name VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'analyst', -- analyst, management, admin
    is_active BOOLEAN DEFAULT TRUE,
    mfa_enabled BOOLEAN DEFAULT FALSE,
    mfa_secret VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Audit log for all sensitive actions
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    action VARCHAR(100) NOT NULL, -- 'report_view', 'alert_approve', 'restricted_access_attempt', etc.
    resource_type VARCHAR(50), -- 'report', 'alert', 'portfolio', etc.
    resource_id INTEGER,
    details JSONB, -- Additional context
    ip_address INET,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX idx_audit_log_created_at ON audit_log(created_at);
CREATE INDEX idx_audit_log_action ON audit_log(action);

-- =============================================================================
-- MODULE 2: Instrument Master + Mapping
-- =============================================================================

-- Instrument types: stock, etf, bond, re_fund, etc.
CREATE TABLE instruments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    instrument_type VARCHAR(50) NOT NULL, -- stock, etf, bond, re_fund, pharma, reinsurer, etc.
    isin VARCHAR(12) UNIQUE,
    wkn VARCHAR(6),
    ticker VARCHAR(20),
    exchange VARCHAR(50),
    currency VARCHAR(3),
    sector VARCHAR(100),
    region VARCHAR(100),
    metadata JSONB, -- Additional flexible fields
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_instruments_isin ON instruments(isin);
CREATE INDEX idx_instruments_wkn ON instruments(wkn);
CREATE INDEX idx_instruments_ticker ON instruments(ticker);
CREATE INDEX idx_instruments_type ON instruments(instrument_type);

-- Instrument aliases for fuzzy matching and resolving duplicates
CREATE TABLE instrument_aliases (
    id SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    alias_name VARCHAR(500) NOT NULL,
    alias_type VARCHAR(50), -- 'common_name', 'ticker_variant', 'import_name', etc.
    confidence FLOAT DEFAULT 1.0,
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_instrument_aliases_name ON instrument_aliases(alias_name);
CREATE INDEX idx_instrument_aliases_instrument ON instrument_aliases(instrument_id);

-- Unresolved mappings (for analyst review)
CREATE TABLE unresolved_mappings (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(500) NOT NULL,
    source_identifier VARCHAR(100), -- ticker, ISIN, WKN from import
    suggested_instrument_id INTEGER REFERENCES instruments(id),
    confidence_score FLOAT,
    status VARCHAR(50) DEFAULT 'pending', -- pending, resolved, rejected
    resolved_by INTEGER REFERENCES users(id),
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_unresolved_mappings_status ON unresolved_mappings(status);

-- =============================================================================
-- MODULE 3: Portfolio Math Engine (Index Units)
-- =============================================================================

-- Strategy profiles (stores the 4 JSON policies)
CREATE TABLE strategy_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    policy_json JSONB NOT NULL, -- Full policy JSON
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Portfolios
CREATE TABLE portfolios (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    owner_id INTEGER REFERENCES users(id),
    strategy_profile_id INTEGER REFERENCES strategy_profiles(id),
    currency VARCHAR(3) DEFAULT 'EUR',
    is_paper_only BOOLEAN DEFAULT FALSE, -- For YOLO profile
    baseline_date DATE, -- Date when baseline was set
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_portfolios_owner ON portfolios(owner_id);
CREATE INDEX idx_portfolios_strategy ON portfolios(strategy_profile_id);

-- Holdings (baseline weights)
CREATE TABLE holdings (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    baseline_weight_pct FLOAT NOT NULL, -- Target allocation
    baseline_units FLOAT NOT NULL, -- Index units at baseline
    baseline_date DATE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(portfolio_id, instrument_id)
);

CREATE INDEX idx_holdings_portfolio ON holdings(portfolio_id);
CREATE INDEX idx_holdings_instrument ON holdings(instrument_id);

-- Daily position aggregates (computed daily)
CREATE TABLE position_aggregates (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    as_of_date DATE NOT NULL,
    current_units FLOAT NOT NULL, -- Updated with returns
    current_weight_pct FLOAT NOT NULL,
    drift_pp FLOAT, -- Drift in percentage points vs baseline
    units_return_since_baseline FLOAT, -- Cumulative return in index units
    contributed_return_pp FLOAT, -- Contribution to portfolio return
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(portfolio_id, instrument_id, as_of_date)
);

CREATE INDEX idx_position_aggregates_portfolio_date ON position_aggregates(portfolio_id, as_of_date);
CREATE INDEX idx_position_aggregates_instrument_date ON position_aggregates(instrument_id, as_of_date);

-- =============================================================================
-- MODULE 4: Market Data Ingestion
-- =============================================================================

-- Price data (daily closes)
CREATE TABLE price_data (
    id SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    price_date DATE NOT NULL,
    close_price FLOAT NOT NULL,
    volume BIGINT,
    source VARCHAR(100), -- 'manual', 'yfinance', 'api_provider', etc.
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(instrument_id, price_date)
);

CREATE INDEX idx_price_data_instrument_date ON price_data(instrument_id, price_date);

-- FX rates (for multi-currency portfolios)
CREATE TABLE fx_rates (
    id SERIAL PRIMARY KEY,
    from_currency VARCHAR(3) NOT NULL,
    to_currency VARCHAR(3) NOT NULL,
    rate_date DATE NOT NULL,
    rate FLOAT NOT NULL,
    source VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(from_currency, to_currency, rate_date)
);

CREATE INDEX idx_fx_rates_date ON fx_rates(rate_date);

-- =============================================================================
-- MODULE 5: News + Filings Ingestion + Document Processing
-- =============================================================================

-- News and filings sources
CREATE TABLE sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source_type VARCHAR(50), -- 'news_api', 'rss', 'sec_edgar', 'manual', etc.
    reliability VARCHAR(50) DEFAULT 'medium', -- high, medium, low
    base_url TEXT,
    config JSONB, -- API keys, feed URLs, etc.
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Documents (news articles, filings, reports)
CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES sources(id),
    document_type VARCHAR(50), -- 'news', 'filing', 'earnings_call', etc.
    title TEXT NOT NULL,
    url TEXT,
    published_at TIMESTAMP,
    author VARCHAR(255),
    raw_storage_path TEXT, -- S3/MinIO path to raw HTML/PDF
    extracted_text_path TEXT, -- S3/MinIO path to extracted text
    text_preview TEXT, -- First 500 chars for display
    metadata JSONB, -- Additional fields
    dedupe_hash VARCHAR(64), -- SHA256 of normalized (title + domain + date)
    is_processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_documents_source ON documents(source_id);
CREATE INDEX idx_documents_published ON documents(published_at);
CREATE INDEX idx_documents_type ON documents(document_type);
CREATE INDEX idx_documents_dedupe ON documents(dedupe_hash);

-- Document-Instrument linking (many-to-many)
CREATE TABLE document_instruments (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    confidence FLOAT DEFAULT 1.0, -- Match confidence (fuzzy vs exact)
    match_method VARCHAR(50), -- 'isin_match', 'ticker_match', 'name_fuzzy', etc.
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(document_id, instrument_id)
);

CREATE INDEX idx_document_instruments_doc ON document_instruments(document_id);
CREATE INDEX idx_document_instruments_instrument ON document_instruments(instrument_id);

-- =============================================================================
-- MODULE 6: Vectorization & Hybrid Retrieval
-- =============================================================================

-- Document chunks (for RAG / semantic search)
CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL, -- Order within document
    chunk_text TEXT NOT NULL,
    chunk_tokens INTEGER, -- Token count
    embedding vector(1536), -- OpenAI ada-002 is 1536 dims (adjust if using different model)
    tsvector_col tsvector, -- For BM25 full-text search
    metadata JSONB, -- Additional context (page number, section, etc.)
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

-- Indexes for hybrid search
CREATE INDEX idx_document_chunks_doc ON document_chunks(document_id);
CREATE INDEX idx_document_chunks_tsvector ON document_chunks USING GIN(tsvector_col);
-- Vector index (IVFFlat or HNSW depending on pgvector version)
-- For smaller datasets, can use: CREATE INDEX idx_document_chunks_embedding ON document_chunks USING ivfflat (embedding vector_cosine_ops);
-- For larger datasets with pgvector 0.5+: CREATE INDEX idx_document_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- =============================================================================
-- MODULE 7: Alert Engine (Rules + LLM + Approval Workflow)
-- =============================================================================

-- Keyword taxonomy (rule-based filtering)
CREATE TABLE keyword_taxonomy (
    id SERIAL PRIMARY KEY,
    instrument_type VARCHAR(50), -- 'all', 'reinsurer', 'pharma', 're_fund', etc.
    category VARCHAR(100) NOT NULL, -- 'fraud_or_accounting', 'going_concern', etc.
    severity VARCHAR(20) NOT NULL, -- 'high', 'medium', 'low'
    keywords TEXT[] NOT NULL, -- Array of keywords/phrases
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_keyword_taxonomy_type ON keyword_taxonomy(instrument_type);
CREATE INDEX idx_keyword_taxonomy_severity ON keyword_taxonomy(severity);

-- Alerts
CREATE TABLE alerts (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id),
    instrument_id INTEGER REFERENCES instruments(id),
    alert_type VARCHAR(50), -- 'news', 'price_move', 'filing', 'technical', etc.
    severity VARCHAR(20) NOT NULL, -- 'high', 'medium', 'low'
    category VARCHAR(100), -- From taxonomy
    title VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL,
    evidence_links JSONB, -- Array of {document_id, chunk_ids, url, source}
    llm_analysis JSONB, -- Structured LLM output
    rule_matches JSONB, -- Keywords/rules that triggered
    status VARCHAR(50) DEFAULT 'pending', -- pending, approved, rejected, auto_approved
    approved_by INTEGER REFERENCES users(id),
    approved_at TIMESTAMP,
    triggered_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_alerts_portfolio ON alerts(portfolio_id);
CREATE INDEX idx_alerts_instrument ON alerts(instrument_id);
CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_triggered ON alerts(triggered_at);

-- =============================================================================
-- MODULE 8: Report Generation
-- =============================================================================

-- Reports
CREATE TABLE reports (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
    report_type VARCHAR(50) NOT NULL, -- 'monthly', 'quarterly', 'annual_ideas', 'weekly_digest', etc.
    report_period_start DATE NOT NULL,
    report_period_end DATE NOT NULL,
    strategy_profile_id INTEGER REFERENCES strategy_profiles(id),
    content_markdown TEXT NOT NULL,
    content_pdf_path TEXT, -- S3/MinIO path to PDF version
    metadata JSONB, -- Word counts, section stats, etc.
    validation_passed BOOLEAN DEFAULT TRUE,
    validation_errors JSONB, -- If validation failed
    generated_by VARCHAR(50) DEFAULT 'system', -- 'system', 'manual', 'user_id'
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_reports_portfolio ON reports(portfolio_id);
CREATE INDEX idx_reports_type ON reports(report_type);
CREATE INDEX idx_reports_period ON reports(report_period_end);

-- Report views (for audit)
CREATE TABLE report_views (
    id SERIAL PRIMARY KEY,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    viewed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_report_views_report ON report_views(report_id);
CREATE INDEX idx_report_views_user ON report_views(user_id);

-- =============================================================================
-- Seed Data: Insert default strategy profiles
-- =============================================================================

-- Ultra Conservative / Buy & Hold
INSERT INTO strategy_profiles (name, policy_json) VALUES (
    'UltraLongTerm_Conservative',
    '{
      "name": "UltraLongTerm_Conservative",
      "alert_policy": {
        "human_approval_required_for_high": true,
        "max_high_alerts_per_week": 2,
        "min_sources_for_high": 2,
        "reliability_required_for_high": "high",
        "ignore_if_only_price_move": true,
        "price_move_triggers": {
          "enabled": false
        },
        "high_categories": [
          "fraud_or_accounting",
          "going_concern_or_insolvency",
          "auditor_resignation",
          "delisting_or_trading_halt",
          "major_sanctions_or_expropriation",
          "material_regulatory_enforcement",
          "material_litigation",
          "catastrophe_loss_extreme",
          "liquidity_gate_or_redemption_freeze",
          "major_clinical_failure_or_safety",
          "export_controls_material"
        ],
        "medium_categories": [
          "management_turnover",
          "guidance_withdrawal",
          "credit_rating_downgrade",
          "large_mna_affecting_thesis",
          "significant_restructuring"
        ],
        "low_categories": [
          "earnings_miss",
          "macro_headlines",
          "routine_guidance_change",
          "price_volatility"
        ],
        "category_overrides_by_instrument_type": {
          "re_fund": {
            "high_keywords": ["redemption suspended", "gating", "liquidity", "valuation cut", "withdrawals paused"]
          }
        }
      },
      "report_policy": {
        "cadence": {
          "monthly": true,
          "biweekly": false,
          "quarterly": true,
          "annual": true
        },
        "max_opportunity_callouts": 2,
        "max_total_words": {
          "monthly": 1600,
          "quarterly": 6000,
          "annual": 2500
        },
        "tone": "cautious_discussion_prompts",
        "must_include_sections": ["summary", "drift", "contributors", "key_events", "watchlist", "opportunities", "appendix"],
        "no_trade_language": true
      },
      "risk_policy": {
        "drift_threshold_pp_for_discussion": 5.0,
        "single_name_weight_threshold_pct_for_discussion": 15.0,
        "require_rebalance_suggestions": false
      },
      "llm_policy": {
        "allowed_outputs": ["summaries", "risk_flags", "discussion_questions"],
        "disallowed_outputs": ["explicit_buy_sell", "price_targets", "certainty_language"],
        "must_cite_sources": true,
        "max_claims_without_citation": 0
      }
    }'::jsonb
);

-- Aggressive Long-term
INSERT INTO strategy_profiles (name, policy_json) VALUES (
    'AggressiveLongTerm',
    '{
      "name": "AggressiveLongTerm",
      "alert_policy": {
        "human_approval_required_for_high": true,
        "max_high_alerts_per_week": 4,
        "min_sources_for_high": 1,
        "reliability_required_for_high": "medium",
        "ignore_if_only_price_move": true,
        "price_move_triggers": {
          "enabled": true,
          "threshold_pct_1d": 8,
          "requires_news_confirmation": true
        },
        "high_categories": [
          "fraud_or_accounting",
          "going_concern_or_insolvency",
          "delisting_or_trading_halt",
          "major_sanctions_or_expropriation",
          "material_regulatory_enforcement",
          "major_product_failure",
          "export_controls_material"
        ],
        "medium_categories": [
          "earnings_surprise_large",
          "guidance_withdrawal",
          "management_turnover",
          "large_mna_affecting_thesis",
          "industry_disruption_signal"
        ],
        "low_categories": [
          "routine_macro",
          "minor_earnings_miss"
        ]
      },
      "report_policy": {
        "cadence": {
          "monthly": true,
          "biweekly": true,
          "quarterly": true,
          "annual": true
        },
        "max_opportunity_callouts": 3,
        "max_total_words": {
          "biweekly": 1200,
          "monthly": 1800,
          "quarterly": 7000,
          "annual": 3000
        },
        "tone": "balanced_opportunity_with_risks",
        "no_trade_language": true
      },
      "risk_policy": {
        "drift_threshold_pp_for_discussion": 7.0,
        "single_name_weight_threshold_pct_for_discussion": 20.0,
        "require_rebalance_suggestions": true,
        "rebalance_style": "soft_suggestions"
      },
      "llm_policy": {
        "allowed_outputs": ["summaries", "bull_bear_base", "watchlist_ideas"],
        "disallowed_outputs": ["guarantees", "uncited_facts"],
        "must_cite_sources": true,
        "max_claims_without_citation": 0
      }
    }'::jsonb
);

-- Trading / Catalyst
INSERT INTO strategy_profiles (name, policy_json) VALUES (
    'Trading_Catalyst',
    '{
      "name": "Trading_Catalyst",
      "alert_policy": {
        "human_approval_required_for_high": false,
        "max_high_alerts_per_day": 5,
        "min_sources_for_high": 1,
        "reliability_required_for_high": "medium",
        "ignore_if_only_price_move": false,
        "price_move_triggers": {
          "enabled": true,
          "threshold_pct_intraday": 4,
          "threshold_pct_1d": 6,
          "volume_spike_multiple": 2.0
        },
        "high_categories": [
          "trading_halt",
          "unexpected_guidance_change",
          "earnings_surprise_large",
          "major_regulatory_action",
          "downgrade_or_upgrade_cluster",
          "merger_or_takeover",
          "material_litigation"
        ],
        "medium_categories": [
          "sector_rotation_signal",
          "macro_release_high_impact",
          "technical_breakout_or_breakdown"
        ],
        "low_categories": [
          "routine_news"
        ]
      },
      "report_policy": {
        "cadence": {
          "daily_digest": true,
          "weekly": true,
          "monthly": false,
          "quarterly": false,
          "annual": false
        },
        "max_opportunity_callouts": 5,
        "max_total_words": {
          "daily_digest": 900,
          "weekly": 1600
        },
        "tone": "actionable_but_risk_noted",
        "no_trade_language": false
      },
      "risk_policy": {
        "max_position_pct": 10.0,
        "max_daily_loss_pct_portfolio": 2.0,
        "require_stop_discussion": true
      },
      "llm_policy": {
        "allowed_outputs": ["catalyst_summary", "setup_risks", "scenario_map"],
        "disallowed_outputs": ["uncited_facts"],
        "must_cite_sources": true,
        "max_claims_without_citation": 0
      }
    }'::jsonb
);

-- YOLO Experimental (Paper Only)
INSERT INTO strategy_profiles (name, policy_json) VALUES (
    'YOLO_Experimental_PaperOnly',
    '{
      "name": "YOLO_Experimental_PaperOnly",
      "alert_policy": {
        "human_approval_required_for_high": false,
        "max_high_alerts_per_day": 10,
        "min_sources_for_high": 1,
        "reliability_required_for_high": "low",
        "ignore_if_only_price_move": false,
        "price_move_triggers": {
          "enabled": true,
          "threshold_pct_intraday": 8,
          "threshold_pct_1d": 12,
          "volume_spike_multiple": 3.0
        },
        "high_categories": [
          "parabolic_move",
          "breakout_high_volume",
          "social_attention_spike",
          "news_catalyst_any"
        ],
        "medium_categories": [
          "momentum_shift",
          "volatility_regime_change"
        ],
        "low_categories": [
          "routine_news"
        ]
      },
      "report_policy": {
        "cadence": {
          "weekly": true,
          "monthly": true
        },
        "max_opportunity_callouts": 10,
        "max_total_words": {
          "weekly": 2200,
          "monthly": 2600
        },
        "tone": "experimental_transparent_uncertainty",
        "no_trade_language": false
      },
      "risk_policy": {
        "paper_only": true,
        "kill_switch": {
          "max_drawdown_pct": 25.0,
          "max_weekly_loss_pct": 10.0
        },
        "max_position_pct": 25.0
      },
      "llm_policy": {
        "allowed_outputs": ["hypotheses", "rules_proposals", "postmortems"],
        "disallowed_outputs": ["real_money_execution"],
        "must_cite_sources": true,
        "max_claims_without_citation": 0
      }
    }'::jsonb
);

-- =============================================================================
-- Seed Data: Insert keyword taxonomy
-- =============================================================================

-- Shared high-severity keywords (all holdings)
INSERT INTO keyword_taxonomy (instrument_type, category, severity, keywords, description) VALUES
('all', 'fraud_or_accounting', 'high', ARRAY['restatement', 'material weakness', 'fraud', 'accounting irregularities', 'SEC investigation', 'BaFin investigation', 'FCA investigation', 'auditor resignation', 'qualified opinion', 'adverse opinion', 'disclaimer of opinion'], 'Fraud and accounting red flags'),
('all', 'going_concern_or_insolvency', 'high', ARRAY['going concern', 'insolvency', 'bankruptcy', 'restructuring', 'debt covenant', 'covenant breach', 'liquidity crisis', 'emergency financing', 'credit line withdrawn'], 'Solvency and liquidity issues'),
('all', 'delisting_or_trading_halt', 'high', ARRAY['trading halt', 'delisting', 'suspended', 'sanctioned', 'blacklist'], 'Market access issues');

-- Reinsurers (Munich Re, Hannover Re)
INSERT INTO keyword_taxonomy (instrument_type, category, severity, keywords, description) VALUES
('reinsurer', 'catastrophe_loss_extreme', 'high', ARRAY['catastrophe loss', 'nat cat', 'hurricane', 'earthquake', 'wildfire losses', 'reserve strengthening', 'adverse development', 'loss ratio spike'], 'Catastrophe losses and reserve issues'),
('reinsurer', 'credit_rating_downgrade', 'medium', ARRAY['solvency ratio', 'SCR', 'rating downgrade', 'S&P downgrade', 'AM Best downgrade'], 'Capital and rating concerns');

-- Pharma / Healthcare (Roche, Sanofi, Euroapi)
INSERT INTO keyword_taxonomy (instrument_type, category, severity, keywords, description) VALUES
('pharma', 'major_clinical_failure_or_safety', 'high', ARRAY['Phase 3 failed', 'trial halted', 'endpoint not met', 'safety signal', 'adverse events'], 'Clinical trial failures'),
('pharma', 'material_regulatory_enforcement', 'high', ARRAY['FDA warning letter', 'EMA inspection', 'GMP violations', 'recall', 'suspension'], 'Regulatory enforcement'),
('pharma', 'material_litigation', 'high', ARRAY['patent invalidated', 'generic entry', 'settlement', 'injunction'], 'IP and litigation issues'),
('pharma', 'supply_disruption', 'medium', ARRAY['supply disruption', 'quality issue', 'plant shutdown', 'customer loss', 'contract termination'], 'Manufacturing and supply issues (Euroapi-specific)');

-- Mega-cap tech / semis (Microsoft, ASML)
INSERT INTO keyword_taxonomy (instrument_type, category, severity, keywords, description) VALUES
('tech', 'material_regulatory_enforcement', 'high', ARRAY['antitrust', 'competition authority', 'DOJ probe', 'EC probe'], 'Antitrust and regulatory'),
('tech', 'security_breach', 'medium', ARRAY['material breach', 'zero-day', 'ransomware', 'data exfiltration'], 'Security incidents'),
('semiconductor', 'export_controls_material', 'high', ARRAY['export restrictions', 'licensing requirement', 'entity list', 'sanctions expansion'], 'Export controls (ASML critical)');

-- Cyclicals/Chemicals (BASF, Lenzing)
INSERT INTO keyword_taxonomy (instrument_type, category, severity, keywords, description) VALUES
('chemical', 'guidance_withdrawal', 'medium', ARRAY['plant closure', 'force majeure', 'gas price shock', 'demand collapse', 'withdraws guidance', 'profit warning'], 'Demand and guidance issues'),
('chemical', 'significant_restructuring', 'medium', ARRAY['impairment', 'asset write-down', 'restructuring charge'], 'Structural changes');

-- Broad ETFs
INSERT INTO keyword_taxonomy (instrument_type, category, severity, keywords, description) VALUES
('etf', 'fund_structure_risk', 'medium', ARRAY['fund closure', 'liquidation', 'index methodology change', 'tax status change', 'tracking error', 'swap counterparty risk'], 'ETF structural risks');

-- Open-ended real estate funds
INSERT INTO keyword_taxonomy (instrument_type, category, severity, keywords, description) VALUES
('re_fund', 'liquidity_gate_or_redemption_freeze', 'high', ARRAY['redemption suspended', 'gating', 'withdrawals suspended', 'valuation reduced', 'write-down', 'liquidity shortage'], 'Real estate fund liquidity crisis'),
('re_fund', 'cash_quota_management', 'medium', ARRAY['cash quota', 'outflows', 'liquidity management measures'], 'Liquidity management measures');

-- =============================================================================
-- Functions and Triggers
-- =============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at trigger to relevant tables
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_instruments_updated_at BEFORE UPDATE ON instruments FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_portfolios_updated_at BEFORE UPDATE ON portfolios FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_holdings_updated_at BEFORE UPDATE ON holdings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_strategy_profiles_updated_at BEFORE UPDATE ON strategy_profiles FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_keyword_taxonomy_updated_at BEFORE UPDATE ON keyword_taxonomy FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
