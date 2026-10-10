-- MasterQUO AI 1.5: AI signals for any symbol of the terminal (proposals of Claude, validated and tracked; never executed).
-- (number 0004 is skipped on purpose: it was used by the withdrawn 1.4 build)
CREATE TABLE IF NOT EXISTS ai_signals (
    signal_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trigger TEXT NOT NULL,                      -- USER / AUTO_SCANNER
    run_id TEXT,
    model_id TEXT,
    prompt_version TEXT,
    status TEXT NOT NULL,                       -- PENDING_ENTRY / OPEN / WIN / LOSS / BREAKEVEN / EXPIRED / TIMEOUT / NO_TRADE / REJECTED / FAILED
    action TEXT,                                -- BUY / SELL / NO_TRADE
    entry_type TEXT,                            -- MARKET / LIMIT
    entry_price REAL,
    stop_loss REAL,
    take_profits_json TEXT,
    rr1 REAL,
    confidence INTEGER,
    horizon TEXT,
    valid_until TEXT,
    price_at_signal REAL,
    validation_json TEXT,
    record_json TEXT,
    filled_at TEXT,
    fill_price REAL,
    closed_at TEXT,
    exit_price REAL,
    outcome_r REAL,
    tp_hit INTEGER,
    account_key TEXT,
    synthetic INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    est_cost_usd REAL
);
CREATE INDEX IF NOT EXISTS ix_ai_signals_symbol ON ai_signals(symbol, created_at);
CREATE INDEX IF NOT EXISTS ix_ai_signals_status ON ai_signals(status);
