-- MCP access profiles (#324): hashed tokens, workspace+project binding,
-- default-deny allowlists. Phase 2 ownership columns may be added later.

CREATE TABLE IF NOT EXISTS mcp_access_profiles (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    profile_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    allowlist TEXT NOT NULL,
    status TEXT NOT NULL,
    expires_at TEXT,
    disabled_at TEXT,
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, profile_id),
    UNIQUE (workspace_id, token_hash)
);

CREATE INDEX IF NOT EXISTS mcp_access_profiles_by_project
    ON mcp_access_profiles (workspace_id, project_id);

CREATE INDEX IF NOT EXISTS mcp_access_profiles_by_token_hash
    ON mcp_access_profiles (token_hash);
