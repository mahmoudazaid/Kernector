-- Workspace AI credential vault (#461): encrypted secrets, one active
-- credential per (workspace_id, provider). Ciphertext never returned via
-- metadata APIs; master key stays outside SQLite.

CREATE TABLE IF NOT EXISTS workspace_ai_credentials (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL COLLATE BINARY,
    provider TEXT NOT NULL,
    encrypted_secret BLOB NOT NULL,
    nonce BLOB NOT NULL,
    encryption_key_version INTEGER NOT NULL,
    key_hint TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rotated_at TEXT,
    PRIMARY KEY (workspace_id, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS workspace_ai_credentials_active_provider
    ON workspace_ai_credentials (workspace_id, provider)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS workspace_ai_credentials_by_provider
    ON workspace_ai_credentials (workspace_id, provider);
