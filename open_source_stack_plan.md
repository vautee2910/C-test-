# Open-source and Low-cost Stack Plan

## 1. Open-source & low-cost stack (replace paid components)

### Orchestration / scheduling
- Dagster OSS is free (paid Dagster+ is hosted; self-hosting is open-source).
- For the cheapest operations, you can also skip orchestration entirely.

Low-cost options (in increasing sophistication):
1. Cron + systemd timers (cheapest, simplest)
2. Celery Beat + Celery workers (good for recurring jobs + queues)
3. Apache Airflow (self-hosted) (heavier ops)
4. Dagster OSS (self-hosted) (nice DX/observability; still free if self-hosted)

**Recommendation:** start with **Celery Beat + Redis + Postgres** (or just cron if tiny). Move to **Dagster OSS** later if you want better observability.

### News/filings and data volume
Store raw docs + index + vectorize so the agent can do quarterly/yearly reviews reliably with citations.

Low-cost open-source approach:
- PostgreSQL + pgvector for embeddings (single DB, simplest ops)
- Store raw documents (HTML/PDF/text) in S3-compatible object storage:
  - MinIO (self-hosted) or cheap cloud bucket
- Use BM25 full-text search in Postgres (tsvector) for deterministic keyword queries
- Use vector search (pgvector) for semantic retrieval
- Use a hybrid retrieval (BM25 + vector) so you don’t miss critical keywords (“going concern”, “restatement”, “trading halt”).

### Suggested open-source stack (baseline)
- Backend: Python + FastAPI
- DB: PostgreSQL (+ pgvector extension)
- Queue/scheduler: Celery + Redis + Celery Beat
- Object storage: MinIO
- Dashboard: Next.js (or Streamlit for faster v1)
- Auth: Keycloak (open-source OIDC) or simple email+MFA (v1)
- Observability: Prometheus + Grafana + Loki (optional but strong)

---

## 2. Strategy Profile JSONs (ready to use)

These are drop-in examples your coding agent can store in `strategy_profiles.*_policy_json`. They’re designed to be enforceable by code.

Notes:
- The “LLM policy” limits what the agent can say/do.
- “Human approval” is required for High on conservative, optional elsewhere.
- Trading enables price/volume triggers; conservative mostly ignores them.

### 2.1 Ultra conservative / Buy & Hold (your portfolio)
```json
{
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
        "high_keywords": [
          "redemption suspended",
          "gating",
          "liquidity",
          "valuation cut",
          "withdrawals paused"
        ]
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
    "must_include_sections": [
      "summary",
      "drift",
      "contributors",
      "key_events",
      "watchlist",
      "opportunities",
      "appendix"
    ],
    "no_trade_language": true
  },
  "risk_policy": {
    "drift_threshold_pp_for_discussion": 5.0,
    "single_name_weight_threshold_pct_for_discussion": 15.0,
    "require_rebalance_suggestions": false
  },
  "llm_policy": {
    "allowed_outputs": [
      "summaries",
      "risk_flags",
      "discussion_questions"
    ],
    "disallowed_outputs": [
      "explicit_buy_sell",
      "price_targets",
      "certainty_language"
    ],
    "must_cite_sources": true,
    "max_claims_without_citation": 0
  }
}
```

### 2.2 Aggressive long-term (more opportunity-seeking, still long horizon)
```json
{
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
    "allowed_outputs": [
      "summaries",
      "bull_bear_base",
      "watchlist_ideas"
    ],
    "disallowed_outputs": [
      "guarantees",
      "uncited_facts"
    ],
    "must_cite_sources": true,
    "max_claims_without_citation": 0
  }
}
```

### 2.3 Trading portfolio (short horizon, technical/catalyst aware)
```json
{
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
    "allowed_outputs": [
      "catalyst_summary",
      "setup_risks",
      "scenario_map"
    ],
    "disallowed_outputs": [
      "uncited_facts"
    ],
    "must_cite_sources": true,
    "max_claims_without_citation": 0
  }
}
```

### 2.4 YOLO sandbox (paper-only, self-evolving rules)
```json
{
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
    "allowed_outputs": [
      "hypotheses",
      "rules_proposals",
      "postmortems"
    ],
    "disallowed_outputs": [
      "real_money_execution"
    ],
    "must_cite_sources": true,
    "max_claims_without_citation": 0
  }
}
```

---

