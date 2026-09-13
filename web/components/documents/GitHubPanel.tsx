"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Loader } from "@/components/ui/Loader";
import {
  disconnectGitHub,
  getGitHubStatus,
  githubOAuthStartUrl,
  syncGitHub,
  type DisconnectGitHubOptions,
  type GetGitHubStatusOptions,
  type GitHubStatusResponse,
  type SyncGitHubOptions,
} from "@/lib/api/connectors";
import { ApiError, isAbortError } from "@/lib/api/errors";
import { formatTimestamp } from "@/lib/format/timestamp";
import { consumeGithubCallback } from "@/lib/documents/github-callback";

export type GitHubPanelProps = {
  apiBaseUrl: string;
  oauthCallback?: string | null;
  getStatus?: (
    options: GetGitHubStatusOptions,
  ) => Promise<GitHubStatusResponse>;
  syncNow?: (options: SyncGitHubOptions) => Promise<unknown>;
  disconnect?: (options: DisconnectGitHubOptions) => Promise<void>;
  onConnectionChange?: (connected: boolean) => void;
  onCatalogChange?: () => void;
  reloadToken?: number;
  onOAuthCallbackConsumed?: () => void;
};

type StatusView =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; status: GitHubStatusResponse };

const ABORT_COPY =
  "The sync request was cancelled or timed out. The run may still be in progress on the server.";

const CALLBACK_ERRORS: Record<string, string> = {
  denied:
    "GitHub authorization was cancelled. You can try connecting again.",
  error: "GitHub authorization failed. Start Connect again.",
  invalid_state:
    "This GitHub authorization link is no longer valid. Start Connect again.",
  unconfigured: "GitHub OAuth is not configured on the server.",
};

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  return "The request failed. Please try again later.";
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M10 2.8a7.2 7.2 0 0 0-2.28 14.03c.36.07.5-.16.5-.35v-1.23c-2.03.44-2.46-.87-2.46-.87-.33-.84-.8-1.07-.8-1.07-.66-.45.05-.44.05-.44.73.05 1.11.75 1.11.75.65 1.11 1.7.79 2.12.6.06-.47.25-.79.46-.97-1.62-.18-3.32-.81-3.32-3.6 0-.8.28-1.45.75-1.96-.08-.18-.33-.92.07-1.91 0 0 .61-.2 2 .75a6.9 6.9 0 0 1 3.64 0c1.39-.95 2-.75 2-.75.4 1 .15 1.73.07 1.91.47.51.75 1.16.75 1.96 0 2.8-1.7 3.42-3.33 3.6.26.22.5.67.5 1.35v2c0 .2.13.42.5.35A7.2 7.2 0 0 0 10 2.8Z"
        fill="currentColor"
      />
    </svg>
  );
}

