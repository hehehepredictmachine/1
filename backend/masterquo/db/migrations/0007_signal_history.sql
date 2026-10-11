-- MasterQUO AI 1.7: history of the Signal contract (engine/signal_contract.py) - one row per signal_id, status updates in place.
CREATE TABLE IF NOT EXISTS signal_history (
    signal_id TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    setup_id TEXT NOT NULL,
    strategy_id TEXT,
    entry_tf TEXT,
    side TEXT,
    status TEXT NOT NULL,
    execution_state TEXT NOT NULL,
    decision_source TEXT NOT NULL,
    ai_verdict TEXT,
    synthetic INTEGER NOT NULL DEFAULT 0,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_signal_history_updated ON signal_history(updated_at);
CREATE INDEX IF NOT EXISTS ix_signal_history_strategy ON signal_history(strategy_id, status);
-- AI qualification is recorded on the bot's tracked signals so its value can be measured against the strategy alone
ALTER TABLE ai_signals ADD COLUMN ai_verdict TEXT;
