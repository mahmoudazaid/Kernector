-- Namespaced versioned opaque records. Transaction control is owned by apply_migrations.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

INSERT INTO schema_version (version)
SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

CREATE TABLE IF NOT EXISTS versioned_workspace_records (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    namespace TEXT NOT NULL COLLATE BINARY,
    record_id TEXT NOT NULL COLLATE BINARY,
    payload TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, namespace, record_id)
);
