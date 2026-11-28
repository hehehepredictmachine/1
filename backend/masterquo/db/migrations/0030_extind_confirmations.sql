-- 1.46 arch (I0729): the exporter re-sends the same objects every 2 s and every read was a new row (unbounded growth of the main
-- database). A repeated read of the same decoded content now extends the newest row of its source instead of adding one:
-- last_seen_at / last_sequence / last_captured_at = the last confirmation, seen_count = number of reads the row stands for.
-- Additive only: existing rows keep their values (NULL = one read, as before) and nothing is deleted.
ALTER TABLE extind_snapshots ADD COLUMN last_seen_at TEXT;
ALTER TABLE extind_snapshots ADD COLUMN last_sequence INTEGER;
ALTER TABLE extind_snapshots ADD COLUMN last_captured_at INTEGER;
ALTER TABLE extind_snapshots ADD COLUMN seen_count INTEGER NOT NULL DEFAULT 1;
-- source / sequence lookups of the ingest (duplicate and exporter-restart detection) and the status() queries
CREATE INDEX IF NOT EXISTS idx_extind_source_seq ON extind_snapshots(source_instance, sequence);
CREATE INDEX IF NOT EXISTS idx_extind_source_avail ON extind_snapshots(source_instance, available_at);
CREATE INDEX IF NOT EXISTS idx_extind_received ON extind_snapshots(adapter, received_at);
CREATE INDEX IF NOT EXISTS idx_extind_mapping ON extind_snapshots(adapter, mapping_status);
-- as_of: the newest approved row of every source of (adapter, instrument) at or before t (one adapter on two charts / terminals);
-- partial on the mapping only - the time_status filter of as_of is checked on the row (it may admit more than 'OK')
CREATE INDEX IF NOT EXISTS idx_extind_asof_source ON extind_snapshots(adapter, instrument, source_instance, available_at)
    WHERE mapping_status='MAPPING_APPROVED';
