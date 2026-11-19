"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useTransition,
} from "react";
import { LoadingState } from "@/components/states/LoadingState";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { SoftSelect } from "@/components/ui/SoftSelect";
import { formatTimestamp } from "@/lib/format/timestamp";
import {
  createMcpProfile,
  getMcpServerInfo,
  listMcpProfiles,
  listMcpTools,
  mcpClientConfig,
  revokeMcpProfile,
  updateMcpAllowlist,
  type McpAccessProfileResponse,
  type McpServerInfoResponse,
  type McpToolCatalogResponse,
} from "@/lib/api/mcp-profiles";
import {
  listProjects,
  type ProjectResponse,
} from "@/lib/api/projects";

export type McpAccessPanelProps = {
  mcpPublicEndpoint: string;
  loadServer?: typeof getMcpServerInfo;
  loadTools?: typeof listMcpTools;
  loadProfiles?: typeof listMcpProfiles;
  loadProjects?: typeof listProjects;
  createProfile?: typeof createMcpProfile;
  saveAllowlist?: typeof updateMcpAllowlist;
  revokeProfile?: typeof revokeMcpProfile;
};

type LoadView =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      server: McpServerInfoResponse;
      tools: McpToolCatalogResponse;
    };

function statusPillClass(status: string): string {
  if (status === "active") return "kern-source-status";
  if (status === "disabled" || status === "expired") {
    return "kern-source-status is-setup";
  }
  return "kern-source-status is-muted";
}

function projectLabel(project: ProjectResponse): string {
  return `${project.name} (${project.slug})`;
}

function McpTokenCallout({
  token,
  endpoint,
}: {
  token: string;
  endpoint: string;
}) {
  const [copied, setCopied] = useState(false);
  const config = mcpClientConfig(endpoint, token);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  function onCopy() {
    void navigator.clipboard.writeText(token).then(
      () => setCopied(true),
      () => setCopied(false),
    );
  }

  return (
    <div
      className="kern-settings-callout kern-settings-callout--ok"
      role="status"
      aria-live="polite"
    >
      <h2>One-time access token</h2>
      <p className="kern-settings-hint">
        Copy now — it will not be shown again. Paste the client config into
        mcp.json for Cursor or Claude Code.
      </p>
      <div className="kern-mcp-token-row">
        <input
          className="kern-settings-input"
          type="text"
          readOnly
          value={token}
          aria-label="One-time access token"
          onFocus={(event) => event.currentTarget.select()}
        />
        <Button variant="secondary" onClick={onCopy}>
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <div className="kern-settings-field">
        <p className="kern-settings-help">Client config</p>
        <pre className="kern-mcp-snippet">{config}</pre>
      </div>
    </div>
  );
}

