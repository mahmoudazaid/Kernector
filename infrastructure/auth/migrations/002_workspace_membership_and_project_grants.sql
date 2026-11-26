-- Workspace membership and explicit project grants (#446).
-- Project existence is validated against the catalog DB at write time;
-- there is no cross-database FK to project tables.

CREATE TABLE IF NOT EXISTS auth_workspace_memberships (
    principal_id TEXT NOT NULL COLLATE BINARY,
    workspace_id TEXT NOT NULL COLLATE BINARY,
    role TEXT NOT NULL COLLATE BINARY,
    status TEXT NOT NULL COLLATE BINARY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (principal_id, workspace_id),
    FOREIGN KEY (principal_id) REFERENCES auth_users (user_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_workspace_memberships_principal
    ON auth_workspace_memberships (principal_id);

CREATE TABLE IF NOT EXISTS auth_project_grants (
    principal_id TEXT NOT NULL COLLATE BINARY,
    workspace_id TEXT NOT NULL COLLATE BINARY,
    project_id TEXT NOT NULL COLLATE BINARY,
    status TEXT NOT NULL COLLATE BINARY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (principal_id, workspace_id, project_id),
    FOREIGN KEY (principal_id, workspace_id)
        REFERENCES auth_workspace_memberships (principal_id, workspace_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_project_grants_principal_workspace
    ON auth_project_grants (principal_id, workspace_id);
