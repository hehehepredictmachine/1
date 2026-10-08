-- MasterQUO AI schema v1. Every monetary value is in the account currency stored alongside.
CREATE TABLE IF NOT EXISTS app_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_app_events_ts ON app_events(ts);

CREATE TABLE IF NOT EXISTS clock_offsets (
    server TEXT PRIMARY KEY,
    offset_seconds INTEGER NOT NULL,
    measured_at TEXT NOT NULL,
    samples INTEGER NOT NULL,
    residual_seconds REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts_seen (
    account_key TEXT PRIMARY KEY,
    login INTEGER NOT NULL,
    server TEXT NOT NULL,
    company TEXT,
    currency TEXT,
    trade_mode TEXT NOT NULL,
    margin_mode TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    account_key TEXT,
    session_epoch INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    data_quality TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_snap_created ON analysis_snapshots(created_at);

CREATE TABLE IF NOT EXISTS setups (
    setup_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    account_key TEXT,
    synthetic INTEGER NOT NULL DEFAULT 0,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    profile TEXT NOT NULL,
    setup_tf TEXT NOT NULL,
    direction TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    state TEXT NOT NULL,
    state_changed_at TEXT NOT NULL,
    last_evaluated_bar TEXT,
    bars_evaluated INTEGER NOT NULL DEFAULT 0,
    ttl_bars INTEGER NOT NULL,
    change_log_json TEXT NOT NULL,
    terminal_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_setups_state ON setups(state);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    setup_id TEXT,
    account_key TEXT,
    session_epoch INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0,
    analysis_direction TEXT NOT NULL,
    signal_stage TEXT NOT NULL,
    decision TEXT NOT NULL,
    execution_permission TEXT NOT NULL,
    expires_at TEXT,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decisions_created ON decisions(created_at);
CREATE INDEX IF NOT EXISTS ix_decisions_setup ON decisions(setup_id);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger TEXT NOT NULL,
    snapshot_id TEXT,
    setup_id TEXT,
    model_requested TEXT,
    model_id TEXT,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT,
    latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    est_cost_usd REAL,
    tool_calls INTEGER,
    output_json TEXT,
    question TEXT
);
CREATE INDEX IF NOT EXISTS ix_agent_runs_started ON agent_runs(started_at);

CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    setup_id TEXT,
    trade_id TEXT,
    status TEXT NOT NULL,
    content_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_attempts (
    attempt_id TEXT PRIMARY KEY,
    entry_key TEXT NOT NULL UNIQUE,
    decision_id TEXT NOT NULL,
    setup_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    account_key TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    volume REAL NOT NULL,
    price_requested REAL,
    sl REAL,
    tp REAL,
    client_tag TEXT NOT NULL,
    state TEXT NOT NULL,
    retcode INTEGER,
    retcode_text TEXT,
    order_ticket INTEGER,
    deal_ticket INTEGER,
    position_ticket INTEGER,
    fill_price REAL,
    filled_volume REAL,
    request_json TEXT,
    result_json TEXT,
    initiated_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS managed_positions (
    position_key TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    account_key TEXT,
    position_ticket INTEGER,
    attempt_id TEXT,
    decision_id TEXT,
    setup_id TEXT,
    strategy_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    volume_initial REAL NOT NULL,
    volume_open REAL NOT NULL,
    entry_price REAL NOT NULL,
    sl REAL,
    tp1 REAL,
    tp2 REAL,
    tp1_done INTEGER NOT NULL DEFAULT 0,
    be_done INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    adopted INTEGER NOT NULL DEFAULT 0,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    planned_risk_money REAL
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    source TEXT NOT NULL,
    account_key TEXT,
    position_ticket INTEGER,
    decision_id TEXT,
    setup_id TEXT,
    strategy_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    volume REAL NOT NULL,
    entry_price REAL,
    exit_price_avg REAL,
    opened_at TEXT,
    closed_at TEXT NOT NULL,
    gross_pnl REAL NOT NULL,
    commission REAL NOT NULL,
    swap REAL NOT NULL,
    fee REAL NOT NULL,
    net_pnl REAL NOT NULL,
    currency TEXT,
    planned_risk_money REAL,
    r_multiple REAL,
    deals_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_trades_closed ON trades(closed_at);

CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    currency TEXT NOT NULL,
    starting_balance REAL NOT NULL,
    balance REAL NOT NULL,
    started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    ts TEXT NOT NULL,
    mode TEXT NOT NULL,
    account_key TEXT,
    balance REAL,
    equity REAL,
    margin REAL,
    free_margin REAL,
    currency TEXT
);
CREATE INDEX IF NOT EXISTS ix_equity_ts ON equity_snapshots(mode, ts);

CREATE TABLE IF NOT EXISTS settings_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    change_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications_sent (
    dedup_key TEXT PRIMARY KEY,
    ts TEXT NOT NULL
);