export function McpAccessPanel({
  mcpPublicEndpoint,
  loadServer = getMcpServerInfo,
  loadTools = listMcpTools,
  loadProfiles = listMcpProfiles,
  loadProjects = listProjects,
  createProfile = createMcpProfile,
  saveAllowlist = updateMcpAllowlist,
  revokeProfile = revokeMcpProfile,
}: McpAccessPanelProps) {
  const [loadView, setLoadView] = useState<LoadView>({ kind: "loading" });
  const [profiles, setProfiles] = useState<McpAccessProfileResponse[]>([]);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingToken, setPendingToken] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [revokeTarget, setRevokeTarget] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [reloadNonce, setReloadNonce] = useState(0);

  const projectOptions = useMemo(
    () => projects.map((project) => projectLabel(project)),
    [projects],
  );
  const projectIdByLabel = useMemo(() => {
    const map = new Map<string, string>();
    for (const project of projects) {
      map.set(projectLabel(project), project.project_id);
    }
    return map;
  }, [projects]);
  const projectLabelById = useMemo(() => {
    const map = new Map<string, string>();
    for (const project of projects) {
      map.set(project.project_id, projectLabel(project));
    }
    return map;
  }, [projects]);
  const selectedProjectLabel =
    (projectId && projectLabelById.get(projectId)) || projectOptions[0] || "";

  const reload = useCallback(() => {
    setLoadView({ kind: "loading" });
    setActionError(null);
    setReloadNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    startTransition(async () => {
      try {
        const [serverInfo, toolCatalog, profileList, projectList] =
          await Promise.all([
            loadServer(),
            loadTools(),
            loadProfiles(),
            loadProjects(),
          ]);
        if (cancelled) return;
        setProfiles(profileList);
        setProjects(projectList);
        setSelectedId((current) => current ?? profileList[0]?.profile_id ?? null);
        setProjectId((current) => {
          if (current && projectList.some((item) => item.project_id === current)) {
            return current;
          }
          return projectList[0]?.project_id ?? "";
        });
        setLoadView({
          kind: "ready",
          server: serverInfo,
          tools: toolCatalog,
        });
        setActionError(null);
      } catch (err) {
        if (!cancelled) {
          setLoadView({
            kind: "error",
            message:
              err instanceof Error ? err.message : "Failed to load MCP admin",
          });
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [loadServer, loadTools, loadProfiles, loadProjects, reloadNonce]);

  const selected = profiles.find((item) => item.profile_id === selectedId) ?? null;
  const allowlistable =
    loadView.kind === "ready"
      ? loadView.tools.tools.filter((tool) => tool.allowlistable)
      : [];
  const unavailable =
    loadView.kind === "ready"
      ? loadView.tools.tools.filter((tool) => !tool.allowlistable)
      : [];
  const endpoint =
    mcpPublicEndpoint ||
    (loadView.kind === "ready" ? loadView.server.endpoint : "/mcp");

  function onCreate() {
    if (!projectId.trim()) {
      setActionError("Select a project before creating a profile.");
      return;
    }
    startTransition(async () => {
      try {
        const created = await createProfile({
          project_id: projectId.trim(),
          name: name.trim(),
        });
        setPendingToken(created.plaintext_token);
        setProfiles((prev) => [created.profile, ...prev]);
        setSelectedId(created.profile.profile_id);
        setName("");
        setActionError(null);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Create failed");
      }
    });
  }

  function onToggleTool(toolId: string, enabled: boolean) {
    if (!selected) return;
    const next = new Set(selected.allowlist);
    if (enabled) next.add(toolId);
    else next.delete(toolId);
    startTransition(async () => {
      try {
        const updated = await saveAllowlist(selected.profile_id, [...next].sort());
        setProfiles((prev) =>
          prev.map((item) =>
            item.profile_id === updated.profile_id ? updated : item,
          ),
        );
        setActionError(null);
      } catch (err) {
        setActionError(
          err instanceof Error ? err.message : "Allowlist update failed",
        );
      }
    });
  }

  function confirmRevoke() {
    if (!revokeTarget) return;
    const target = revokeTarget;
    setRevokeTarget(null);
    startTransition(async () => {
      try {
        const updated = await revokeProfile(target);
        setProfiles((prev) =>
          prev.map((item) =>
            item.profile_id === updated.profile_id ? updated : item,
          ),
        );
        setPendingToken(null);
        setActionError(null);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Revoke failed");
      }
    });
  }

  if (loadView.kind === "loading") {
    return (
      <div className="kern-settings" aria-busy="true">
        <h1 id="mcp-access-heading">MCP access profiles</h1>
        <div className="kern-content-state">
          <LoadingState label="Loading MCP access" />
        </div>
      </div>
    );
  }

  if (loadView.kind === "error") {
    return (
      <div className="kern-settings" role="alert">
        <h1 id="mcp-access-heading">MCP access profiles</h1>
        <p className="kern-settings-lead">{loadView.message}</p>
        <Button variant="secondary" disabled={isPending} onClick={reload}>
          {isPending ? "Checking…" : "Retry"}
        </Button>
      </div>
    );
  }

  const { server, tools } = loadView;

  return (
    <section className="kern-settings" aria-labelledby="mcp-access-heading">
      <h1 id="mcp-access-heading">MCP access profiles</h1>
      <p className="kern-settings-lead">
        Manage Kernector&apos;s hosted MCP server profiles. There is no remote
        MCP URL field — clients connect to this deployment only.
      </p>

      {actionError ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{actionError}</p>
        </div>
      ) : null}

      <fieldset className="kern-settings-fieldset" aria-label="MCP server status">
        <legend>Server</legend>
        <div className="kern-settings-stack">
          <div className="kern-settings-field">
            <p className="kern-settings-help">Endpoint</p>
            <p className="kern-settings-hint">
              <code>{endpoint}</code>
            </p>
          </div>
          <div className="kern-source-metrics">
            <div>
              <span className="kern-metric-label">Transport</span>
              <span className="kern-metric-value">{server.transport}</span>
            </div>
            <div>
              <span className="kern-metric-label">Auth</span>
              <span className="kern-metric-value">{server.auth_mode}</span>
            </div>
          </div>
          <div className="kern-sync-heading">
            <h3>Status</h3>
            <span className={statusPillClass(server.status)}>{server.status}</span>
          </div>
        </div>
      </fieldset>

      <fieldset className="kern-settings-fieldset" aria-label="MCP tool catalog">
        <legend>Tools</legend>
        <p className="kern-settings-hint">
          Allowlistable tools can be enabled per profile. Isolation-blocked tools
          stay unavailable.
        </p>
        <ul className="kern-mcp-tool-list">
          {tools.tools.map((tool) => (
            <li key={tool.tool_id}>
              <div className="kern-sync-heading">
                <h3>
                  <code>{tool.tool_id}</code>
                </h3>
                <span
                  className={
                    tool.allowlistable
                      ? "kern-source-status"
                      : "kern-source-status is-muted"
                  }
                >
                  {tool.allowlistable ? "allowlistable" : "unavailable"}
                </span>
              </div>
              <p className="kern-settings-hint">
                {tool.kind}
                {tool.side_effecting ? " · side-effecting" : ""}
                {!tool.allowlistable && tool.unavailable_reason
                  ? ` — ${tool.unavailable_reason}`
                  : ""}
              </p>
            </li>
          ))}
        </ul>
      </fieldset>

      <fieldset className="kern-settings-fieldset">
        <legend>Create profile</legend>
        <div className="kern-settings-stack">
          {projects.length === 0 ? (
            <div
              className="kern-settings-callout kern-settings-callout--warn"
              role="status"
            >
              <p>
                No projects in this workspace yet. Create a project first, then
                refresh this page to issue an MCP profile.
              </p>
              <Button variant="secondary" disabled={isPending} onClick={reload}>
                {isPending ? "Checking…" : "Refresh projects"}
              </Button>
            </div>
          ) : (
            <SoftSelect
              id="mcp-project"
              label="Project"
              value={selectedProjectLabel}
              options={projectOptions}
              onChange={(label) => {
                setProjectId(projectIdByLabel.get(label) ?? "");
                setActionError(null);
              }}
            />
          )}
          <div className="kern-settings-field">
            <label htmlFor="mcp-profile-name">Profile name</label>
            <input
              id="mcp-profile-name"
              className="kern-settings-input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoComplete="off"
              disabled={projects.length === 0}
            />
            <p className="kern-settings-hint">
              A label for this client (for example <code>cursor</code>).
            </p>
          </div>
          <Button
            onClick={onCreate}
            disabled={
              isPending || projects.length === 0 || !projectId || !name.trim()
            }
          >
            Create profile
          </Button>
        </div>
      </fieldset>

      {pendingToken ? (
        <McpTokenCallout token={pendingToken} endpoint={endpoint} />
      ) : null}

      <fieldset className="kern-settings-fieldset">
        <legend>Profiles</legend>
        {profiles.length === 0 ? (
          <p className="kern-settings-hint">No profiles yet.</p>
        ) : (
          <div
            className="kern-settings-radios"
            role="radiogroup"
            aria-label="Profiles"
          >
            {profiles.map((profile) => (
              <label key={profile.profile_id} className="kern-settings-radio">
                <input
                  type="radio"
                  name="mcp-profile"
                  value={profile.profile_id}
                  checked={selectedId === profile.profile_id}
                  onChange={() => setSelectedId(profile.profile_id)}
                />
                <span>
                  {profile.name} ({profile.status}) — {profile.project_id}
                </span>
              </label>
            ))}
          </div>
        )}
      </fieldset>

      {selected ? (
        <fieldset className="kern-settings-fieldset">
          <legend>Allowlist — {selected.name}</legend>
          <div className="kern-source-metrics">
            <div>
              <span className="kern-metric-label">Project</span>
              <span className="kern-metric-value">{selected.project_id}</span>
            </div>
            <div>
              <span className="kern-metric-label">Status</span>
              <span className={statusPillClass(selected.status)}>
                {selected.status}
              </span>
            </div>
          </div>
          <div className="kern-sync-section">
            <div className="kern-sync-heading">
              <h3>Created</h3>
              <time className="kern-sync-time" dateTime={selected.created_at}>
                {formatTimestamp(selected.created_at)}
              </time>
            </div>
            <div className="kern-sync-heading">
              <h3>Updated</h3>
              <time className="kern-sync-time" dateTime={selected.updated_at}>
                {formatTimestamp(selected.updated_at)}
              </time>
            </div>
          </div>

          <div className="kern-settings-stack">
            {allowlistable.map((tool) => (
              <label key={tool.tool_id} className="kern-settings-radio">
                <input
                  type="checkbox"
                  checked={selected.allowlist.includes(tool.tool_id)}
                  disabled={selected.status !== "active" || isPending}
                  onChange={(event) =>
                    onToggleTool(tool.tool_id, event.target.checked)
                  }
                />
                <span>
                  {tool.tool_id}
                  {tool.side_effecting ? " (side-effecting, HITL required)" : ""}
                </span>
              </label>
            ))}
          </div>

          {unavailable.map((tool) => (
            <p key={tool.tool_id} className="kern-settings-hint">
              <code>{tool.tool_id}</code>: unavailable — {tool.unavailable_reason}
            </p>
          ))}

          <Button
            variant="danger"
            disabled={selected.status === "revoked" || isPending}
            onClick={() => setRevokeTarget(selected.profile_id)}
          >
            Revoke profile
          </Button>
        </fieldset>
      ) : null}

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke MCP access profile?"
        description="Revoked profiles cannot authenticate. This cannot be undone."
        confirmLabel="Revoke"
        tone="danger"
        busy={isPending}
        onConfirm={confirmRevoke}
        onCancel={() => setRevokeTarget(null)}
      />
    </section>
  );
}
