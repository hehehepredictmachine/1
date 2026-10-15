-- 1.12: SHADOW decisions of the scalp profile (M5 Range -> M1 Sweep/Reclaim -> Retest), recorded BEFORE the outcome.
CREATE TABLE IF NOT EXISTS scalp_shadow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    setup_id TEXT NOT NULL UNIQUE,
    profile_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    decision_time_utc TEXT NOT NULL,
    status TEXT NOT NULL,
    reasons TEXT,
    plan TEXT NOT NULL,
    gates TEXT,
    hedge TEXT,
    outcome_status TEXT NOT NULL DEFAULT 'PENDING',
    outcome TEXT,
    net_r REAL,
    settled_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_scalp_shadow_open ON scalp_shadow(outcome_status, decision_time_utc);
