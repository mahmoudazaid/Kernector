"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useTransition,
} from "react";
import { LoadingState } from "@/components/states/LoadingState";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { SoftDatePicker } from "@/components/ui/SoftDatePicker";
import { SoftSelect } from "@/components/ui/SoftSelect";
import { formatTimestamp } from "@/lib/format/timestamp";
import {
  createMcpProfile,
  listMcpProfiles,
  listMcpTools,
  mcpClientConfig,
  revokeMcpProfile,
  updateMcpAllowlist,
  type McpAccessProfileResponse,
  type McpToolCatalogResponse,
} from "@/lib/api/mcp-profiles";
import {
  listProjects,
  type ProjectResponse,
} from "@/lib/api/projects";

export type McpAccessPanelProps = {
  mcpPublicEndpoint: string;
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
      tools: McpToolCatalogResponse;
    };

const MAX_EXPIRY_DAYS = 365;
const EXPIRY_PRESET_DAYS = [7, 30, 60, 90] as const;
const EXPIRY_CUSTOM = "Custom…";
const EXPIRY_NONE = "No expiration";

function projectLabel(project: ProjectResponse): string {
  return `${project.name} (${project.slug})`;
}

function ymdPlusDays(days: number): string {
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/** Calendar day label from ``YYYY-MM-DD`` via Instrument timestamp format. */
function formatDayLabel(ymd: string): string {
  return formatTimestamp(`${ymd}T12:00:00`).replace(/,.*$/, "");
}

function expiryPresetLabel(days: number): string {
  return `${days} days (${formatDayLabel(ymdPlusDays(days))})`;
}

/**
 * Resolve expiry SoftSelect choice to ISO start-of-day (invalid that day),
 * or null for lifetime.
 */
function expiresAtFromChoice(
  choice: string,
  customYmd: string,
): string | null {
  if (choice === EXPIRY_NONE) return null;
  let ymd: string | null = null;
  if (choice === EXPIRY_CUSTOM) {
    ymd = parseCustomExpiryYmd(customYmd);
  } else {
    const match = /^(\d+) days/.exec(choice);
    if (!match) return null;
    ymd = ymdPlusDays(Number(match[1]));
  }
  if (!ymd) return null;
  const start = new Date(`${ymd}T00:00:00`);
  if (Number.isNaN(start.getTime())) return null;
  return start.toISOString();
}

/** Accept ``YYYY-MM-DD`` from tomorrow through +365 days. */
function parseCustomExpiryYmd(value: string): string | null {
  const ymd = value.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(ymd)) return null;
  const min = ymdPlusDays(1);
  const max = ymdPlusDays(MAX_EXPIRY_DAYS);
  if (ymd < min || ymd > max) return null;
  const parsed = new Date(`${ymd}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return null;
  return ymd;
}

function DeleteToolIcon() {
  return (
    <svg
      className="kern-mcp-tool-delete-icon"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M7.5 4.5h5M5 6.5h10M8.25 6.5v7.25M11.75 6.5v7.25M7 6.5l.5 8.25h5l.5-8.25"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg
      className="kern-mcp-copy-icon"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="7"
        y="7"
        width="9"
        height="9"
        rx="1.5"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path
        d="M13 7V5.5A1.5 1.5 0 0 0 11.5 4h-7A1.5 1.5 0 0 0 3 5.5v7A1.5 1.5 0 0 0 4.5 14H6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function useCopiedFlag(resetMs = 1500) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), resetMs);
    return () => window.clearTimeout(timer);
  }, [copied, resetMs]);
  return {
    copied,
    copy(text: string) {
      void navigator.clipboard.writeText(text).then(
        () => setCopied(true),
        () => setCopied(false),
      );
    },
  };
}

type ToolCatalogItem = McpToolCatalogResponse["tools"][number];

function ToolsPermissionPanel({
  selectedIds,
  allowlistable,
  unavailable,
  onToggle,
  disabled,
  emptyTitle = "No tools added yet",
  emptyBody = "Tool permissions permit access to specific MCP tools on this server. Tokens start with an empty allowlist until you add tools.",
}: {
  selectedIds: string[];
  allowlistable: ToolCatalogItem[];
  unavailable: ToolCatalogItem[];
  onToggle: (toolId: string, enabled: boolean) => void;
  disabled?: boolean;
  emptyTitle?: string;
  emptyBody?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="kern-mcp-perm" aria-label="Tool permissions" ref={rootRef}>
      <div className="kern-mcp-perm-head">
        <div className="kern-mcp-perm-tab" aria-current="true">
          <span className="kern-mcp-perm-tab-label">Tools</span>
          <span
            className="kern-mcp-perm-count"
            aria-label={`${selectedIds.length} tools`}
          >
            {selectedIds.length}
          </span>
        </div>
        <div className="kern-mcp-perm-add">
          <Button
            variant="secondary"
            disabled={disabled || allowlistable.length === 0}
            aria-haspopup="listbox"
            aria-expanded={open}
            aria-controls={menuId}
            onClick={() => setOpen((current) => !current)}
          >
            + Add tools
          </Button>
          {open ? (
            <div
              id={menuId}
              className="kern-mcp-perm-menu"
              role="listbox"
              aria-multiselectable="true"
              aria-label="Allowlistable tools"
            >
              {allowlistable.length === 0 ? (
                <p className="kern-settings-hint">
                  No allowlistable tools are available on this server.
                </p>
              ) : (
                allowlistable.map((tool) => {
                  const selected = selectedIds.includes(tool.tool_id);
                  return (
                    <label
                      key={tool.tool_id}
                      className={[
                        "kern-settings-radio",
                        selected ? "is-selected" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      role="option"
                      aria-selected={selected}
                    >
                      <input
                        type="checkbox"
                        checked={selected}
                        disabled={disabled}
                        onChange={(event) =>
                          onToggle(tool.tool_id, event.target.checked)
                        }
                      />
                      <span>
                        {tool.tool_id}
                        {tool.side_effecting
                          ? " (side-effecting, HITL required)"
                          : ""}
                      </span>
                    </label>
                  );
                })
              )}
              {unavailable.map((tool) => (
                <p key={tool.tool_id} className="kern-settings-hint">
                  <code>{tool.tool_id}</code>: unavailable —{" "}
                  {tool.unavailable_reason}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      {selectedIds.length === 0 ? (
        <div className="kern-mcp-perm-empty">
          <div className="kern-mcp-perm-empty-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="40" height="40" fill="none">
              <path
                d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <h3>{emptyTitle}</h3>
          <p>{emptyBody}</p>
        </div>
      ) : (
        <ul className="kern-mcp-perm-list">
          {selectedIds.map((toolId) => (
            <li key={toolId}>
              <code>{toolId}</code>
              <button
                type="button"
                className="kern-mcp-tool-delete"
                disabled={disabled}
                aria-label={`Remove ${toolId}`}
                onClick={() => onToggle(toolId, false)}
              >
                <DeleteToolIcon />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function McpTokenCallout({
  token,
  endpoint,
  tokenName,
  description,
  onDismiss,
}: {
  token: string;
  endpoint: string;
  tokenName: string;
  description: string;
  onDismiss: () => void;
}) {
  const tokenCopy = useCopiedFlag();
  const configCopy = useCopiedFlag();
  const config = mcpClientConfig(endpoint, token);

  return (
    <div
      className="kern-settings-callout kern-settings-callout--ok"
      role="status"
      aria-live="polite"
    >
      <h2>Make sure to copy your token now</h2>
      <p className="kern-settings-hint">
        You will not be able to see <strong>{tokenName}</strong> again. Paste
        the client config into mcp.json for Cursor or Claude Code.
      </p>
      {description ? (
        <p className="kern-settings-hint">{description}</p>
      ) : null}
      <div className="kern-settings-field">
        <p className="kern-settings-help">Token</p>
        <div className="kern-mcp-token-field">
          <input
            className="kern-settings-input"
            type="text"
            readOnly
            value={token}
            aria-label="One-time access token"
            onFocus={(event) => event.currentTarget.select()}
          />
          <button
            type="button"
            className="kern-mcp-copy-btn"
            aria-label={tokenCopy.copied ? "Token copied" : "Copy token"}
            onClick={() => tokenCopy.copy(token)}
          >
            <CopyIcon />
          </button>
        </div>
      </div>
      <div className="kern-settings-field">
        <p className="kern-settings-help">Client config</p>
        <div className="kern-mcp-snippet-wrap">
          <pre className="kern-mcp-snippet">{config}</pre>
          <button
            type="button"
            className="kern-mcp-copy-btn kern-mcp-snippet-copy"
            aria-label={
              configCopy.copied ? "Client config copied" : "Copy client config"
            }
            onClick={() => configCopy.copy(config)}
          >
            <CopyIcon />
          </button>
        </div>
      </div>
      <Button variant="secondary" onClick={onDismiss}>
        Done
      </Button>
    </div>
  );
}

function expirySummary(expiresAt: string | null): string {
  if (!expiresAt) return "This token has no expiration date.";
  return `Expires ${formatTimestamp(expiresAt)}`;
}

export function McpAccessPanel({
  mcpPublicEndpoint,
  loadTools = listMcpTools,
  loadProfiles = listMcpProfiles,
  loadProjects = listProjects,
  createProfile = createMcpProfile,
  saveAllowlist = updateMcpAllowlist,
  revokeProfile = revokeMcpProfile,
}: McpAccessPanelProps) {
  const [loadView, setLoadView] = useState<LoadView>({ kind: "loading" });
  const [screen, setScreen] = useState<"list" | "create">("list");
  const [profiles, setProfiles] = useState<McpAccessProfileResponse[]>([]);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingToken, setPendingToken] = useState<string | null>(null);
  const [pendingTokenName, setPendingTokenName] = useState("");
  const [pendingTokenDescription, setPendingTokenDescription] = useState("");
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [expiryChoice, setExpiryChoice] = useState(() => expiryPresetLabel(30));
  const [customExpiryYmd, setCustomExpiryYmd] = useState(() =>
    ymdPlusDays(30),
  );
  const [draftTools, setDraftTools] = useState<string[]>([]);
  const [revokeTarget, setRevokeTarget] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [reloadNonce, setReloadNonce] = useState(0);

  const expiryOptions = useMemo(
    () => [
      ...EXPIRY_PRESET_DAYS.map((days) => expiryPresetLabel(days)),
      EXPIRY_CUSTOM,
      EXPIRY_NONE,
    ],
    [],
  );

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
        const [toolCatalog, profileList, projectList] = await Promise.all([
          loadTools(),
          loadProfiles(),
          loadProjects(),
        ]);
        if (cancelled) return;
        setProfiles(profileList);
        setProjects(projectList);
        setProjectId((current) => {
          if (current && projectList.some((item) => item.project_id === current)) {
            return current;
          }
          return projectList[0]?.project_id ?? "";
        });
        setLoadView({
          kind: "ready",
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
  }, [loadTools, loadProfiles, loadProjects, reloadNonce]);

  const allowlistable =
    loadView.kind === "ready"
      ? loadView.tools.tools.filter((tool) => tool.allowlistable)
      : [];
  const unavailable =
    loadView.kind === "ready"
      ? loadView.tools.tools.filter((tool) => !tool.allowlistable)
      : [];
  const endpoint = mcpPublicEndpoint || "/mcp";

  const customYmdParsed = parseCustomExpiryYmd(customExpiryYmd);
  const expiryHintYmd =
    expiryChoice === EXPIRY_NONE
      ? ""
      : expiryChoice === EXPIRY_CUSTOM
        ? (customYmdParsed ?? "")
        : (() => {
            const match = /^(\d+) days/.exec(expiryChoice);
            return match ? ymdPlusDays(Number(match[1])) : "";
          })();
  const customDateMin = ymdPlusDays(1);
  const customDateMax = ymdPlusDays(MAX_EXPIRY_DAYS);

  function resetCreateForm() {
    setName("");
    setDescription("");
    setExpiryChoice(expiryPresetLabel(30));
    setCustomExpiryYmd(ymdPlusDays(30));
    setDraftTools([]);
  }

  function openCreate() {
    resetCreateForm();
    setPendingToken(null);
    setPendingTokenName("");
    setPendingTokenDescription("");
    setActionError(null);
    setScreen("create");
  }

  function cancelCreate() {
    resetCreateForm();
    setActionError(null);
    setScreen("list");
  }

  function onCreate() {
    if (!projectId.trim()) {
      setActionError("Select a project before creating a token.");
      return;
    }
    if (expiryChoice === EXPIRY_CUSTOM && customYmdParsed === null) {
      setActionError(
        `Pick a custom expiration date between ${formatDayLabel(customDateMin)} and ${formatDayLabel(customDateMax)}.`,
      );
      return;
    }
    const toolsToGrant = [...draftTools];
    const tokenName = name.trim();
    const tokenDescription = description.trim();
    startTransition(async () => {
      try {
        const created = await createProfile({
          project_id: projectId.trim(),
          name: tokenName,
          expires_at: expiresAtFromChoice(expiryChoice, customExpiryYmd),
          description: tokenDescription,
        });
        let profile = created.profile;
        if (toolsToGrant.length > 0) {
          profile = await saveAllowlist(
            created.profile.profile_id,
            toolsToGrant.toSorted(),
          );
        }
        setPendingToken(created.plaintext_token);
        setPendingTokenName(tokenName);
        setPendingTokenDescription(
          profile.description?.trim() || tokenDescription,
        );
        setProfiles((prev) => [profile, ...prev]);
        resetCreateForm();
        setActionError(null);
        setScreen("list");
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Create failed");
      }
    });
  }

  function onToggleDraftTool(toolId: string, enabled: boolean) {
    setDraftTools((current) => {
      const next = new Set(current);
      if (enabled) next.add(toolId);
      else next.delete(toolId);
      return [...next].sort();
    });
  }

  function confirmRevoke() {
    if (!revokeTarget) return;
    const target = revokeTarget;
    setRevokeTarget(null);
    startTransition(async () => {
      try {
        await revokeProfile(target);
        setProfiles((prev) =>
          prev.filter((item) => item.profile_id !== target),
        );
        setPendingToken(null);
        setPendingTokenName("");
        setPendingTokenDescription("");
        setActionError(null);
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Revoke failed");
      }
    });
  }

  const visibleProfiles = profiles.filter(
    (profile) => profile.status !== "revoked",
  );

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

  const formDisabled = projects.length === 0;

  if (screen === "create") {
    return (
      <section
        className="kern-settings kern-mcp-settings"
        aria-labelledby="mcp-access-heading"
      >
        <h1 id="mcp-access-heading">New MCP access token</h1>
        <p className="kern-settings-lead">
          Create a project-scoped token for Cursor or Claude Code. After
          generation the secret is shown once and cannot be retrieved again.
        </p>

        {actionError ? (
          <div
            className="kern-settings-callout kern-settings-callout--error"
            role="alert"
          >
            <p>{actionError}</p>
          </div>
        ) : null}

        <fieldset className="kern-settings-fieldset">
          <legend>Create token</legend>
          <div className="kern-settings-stack">
            {projects.length === 0 ? (
              <div
                className="kern-settings-callout kern-settings-callout--warn"
                role="status"
              >
                <p>
                  No projects in this workspace yet. Create a project first, then
                  refresh this page to issue an MCP token.
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
              <label htmlFor="mcp-token-name">Token name *</label>
              <input
                id="mcp-token-name"
                className="kern-settings-input"
                value={name}
                onChange={(event) => setName(event.target.value)}
                autoComplete="off"
                disabled={formDisabled}
                required
              />
              <p className="kern-settings-hint">
                A unique name for this token. May be visible to workspace admins
                or anyone with the token (for example <code>cursor</code>).
              </p>
            </div>

            <div className="kern-settings-field">
              <label htmlFor="mcp-token-description">Description</label>
              <textarea
                id="mcp-token-description"
                className="kern-settings-input kern-settings-textarea"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
                disabled={formDisabled}
                placeholder="Optional note for your team"
              />
              <p className="kern-settings-hint">
                Optional. Shown on the token list for your team.
              </p>
            </div>

            <div className="kern-mcp-expiry-row">
              <div className="kern-mcp-expiry-col">
                <label htmlFor="mcp-token-expires">Expiration</label>
                <SoftSelect
                  id="mcp-token-expires"
                  label="Expiration"
                  hideLabel
                  value={
                    expiryOptions.includes(expiryChoice)
                      ? expiryChoice
                      : expiryPresetLabel(30)
                  }
                  options={expiryOptions}
                  onChange={(next) => {
                    setExpiryChoice(next);
                    if (next === EXPIRY_CUSTOM && !customExpiryYmd.trim()) {
                      setCustomExpiryYmd(ymdPlusDays(30));
                    }
                    setActionError(null);
                  }}
                />
              </div>
              {expiryChoice === EXPIRY_CUSTOM ? (
                <div className="kern-mcp-expiry-col">
                  <label htmlFor="mcp-token-expires-custom">Select date *</label>
                  <SoftDatePicker
                    id="mcp-token-expires-custom"
                    label="Select date"
                    hideLabel
                    min={customDateMin}
                    max={customDateMax}
                    value={customExpiryYmd}
                    onChange={(next) => {
                      setCustomExpiryYmd(next);
                      setActionError(null);
                    }}
                    disabled={formDisabled}
                  />
                </div>
              ) : null}
            </div>
            <p
              id="mcp-token-expires-hint"
              className={
                expiryChoice === EXPIRY_NONE
                  ? "kern-settings-hint kern-settings-hint--warn"
                  : expiryChoice === EXPIRY_CUSTOM &&
                      customExpiryYmd.trim() !== "" &&
                      customYmdParsed === null
                    ? "kern-settings-hint kern-settings-hint--error"
                    : "kern-settings-hint"
              }
              role={
                expiryChoice === EXPIRY_NONE ||
                (expiryChoice === EXPIRY_CUSTOM &&
                  customExpiryYmd.trim() !== "" &&
                  customYmdParsed === null)
                  ? "alert"
                  : undefined
              }
            >
              {expiryChoice === EXPIRY_NONE
                ? "Kernector strongly recommends setting an expiration date to help keep access secure."
                : expiryChoice === EXPIRY_CUSTOM &&
                    customExpiryYmd.trim() !== "" &&
                    customYmdParsed === null
                  ? `Pick a date between ${formatDayLabel(customDateMin)} and ${formatDayLabel(customDateMax)}.`
                  : expiryHintYmd
                    ? `The token is invalid from the start of ${formatDayLabel(expiryHintYmd)}.`
                    : "The token will expire on the selected date."}
            </p>

            <ToolsPermissionPanel
              selectedIds={draftTools}
              allowlistable={allowlistable}
              unavailable={unavailable}
              onToggle={onToggleDraftTool}
              disabled={formDisabled || isPending}
            />

            <div className="kern-mcp-create-actions">
              <Button
                onClick={onCreate}
                disabled={
                  isPending || formDisabled || !projectId || !name.trim()
                }
              >
                Generate token
              </Button>
              <Button variant="secondary" disabled={isPending} onClick={cancelCreate}>
                Cancel
              </Button>
            </div>
            <p className="kern-settings-hint">
              This token will be ready for use immediately. The secret is shown
              once after generation.
            </p>
          </div>
        </fieldset>
      </section>
    );
  }

  return (
    <section
      className="kern-settings kern-mcp-settings"
      aria-labelledby="mcp-access-heading"
    >
      <div className="kern-mcp-list-head">
        <h1 id="mcp-access-heading">MCP access tokens</h1>
        <Button onClick={openCreate}>Generate new token</Button>
      </div>
      <p className="kern-settings-lead">
        Project-scoped tokens. Secrets are never shown
        again after creation — delete and create a new token if needed.
      </p>

      {actionError ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{actionError}</p>
        </div>
      ) : null}

      {pendingToken ? (
        <McpTokenCallout
          token={pendingToken}
          endpoint={endpoint}
          tokenName={pendingTokenName || "this token"}
          description={pendingTokenDescription}
          onDismiss={() => {
            setPendingToken(null);
            setPendingTokenName("");
            setPendingTokenDescription("");
          }}
        />
      ) : null}

      <fieldset className="kern-settings-fieldset">
        <legend>Tokens</legend>
        {visibleProfiles.length === 0 ? (
          <p className="kern-settings-hint">No tokens yet.</p>
        ) : (
          <ul className="kern-mcp-token-list" aria-label="Tokens">
            {visibleProfiles.map((profile) => {
              const projectName =
                projectLabelById.get(profile.project_id) ?? profile.project_id;
              const note = profile.description?.trim() ?? "";
              return (
                <li key={profile.profile_id} className="kern-mcp-token-item">
                  <div className="kern-mcp-token-item-main">
                    <div className="kern-mcp-token-item-title">
                      <span className="kern-mcp-token-name">{profile.name}</span>
                    </div>
                    {note ? (
                      <p className="kern-settings-hint">{note}</p>
                    ) : null}
                    <p className="kern-settings-hint">{projectName}</p>
                    <p className="kern-settings-hint">
                      {expirySummary(profile.expires_at)}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="kern-mcp-tool-delete"
                    aria-label={`Delete ${profile.name}`}
                    disabled={isPending}
                    onClick={() => setRevokeTarget(profile.profile_id)}
                  >
                    <DeleteToolIcon />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </fieldset>

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Delete MCP token?"
        description="Deleted tokens cannot authenticate. This cannot be undone."
        confirmLabel="Delete"
        tone="danger"
        busy={isPending}
        onConfirm={confirmRevoke}
        onCancel={() => setRevokeTarget(null)}
      />
    </section>
  );
}
