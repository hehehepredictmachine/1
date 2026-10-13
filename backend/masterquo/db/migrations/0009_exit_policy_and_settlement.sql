-- 1.10: one exit policy (MQ-EXIT-POLICY-1.0.0) stored with every position at open - live, PAPER, ML labels and replay
-- use the SAME targets/weights/BE/time-exit; settings changed later never alter an open position.
-- TP1 state comes from the execution (REQUESTED/UNKNOWN/CONFIRMED/REJECTED), not from sending the request.
-- trades.status: CLOSED = the whole position is closed and settled; OPEN_PARTIAL = partial exits only (never in statistics);
-- UNSETTLED = closed but the P/L could not be calculated (never booked as 0).
ALTER TABLE managed_positions ADD COLUMN exit_policy_json TEXT;
ALTER TABLE managed_positions ADD COLUMN targets_done INTEGER NOT NULL DEFAULT 0;
ALTER TABLE managed_positions ADD COLUMN tp1_state TEXT;
ALTER TABLE managed_positions ADD COLUMN tp1_requested_at TEXT;
ALTER TABLE managed_positions ADD COLUMN tp1_volume REAL;
ALTER TABLE managed_positions ADD COLUMN exit_note TEXT;
ALTER TABLE trades ADD COLUMN status TEXT NOT NULL DEFAULT 'CLOSED';
ALTER TABLE trades ADD COLUMN exit_policy_version TEXT;
CREATE INDEX IF NOT EXISTS ix_trades_status ON trades(status);
