-- PMW-SH-1: SCALPING / HEDGING signals, frozen trade plans with their state machines, idempotent actions and position ownership
-- (additive; legacy tables untouched).
CREATE TABLE IF NOT EXISTS sh_signals (
    signal_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    instrument TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT,
    status TEXT NOT NULL,
    status_reason TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    valid_until REAL,
    config_hash TEXT,
    payload TEXT NOT NULL,
    risk TEXT,
    coordination TEXT
);
CREATE INDEX IF NOT EXISTS ix_sh_signals_t ON sh_signals(instrument, strategy, created_at);
CREATE TABLE IF NOT EXISTS sh_plans (
    plan_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    instrument TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    exec_mode TEXT NOT NULL,
    account_key TEXT,
    state TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    plan TEXT NOT NULL,
    fsm TEXT,
    primary_ticket INTEGER,
    hedge_ticket INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    closed_at REAL,
    result TEXT
);
CREATE INDEX IF NOT EXISTS ix_sh_plans_state ON sh_plans(state, symbol);
CREATE TABLE IF NOT EXISTS sh_actions (
    action_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    request TEXT,
    result TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sh_actions_plan ON sh_actions(plan_id);
CREATE TABLE IF NOT EXISTS sh_owners (
    account_key TEXT NOT NULL,
    position_ticket INTEGER NOT NULL,
    plan_id TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (account_key, position_ticket)
);
CREATE TABLE IF NOT EXISTS sh_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT,
    t REAL NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sh_events_plan ON sh_events(plan_id, t);
