-- Artifact descriptors and external-key index (#373, ADR 0011).
-- Project membership is derived; it is not stored on descriptors.

CREATE TABLE IF NOT EXISTS artifact_descriptors (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT,
    url TEXT,
    diagnostic TEXT,
    contexts_json TEXT NOT NULL,
    component_ids_json TEXT NOT NULL,
    parts_json TEXT NOT NULL,
    external_keys_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, source_type, source_id)
);

CREATE TABLE IF NOT EXISTS artifact_external_keys (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    external_key TEXT NOT NULL COLLATE BINARY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    PRIMARY KEY (workspace_id, external_key, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS artifact_external_keys_by_key
    ON artifact_external_keys (workspace_id, external_key);