## 3. Keyword taxonomy per holding type (for rule-based filtering)

Use this taxonomy in your Stage A deterministic filter before the LLM. Keep it editable in DB.

### 3.1 Shared high-severity keywords (all holdings)
**Fraud/accounting**
- “restatement”, “material weakness”, “fraud”, “accounting irregularities”, “SEC investigation”, “BaFin investigation”, “FCA investigation”
- “auditor resignation”, “qualified opinion”, “adverse opinion”, “disclaimer of opinion”

**Solvency/liquidity**
- “going concern”, “insolvency”, “bankruptcy”, “restructuring”, “debt covenant”, “covenant breach”
- “liquidity crisis”, “emergency financing”, “credit line withdrawn”

**Market access**
- “trading halt”, “delisting”, “suspended”, “sanctioned”, “blacklist”

### 3.2 Reinsurers (Munich Re, Hannover Re)
**Catastrophe / reserves**
- “catastrophe loss”, “nat cat”, “hurricane”, “earthquake”, “wildfire losses”
- “reserve strengthening”, “adverse development”, “loss ratio spike”

**Capital / rating**
- “solvency ratio”, “SCR”, “rating downgrade”, “S&P downgrade”, “AM Best downgrade”

### 3.3 Pharma / healthcare (Roche, Sanofi, Euroapi)
**Clinical**
- “Phase 3 failed”, “trial halted”, “endpoint not met”, “safety signal”, “adverse events”

**Regulatory**
- “FDA warning letter”, “EMA inspection”, “GMP violations”, “recall”, “suspension”

**IP / litigation**
- “patent invalidated”, “generic entry”, “settlement”, “injunction”

**Euroapi-specific (manufacturing/API exposure)**
- “supply disruption”, “quality issue”, “plant shutdown”, “customer loss”, “contract termination”

### 3.4 Mega-cap tech / semis (Microsoft, ASML)
**Regulatory**
- “antitrust”, “competition authority”, “DOJ/EC probe”

**Security**
- “material breach”, “zero-day”, “ransomware”, “data exfiltration”

**Export controls (ASML critical)**
- “export restrictions”, “licensing requirement”, “entity list”, “sanctions expansion”

### 3.5 Cyclicals/chemicals (BASF, Lenzing)
**Demand/energy**
- “plant closure”, “force majeure”, “gas price shock”, “demand collapse”

**Guidance**
- “withdraws guidance”, “profit warning”

**Structural**
- “impairment”, “asset write-down”, “restructuring charge”

### 3.6 Broad ETFs (MSCI World, S&P 500, Nasdaq, DAX, EuroStoxx)
Mostly low alert, but watch:
- “fund closure”, “liquidation”, “index methodology change”, “tax status change”
- “tracking error”, “swap counterparty risk” (synthetic ETFs)

### 3.7 Open-ended real estate funds (HausInvest, KanAm-type)
**High severity**
- “redemption suspended”, “gating”, “withdrawals suspended”
- “valuation reduced”, “write-down”, “liquidity shortage”

**Medium**
- “cash quota”, “outflows”, “liquidity management measures”

---

## 4. Report templates with exact headings + word limits + validations

These templates are for the coding agent to enforce constraints.

### 4.1 Monthly report (Ultra conservative)
**Total max words:** 1600

**Max opportunities:** 2

**Max bullets per section:** specified

Template:
1. Executive Summary (max 180 words)
   - 3 bullets max
2. Allocation & Drift vs Baseline (max 260 words)
   - Table allowed (weights & drift)
   - 5 bullets max describing notable drifts
3. Performance (Index Units) (max 220 words)
   - Top contributors (max 5 bullets)
   - Top detractors (max 5 bullets)
4. Key Events Since Last Report (max 350 words)
   - Group by category (Regulatory / Financial / Operational / Macro)
   - 8 bullets max total
   - Every bullet must link to evidence if factual
5. Watchlist (Non-Urgent) (max 220 words)
   - 6 bullets max
6. Opportunities (Max 2) (max 260 words total)
   For each opportunity:
   - “What changed?” (1–2 sentences)
   - “Why it might matter long-term” (1–2 sentences)
   - “What to verify next” (1 sentence)
   - Must cite sources
7. Appendix: Holdings Notes (max 350 words)
   - 1 bullet per holding max

