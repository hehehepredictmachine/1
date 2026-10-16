-- 1.13: analytics snapshots (results available at decision time - never rewritten by later recomputation) and the
-- Double Bottom pattern library (raw samples kept separately from validation results and reports).
CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    snapshot_id TEXT NOT NULL UNIQUE,
    module TEXT NOT NULL,
    symbol TEXT,
    timeframe TEXT,
    as_of TEXT,
    available_at TEXT,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analytics_snapshots_q ON analytics_snapshots(module, timeframe, as_of);
CREATE TABLE IF NOT EXISTS pattern_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    start_utc TEXT NOT NULL,
    end_utc TEXT NOT NULL,
    bars TEXT NOT NULL,
    data_sha256 TEXT NOT NULL,
    origin TEXT NOT NULL,
    note TEXT,
    deleted INTEGER NOT NULL DEFAULT 0,
    UNIQUE (symbol, timeframe, start_utc, end_utc, data_sha256)
);
CREATE TABLE IF NOT EXISTS pattern_jobs (
    job_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    sample_ids TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    counts TEXT,
    report_id TEXT,
    export_status TEXT,
    error TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS pattern_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    sample_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    result TEXT NOT NULL,
    UNIQUE (job_id, sample_id)
);
CREATE TABLE IF NOT EXISTS pattern_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    pattern_id TEXT NOT NULL,
    symbol TEXT,
    timeframe TEXT,
    status TEXT NOT NULL,
    available_at TEXT,
    payload TEXT NOT NULL,
    UNIQUE (pattern_id, status)
);
