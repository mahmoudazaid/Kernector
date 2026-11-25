-- Index unresolved-key lookups and stamp evidence write time (#374 follow-up).
-- Exact subject_unresolved_key / object_unresolved_key matches replace LIKE
-- scans so skipped syncs stay O(keys) and underscores in Jira keys are literal.

ALTER TABLE relationship_evidence ADD COLUMN recorded_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00';

CREATE INDEX IF NOT EXISTS relationships_by_subject_unresolved
    ON relationships (workspace_id, subject_unresolved_key)
    WHERE subject_unresolved_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS relationships_by_object_unresolved
    ON relationships (workspace_id, object_unresolved_key)
    WHERE object_unresolved_key IS NOT NULL;
