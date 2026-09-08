"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import {
  disconnectGoogleDrive,
  getGoogleDriveStatus,
  googleDriveOAuthStartUrl,
  syncGoogleDrive,
  type DisconnectGoogleDriveOptions,
  type GetGoogleDriveStatusOptions,
  type GoogleDriveStatusResponse,
  type SyncGoogleDriveOptions,
} from "@/lib/api/connectors";
import { ApiError } from "@/lib/api/errors";

export type GoogleDrivePanelProps = {
  apiBaseUrl: string;
  getStatus?: (
    options: GetGoogleDriveStatusOptions,
  ) => Promise<GoogleDriveStatusResponse>;
  syncNow?: (
    options: SyncGoogleDriveOptions,
  ) => Promise<unknown>;
  disconnect?: (
    options: DisconnectGoogleDriveOptions,
  ) => Promise<void>;
  onConnectionChange?: (connected: boolean) => void;
};

type StatusView =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; status: GoogleDriveStatusResponse };

const ABORT_COPY =
  "The sync request was cancelled or timed out. The run may still be in progress on the server.";

const CALLBACK_ERRORS: Record<string, string> = {
  denied:
    "Google Drive authorization was cancelled. You can try connecting again.",
  error: "Google Drive authorization failed. Start Connect again.",
  invalid_state:
    "This Google Drive authorization link is no longer valid. Start Connect again.",
  unconfigured:
    "Google Drive OAuth is not configured on the server.",
};

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  return "The request failed. Please try again later.";
}

function readDriveCallback(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const params = new URLSearchParams(window.location.search);
  const drive = params.get("drive");
  if (!drive) {
    return null;
  }
  params.delete("drive");
  const query = params.toString();
  const next = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
  window.history.replaceState(null, "", next);
  return drive;
}

function formatLastSync(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function CloudIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M5.5 14.5h8.2c1.6 0 2.8-1.3 2.8-2.8 0-1.4-1-2.5-2.3-2.7A4 4 0 0 0 6.2 8.2 2.8 2.8 0 0 0 5.5 14.5Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function GoogleDrivePanel({
  apiBaseUrl,
  getStatus = getGoogleDriveStatus,
  syncNow = syncGoogleDrive,
  disconnect = disconnectGoogleDrive,
  onConnectionChange,
}: GoogleDrivePanelProps) {
  const [view, setView] = useState<StatusView>({ kind: "loading" });
  const [callbackError, setCallbackError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const busyRef = useRef(false);
  const onConnectionChangeRef = useRef(onConnectionChange);
  onConnectionChangeRef.current = onConnectionChange;

  async function loadStatus() {
    try {
      const status = await getStatus({ baseUrl: apiBaseUrl });
      setView({ kind: "ready", status });
    } catch (error) {
      setView({ kind: "error", message: actionErrorMessage(error) });
    }
  }

  useEffect(() => {
    const drive = readDriveCallback();
    if (drive && drive !== "connected") {
      setCallbackError(CALLBACK_ERRORS[drive] ?? CALLBACK_ERRORS.error);
    }
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, []);

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
    } catch (error) {
      if (error instanceof ApiError && error.code === "aborted") {
        setActionError(ABORT_COPY);
        void loadStatus();
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
    } catch (error) {
      setActionError(actionErrorMessage(error));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  const status = view.kind === "ready" ? view.status : null;
  const reauth = Boolean(status?.reauthorization_required);
  const oauthStartHref = googleDriveOAuthStartUrl(apiBaseUrl);
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
  const alertMessage =
    view.kind === "error"
      ? view.message
      : callbackError ??
        actionError ??
        (reauth
          ? "Google Drive authorization was revoked. Connect again."
          : null);
  function onConnectClick(event: MouseEvent<HTMLAnchorElement>) {
    if (status !== null && !status.oauth_ready) {
      event.preventDefault();
      setActionError("Google Drive OAuth is not configured on the server.");
      return;
    }
    setRedirecting(true);
  }

  const connectControl = (
    <a className="kern-btn" href={oauthStartHref} onClick={onConnectClick}>
      {redirecting ? "Redirecting to Google…" : "Connect"}
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
            <CloudIcon />
          </span>
          <div className="kern-available-copy">
            <h3>Google Drive</h3>
            <p className="kern-source-kind">Sign in with your Google account</p>
          </div>
          {view.kind === "loading" ? (
            <p className="visually-hidden" role="status">
              Loading Google Drive…
            </p>
          ) : null}
          {connectControl}
        </article>
      </div>
    );
  }

  return (
    <article className="kern-source-card">
      <div className="kern-source-card-title">
        <div className="kern-source-name">
          <span className="kern-source-icon">
            <CloudIcon />
          </span>
          <div>
            <h3>Google Drive</h3>
            <p className="kern-source-kind">Cloud connector</p>
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
            {status?.account_email ?? "Connected account"}
          </span>
        </div>
        <div>
          <span className="kern-metric-label">Documents</span>
          <span className="kern-metric-value">{status?.document_count ?? 0}</span>
        </div>
        {status?.folder_count != null ? (
          <div>
            <span className="kern-metric-label">Folders</span>
            <span className="kern-metric-value">{status.folder_count}</span>
          </div>
        ) : null}
      </div>
      <div className="kern-sync-section" role="status">
        <div className="kern-sync-heading">
          <h3>Last sync</h3>
          <time className="kern-sync-time">
            {lastSync ? formatLastSync(lastSync.synced_at) : "Never"}
          </time>
        </div>
        {lastSync ? (
          <div
            className="kern-sync-results kern-sync-results--oauth"
            aria-label="Last synchronization result"
          >
            <div>
              <span className="kern-metric-label">New</span>
              <span className="kern-metric-value">{lastSync.new_count}</span>
            </div>
            <div>
              <span className="kern-metric-label">Updated</span>
              <span className="kern-metric-value">{lastSync.updated_count}</span>
            </div>
            <div>
              <span className="kern-metric-label">Unchanged</span>
              <span className="kern-metric-value">
                {lastSync.unchanged_count}
              </span>
            </div>
            <div>
              <span className="kern-metric-label">Failed</span>
              <span
                className={`kern-metric-value${lastSync.failed_count === 0 ? " is-ok" : ""}`}
              >
                {lastSync.failed_count}
              </span>
            </div>
          </div>
        ) : null}
      </div>

      <div className="kern-source-actions is-split">
        {reauth ? (
          connectControl
        ) : (
          <Button type="button" disabled={busy} onClick={() => void onSync()}>
            {busy ? "Syncing…" : "Sync now"}
          </Button>
        )}
        <Button
          type="button"
          variant="danger"
          disabled={busy}
          onClick={() => setConfirmOpen(true)}
        >
          Disconnect
        </Button>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="Disconnect Google Drive?"
        description="Indexed documents stay in the catalog. You can connect again later."
        confirmLabel="Disconnect"
        tone="danger"
        busy={busy}
        onConfirm={() => void onDisconnect()}
        onCancel={() => setConfirmOpen(false)}
      />
    </article>
  );
}
