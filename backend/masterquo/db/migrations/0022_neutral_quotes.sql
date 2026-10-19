-- PMW-UPD-08: rolling signal neutralization state/events and Newtonian quote forecasts/outcomes (additive).
CREATE TABLE IF NOT EXISTS neutralizer_state (
    state_key TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL,
    seq INTEGER NOT NULL,
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS neutralization_events (
    event_key TEXT PRIMARY KEY,
    state_key TEXT NOT NULL,
    t REAL NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_neutralization_events_key ON neutralization_events(state_key, t);
CREATE TABLE IF NOT EXISTS quote_forecasts (
    forecast_id TEXT PRIMARY KEY,
    context TEXT NOT NULL,
    side TEXT NOT NULL,
    scale INTEGER NOT NULL,
    issued_at TEXT NOT NULL,
    target_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_quote_forecasts_ctx ON quote_forecasts(context, issued_at);
CREATE TABLE IF NOT EXISTS quote_outcomes (
    forecast_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    outcome REAL,
    error REAL,
    payload TEXT
);
