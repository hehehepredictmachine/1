-- MasterQUO AI 1.3: execution modes without READ_ONLY (rename of stored mode values) and the ML pipeline.
UPDATE order_attempts SET mode='AUTO_DEMO' WHERE mode='DEMO_EXECUTION';
UPDATE order_attempts SET mode='AUTO_LIVE' WHERE mode='LIVE_EXECUTION';
UPDATE order_attempts SET entry_key=replace(replace(entry_key, 'DEMO_EXECUTION:', 'AUTO_DEMO:'), 'LIVE_EXECUTION:', 'AUTO_LIVE:');
UPDATE managed_positions SET mode='AUTO_DEMO' WHERE mode='DEMO_EXECUTION';
UPDATE managed_positions SET mode='AUTO_LIVE' WHERE mode='LIVE_EXECUTION';
UPDATE managed_positions SET position_key=replace(replace(position_key, 'DEMO_EXECUTION:', 'AUTO_DEMO:'), 'LIVE_EXECUTION:', 'AUTO_LIVE:');
UPDATE trades SET mode='AUTO_DEMO' WHERE mode='DEMO_EXECUTION';
UPDATE trades SET mode='AUTO_LIVE' WHERE mode='LIVE_EXECUTION';

-- One row per setup decision point (first CONFIRMED of a setup version); rejected/unexecuted setups included.
CREATE TABLE IF NOT EXISTS ml_samples (
    sample_id TEXT PRIMARY KEY,                 -- setup_id + ':' + setup version
    setup_id TEXT NOT NULL,
    setup_version INTEGER NOT NULL,
    group_id TEXT NOT NULL,                     -- setup_id (versions of one setup never split across folds)
    event_id TEXT,
    symbol TEXT NOT NULL,
    feed_id TEXT NOT NULL,                      -- account server / SYNTHETIC / BACKFILL source
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    direction TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    asof_utc TEXT NOT NULL,                     -- decision time (signal availability)
    feature_schema_version TEXT NOT NULL,
    features_json TEXT NOT NULL,
    entry_json TEXT NOT NULL,                   -- entry/SL/TP/horizon policy fixed at creation
    cost_model_version TEXT NOT NULL,
    label_policy_version TEXT NOT NULL,
    source TEXT NOT NULL,                       -- LIVE_SCAN / BACKFILL_REPLAY / SYNTHETIC
    quality TEXT NOT NULL,                      -- HIGH (live M1 + quotes) / APPROX (OHLC only)
    status TEXT NOT NULL,                       -- PENDING / LABELED / NO_ENTRY / AMBIGUOUS / MISSING_DATA / UNRESOLVED / CANCELLED
    label INTEGER,                              -- 1 net > 0, 0 net <= 0, NULL when not labelled
    outcome_r REAL, mfe_r REAL, mae_r REAL,
    exit_reason TEXT,
    label_end_utc TEXT,                         -- when the outcome window ended
    label_known_utc TEXT,                       -- when the label became known to the system (training cutoff)
    outcome_source TEXT,                        -- HYPOTHETICAL / PAPER / AUTO_DEMO / AUTO_LIVE
    realized_json TEXT,
    synthetic INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ml_samples_status ON ml_samples(status, quality);
CREATE INDEX IF NOT EXISTS ix_ml_samples_asof ON ml_samples(asof_utc);

CREATE TABLE IF NOT EXISTS ml_models (
    model_id TEXT PRIMARY KEY,
    family TEXT NOT NULL,                       -- DECISION_TREE / XGBOOST
    version INTEGER NOT NULL,
    status TEXT NOT NULL,                       -- CANDIDATE / CHAMPION / CHALLENGER / REJECTED / RETIRED / FAILED
    created_at TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    path TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    promotion_json TEXT,
    promoted_at TEXT,
    retired_at TEXT
);

CREATE TABLE IF NOT EXISTS ml_jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                         -- TRAIN
    status TEXT NOT NULL,                       -- QUEUED / RUNNING / DONE / FAILED / CANCELLED / INTERRUPTED
    created_at TEXT NOT NULL,
    started_at TEXT, finished_at TEXT,
    snapshot_id TEXT,
    detail_json TEXT
);

CREATE TABLE IF NOT EXISTS ml_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,                         -- PROMOTE / ROLLBACK / REJECT / DRIFT / DEGRADED / FALLBACK
    model_id TEXT,
    detail_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ml_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    setup_id TEXT NOT NULL,
    setup_version INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    role TEXT NOT NULL,                         -- CHAMPION / CHALLENGER
    raw_score REAL,
    calibrated_probability REAL,
    readiness TEXT NOT NULL,
    contract_json TEXT NOT NULL,
    UNIQUE(setup_id, setup_version, model_id)
);
