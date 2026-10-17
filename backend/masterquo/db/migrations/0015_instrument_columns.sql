-- 1.15: training per instrument. SHADOW forecasts / scalp decisions carry the canonical instrument so that a XAUUSD model is
-- never scored on BTC bars (and the other way round). Existing rows were produced by the XAUUSD-only services.
ALTER TABLE forecast_shadow ADD COLUMN instrument TEXT NOT NULL DEFAULT 'XAUUSD';
ALTER TABLE scalp_shadow ADD COLUMN instrument TEXT NOT NULL DEFAULT 'XAUUSD';
CREATE INDEX IF NOT EXISTS idx_forecast_shadow_inst ON forecast_shadow(instrument, outcome_status);
CREATE INDEX IF NOT EXISTS idx_scalp_shadow_inst ON scalp_shadow(instrument, outcome_status);
