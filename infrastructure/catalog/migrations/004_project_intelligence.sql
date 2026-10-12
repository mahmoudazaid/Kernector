-- Project Intelligence identity (#372, ADR 0011): projects, source
-- associations and components. Every row carries workspace_id.

CREATE TABLE IF NOT EXISTS projects (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, project_id),
    UNIQUE (workspace_id, slug)
);

CREATE TABLE IF NOT EXISTS source_associations (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    project_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_value TEXT NOT NULL,
    roles TEXT NOT NULL,
    state TEXT NOT NULL,
    evidence TEXT NOT NULL,
    created_by TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, project_id, connector_id, scope_kind, scope_value)
);

CREATE INDEX IF NOT EXISTS source_associations_by_scope
    ON source_associations (workspace_id, connector_id, scope_kind, scope_value);

CREATE TABLE IF NOT EXISTS project_components (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    project_id TEXT NOT NULL,
    component_id TEXT NOT NULL,
    name TEXT NOT NULL,
    reason TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, project_id, component_id)
);

CREATE TABLE IF NOT EXISTS project_component_members (
    workspace_id TEXT NOT NULL COLLATE BINARY,
    project_id TEXT NOT NULL,
    component_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    scope_kind TEXT NOT NULL,
    scope_value TEXT NOT NULL,
    path_prefix TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (
        workspace_id, project_id, connector_id, scope_kind, scope_value, path_prefix
    )
);

CREATE INDEX IF NOT EXISTS project_component_members_by_component
    ON project_component_members (workspace_id, project_id, component_id);
