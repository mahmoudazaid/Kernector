-- Add opaque connector instance identity for scoped reconciliation.

ALTER TABLE catalog_documents ADD COLUMN connector_id TEXT;
