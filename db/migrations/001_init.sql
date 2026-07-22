-- T010：温层 schema（data-model B 节）。永久保留 + 定期备份 OSS（宪法 V）。

-- 配置留痕：每笔交易/每次决策关联版本号
CREATE TABLE IF NOT EXISTS config_changes (
    config_version  BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor           TEXT NOT NULL,
    file            TEXT NOT NULL,
    diff            TEXT,
    git_sha         TEXT
);

-- 每笔交易（含 shadow）。fee/funding/gross 分离存储（宪法 V）
CREATE TABLE IF NOT EXISTS trade_ledger (
    trade_id        TEXT PRIMARY KEY,
    symbol_uid      TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    tier            TEXT NOT NULL CHECK (tier IN ('live','shadow')),
    open_ts         TIMESTAMPTZ,
    close_ts        TIMESTAMPTZ,
    side            TEXT,
    entry_px        NUMERIC,
    exit_px         NUMERIC,
    qty             NUMERIC,
    notional_usd    NUMERIC,
    gross_pnl       NUMERIC,
    fee             NUMERIC,
    funding_pnl     NUMERIC,
    net_pnl         NUMERIC,
    slippage_bps    NUMERIC,
    llm_stance      NUMERIC,
    llm_conviction  NUMERIC,
    llm_veto        BOOLEAN,
    quant_score     NUMERIC,
    config_version  BIGINT REFERENCES config_changes(config_version)
);
CREATE INDEX IF NOT EXISTS idx_ledger_attr ON trade_ledger (symbol_uid, strategy, open_ts);

-- LLM 决策全文（宪法 V：现在不存，未来不可补回）
CREATE TABLE IF NOT EXISTS llm_decisions (
    decision_id     TEXT PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol_uid      TEXT NOT NULL,
    trigger         TEXT CHECK (trigger IN ('scheduled','sentinel','event')),
    graph_run_id    TEXT,
    model_versions  JSONB,
    full_prompt     TEXT NOT NULL,
    full_output     TEXT NOT NULL,
    bull_argument   TEXT,
    bear_argument   TEXT,
    trader_verdict  JSONB,
    token_cost      NUMERIC,
    latency_ms      INT
);

-- 对账留痕：每 30s 一行
CREATE TABLE IF NOT EXISTS positions_snapshot (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol_uid  TEXT NOT NULL,
    local_qty   NUMERIC,
    exchange_qty NUMERIC,
    consistent  BOOLEAN NOT NULL
);

-- 运行事件日志
CREATE TABLE IF NOT EXISTS system_events (
    event_id    BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity    TEXT NOT NULL CHECK (severity IN ('info','warn','fatal')),
    source      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     JSONB
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON system_events (ts);
