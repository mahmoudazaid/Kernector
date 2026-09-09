-- Versioned catalog documents. Transaction control is owned by apply_migrations.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

INSERT INTO schema_version (version)
SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM schema_version);

CREATE TABLE IF NOT EXISTS catalog_documents (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    file_name TEXT NOT NULL,
    title TEXT,
    content_format TEXT,
    status TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    error TEXT,
    revision TEXT,
    UNIQUE (workspace_id, source_type, source_id)
);
