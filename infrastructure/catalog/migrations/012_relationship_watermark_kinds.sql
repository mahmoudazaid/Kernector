-- Namespaced relationship record watermarks (#375).
-- Rebuild so kind is part of the primary key; existing rows become provider_declared.

CREATE TABLE relationship_record_watermarks__v2 (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    source_type TEXT NOT NULL COLLATE BINARY,
    source_id TEXT NOT NULL COLLATE BINARY,
    kind TEXT NOT NULL COLLATE BINARY,
    links_fingerprint TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, source_type, source_id, kind)
);

INSERT INTO relationship_record_watermarks__v2 (
    workspace_id, source_type, source_id, kind, links_fingerprint, recorded_at
)
SELECT
    workspace_id,
    source_type,
    source_id,
    'provider_declared',
    links_fingerprint,
    recorded_at
FROM relationship_record_watermarks;

DROP TABLE relationship_record_watermarks;

ALTER TABLE relationship_record_watermarks__v2
    RENAME TO relationship_record_watermarks;
