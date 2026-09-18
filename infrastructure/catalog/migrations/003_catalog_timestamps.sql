-- Replace uploaded_at with created_at / updated_at.
-- Legacy default: both timestamps are copied from the former uploaded_at value,
-- then the legacy column is dropped via table rebuild.

ALTER TABLE catalog_documents ADD COLUMN created_at TEXT;
ALTER TABLE catalog_documents ADD COLUMN updated_at TEXT;

UPDATE catalog_documents
SET created_at = uploaded_at,
    updated_at = uploaded_at;

CREATE TABLE catalog_documents_new (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    file_name TEXT NOT NULL,
    title TEXT,
    content_format TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    chunk_count INTEGER NOT NULL,
    error TEXT,
    revision TEXT,
    connector_id TEXT,
    UNIQUE (workspace_id, source_type, source_id)
);

INSERT INTO catalog_documents_new (
    workspace_id, source_id, source_type, file_name, title, content_format,
    status, created_at, updated_at, chunk_count, error, revision, connector_id
)
SELECT
    workspace_id, source_id, source_type, file_name, title, content_format,
    status, created_at, updated_at, chunk_count, error, revision, connector_id
FROM catalog_documents;

DROP TABLE catalog_documents;
ALTER TABLE catalog_documents_new RENAME TO catalog_documents;
