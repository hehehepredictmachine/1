-- PMW-UPD-07: Structure Intelligence (additive only - existing samples, results, zones and events are preserved).
-- R07/R08 pattern library: frozen manifest per job, immutable result ids, usable_at, event history with versions.
ALTER TABLE pattern_jobs ADD COLUMN manifest TEXT;
ALTER TABLE pattern_jobs ADD COLUMN manifest_sha TEXT;
ALTER TABLE pattern_jobs ADD COLUMN resumed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pattern_results ADD COLUMN result_id TEXT;
ALTER TABLE pattern_results ADD COLUMN sample_sha TEXT;
ALTER TABLE pattern_results ADD COLUMN usable_at TEXT;
ALTER TABLE pattern_results ADD COLUMN created_at TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_pattern_results_rid ON pattern_results(result_id);
CREATE TABLE IF NOT EXISTS pattern_events_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_key TEXT NOT NULL UNIQUE,
    pattern_id TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    symbol TEXT,
    timeframe TEXT,
    status TEXT NOT NULL,
    available_at TEXT,
    payload TEXT NOT NULL
);
-- R09 zones: revision, lifecycle checkpoint, episode state, blacklist / trigger flags, tombstones, idempotent interaction events.
ALTER TABLE lab_zones ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE lab_zones ADD COLUMN last_processed_bar TEXT;
ALTER TABLE lab_zones ADD COLUMN inside INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lab_zones ADD COLUMN blacklist INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lab_zones ADD COLUMN trigger_flags TEXT;
ALTER TABLE lab_zones ADD COLUMN score TEXT;
ALTER TABLE lab_zones ADD COLUMN broken_at TEXT;
ALTER TABLE lab_zones ADD COLUMN expires_at TEXT;
ALTER TABLE lab_zones ADD COLUMN created_at TEXT;
ALTER TABLE lab_zones ADD COLUMN tombstone INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lab_zones ADD COLUMN flags TEXT;
CREATE TABLE IF NOT EXISTS lab_zone_events (
    event_key TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    bar_t TEXT,
    type TEXT NOT NULL,
    seq INTEGER NOT NULL,
    at TEXT NOT NULL,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS ix_lab_zone_events_zone ON lab_zone_events(zone_id, seq);
CREATE TABLE IF NOT EXISTS lab_zone_checkpoints (
    asset TEXT NOT NULL,
    tf TEXT NOT NULL,
    last_bar TEXT,
    sequence INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (asset, tf)
);
-- R04/R13 structure intelligence snapshots and the forecast archive (emitted before outcomes are known) + maturation.
CREATE TABLE IF NOT EXISTS si_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    instrument TEXT NOT NULL,
    as_of TEXT NOT NULL,
    seq INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_si_snapshots_inst ON si_snapshots(instrument, as_of);
CREATE TABLE IF NOT EXISTS si_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument TEXT NOT NULL,
    task_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    horizon INTEGER NOT NULL,
    snapshot_id TEXT,
    emitted_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE (instrument, task_id, model_id, as_of, horizon)
);
CREATE TABLE IF NOT EXISTS si_outcomes (
    forecast_id INTEGER NOT NULL,
    data_revision TEXT NOT NULL,
    matured_at TEXT NOT NULL,
    r_h REAL,
    label TEXT,
    status TEXT NOT NULL,
    PRIMARY KEY (forecast_id, data_revision)
);
-- R12 Manual Trade Pad: durable intents and idempotent actions (PREPARED/SENDING before the terminal call).
CREATE TABLE IF NOT EXISTS manual_intents (
    intent_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    account TEXT,
    instrument TEXT NOT NULL,
    side TEXT NOT NULL,
    state TEXT NOT NULL,
    plan TEXT NOT NULL,
    source_pattern_id TEXT
);
CREATE TABLE IF NOT EXISTS manual_actions (
    idempotency_key TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    action TEXT NOT NULL,
    action_revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    request TEXT,
    result TEXT
);
CREATE INDEX IF NOT EXISTS ix_manual_actions_intent ON manual_actions(intent_id);
