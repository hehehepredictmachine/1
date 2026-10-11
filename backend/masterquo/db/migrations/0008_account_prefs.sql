-- 1.8: user preferences per trading account (server:login) - setup view selection and the leverage / exposure limit.
-- One source for the engine and the monitor; changing them affects FUTURE decisions only.
CREATE TABLE IF NOT EXISTS account_prefs (
    account_key TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_key, key)
);
