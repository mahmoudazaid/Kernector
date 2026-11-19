"use client";

import { useEffect, useState, useTransition } from "react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  claudeCodeMcpConfig,
  createMcpProfile,
  cursorMcpConfig,
  getMcpServerInfo,
  listMcpProfiles,
  listMcpTools,
  revokeMcpProfile,
  updateMcpAllowlist,
  type McpAccessProfileResponse,
  type McpServerInfoResponse,
  type McpToolCatalogResponse,
} from "@/lib/api/mcp-profiles";

export type McpAccessPanelProps = {
  mcpPublicEndpoint: string;
  loadServer?: typeof getMcpServerInfo;
  loadTools?: typeof listMcpTools;
  loadProfiles?: typeof listMcpProfiles;
  createProfile?: typeof createMcpProfile;
  saveAllowlist?: typeof updateMcpAllowlist;
  revokeProfile?: typeof revokeMcpProfile;
};

export function McpAccessPanel({
  mcpPublicEndpoint,
  loadServer = getMcpServerInfo,
  loadTools = listMcpTools,
  loadProfiles = listMcpProfiles,
  createProfile = createMcpProfile,
  saveAllowlist = updateMcpAllowlist,
  revokeProfile = revokeMcpProfile,
}: McpAccessPanelProps) {
  const [server, setServer] = useState<McpServerInfoResponse | null>(null);
  const [tools, setTools] = useState<McpToolCatalogResponse | null>(null);
  const [profiles, setProfiles] = useState<McpAccessProfileResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pendingToken, setPendingToken] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [revokeTarget, setRevokeTarget] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    startTransition(async () => {
      try {
        const [serverInfo, toolCatalog, profileList] = await Promise.all([
          loadServer(),
          loadTools(),
          loadProfiles(),
        ]);
        if (cancelled) return;
        setServer(serverInfo);
        setTools(toolCatalog);
        setProfiles(profileList);
        setSelectedId(profileList[0]?.profile_id ?? null);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load MCP admin");
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [loadServer, loadTools, loadProfiles]);

  const selected = profiles.find((item) => item.profile_id === selectedId) ?? null;
  const allowlistable =
    tools?.tools.filter((tool) => tool.allowlistable) ?? [];

  function onCreate() {
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
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Create failed");
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
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Allowlist update failed");
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
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Revoke failed");
      }
    });
  }

  return (
    <section className="kern-settings-panel" aria-labelledby="mcp-access-heading">
      <h1 id="mcp-access-heading">MCP access profiles</h1>
      <p>
        Manage Kernector&apos;s hosted MCP server profiles. There is no remote
        MCP URL field — clients connect to this deployment only.
      </p>

      {error ? (
        <p role="alert" className="kern-callout kern-callout-error">
          {error}
        </p>
      ) : null}

      {server ? (
        <div aria-label="MCP server status">
          <p>
            Endpoint: <code>{mcpPublicEndpoint || server.endpoint}</code>
          </p>
          <p>
            Transport: {server.transport}; auth: {server.auth_mode}; status:{" "}
            {server.status}
          </p>
        </div>
      ) : (
        <p aria-busy={isPending}>Loading server…</p>
      )}

      {tools ? (
        <div aria-label="MCP tool catalog">
          <h2>Tools</h2>
          <ul>
            {tools.tools.map((tool) => (
              <li key={tool.tool_id}>
                {tool.tool_id} — {tool.kind}
                {tool.side_effecting ? "; side-effecting" : ""}
                {tool.allowlistable
                  ? "; allowlistable"
                  : `; unavailable — ${tool.unavailable_reason}`}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <h2>Create profile</h2>
      <label htmlFor="mcp-project-id">
        Project id
        <input
          id="mcp-project-id"
          value={projectId}
          onChange={(event) => setProjectId(event.target.value)}
          autoComplete="off"
        />
      </label>
      <label htmlFor="mcp-profile-name">
        Profile name
        <input
          id="mcp-profile-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          autoComplete="off"
        />
      </label>
      <button type="button" onClick={onCreate} disabled={isPending || !projectId || !name}>
        Create profile
      </button>

      {pendingToken ? (
        <div role="status" aria-live="polite">
          <h2>One-time access token</h2>
          <p>Copy now — it will not be shown again.</p>
          <pre>{pendingToken}</pre>
          <h3>Cursor</h3>
          <pre>{cursorMcpConfig(mcpPublicEndpoint || "/mcp", pendingToken)}</pre>
          <h3>Claude Code</h3>
          <pre>
            {claudeCodeMcpConfig(mcpPublicEndpoint || "/mcp", pendingToken)}
          </pre>
          <button type="button" onClick={() => setPendingToken(null)}>
            Dismiss token
          </button>
        </div>
      ) : null}

      <h2>Profiles</h2>
      <ul>
        {profiles.map((profile) => (
          <li key={profile.profile_id}>
            <button type="button" onClick={() => setSelectedId(profile.profile_id)}>
              {profile.name} ({profile.status}) — {profile.project_id}
            </button>
          </li>
        ))}
      </ul>

      {selected ? (
        <div>
          <h2>Allowlist — {selected.name}</h2>
          <ul>
            {allowlistable.map((tool) => (
              <li key={tool.tool_id}>
                <label>
                  <input
                    type="checkbox"
                    checked={selected.allowlist.includes(tool.tool_id)}
                    disabled={selected.status !== "active"}
                    onChange={(event) =>
                      onToggleTool(tool.tool_id, event.target.checked)
                    }
                  />
                  {tool.tool_id}
                  {tool.side_effecting ? " (side-effecting, HITL required)" : ""}
                </label>
              </li>
            ))}
          </ul>
          {tools?.tools
            .filter((tool) => !tool.allowlistable)
            .map((tool) => (
              <p key={tool.tool_id}>
                {tool.tool_id}: unavailable — {tool.unavailable_reason}
              </p>
            ))}
          <button
            type="button"
            disabled={selected.status === "revoked"}
            onClick={() => setRevokeTarget(selected.profile_id)}
          >
            Revoke profile
          </button>
        </div>
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
