-- PMW-UPD-06 Liquidation heatmap: point-in-time archive. first_received_at is assigned ONCE by the backend at ingest; a repeated
-- identical payload only updates last_seen_at (never a new "fresh" snapshot, never summed). A file import keeps imported_at, the
-- declared original receipt time and its trust level separately.
CREATE TABLE IF NOT EXISTS liq_heatmap_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    target_asset TEXT NOT NULL,
    provider TEXT NOT NULL,
    variant TEXT NOT NULL,
    source_symbol TEXT NOT NULL,
    exchange TEXT,
    range TEXT,
    data_kind TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    first_received_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    source_generated_at TEXT,
    origin TEXT NOT NULL,
    declared_received_at TEXT,
    availability_trust TEXT NOT NULL,
    status TEXT NOT NULL,
    grid TEXT,
    zones TEXT,
    request TEXT
);
CREATE INDEX IF NOT EXISTS idx_liq_snap_key ON liq_heatmap_snapshots(source_key, first_received_at);
CREATE TABLE IF NOT EXISTS liq_source_status (
    source_key TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    retry_at TEXT
);
