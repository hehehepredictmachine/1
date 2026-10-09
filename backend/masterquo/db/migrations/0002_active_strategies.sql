-- MasterQUO AI 1.2: ACTIVE setups of S01-S10, AUTO strategy selection log.
CREATE TABLE IF NOT EXISTS strategy_setups (
    setup_id TEXT PRIMARY KEY,
    account_key TEXT,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    direction TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    structure_key TEXT NOT NULL,
    event_id TEXT NOT NULL,
    stage TEXT NOT NULL,                 -- WATCH / EARLY / CONFIRMED (last published)
    status TEXT NOT NULL,                -- ACTIVE / INVALIDATED / EXPIRED / MISSED_ENTRY / CANCELLED / ENTERED
    version INTEGER NOT NULL,
    score REAL,
    first_seen_at TEXT NOT NULL,
    first_price REAL,
    updated_at TEXT NOT NULL,
    stage_changed_at TEXT NOT NULL,
    data_updates INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    terminal_reason TEXT,
    terminal_at TEXT,
    stale INTEGER NOT NULL DEFAULT 0,
    synthetic INTEGER NOT NULL DEFAULT 0,
    record_json TEXT NOT NULL,
    history_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_strategy_setups_status ON strategy_setups(status, symbol);
CREATE INDEX IF NOT EXISTS ix_strategy_setups_seen ON strategy_setups(first_seen_at);

CREATE TABLE IF NOT EXISTS strategy_selection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    account_key TEXT,
    strategy_mode TEXT NOT NULL,
    previous_strategy TEXT,
    previous_setup TEXT,
    selected_strategy TEXT,
    selected_setup TEXT,
    snapshot_id TEXT,
    reason TEXT NOT NULL,
    ranking_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_selection_log_at ON strategy_selection_log(at);
