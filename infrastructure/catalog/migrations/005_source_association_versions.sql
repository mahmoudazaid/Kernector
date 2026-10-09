-- Retired source-association versions (#372). Keeps the highest version a
-- removed association reached for its workspace/project/scope key, so a
-- recreated association continues the sequence and a stale expected_version
-- from before the removal never matches again.

CREATE TABLE IF NOT EXISTS source_association_versions (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    project_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_value TEXT NOT NULL,
    last_version INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, project_id, connector_id, scope_kind, scope_value)
);