Validation rules:
- Reject report if opportunities > 2
- Reject if any currency symbol “$”, “€” appears (for management version)
- Reject if contains “buy”, “sell”, “enter”, “exit”, “target price” (conservative profile)
- Reject if any factual claim lacks a citation

### 4.2 Quarterly position review (Ultra conservative)
**Total max words:** 6000 (across all holdings)

For each holding (max 260 words each):
- Snapshot (weights, drift, YTD units return)
- What happened (90 days) (max 4 bullets)
- Thesis watchpoints (max 3 bullets)
- Outlook (Base/Bull/Bear) (3 lines max)
- Rebalance discussion prompt (only if drift threshold exceeded)

### 4.3 Annual ideas report (Conservative)
**Max words:** 2500

Sections:
- Portfolio exposures summary (max 250)
- Gaps / concentration observations (max 250)
- Research candidates (5–10) (max 1500 total; each ≤ 150 words)
- Top 1–3 to prioritize (max 350)
- Appendix: screening notes (max 200)

Validation:
- Must include “Key risk” and “What to verify” for each candidate
- Must label as “research watchlist” (not recommendation)

### 4.4 Trading weekly report (Trading profile)
**Max words:** 1600
- Market regime (max 150)
- Open positions status (max 350)
- Catalyst calendar (max 250)
- Setups (max 5, each ≤ 150)
- Risk notes (max 200)
- Evidence links required for catalysts/news

---

## 5. Complete implementation plan (open-source + low-cost)

### 5.1 Architecture (services)

**A) API backend (FastAPI)**
Responsibilities:
- auth + RBAC
- portfolios/holdings/instruments CRUD
- analytics endpoints (weights, drift, units return)
- alerts + approvals
- reports library
- mapping tasks

**B) Worker service (Celery)**
Responsibilities:
- scheduled ingestion (beat)
- event-driven jobs
- heavy compute (units recompute, look-through aggregation)
- LLM workflows (alert/report generation)

**C) Document store**
- MinIO bucket:
  - raw/news/...
  - raw/filings/...
  - text/... (extracted text)
  - chunks/... (chunked text)

**D) DB (Postgres + pgvector)**
Stores:
- structured data
- full-text indexes (tsvector)
- embeddings (vectors)

### 5.2 Scheduling (low-cost)
Use Celery Beat schedules:
- hourly: ingest_news
- daily: ingest_prices_fx, ingest_filings, recompute_positions_daily
- weekly: generate_weekly_reports (trading/yolo)
- monthly: generate_monthly_reports (conservative/aggressive), update_lookthrough
- quarterly: generate_quarterly_reviews
- annually: generate_annual_ideas

If you want zero moving parts: implement with cron calling API endpoints that enqueue Celery tasks.

### 5.3 Data volume strategy (how to “amass a lot of data” safely)

**Document lifecycle**
1. Ingest → store raw → extract text
2. Chunk text (e.g., 500–800 tokens chunks)
3. Store:
   - chunk text in object storage
   - chunk metadata in DB
   - vector embedding in pgvector

**Retrieval strategy (hybrid)**
- For alerts: prefer keyword matches first (deterministic)
- For summaries/reports: hybrid query:
  - BM25 full text results + top vector neighbors
- Always return evidence URLs and chunk references

**Retention policies**
- Raw docs: keep 24–36 months (configurable)
- Embeddings/chunks: keep same
- Allow archiving to cheaper storage if needed

### 5.4 Implementation details by module

#### Module 1: Auth + RBAC + audit
- Use Keycloak (OIDC) OR simple auth:
  - email magic link + TOTP MFA
- Middleware enforces permissions.
- Audit log events for:
  - report view/export
  - alert approve/reject
  - strategy profile changes
  - restricted field access attempts

**Acceptance**
- Management role cannot access restricted values even via API.

#### Module 2: Instrument master + mapping

**Instrument resolution priority**
- ISIN > WKN > ticker+exchange > alias fuzzy match

**Mapping tasks**
- unresolved lots appear in /admin/mappings
- analyst confirms mapping
- system writes instrument_aliases to prevent future mismatch

**Acceptance**
- Your duplicates (“ISHARES Nasdaq 100” vs “ISHSVII-Nasdaq 100”) resolve to same instrument after mapping once.

#### Module 3: Portfolio math engine (Index Units)
- Baseline snapshot creation:
  - either from imported initial_weight_pct
  - or computed from baseline market values (if allowed internally)
