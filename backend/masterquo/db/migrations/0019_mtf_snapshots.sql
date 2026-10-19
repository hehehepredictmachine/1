-- PMW-UPD-05 Multi TimeFrame Scalping Dashboard: durable archive of the compact MTFContextSnapshot (without bar series). A past
-- decision is inspected from this archive by id; a missing id is ARCHIVE_SNAPSHOT_UNAVAILABLE, never replaced by the latest one.
CREATE TABLE IF NOT EXISTS mtf_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    session_epoch TEXT,
    as_of TEXT,
    computed_at TEXT NOT NULL,
    setup_ids TEXT,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mtf_snapshots_asset ON mtf_snapshots(asset, computed_at);
