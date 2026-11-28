-- Bind MCP access profiles to an acting principal (#447).
-- Nullable for legacy rows; authentication fails closed when NULL.
-- New profiles must assign a non-null user_id (recreate/rebind legacy tokens).

ALTER TABLE mcp_access_profiles ADD COLUMN user_id TEXT;
