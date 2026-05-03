"""
ATLAS Database Schema
PostgreSQL tables for all system data.
"""

DB_SCHEMA = """
-- Market price data (1m candles)
CREATE TABLE IF NOT EXISTS market_data (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(20)   NOT NULL,
    timeframe   VARCHAR(5)    NOT NULL,  -- '1m', '15m', '1d'
    open        NUMERIC(18,8) NOT NULL,
    high        NUMERIC(18,8) NOT NULL,
    low         NUMERIC(18,8) NOT NULL,
    close       NUMERIC(18,8) NOT NULL,
    volume      NUMERIC(18,8) NOT NULL,
    timestamp   TIMESTAMPTZ   NOT NULL,
    UNIQUE (symbol, timeframe, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_market_data_sym_ts ON market_data (symbol, timeframe, timestamp DESC);

-- Computed technical indicators
CREATE TABLE IF NOT EXISTS indicators (
    id          BIGSERIAL PRIMARY KEY,
    symbol      VARCHAR(20)   NOT NULL,
    timeframe   VARCHAR(5)    NOT NULL,
    rsi         NUMERIC(8,4),
    macd        NUMERIC(12,6),
    macd_signal NUMERIC(12,6),
    macd_hist   NUMERIC(12,6),
    ema9        NUMERIC(18,8),
    ema21       NUMERIC(18,8),
    ema50       NUMERIC(18,8),
    atr         NUMERIC(18,8),
    vwap        NUMERIC(18,8),
    bb_upper    NUMERIC(18,8),
    bb_lower    NUMERIC(18,8),
    rvol        NUMERIC(8,4),   -- relative volume vs 20-day avg
    timestamp   TIMESTAMPTZ   NOT NULL,
    UNIQUE (symbol, timeframe, timestamp)
);

-- Raw news articles
CREATE TABLE IF NOT EXISTS news_raw (
    id          BIGSERIAL PRIMARY KEY,
    source      VARCHAR(50)   NOT NULL,  -- 'reddit', 'yahoo', 'rss'
    url         TEXT          UNIQUE,
    headline    TEXT          NOT NULL,
    body_text   TEXT,
    symbol      VARCHAR(20),             -- NULL = general market
    scraped_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_news_raw_sym ON news_raw (symbol, scraped_at DESC);

-- LLM-processed sentiment
CREATE TABLE IF NOT EXISTS news_sentiment (
    id              BIGSERIAL PRIMARY KEY,
    news_raw_id     BIGINT REFERENCES news_raw(id),
    sentiment_score NUMERIC(4,3) NOT NULL,  -- -1.0 to +1.0
    summary         TEXT,
    bullish_flag    BOOLEAN,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Market regime classifications
CREATE TABLE IF NOT EXISTS market_regime (
    id           BIGSERIAL PRIMARY KEY,
    regime_type  VARCHAR(20) NOT NULL,  -- 'bull','bear','chop','volatile','crisis'
    active_policy VARCHAR(10) NOT NULL, -- 'A','B','C'
    regime_score NUMERIC(6,4),
    vix_proxy    NUMERIC(8,4),
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Trade signals from Meta-Controller
CREATE TABLE IF NOT EXISTS trade_signals (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(20)   NOT NULL,
    direction       VARCHAR(5)    NOT NULL,  -- 'LONG','SHORT'
    entry_price     NUMERIC(18,8) NOT NULL,
    target_1        NUMERIC(18,8),
    target_2        NUMERIC(18,8),
    stop_loss       NUMERIC(18,8) NOT NULL,
    confidence      NUMERIC(5,3)  NOT NULL,
    strategy_dna    VARCHAR(50),             -- 'momentum','mean_rev','sentiment'
    rl_vote         NUMERIC(5,3),            -- PPO policy confidence
    analyst_score   NUMERIC(5,3),
    tech_score      NUMERIC(5,3),
    risk_score      NUMERIC(5,3),
    contrarian_pen  NUMERIC(5,3),
    regime_at_signal VARCHAR(20),
    active_policy   VARCHAR(10),
    reasoning       TEXT,
    status          VARCHAR(20) DEFAULT 'PENDING',  -- PENDING/EXECUTED/SKIPPED
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Actual executed trades
CREATE TABLE IF NOT EXISTS trades (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT REFERENCES trade_signals(id),
    symbol          VARCHAR(20)   NOT NULL,
    direction       VARCHAR(5)    NOT NULL,
    entry_price     NUMERIC(18,8),
    exit_price      NUMERIC(18,8),
    quantity        NUMERIC(18,8) NOT NULL,
    pnl_usd         NUMERIC(18,4),
    pnl_pct         NUMERIC(8,4),
    entry_at        TIMESTAMPTZ,
    exit_at         TIMESTAMPTZ,
    exit_reason     VARCHAR(50),  -- 'target1','target2','stop','trailing','time','manual','sentiment'
    status          VARCHAR(20) DEFAULT 'OPEN'  -- OPEN/CLOSED/CANCELLED
);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status, entry_at DESC);

-- Agent reasoning logs (per trade signal)
CREATE TABLE IF NOT EXISTS agent_logs (
    id              BIGSERIAL PRIMARY KEY,
    signal_id       BIGINT REFERENCES trade_signals(id),
    agent_name      VARCHAR(30)  NOT NULL,  -- 'analyst','technician','risk','contrarian','judge','rl_policy'
    input_summary   TEXT,
    output_json     JSONB,
    vote            VARCHAR(10),            -- 'BUY','SKIP','CAUTION'
    score           NUMERIC(5,3),
    reasoning       TEXT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Portfolio state snapshots
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    total_capital   NUMERIC(18,4) NOT NULL,
    deployed_usd    NUMERIC(18,4) NOT NULL,
    daily_pnl_usd   NUMERIC(18,4) NOT NULL,
    daily_pnl_pct   NUMERIC(8,4)  NOT NULL,
    open_positions  INT           NOT NULL,
    circuit_active  BOOLEAN       DEFAULT FALSE,
    snapshot_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Daily post-mortem reports (HERMES)
CREATE TABLE IF NOT EXISTS daily_reports (
    id              BIGSERIAL PRIMARY KEY,
    report_date     DATE          NOT NULL UNIQUE,
    total_trades    INT,
    wins            INT,
    losses          INT,
    total_pnl_usd   NUMERIC(18,4),
    win_rate        NUMERIC(5,3),
    best_strategy   VARCHAR(50),
    llm_analysis    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

if __name__ == "__main__":
    import asyncio
    import asyncpg
    from dotenv import load_dotenv
    import os
    import re

    load_dotenv()

    async def create_schema():
        db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(db_url)
        # Split and run each statement
        for stmt in DB_SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(stmt)
        await conn.close()
        print("[DB] Schema created successfully.")

    asyncio.run(create_schema())
