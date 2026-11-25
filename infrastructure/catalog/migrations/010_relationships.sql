-- Evidence-backed relationships (#374, ADR 0011).
-- Edge identity is (workspace, project, subject_token, relation_type, object_token).
-- Endpoints may be resolved SourceReferences or unresolved external keys.

CREATE TABLE IF NOT EXISTS relationships (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    relationship_id TEXT NOT NULL COLLATE BINARY,
    project_id TEXT NOT NULL COLLATE BINARY,
    relation_type TEXT NOT NULL COLLATE BINARY,
    subject_token TEXT NOT NULL COLLATE BINARY,
    object_token TEXT NOT NULL COLLATE BINARY,
    subject_kind TEXT NOT NULL,
    subject_source_type TEXT,
    subject_source_id TEXT,
    subject_part_key TEXT,
    subject_unresolved_key TEXT,
    object_kind TEXT NOT NULL,
    object_source_type TEXT,
    object_source_id TEXT,
    object_part_key TEXT,
    object_unresolved_key TEXT,
    origin TEXT NOT NULL,
    verification TEXT NOT NULL,
    confidence REAL NOT NULL,
    freshness TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_verified_at TEXT,
    decision_actor TEXT,
    decision_at TEXT,
    decision_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (workspace_id, relationship_id),
    UNIQUE (workspace_id, project_id, subject_token, relation_type, object_token)
);

CREATE INDEX IF NOT EXISTS relationships_by_project_subject
    ON relationships (workspace_id, project_id, subject_token);

CREATE INDEX IF NOT EXISTS relationships_by_project_object
    ON relationships (workspace_id, project_id, object_token);

CREATE TABLE IF NOT EXISTS relationship_evidence (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    relationship_id TEXT NOT NULL COLLATE BINARY,
    source_type TEXT NOT NULL COLLATE BINARY,
    source_id TEXT NOT NULL COLLATE BINARY,
    revision TEXT NOT NULL COLLATE BINARY,
    locator TEXT NOT NULL COLLATE BINARY,
    extractor_id TEXT NOT NULL COLLATE BINARY,
    PRIMARY KEY (
        workspace_id,
        relationship_id,
        source_type,
        source_id,
        revision,
        locator,
        extractor_id
    )
);

CREATE INDEX IF NOT EXISTS relationship_evidence_by_source
    ON relationship_evidence (workspace_id, source_type, source_id);

CREATE TABLE IF NOT EXISTS relationship_record_watermarks (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    source_type TEXT NOT NULL COLLATE BINARY,
    source_id TEXT NOT NULL COLLATE BINARY,
    links_fingerprint TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, source_type, source_id)
);