export function GitHubPanel({
  apiBaseUrl,
  getStatus = getGitHubStatus,
  syncNow = syncGitHub,
  disconnect = disconnectGitHub,
  onConnectionChange,
  onCatalogChange,
  reloadToken = 0,
  oauthCallback = null,
  onOAuthCallbackConsumed,
}: GitHubPanelProps) {
  const [view, setView] = useState<StatusView>({ kind: "loading" });
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const busyRef = useRef(false);
  const onConnectionChangeRef = useRef(onConnectionChange);
  const onCatalogChangeRef = useRef(onCatalogChange);
  const onOAuthCallbackConsumedRef = useRef(onOAuthCallbackConsumed);

  useEffect(() => {
    onConnectionChangeRef.current = onConnectionChange;
    onCatalogChangeRef.current = onCatalogChange;
    onOAuthCallbackConsumedRef.current = onOAuthCallbackConsumed;
  });

  async function loadStatus(): Promise<GitHubStatusResponse | null> {
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
    let ignore = false;
    void (async () => {
      await loadStatus();
      if (ignore) {
        return;
      }
    })();
    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, []);

  useEffect(() => {
    if (oauthCallback == null) {
      return;
    }
    const github = oauthCallback;
    consumeGithubCallback();
    onOAuthCallbackConsumedRef.current?.();
    if (github === "connected") {
      void loadStatus();
    } else {
      setActionError(CALLBACK_ERRORS[github] ?? CALLBACK_ERRORS.error);
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

  const connected = view.kind === "ready" && view.status.connected;

  useEffect(() => {
    if (view.kind === "loading") {
      return;
    }
    onConnectionChangeRef.current?.(connected);
  }, [connected, view.kind]);

  async function onSync() {
    if (busyRef.current) {
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    try {
      await syncNow({ baseUrl: apiBaseUrl });
      await loadStatus();
      onCatalogChangeRef.current?.();
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

  async function onDisconnect() {
    if (busyRef.current) {
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    try {
      await disconnect({ baseUrl: apiBaseUrl });
      setConfirmOpen(false);
      await loadStatus();
      onCatalogChangeRef.current?.();
    } catch (error) {
      setActionError(actionErrorMessage(error));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  const status = view.kind === "ready" ? view.status : null;
  const reauth = Boolean(status?.reauthorization_required);
  const oauthStartHref = githubOAuthStartUrl(apiBaseUrl);
  const statusLabel =
    view.kind === "loading"
      ? "Checking"
      : view.kind === "error"
        ? "Unavailable"
        : reauth
          ? "Reconnect required"
          : status?.connected
            ? "Connected"
            : "Available";

  const lastSync = status?.last_sync ?? null;
  const failedCount = lastSync?.failed_count ?? 0;
  const alertMessage =
    view.kind === "error"
      ? view.message
      : (actionError ??
        (reauth
          ? "GitHub authorization was revoked. Connect again."
          : null));

  function onConnectClick(event: MouseEvent<HTMLAnchorElement>) {
    if (status !== null && !status.oauth_ready) {
      event.preventDefault();
      setActionError("GitHub OAuth is not configured on the server.");
      return;
    }
    if (status !== null && !(status.owner && status.repo)) {
      event.preventDefault();
      setActionError(
        "Set GITHUB_OWNER and GITHUB_REPO on the server before connecting.",
      );
      return;
    }
    setRedirecting(true);
  }

  const connectControl = (
    <a className="kern-btn" href={oauthStartHref} onClick={onConnectClick}>
      {redirecting ? "Redirecting to GitHub…" : "Connect"}
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
            <GitHubIcon />
          </span>
          <div className="kern-available-copy">
            <h3>GitHub</h3>
            <p className="kern-source-kind">Sign in with your GitHub account</p>
          </div>
          {view.kind === "loading" ? (
            <p className="visually-hidden" role="status">
              Loading GitHub…
            </p>
          ) : null}
          {connectControl}
        </article>
      </div>
    );
  }

  const syncDisabled = busy || reauth;
  const repoLabel =
    status?.owner && status?.repo
      ? `${status.owner}/${status.repo}`
      : "Configured repository";

  return (
    <article className="kern-source-card" aria-busy={busy}>
      {busy ? (
        <div className="kern-source-busy-overlay">
          <Loader label="Syncing GitHub" size="sm" />
        </div>
      ) : null}
      <div className="kern-source-card-title">
        <div className="kern-source-name">
          <span className="kern-source-icon">
            <GitHubIcon />
          </span>
          <div>
            <h3>GitHub</h3>
            <p className="kern-source-kind">Repository knowledge</p>
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

      <div className="kern-source-metrics">
        <div>
          <span className="kern-metric-label">Account</span>
          <span className="kern-metric-value">
            {status?.account_login ?? "Connected account"}
          </span>
        </div>
        <div>
          <span className="kern-metric-label">Repository</span>
          <span className="kern-metric-value">{repoLabel}</span>
        </div>
        <div>
          <span className="kern-metric-label">Indexed</span>
          <span className="kern-metric-value">
            {status?.document_count ?? 0}
          </span>
        </div>
      </div>
      <div className="kern-sync-section" role="status">
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
              ? "1 document failed to index. See Documents."
              : `${failedCount} documents failed to index. See Documents.`}
          </p>
        </div>
      ) : null}

      <div className="kern-source-actions is-split">
        <div className="kern-action-group">
          {reauth ? (
            connectControl
          ) : (
            <Button
              type="button"
              variant="secondary"
              disabled={syncDisabled}
              onClick={() => void onSync()}
            >
              Sync
            </Button>
          )}
        </div>
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => setConfirmOpen(true)}
        >
          Disconnect
        </Button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="Disconnect GitHub?"
        description="This removes the stored GitHub grant from this workspace. Indexed documents stay until you delete them or the next sync reconciles removals."
        confirmLabel="Disconnect"
        cancelLabel="Cancel"
        busy={busy}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => void onDisconnect()}
      />
    </article>
  );
}
