-- Optional human description for MCP access profiles (Admin UI list).
ALTER TABLE mcp_access_profiles ADD COLUMN description TEXT NOT NULL DEFAULT '';
