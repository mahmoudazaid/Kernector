-- Server-side workspace selection for multi-membership sessions (#447).

ALTER TABLE auth_sessions ADD COLUMN selected_workspace_id TEXT;
