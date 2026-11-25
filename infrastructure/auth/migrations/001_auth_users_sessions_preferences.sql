-- Local users, sessions, preferences, and login-attempt bookkeeping (#182).

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

INSERT INTO schema_version (version)
SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

CREATE TABLE IF NOT EXISTS auth_users (
    user_id TEXT NOT NULL COLLATE BINARY PRIMARY KEY,
    username TEXT NOT NULL COLLATE BINARY,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (username)
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id_hash TEXT NOT NULL COLLATE BINARY PRIMARY KEY,
    user_id TEXT NOT NULL COLLATE BINARY,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_users (user_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id
    ON auth_sessions (user_id);

CREATE TABLE IF NOT EXISTS auth_user_preferences (
    user_id TEXT NOT NULL COLLATE BINARY PRIMARY KEY,
    provider TEXT,
    model TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_users (user_id)
);

CREATE TABLE IF NOT EXISTS auth_login_attempts (
    username TEXT NOT NULL COLLATE BINARY PRIMARY KEY,
    failure_count INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    updated_at TEXT NOT NULL
);
