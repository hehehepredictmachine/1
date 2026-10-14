-- 1.11: SHADOW price forecasts of the gold_candles module, logged BEFORE the outcome is known and scored afterwards.
CREATE TABLE IF NOT EXISTS forecast_shadow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    run_id TEXT NOT NULL,
    feature_time_utc TEXT NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    target_time_utc TEXT NOT NULL,
    close_now REAL NOT NULL,
    neutral_band REAL NOT NULL,
    p_down REAL NOT NULL, p_flat REAL NOT NULL, p_up REAL NOT NULL,
    q10 REAL, q50 REAL, q90 REAL,
    session_check TEXT,
    horizon_status TEXT,
    outcome_close REAL,
    outcome_class TEXT,
    outcome_status TEXT,
    scored_at TEXT,
    UNIQUE (run_id, feature_time_utc, horizon_minutes)
);
CREATE INDEX IF NOT EXISTS ix_forecast_shadow_open ON forecast_shadow(outcome_status, target_time_utc);
