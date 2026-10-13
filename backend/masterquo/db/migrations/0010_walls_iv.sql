-- 1.10: volatility walls - imported implied volatility observations (with publication time) and frozen session snapshots.
CREATE TABLE IF NOT EXISTS iv_observations (
    obs_id TEXT PRIMARY KEY,
    observed_at TEXT NOT NULL,
    available_at TEXT NOT NULL,
    valid_until TEXT NOT NULL,
    underlier TEXT NOT NULL,
    source TEXT NOT NULL,
    sigma_annual REAL NOT NULL,
    day_count_basis TEXT NOT NULL,
    tenor_days REAL,
    expiry TEXT,
    quality TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    imported_by TEXT,
    json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_iv_available ON iv_observations(available_at);

CREATE TABLE IF NOT EXISTS walls_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    anchor_time TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_walls_anchor ON walls_snapshots(symbol, anchor_time);
