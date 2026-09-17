-- Response feedback ratings keyed by (workspace_id, request_id).

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

INSERT INTO schema_version (version)
SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

CREATE TABLE IF NOT EXISTS response_feedback (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    request_id TEXT NOT NULL COLLATE BINARY,
    rating TEXT NOT NULL,
    conversation_id TEXT,
    client_message_id TEXT,
    run_id TEXT,
    reason TEXT,
    comment TEXT,
    prompt_key TEXT,
    prompt_version TEXT,
    model TEXT,
    tools_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (workspace_id, request_id)
);
