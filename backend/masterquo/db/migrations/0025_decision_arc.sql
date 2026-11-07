-- 1.33 decision architecture (PMW-ARC-1): decision records of BOTH paths, execution intents (dedup + reconciliation) and the shared
-- atomic risk reservation. Additive only: 1.32 never reads these tables (rollback = old binary ignores them).
CREATE TABLE IF NOT EXISTS decision_records (
    record_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    path TEXT NOT NULL,                 -- ACTIVE / SH
    source_id TEXT NOT NULL,            -- engine decision_id / SH signal_id
    strategy_id TEXT,
    symbol TEXT,
    account_key TEXT,
    mode TEXT,
    direction TEXT,
    base_verdict TEXT NOT NULL,         -- verdict of the strategy before the coordinator (ENTER / WAIT / NO_TRADE)
    final_verdict TEXT NOT NULL,        -- ENTER / WAIT / NO_TRADE / BLOCKED
    reason_codes TEXT NOT NULL,         -- JSON list
    models_json TEXT,                   -- ModelForecast list with role and influence
    inputs_hash TEXT NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE(path, source_id, inputs_hash)
);
CREATE INDEX IF NOT EXISTS ix_decision_records_created ON decision_records(created_at);
CREATE INDEX IF NOT EXISTS ix_decision_records_source ON decision_records(path, source_id);

CREATE TABLE IF NOT EXISTS execution_intents (
    intent_id TEXT PRIMARY KEY,
    dedup_key TEXT NOT NULL UNIQUE,     -- path:mode:account:setup/plan - one entry intent per decision subject
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- ENTRY
    record_id TEXT,
    source_ref TEXT,                    -- order_attempts.attempt_id / sh_actions.action_id
    mode TEXT NOT NULL,
    account_key TEXT,
    symbol TEXT,
    side TEXT,
    volume REAL,
    risk_money REAL,
    state TEXT NOT NULL,                -- NEW / RESERVED / SENT / FILLED / PARTIAL / REJECTED / BLOCKED / UNKNOWN / RECONCILED_FILLED / RECONCILED_NOT_FOUND
    reservation_id TEXT,
    outcome_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_execution_intents_state ON execution_intents(state);

CREATE TABLE IF NOT EXISTS risk_reservations (
    reservation_id TEXT PRIMARY KEY,
    reservation_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_ts REAL NOT NULL,
    updated_at TEXT NOT NULL,
    path TEXT NOT NULL,
    subject TEXT NOT NULL,              -- SH plan_id / ACTIVE order attempt_id: once the subject is visible as an open position it is not counted twice
    mode TEXT NOT NULL,
    account_key TEXT,
    risk_money REAL,
    positions INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL,                -- HELD / UNKNOWN / CONSUMED / RELEASED / EXPIRED
    note TEXT
);
CREATE INDEX IF NOT EXISTS ix_risk_reservations_state ON risk_reservations(state);
CREATE UNIQUE INDEX IF NOT EXISTS ux_risk_reservations_live ON risk_reservations(reservation_key) WHERE state IN ('HELD','UNKNOWN');
