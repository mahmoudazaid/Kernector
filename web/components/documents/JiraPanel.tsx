"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { JiraPicker } from "@/components/documents/JiraPicker";
import { Loader } from "@/components/ui/Loader";
import {
  disconnectJira,
  getJiraStatus,
  jiraOAuthStartUrl,
  listJiraProjects,
  listJiraSites,
  putJiraSelection,
  putJiraSite,
  syncJira,
  type DisconnectJiraOptions,
  type GetJiraStatusOptions,
  type JiraProjectPageResponse,
  type JiraSelectionResponse,
  type JiraSiteListResponse,
  type JiraStatusResponse,
  type ListJiraProjectsOptions,
  type ListJiraSitesOptions,
  type PutJiraSelectionOptions,
  type PutJiraSiteOptions,
  type SyncJiraOptions,
} from "@/lib/api/connectors";
import { ApiError, isAbortError } from "@/lib/api/errors";
import { formatTimestamp } from "@/lib/format/timestamp";
import { consumeJiraCallback } from "@/lib/documents/jira-callback";

export type JiraPanelProps = {
  apiBaseUrl: string;
  oauthCallback?: string | null;
  getStatus?: (options: GetJiraStatusOptions) => Promise<JiraStatusResponse>;
  listSites?: (options: ListJiraSitesOptions) => Promise<JiraSiteListResponse>;
  selectSite?: (options: PutJiraSiteOptions) => Promise<JiraSelectionResponse>;
  listProjects?: (
    options: ListJiraProjectsOptions,
  ) => Promise<JiraProjectPageResponse>;
  saveSelection?: (
    options: PutJiraSelectionOptions,
  ) => Promise<JiraSelectionResponse>;
  syncNow?: (options: SyncJiraOptions) => Promise<unknown>;
  disconnect?: (options: DisconnectJiraOptions) => Promise<void>;
  onConnectionChange?: (connected: boolean) => void;
  onCatalogChange?: () => void;
  reloadToken?: number;
  onOAuthCallbackConsumed?: () => void;
};

type StatusView =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; status: JiraStatusResponse };

const NO_KEYS: string[] = [];

const ABORT_COPY =
  "The sync request was cancelled or timed out. The run may still be in progress on the server.";

const CALLBACK_ERRORS: Record<string, string> = {
  denied: "Jira authorization was cancelled. You can try connecting again.",
  error: "Jira authorization failed. Start Connect again.",
  invalid_state:
    "This Jira authorization link is no longer valid. Start Connect again.",
  unconfigured: "Jira OAuth is not configured on the server.",
  no_site:
    "This Atlassian account has no Jira Cloud site this app can read. Check site access, then connect again.",
};

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  return "The request failed. Please try again later.";
}

function purgeProjectsDescription(dropped: string[]): string {
  const noun = dropped.length === 1 ? "project" : "projects";
  const determiner = dropped.length === 1 ? "its" : "their";
  return `Removing ${noun} ${dropped.join(", ")} will delete ${determiner} synced issues from the knowledge base. This cannot be undone from here.`;
}

