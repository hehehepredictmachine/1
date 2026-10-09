-- MasterQUO central server schema v1 (portable PostgreSQL / SQLite-dev).
-- Times: *_at = epoch seconds (UTC, server clock), *_ms = epoch milliseconds. Money: DOUBLE PRECISION in account currency.

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,                 -- lower-cased
    display_name TEXT,
    password_hash TEXT,                         -- Argon2id (NULL until the invited user sets a password)
    status TEXT NOT NULL,                       -- PENDING_VERIFICATION / ACTIVE / BLOCKED
    role TEXT NOT NULL DEFAULT 'USER',          -- USER / ADMIN (assigned only by the server)
    created_at BIGINT NOT NULL,
    email_verified_at BIGINT,
    password_changed_at BIGINT,
    totp_secret_enc TEXT,                       -- Fernet-encrypted TOTP secret (admin MFA)
    totp_enabled INTEGER NOT NULL DEFAULT 0,
    blocked_at BIGINT,
    blocked_reason TEXT
);

CREATE TABLE recovery_codes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    code_hash TEXT NOT NULL,
    used_at BIGINT
);
CREATE INDEX ix_recovery_user ON recovery_codes(user_id);

CREATE TABLE sessions (
    id_hash TEXT PRIMARY KEY,                   -- SHA-256 of the random session token
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,                         -- WEB (cookie + CSRF) / CLIENT (bearer, bot client)
    csrf TEXT,
    mfa_ok INTEGER NOT NULL DEFAULT 0,
    created_at BIGINT NOT NULL,
    last_seen_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    revoked_at BIGINT,
    ip TEXT,
    user_agent TEXT
);
CREATE INDEX ix_sessions_user ON sessions(user_id);

CREATE TABLE user_tokens (
    token_hash TEXT PRIMARY KEY,                -- SHA-256 of a 256-bit random token
    user_id TEXT NOT NULL REFERENCES users(id),
    purpose TEXT NOT NULL,                      -- VERIFY_EMAIL / RESET_PASSWORD / INVITE
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    used_at BIGINT
);
CREATE INDEX ix_tokens_user ON user_tokens(user_id);

CREATE TABLE licenses (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    key_hash TEXT NOT NULL UNIQUE,              -- SHA-256 of the full key (the key itself is never stored)
    key_hint TEXT NOT NULL,                     -- safe display id: prefix + last 4 characters
    type TEXT NOT NULL,                         -- STD_48H
    duration_s BIGINT NOT NULL,                 -- 172800
    status TEXT NOT NULL,                       -- ISSUED / ACTIVE / EXPIRED / REVOKED
    note TEXT,
    created_by TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    activated_at BIGINT,
    expires_at BIGINT,
    revoked_at BIGINT,
    revoked_by TEXT,
    revoke_reason TEXT
);
CREATE INDEX ix_licenses_user ON licenses(user_id);

CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    public_key TEXT NOT NULL,                   -- Ed25519 public key (PEM); private key never leaves the client (DPAPI)
    install_id TEXT NOT NULL,
    name TEXT,
    created_at BIGINT NOT NULL,
    last_seen_at BIGINT,
    revoked_at BIGINT,
    revoke_reason TEXT
);
CREATE INDEX ix_devices_user ON devices(user_id);