- Daily recompute:
  - load baseline_units
  - apply returns (price series + FX)
  - compute current weights and drift
- Store daily in position_aggregates

**Acceptance**
- Portfolio totals always sum to 100% (± tiny float error).
- No currency symbols leak in mgmt API.

#### Module 4: Market data ingestion
**Open-source/low-cost approach**
- If you don’t want paid providers initially:
  - Use free tiers where possible, but expect coverage gaps.
- Implement connector interface so you can swap providers later.

**Data checks**
- missing prices list stored and flagged (internal ops alert)

#### Module 5: News + filings ingestion + document processing

**Pipeline**
- Fetch items (hourly/daily)
- Dedup by normalized title+domain+published_time
- Store raw html/pdf to MinIO
- Extract text (pdf/text extraction)
- Chunk + embed
- Entity linking:
  - dictionary match on instrument names/tickers/ISIN
  - plus fuzzy match for common variants

**Acceptance**
- Each news_item has:
  - URL
  - stored document reference
  - linked instruments with confidence

#### Module 6: Vectorization & retrieval
- Add pgvector extension
- Table: document_chunks
- id, document_id, chunk_index, text, tsvector, embedding vector, metadata json
- Indexes:
  - GIN on tsvector
  - ivfflat/hnsw on embedding (depending on pgvector version)

**Hybrid query**
- Query BM25 by keywords + filter by instrument_id/date range
- Query vector by embedding similarity
- Merge and rerank (simple weighted scoring)

**Acceptance**
- Quarterly review can retrieve top events per holding in last 90 days with citations.

#### Module 7: Alert engine (rules + LLM)

**Stage A rules**
- Use taxonomy above per instrument type.
- Score events by:
  - keyword hit strength
  - source reliability
  - novelty (dedup)
  - recency

**Stage B LLM**
- Prompt includes:
  - strategy policy summary
  - metrics (weight, drift, units performance)
  - retrieved evidence chunks
- LLM outputs strict JSON schema.
- Validate schema; if invalid → fall back to “Medium/Low draft” or route to analyst.

**Approval workflow**
- High severity in conservative/aggressive requires approval.

**Acceptance**
- No High alert without at least the configured minimum sources.

#### Module 8: Reports
Implement report generation jobs that:
- gather metrics
- gather top evidence per period
- prompt LLM with template + constraints
- validate:
  - word counts
  - opportunity callout cap
  - banned phrases
  - citation presence

Render:
- Store markdown in DB
- Optional: convert to PDF for download

**Acceptance**
- Monthly conservative reports always have ≤2 opportunities and no “buy/sell” language.

#### Module 9: Dashboard UI
Implement pages:
- Portfolio overview
- Holdings table + drilldown
- Look-through exposures
- Alerts inbox with approvals
- Reports library
- Admin: mappings + strategy profiles

**Acceptance**
- Management sees “safe view” only (no restricted fields).

### 5.5 DevOps & deployment (low-cost)
- Docker compose for dev/staging:
  - api, worker, beat, postgres, redis, minio, frontend
- Prod options:
  - single VM with docker-compose (cheapest)
  - or k8s (more robust)

Backups:
- nightly Postgres dump
- MinIO bucket replication/backups

Observability (optional but recommended):
- Prometheus + Grafana for metrics
- Loki for logs

---

## 6. Milestones (deliverable-focused)

- **Milestone 1: Core portfolio platform (MVP)**
  - imports + mapping + baseline + daily recompute
  - dashboard: holdings/drift
  - RBAC + audit

- **Milestone 2: News ingestion + vector store + conservative alerts**
  - ingest news hourly
  - store docs + chunk + embed
  - alert engine + approval workflow

- **Milestone 3: Monthly + quarterly reports**
  - monthly conservative report with validations
  - quarterly position review pack

- **Milestone 4: Multi-strategy profiles + trading/yolo modes**
  - strategy profile editor
  - trading alert triggers
  - yolo paper-only portfolio + kill switch rules

---

## 7. Definition of done

1. No $ leaks in management UI/API.
2. Strategy profiles drive alert/report behavior.
3. Alerts are evidence-linked and schema-validated.
4. Reports obey word limits, section headings, and opportunity caps.
5. All ingested documents are searchable via hybrid retrieval and citeable.
6. Audit logs exist for all sensitive actions.
7. Self-hostable, open-source stack runs via docker-compose.