export function JiraIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M10 2.5 17.5 10 10 17.5 2.5 10 10 2.5Zm0 4.2L6.7 10l3.3 3.3 3.3-3.3L10 6.7Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function JiraPanel({
  apiBaseUrl,
  getStatus = getJiraStatus,
  listSites = listJiraSites,
  selectSite = putJiraSite,
  listProjects = listJiraProjects,
  saveSelection = putJiraSelection,
  syncNow = syncJira,
  disconnect = disconnectJira,
  onConnectionChange,
  onCatalogChange,
  reloadToken = 0,
  oauthCallback = null,
  onOAuthCallbackConsumed,
}: JiraPanelProps) {
  const [view, setView] = useState<StatusView>({ kind: "loading" });
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerNotice, setPickerNotice] = useState<string | null>(null);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [pendingKeys, setPendingKeys] = useState<string[] | null>(null);
  const [pendingDrops, setPendingDrops] = useState<string[]>([]);
  const [pendingSite, setPendingSite] = useState<string | null>(null);
  const busyRef = useRef(false);
  const onConnectionChangeRef = useRef(onConnectionChange);
  const onCatalogChangeRef = useRef(onCatalogChange);
  const onOAuthCallbackConsumedRef = useRef(onOAuthCallbackConsumed);

  useEffect(() => {
    onConnectionChangeRef.current = onConnectionChange;
    onCatalogChangeRef.current = onCatalogChange;
    onOAuthCallbackConsumedRef.current = onOAuthCallbackConsumed;
  });

  async function loadStatus(): Promise<JiraStatusResponse | null> {
    try {
      const status = await getStatus({ baseUrl: apiBaseUrl });
      setView({ kind: "ready", status });
      return status;
    } catch (error) {
      setView({ kind: "error", message: actionErrorMessage(error) });
      return null;
    }
  }

  useEffect(() => {
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, []);

  useEffect(() => {
    if (oauthCallback == null) {
      return;
    }
    const jira = oauthCallback;
    consumeJiraCallback();
    onOAuthCallbackConsumedRef.current?.();
    if (jira === "connected") {
      setPickerOpen(true);
      void loadStatus();
    } else {
      setActionError(CALLBACK_ERRORS[jira] ?? CALLBACK_ERRORS.error);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- callback token
  }, [oauthCallback]);

  useEffect(() => {
    if (reloadToken === 0) {
      return;
    }
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- parent nonce
  }, [reloadToken]);

  const status = view.kind === "ready" ? view.status : null;
  const connected = Boolean(status?.connected);
  const documentCount = status?.document_count ?? 0;
  const currentKeys = status?.project_keys ?? NO_KEYS;

  useEffect(() => {
    if (view.kind === "loading") {
      return;
    }
    onConnectionChangeRef.current?.(connected);
  }, [connected, view.kind]);

  async function runBusy(action: () => Promise<void>) {
    if (busyRef.current) {
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    try {
      await action();
    } catch (error) {
      if (isAbortError(error)) {
        setActionError(ABORT_COPY);
        void loadStatus();
        onCatalogChangeRef.current?.();
      } else {
        setActionError(actionErrorMessage(error));
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function onSync() {
    if (status?.setup_required || currentKeys.length === 0) {
      setPickerOpen(true);
      return;
    }
    void runBusy(async () => {
      await syncNow({ baseUrl: apiBaseUrl });
      await loadStatus();
      onCatalogChangeRef.current?.();
    });
  }

  function saveProjects(keys: string[]) {
    setPendingKeys(null);
    setPendingDrops([]);
    setPickerOpen(false);
    void runBusy(async () => {
      await saveSelection({ baseUrl: apiBaseUrl, projectKeys: keys });
      if (keys.length > 0) {
        await syncNow({ baseUrl: apiBaseUrl });
      }
      await loadStatus();
      onCatalogChangeRef.current?.();
    });
  }

  function onPickerConfirm(keys: string[]) {
    const next = new Set(keys);
    const dropped = currentKeys.filter((key) => !next.has(key));
    if (dropped.length > 0 && documentCount > 0) {
      setPendingKeys(keys);
      setPendingDrops(dropped);
      return;
    }
    saveProjects(keys);
  }

  function saveSite(cloudId: string) {
    setPendingSite(null);
    setPickerNotice(null);
    void runBusy(async () => {
      try {
        await selectSite({ baseUrl: apiBaseUrl, cloudId });
      } catch (error) {
        setPickerNotice(actionErrorMessage(error));
        return;
      }
      await loadStatus();
      onCatalogChangeRef.current?.();
    });
  }

  function onSelectSite(cloudId: string) {
    const current = status?.site?.cloud_id ?? null;
    if (current && current !== cloudId && documentCount > 0) {
      setPendingSite(cloudId);
      return;
    }
    saveSite(cloudId);
  }

  function onDisconnect() {
    void runBusy(async () => {
      await disconnect({ baseUrl: apiBaseUrl });
      setDisconnectOpen(false);
      setPickerOpen(false);
      await loadStatus();
      onCatalogChangeRef.current?.();
    });
  }

  const reauth = Boolean(status?.reauthorization_required);
  const siteRequired = status?.connection_state === "site_selection_required";
  const setupRequired = Boolean(status?.setup_required);
  const statusLabel =
    view.kind === "loading"
      ? "Checking"
      : view.kind === "error"
        ? "Unavailable"
        : reauth
          ? "Reconnect required"
          : siteRequired
            ? "Choose a site"
            : setupRequired
              ? "Choose projects"
              : connected
                ? "Connected"
                : "Available";

  const lastSync = status?.last_sync ?? null;
  const failedCount = lastSync?.failed_count ?? 0;
  const alertMessage =
    view.kind === "error"
      ? view.message
      : (actionError ??
        (reauth ? "Jira authorization was revoked. Connect again." : null));

  function onConnectClick(event: MouseEvent<HTMLAnchorElement>) {
    if (status !== null && !status.oauth_ready) {
      event.preventDefault();
      setActionError(CALLBACK_ERRORS.unconfigured);
      return;
    }
    setRedirecting(true);
  }

  const connectControl = (
    <a
      className="kern-btn"
      href={jiraOAuthStartUrl(apiBaseUrl)}
      onClick={onConnectClick}
    >
      {redirecting ? "Redirecting to Atlassian…" : "Connect"}
    </a>
  );

  if (!connected) {
    return (
      <div className="kern-drive-available">
        {alertMessage ? (
          <div
            className="kern-settings-callout kern-settings-callout--error kern-drive-available-alert"
            role="alert"
          >
            <p>{alertMessage}</p>
          </div>
        ) : null}
        <article className="kern-available-card">
          <span className="kern-source-icon">
            <JiraIcon />
          </span>
          <div className="kern-available-copy">
            <h3>Jira</h3>
            <p className="kern-source-kind">Sign in with your Atlassian account</p>
          </div>
          {view.kind === "loading" ? (
            <p className="visually-hidden" role="status">
              Loading Jira…
            </p>
          ) : null}
          {connectControl}
        </article>
      </div>
    );
  }

  const cardBusy = busy && !pickerOpen;
  const pendingSiteName = status?.site?.name ?? "the current site";

  return (
    <article className="kern-source-card" aria-busy={cardBusy}>
      {cardBusy ? (
        <div className="kern-source-busy-overlay">
          <Loader label="Syncing Jira" size="sm" />
        </div>
      ) : null}
      <div className="kern-source-card-title">
        <div className="kern-source-name">
          <span className="kern-source-icon">
            <JiraIcon />
          </span>
          <div>
            <h3>Jira</h3>
            <p className="kern-source-kind">Project issues</p>
          </div>
        </div>
        <span className={`kern-source-status${reauth ? " is-muted" : ""}`}>
          {statusLabel}
        </span>
      </div>

      {alertMessage ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{alertMessage}</p>
        </div>
      ) : null}

      {setupRequired && !reauth ? (
        <div
          className="kern-settings-callout kern-settings-callout--warn"
          role="status"
        >
          <p>
            {siteRequired
              ? "Choose a Jira site, then pick projects to sync."
              : "Choose Jira projects to sync before indexing."}
          </p>
        </div>
      ) : null}

      <div className="kern-source-metrics">
        <div>
          <span className="kern-metric-label">Account</span>
          <span className="kern-metric-value">
            {status?.account_name ?? "Connected account"}
          </span>
        </div>
        <div>
          <span className="kern-metric-label">Indexed</span>
          <span className="kern-metric-value">{documentCount}</span>
        </div>
      </div>

      <div className="kern-sync-section" role="status">
        <div className="kern-sync-heading">
          <h3>Site</h3>
          <span className="kern-sync-time">
            {status?.site?.name ?? "Not selected"}
          </span>
        </div>
        <div className="kern-sync-heading">
          <h3>Projects</h3>
          <span className="kern-sync-time">
            {currentKeys.length > 0 ? currentKeys.join(", ") : "Not selected"}
          </span>
        </div>
        <div className="kern-sync-heading">
          <h3>Last synced</h3>
          <time className="kern-sync-time" dateTime={lastSync?.synced_at}>
            {lastSync ? formatTimestamp(lastSync.synced_at) : "Never"}
          </time>
        </div>
      </div>

      {failedCount > 0 ? (
        <div className="kern-settings-callout kern-settings-callout--warn">
          <p>
            {failedCount === 1
              ? "1 issue failed to index. See Documents."
              : `${failedCount} issues failed to index. See Documents.`}
          </p>
        </div>
      ) : null}

      <div className="kern-source-actions is-split">
        <div className="kern-action-group">
          {reauth ? (
            connectControl
          ) : (
            <>
              <Button
                type="button"
                disabled={busy}
                onClick={() => setPickerOpen(true)}
              >
                Browse
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={busy}
                onClick={onSync}
              >
                Sync
              </Button>
            </>
          )}
        </div>
        <Button
          type="button"
          variant="danger"
          disabled={busy}
          onClick={() => setDisconnectOpen(true)}
        >
          Disconnect
        </Button>
      </div>

      {pickerOpen && !reauth ? (
        <JiraPicker
          open
          apiBaseUrl={apiBaseUrl}
          site={status?.site ?? null}
          initialProjectKeys={currentKeys}
          busy={busy}
          listSites={listSites}
          listProjects={listProjects}
          notice={pickerNotice}
          onSelectSite={onSelectSite}
          onConfirm={onPickerConfirm}
          onCancel={() => {
            setPickerNotice(null);
            setPickerOpen(false);
          }}
        />
      ) : null}

      <ConfirmDialog
        open={pendingKeys !== null}
        title="Remove synced Jira documents?"
        description={purgeProjectsDescription(pendingDrops)}
        confirmLabel="Remove"
        cancelLabel="Cancel"
        tone="danger"
        busy={busy}
        onCancel={() => {
          setPendingKeys(null);
          setPendingDrops([]);
        }}
        onConfirm={() => {
          if (pendingKeys !== null) {
            saveProjects(pendingKeys);
          }
        }}
      />

      <ConfirmDialog
        open={pendingSite !== null}
        title="Switch Jira site?"
        description={`Switching away from ${pendingSiteName} clears the project selection and deletes its synced issues from the knowledge base.`}
        confirmLabel="Switch site"
        cancelLabel="Cancel"
        tone="danger"
        busy={busy}
        onCancel={() => setPendingSite(null)}
        onConfirm={() => {
          if (pendingSite !== null) {
            saveSite(pendingSite);
          }
        }}
      />

      <ConfirmDialog
        open={disconnectOpen}
        title="Disconnect Jira?"
        description="This removes the stored Jira grant and deletes synced Jira issues from this workspace. Atlassian has no revoke endpoint; remove the app under your Atlassian account's connected apps to revoke access there."
        confirmLabel="Disconnect"
        cancelLabel="Cancel"
        tone="danger"
        busy={busy}
        onCancel={() => setDisconnectOpen(false)}
        onConfirm={onDisconnect}
      />
    </article>
  );
}
