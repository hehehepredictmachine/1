-- 1.14: lab (two assets XAUUSD/BTC): persistent supply/demand zones (versioned, with interaction history), point-in-time
-- forecast archive (Fourier / kinematics), repaint observations, model trial registry, holdout access log, inference
-- telemetry summaries and lab result snapshots. Every row carries the canonical asset.
CREATE TABLE IF NOT EXISTS lab_zones (
    zone_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    asset TEXT NOT NULL,
    broker_symbol TEXT,
    source TEXT NOT NULL,
    tf TEXT NOT NULL,
    kind TEXT NOT NULL,
    top REAL NOT NULL,
    bottom REAL NOT NULL,
    origin_time TEXT NOT NULL,
    confirmed_at TEXT,
    state TEXT NOT NULL,
    touch_count INTEGER NOT NULL DEFAULT 0,
    quality TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    history TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lab_zones_asset ON lab_zones(asset, tf, state);
CREATE TABLE IF NOT EXISTS lab_forecasts (
    forecast_id TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    module TEXT NOT NULL,
    tf TEXT,
    issued_as_of TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lab_forecasts_q ON lab_forecasts(asset, module, issued_as_of);
CREATE TABLE IF NOT EXISTS lab_repaint (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT NOT NULL,
    module TEXT NOT NULL,
    tf TEXT NOT NULL,
    bar_open TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    change TEXT NOT NULL,
    before TEXT,
    after TEXT
);
CREATE INDEX IF NOT EXISTS ix_lab_repaint_q ON lab_repaint(asset, module, tf);
CREATE TABLE IF NOT EXISTS lab_trials (
    trial_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    asset TEXT NOT NULL,
    horizon TEXT NOT NULL,
    model_family TEXT NOT NULL,
    protocol_id TEXT NOT NULL,
    data_hash TEXT,
    config TEXT NOT NULL,
    seeds TEXT NOT NULL,
    status TEXT NOT NULL,
    metrics TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS ix_lab_trials_q ON lab_trials(asset, horizon, protocol_id);
CREATE TABLE IF NOT EXISTS lab_holdout_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    asset TEXT NOT NULL,
    horizon TEXT NOT NULL,
    protocol_id TEXT NOT NULL,
    holdout_hash TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    result TEXT
);
CREATE TABLE IF NOT EXISTS lab_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    asset TEXT NOT NULL,
    tf TEXT NOT NULL,
    as_of TEXT,
    trace_id TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lab_snapshots_q ON lab_snapshots(asset, tf, as_of);