CREATE TABLE license_activations (
    id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(id),
    device_id TEXT NOT NULL REFERENCES devices(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    created_at BIGINT NOT NULL,
    released_at BIGINT,
    release_reason TEXT,
    released_by TEXT
);
-- one seat per license: at most one unreleased activation
CREATE UNIQUE INDEX ux_activation_seat ON license_activations(license_id) WHERE released_at IS NULL;

CREATE TABLE device_nonces (
    nonce TEXT PRIMARY KEY,
    purpose TEXT NOT NULL,                      -- ACTIVATE / DEVICE
    user_id TEXT,
    device_id TEXT,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    used_at BIGINT
);

CREATE TABLE op_authorizations (
    jti TEXT PRIMARY KEY,
    activation_id TEXT NOT NULL REFERENCES license_activations(id),
    intent_id TEXT NOT NULL,
    op TEXT NOT NULL,
    detail_json TEXT,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    UNIQUE (activation_id, intent_id)
);

CREATE TABLE trading_accounts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    device_id TEXT NOT NULL REFERENCES devices(id),
    server TEXT NOT NULL,
    login TEXT NOT NULL,
    company TEXT,
    trade_mode TEXT NOT NULL,                   -- DEMO / REAL / CONTEST (as reported by the terminal)
    currency TEXT,
    currency_digits INTEGER NOT NULL DEFAULT 2,
    bot_magic BIGINT,
    linked_at BIGINT NOT NULL,
    unlinked_at BIGINT,
    history_status TEXT NOT NULL DEFAULT 'NOT_STARTED',  -- NOT_STARTED / IMPORTING / COMPLETE / INCOMPLETE
    history_from_ms BIGINT,
    history_to_ms BIGINT,
    last_seq BIGINT,
    last_measured_ms BIGINT,
    last_received_at BIGINT,
    last_balance DOUBLE PRECISION,
    last_equity DOUBLE PRECISION,
    last_currency TEXT
);
CREATE INDEX ix_accounts_user ON trading_accounts(user_id);
CREATE UNIQUE INDEX ux_accounts_device_active ON trading_accounts(device_id) WHERE unlinked_at IS NULL;

CREATE TABLE account_snapshots (
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    seq BIGINT NOT NULL,
    measured_ms BIGINT NOT NULL,
    received_at BIGINT NOT NULL,
    balance DOUBLE PRECISION NOT NULL,
    equity DOUBLE PRECISION NOT NULL,
    margin DOUBLE PRECISION,
    margin_free DOUBLE PRECISION,
    currency TEXT NOT NULL,
    stale_on_arrival INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, seq)
);

CREATE TABLE trade_deals (
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    ticket TEXT NOT NULL,
    order_ticket TEXT,
    position_id TEXT,
    time_ms BIGINT NOT NULL,
    type INTEGER NOT NULL,
    entry INTEGER NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION,
    profit DOUBLE PRECISION NOT NULL,
    commission DOUBLE PRECISION NOT NULL,
    swap DOUBLE PRECISION NOT NULL,
    fee DOUBLE PRECISION NOT NULL,
    symbol TEXT,
    magic BIGINT,
    comment TEXT,
    received_at BIGINT NOT NULL,
    PRIMARY KEY (account_id, ticket)
);
CREATE INDEX ix_deals_position ON trade_deals(account_id, position_id);

CREATE TABLE reconstructed_trades (
    account_id TEXT NOT NULL REFERENCES trading_accounts(id),
    cycle_id TEXT NOT NULL,
    position_id TEXT NOT NULL,
    symbol TEXT,
    direction TEXT,
    status TEXT NOT NULL,                       -- COMPLETE / OPEN / INCOMPLETE
    outcome TEXT,                               -- WIN / LOSS / NEUTRAL (COMPLETE only)
    open_ms BIGINT,
    close_ms BIGINT,
    volume DOUBLE PRECISION,
    gross DOUBLE PRECISION,
    commission DOUBLE PRECISION,
    swap DOUBLE PRECISION,
    fee DOUBLE PRECISION,
    net DOUBLE PRECISION,
    bot INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    PRIMARY KEY (account_id, cycle_id)
);
CREATE INDEX ix_cycles_close ON reconstructed_trades(account_id, close_ms);

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY,
    at BIGINT NOT NULL,
    actor_user_id TEXT,
    actor_role TEXT,
    action TEXT NOT NULL,
    target_user_id TEXT,
    target_type TEXT,
    target_id TEXT,
    before_json TEXT,
    after_json TEXT,
    ip TEXT
);
CREATE INDEX ix_audit_target ON audit_events(target_user_id, at);

CREATE TABLE mail_outbox (
    id TEXT PRIMARY KEY,
    created_at BIGINT NOT NULL,
    to_addr TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE server_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
