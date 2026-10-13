-- Content, metadata, and processing fingerprints plus the provider content hash
-- (ADR 0012). NULL means unknown: legacy rows and rows that never reached READY.

ALTER TABLE catalog_documents ADD COLUMN content_fingerprint TEXT;
ALTER TABLE catalog_documents ADD COLUMN metadata_fingerprint TEXT;
ALTER TABLE catalog_documents ADD COLUMN processing_fingerprint TEXT;
ALTER TABLE catalog_documents ADD COLUMN provider_content_hash TEXT;
