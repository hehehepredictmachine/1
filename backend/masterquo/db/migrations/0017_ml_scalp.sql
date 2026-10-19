-- PMW-UPD-03 SCALP_NET_PROFIT_MARKET_V1: every scalp candidate BEFORE any model filter (one row per setup x side), its full
-- cycle label written later (never overwriting the prediction), predictions with model hash / TTL, and the shared evaluation
-- ledger of used holdout periods (all tasks / sessions).
CREATE TABLE IF NOT EXISTS ml_scalp_samples (
    sample_id TEXT PRIMARY KEY,
    instrument TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    setup_id TEXT NOT NULL,
    range_id TEXT,
    side TEXT NOT NULL,
    signal_time TEXT NOT NULL,
    decision_time TEXT NOT NULL,
    session_epoch TEXT,
    feature_schema TEXT NOT NULL,
    features TEXT NOT NULL,
    plan TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    costs TEXT,
    status TEXT NOT NULL,
    net_r REAL,
    y INTEGER,
    label_end TEXT,
    label_available_at TEXT,
    precision TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ml_scalp_samples_status ON ml_scalp_samples(instrument, status);
CREATE TABLE IF NOT EXISTS ml_scalp_predictions (
    prediction_id TEXT PRIMARY KEY,
    sample_id TEXT NOT NULL,
    model_hash TEXT,
    role TEXT,
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    session_epoch TEXT,
    as_of TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_margin REAL,
    p REAL,
    expected_net_r REAL,
    proposed_filter INTEGER,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_ml_scalp_pred ON ml_scalp_predictions(instrument, computed_at);
CREATE TABLE IF NOT EXISTS eval_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    instrument TEXT NOT NULL,
    task_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    artifact_hash TEXT NOT NULL,
    status TEXT NOT NULL
);
