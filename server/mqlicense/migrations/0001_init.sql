-- MasterQUO License Server - initial schema. Secrets are never stored in plaintext:
-- license keys -> HMAC-SHA256 (server pepper); session tokens and admin session ids -> SHA-256; passwords -> Argon2id;
-- admin TOTP secrets -> Fernet-encrypted; recovery codes -> SHA-256.
CREATE TABLE IF NOT EXISTS server_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS admins (
    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('ADMIN','VIEWER')), totp_secret_enc TEXT NOT NULL, recovery_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','DISABLED')), created_at INTEGER NOT NULL,
    password_changed_at INTEGER NOT NULL, failed_logins INTEGER NOT NULL DEFAULT 0, locked_until INTEGER NOT NULL DEFAULT 0,
    last_login_at INTEGER
);
CREATE TABLE IF NOT EXISTS admin_sessions (
    id_hash TEXT PRIMARY KEY, admin_id TEXT NOT NULL REFERENCES admins(id), csrf TEXT NOT NULL, created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL, revoked_at INTEGER, ip TEXT, user_agent TEXT
);
CREATE INDEX IF NOT EXISTS ix_admin_sessions_admin ON admin_sessions(admin_id);
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT, mt5_login TEXT, note TEXT, created_at INTEGER NOT NULL, created_by TEXT,
    stats_allowed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY, key_hash TEXT NOT NULL UNIQUE, key_hint TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
    created_by TEXT NOT NULL, customer_id TEXT REFERENCES customers(id), note TEXT, max_sessions INTEGER NOT NULL DEFAULT 1,
    revoked_at INTEGER, revoked_by TEXT, revoke_reason TEXT, replaced_by TEXT, replaces TEXT,
    first_used_at INTEGER, last_used_at INTEGER, CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS ix_licenses_expires ON licenses(expires_at);
CREATE INDEX IF NOT EXISTS ix_licenses_customer ON licenses(customer_id);
CREATE TABLE IF NOT EXISTS license_sessions (
    id TEXT PRIMARY KEY, license_id TEXT NOT NULL REFERENCES licenses(id), token_hash TEXT NOT NULL UNIQUE, boot_id TEXT NOT NULL,
    created_at INTEGER NOT NULL, lease_expires_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL, ended_at INTEGER, end_reason TEXT,
    client_version TEXT, client_label TEXT, ip TEXT, telemetry_json TEXT, telemetry_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_sessions_license ON license_sessions(license_id, ended_at, lease_expires_at);
CREATE TABLE IF NOT EXISTS used_nonces (nonce TEXT PRIMARY KEY, used_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT,
    target_id TEXT, result TEXT NOT NULL, detail_json TEXT, ip TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_at ON audit(at);
