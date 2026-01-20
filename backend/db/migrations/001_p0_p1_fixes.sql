-- Migration 001: P0 and P1 Critical Fixes
-- Adds: corporate actions, portfolio events, instrument taxonomy fix, chunk offsets

-- =============================================================================
-- P0.2: Enhanced Index Units Math - Corporate Actions
-- =============================================================================

CREATE TABLE IF NOT EXISTS corporate_actions (
    id SERIAL PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    action_type VARCHAR(50) NOT NULL, -- 'split', 'dividend', 'symbol_change', 'merger', 'spinoff'
    action_date DATE NOT NULL,
    ratio FLOAT, -- For splits: 2.0 for 2-for-1 split
    amount FLOAT, -- For dividends: amount per share
    new_instrument_id INTEGER REFERENCES instruments(id), -- For symbol changes/mergers
    description TEXT,
    is_processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_corporate_actions_instrument ON corporate_actions(instrument_id);
CREATE INDEX idx_corporate_actions_date ON corporate_actions(action_date);
CREATE INDEX idx_corporate_actions_processed ON corporate_actions(is_processed);

-- =============================================================================
-- P0.2: Enhanced Index Units Math - Portfolio Events
-- =============================================================================

CREATE TABLE IF NOT EXISTS portfolio_events (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL, -- 'baseline_reset', 'deposit', 'withdrawal', 'rebalance', 'holding_add', 'holding_remove'
    event_date DATE NOT NULL,
    instrument_id INTEGER REFERENCES instruments(id), -- If event relates to specific holding
    amount FLOAT, -- For deposits/withdrawals (in portfolio currency)
    details JSONB, -- Flexible event-specific data
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_portfolio_events_portfolio ON portfolio_events(portfolio_id);
CREATE INDEX idx_portfolio_events_date ON portfolio_events(event_date);
CREATE INDEX idx_portfolio_events_type ON portfolio_events(event_type);

-- =============================================================================
-- P0.4: Fix Instrument Taxonomy (Separate asset_type from industry_tag)
-- =============================================================================

-- Add new columns for proper taxonomy
ALTER TABLE instruments
ADD COLUMN IF NOT EXISTS asset_type VARCHAR(50), -- 'stock', 'etf', 'bond', 'fund', 're_fund', 'crypto'
ADD COLUMN IF NOT EXISTS industry_tag VARCHAR(50); -- 'reinsurer', 'pharma', 'tech', 'semiconductor', 'chemical', etc.

-- Migrate existing instrument_type to asset_type (best effort)
-- This is a data migration that needs manual review
UPDATE instruments SET asset_type = 'stock' WHERE instrument_type IN ('reinsurer', 'pharma', 'tech', 'semiconductor', 'chemical');
UPDATE instruments SET asset_type = 'etf' WHERE instrument_type = 'etf';
UPDATE instruments SET asset_type = 'fund' WHERE instrument_type IN ('fund', 're_fund');

-- Migrate industry tags
UPDATE instruments SET industry_tag = 'reinsurer' WHERE instrument_type = 'reinsurer';
UPDATE instruments SET industry_tag = 'pharma' WHERE instrument_type IN ('pharma', 'healthcare');
UPDATE instruments SET industry_tag = 'tech' WHERE instrument_type = 'tech';
UPDATE instruments SET industry_tag = 'semiconductor' WHERE instrument_type = 'semiconductor';
UPDATE instruments SET industry_tag = 'chemical' WHERE instrument_type IN ('chemical', 'chemicals');
UPDATE instruments SET industry_tag = 'etf' WHERE instrument_type = 'etf';
UPDATE instruments SET industry_tag = 're_fund' WHERE instrument_type = 're_fund';

-- Create index on new taxonomy columns
CREATE INDEX IF NOT EXISTS idx_instruments_asset_type ON instruments(asset_type);
CREATE INDEX IF NOT EXISTS idx_instruments_industry_tag ON instruments(industry_tag);

-- Update keyword_taxonomy to use industry_tag
-- Note: This is compatible - instrument_type column in keyword_taxonomy can map to either
-- Just document that it should match industry_tag going forward
COMMENT ON COLUMN keyword_taxonomy.instrument_type IS 'Maps to instruments.industry_tag (or "all" for universal rules)';

-- =============================================================================
-- P1.9: Add char_start/char_end to document_chunks for precise citations
-- =============================================================================

ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS char_start INTEGER, -- Character offset in original document
ADD COLUMN IF NOT EXISTS char_end INTEGER,   -- End character offset
ADD COLUMN IF NOT EXISTS source_page INTEGER; -- For PDF documents (page number)

CREATE INDEX IF NOT EXISTS idx_document_chunks_char_range ON document_chunks(document_id, char_start, char_end);

-- =============================================================================
-- P2: Data Retention - Add retention metadata
-- =============================================================================

ALTER TABLE documents
ADD COLUMN IF NOT EXISTS retention_until DATE, -- Auto-calculated based on policy
ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_documents_retention ON documents(retention_until) WHERE is_archived = FALSE;

-- =============================================================================
-- Functions and Triggers for new tables
-- =============================================================================

-- Update trigger for corporate_actions
CREATE TRIGGER update_corporate_actions_updated_at
BEFORE UPDATE ON corporate_actions
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Seed Data Updates
-- =============================================================================

-- Update existing instruments to have proper asset_type and industry_tag defaults
UPDATE instruments SET asset_type = 'stock' WHERE asset_type IS NULL AND instrument_type NOT IN ('etf', 'fund', 're_fund');
UPDATE instruments SET asset_type = 'etf' WHERE asset_type IS NULL AND instrument_type = 'etf';

-- Add source reliability data (for alert hard gates)
ALTER TABLE sources
ADD COLUMN IF NOT EXISTS reliability_score FLOAT DEFAULT 0.5, -- 0.0 to 1.0
ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_sources_reliability ON sources(reliability_score) WHERE is_active = TRUE;

COMMENT ON COLUMN sources.reliability_score IS 'Source reliability: 0.0-0.3=low, 0.4-0.7=medium, 0.8-1.0=high';
COMMENT ON COLUMN sources.is_verified IS 'Whether source has been manually verified by admin';

-- =============================================================================
-- Alert Hard Gates - Add tracking columns
-- =============================================================================

ALTER TABLE alerts
ADD COLUMN IF NOT EXISTS source_count INTEGER DEFAULT 1, -- Number of independent sources
ADD COLUMN IF NOT EXISTS min_source_reliability FLOAT; -- Lowest reliability score among sources

CREATE INDEX IF NOT EXISTS idx_alerts_source_metrics ON alerts(source_count, min_source_reliability);

-- =============================================================================
-- Performance Optimizations
-- =============================================================================

-- Add composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_position_aggregates_portfolio_instrument
ON position_aggregates(portfolio_id, instrument_id, as_of_date DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_portfolio_severity_status
ON alerts(portfolio_id, severity, status, triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_documents_published_type
ON documents(published_at DESC, document_type) WHERE is_processed = TRUE;

-- =============================================================================
-- Notes for manual actions required:
-- =============================================================================

-- TODO: Review and correct asset_type and industry_tag for all instruments
-- TODO: Set reliability_score for all active sources
-- TODO: Backfill char_start/char_end for existing chunks (if needed)
-- TODO: Set retention_until dates based on document_type and published_at
