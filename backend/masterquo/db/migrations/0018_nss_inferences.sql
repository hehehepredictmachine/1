-- PMW-UPD-04 Neural Scalp System: one row per inference of a candidate (written BEFORE the label exists, never rewritten), the
-- later label added in separate columns. Unique key per the specification (task, instrument, profile, setup, side, decision time,
-- model, snapshot).
CREATE TABLE IF NOT EXISTS nss_inferences (
    inference_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    instrument TEXT NOT NULL,
    profile_hash TEXT NOT NULL,
    setup_id TEXT NOT NULL,
    side TEXT NOT NULL,
    signal_time TEXT NOT NULL,
    decision_time TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    session_epoch TEXT,
    model_hash TEXT,
    snapshot_hash TEXT NOT NULL,
    mode TEXT NOT NULL,
    technical_status TEXT NOT NULL,
    output TEXT,
    plan TEXT NOT NULL,
    timings TEXT,
    label_status TEXT NOT NULL DEFAULT 'PENDING',
    label_event TEXT,
    label_net_r REAL,
    label_end TEXT,
    label_available_at TEXT,
    UNIQUE (task_id, instrument, profile_hash, setup_id, side, decision_time, model_hash, snapshot_hash)
);
CREATE INDEX IF NOT EXISTS idx_nss_inf_time ON nss_inferences(instrument, computed_at);
CREATE INDEX IF NOT EXISTS idx_nss_inf_label ON nss_inferences(instrument, label_status);
