-- 1.38 PMW-SH-PACK-2: variant identity of SH signals and plans (additive). `strategy` stays the compatible family name
-- (SCALPING / HEDGING); `strategy_id` = PMW_SC01..SC10 / PMW_HG01..HG10. Old rows keep NULL and are read as LEGACY_SCALPING /
-- LEGACY_HEDGING - never assigned to a new variant and never inheriting its results or validation.
ALTER TABLE sh_signals ADD COLUMN strategy_id TEXT;
ALTER TABLE sh_signals ADD COLUMN signal_tf TEXT;
ALTER TABLE sh_plans ADD COLUMN strategy_id TEXT;
ALTER TABLE sh_plans ADD COLUMN signal_tf TEXT;
CREATE INDEX IF NOT EXISTS ix_sh_signals_variant ON sh_signals(instrument, strategy_id, signal_tf, created_at);
CREATE INDEX IF NOT EXISTS ix_sh_plans_variant ON sh_plans(strategy_id, symbol, created_at);
