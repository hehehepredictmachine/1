-- PMW-UPD-02: point-in-time archive of external indicator reads (IQ Gold Gann / IQ Star Lines / PAL02M) - every accepted
-- envelope is kept (revisions and removals stay visible); received_at is assigned ONCE by the backend at ingest.
CREATE TABLE IF NOT EXISTS extind_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    adapter TEXT NOT NULL,
    source_instance TEXT NOT NULL,
    instrument TEXT,
    symbol TEXT NOT NULL,
    chart_id TEXT,
    tf TEXT,
    generation INTEGER NOT NULL,
    sequence INTEGER NOT NULL,
    product_version TEXT,
    mapping_version INTEGER,
    mapping_status TEXT NOT NULL,
    time_status TEXT NOT NULL,
    captured_at_server INTEGER,
    received_at TEXT NOT NULL,
    available_at TEXT NOT NULL,
    levels TEXT NOT NULL,
    windows TEXT NOT NULL,
    events TEXT NOT NULL,
    objects_count INTEGER NOT NULL,
    envelope_sha256 TEXT NOT NULL,
    UNIQUE (source_instance, generation, sequence)
);
CREATE INDEX IF NOT EXISTS idx_extind_asof ON extind_snapshots(adapter, instrument, available_at);
