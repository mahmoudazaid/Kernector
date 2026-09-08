"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { GoogleDrivePicker } from "@/components/documents/GoogleDrivePicker";
import {
  disconnectGoogleDrive,
  getGoogleDriveSelection,
  getGoogleDriveStatus,
  googleDriveOAuthStartUrl,
  listGoogleDriveItems,
  putGoogleDriveSelection,
  syncGoogleDrive,
  type DisconnectGoogleDriveOptions,
  type GetGoogleDriveSelectionOptions,
  type GetGoogleDriveStatusOptions,
  type GoogleDriveBrowseItemResponse,
  type GoogleDriveSelectionResponse,
  type GoogleDriveStatusResponse,
  type ListGoogleDriveItemsOptions,
  type PutGoogleDriveSelectionOptions,
  type SyncGoogleDriveOptions,
} from "@/lib/api/connectors";
import { ApiError } from "@/lib/api/errors";

export type GoogleDrivePanelProps = {
  apiBaseUrl: string;
  getStatus?: (
    options: GetGoogleDriveStatusOptions,
  ) => Promise<GoogleDriveStatusResponse>;
  listItems?: (options: ListGoogleDriveItemsOptions) => Promise<{
    items: GoogleDriveBrowseItemResponse[];
    next_page_token?: string | null;
  }>;
  loadSelection?: (
    options: GetGoogleDriveSelectionOptions,
  ) => Promise<GoogleDriveSelectionResponse>;
  saveSelection?: (
    options: PutGoogleDriveSelectionOptions,
  ) => Promise<GoogleDriveSelectionResponse>;
  syncNow?: (options: SyncGoogleDriveOptions) => Promise<unknown>;
  disconnect?: (options: DisconnectGoogleDriveOptions) => Promise<void>;
  onConnectionChange?: (connected: boolean) => void;
  onCatalogChange?: () => void;
  reloadToken?: number;
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
  unconfigured: "Google Drive OAuth is not configured on the server.",
};

const EMPTY_SELECTION: GoogleDriveSelectionResponse = {
  folders: [],
  files: [],
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
  listItems = listGoogleDriveItems,
  loadSelection = getGoogleDriveSelection,
  saveSelection = putGoogleDriveSelection,
  syncNow = syncGoogleDrive,
  disconnect = disconnectGoogleDrive,
  onConnectionChange,
  onCatalogChange,
  reloadToken = 0,
}: GoogleDrivePanelProps) {
  const [view, setView] = useState<StatusView>({ kind: "loading" });
  const [callbackError, setCallbackError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selection, setSelection] =
    useState<GoogleDriveSelectionResponse>(EMPTY_SELECTION);
  const busyRef = useRef(false);
  const onConnectionChangeRef = useRef(onConnectionChange);
  onConnectionChangeRef.current = onConnectionChange;
  const onCatalogChangeRef = useRef(onCatalogChange);
  onCatalogChangeRef.current = onCatalogChange;

  async function loadStatus() {
    try {
      const status = await getStatus({ baseUrl: apiBaseUrl });
      setView({ kind: "ready", status });
      return status;
    } catch (error) {
      setView({ kind: "error", message: actionErrorMessage(error) });
      return null;
    }
  }

  async function refreshSelection() {
    try {
      const current = await loadSelection({ baseUrl: apiBaseUrl });
      setSelection(current);
      return current;
    } catch {
      setSelection(EMPTY_SELECTION);
      return EMPTY_SELECTION;
    }
  }

  useEffect(() => {
    const drive = readDriveCallback();
    if (drive === "connected") {
      setPickerOpen(true);
    } else if (drive) {
      setCallbackError(CALLBACK_ERRORS[drive] ?? CALLBACK_ERRORS.error);
    }
    void (async () => {
      const status = await loadStatus();
      if (status?.connected) {
        await refreshSelection();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, []);

  useEffect(() => {
    if (reloadToken === 0) {
      return;
    }
    void (async () => {
      const status = await loadStatus();
      if (status?.connected) {
        await refreshSelection();
      }
    })();
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
      if (error instanceof ApiError && error.code === "aborted") {
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

  async function onAddSelection(next: GoogleDriveSelectionResponse) {
    if (busyRef.current) {
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setActionError(null);
    try {
      const saved = await saveSelection({
        baseUrl: apiBaseUrl,
        selection: next,
      });
      setSelection(saved);
      await syncNow({ baseUrl: apiBaseUrl });
      setPickerOpen(false);
      await loadStatus();
      onCatalogChangeRef.current?.();
    } catch (error) {
      if (error instanceof ApiError && error.code === "aborted") {
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
      setPickerOpen(false);
      setSelection(EMPTY_SELECTION);
      await loadStatus();
      onCatalogChangeRef.current?.();
    } catch (error) {
      setActionError(actionErrorMessage(error));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function openPicker() {
    setActionError(null);
    if (connected) {
      await refreshSelection();
    }
    setPickerOpen(true);
  }

  const status = view.kind === "ready" ? view.status : null;
  const reauth = Boolean(status?.reauthorization_required);
  const setupRequired =
    Boolean(status?.setup_required) ||
    status?.connection_state === "setup_required";
  const oauthStartHref = googleDriveOAuthStartUrl(apiBaseUrl);
  const statusLabel =
    view.kind === "loading"
      ? "Checking"
      : view.kind === "error"
        ? "Unavailable"
        : reauth
          ? "Reconnect required"
          : setupRequired
            ? "Setup required"
            : status?.connected
              ? "Connected"
              : "Available";

  const lastSync = status?.last_sync ?? null;
  const alertMessage =
    view.kind === "error"
      ? view.message
      : (callbackError ??
        actionError ??
        (reauth
          ? "Google Drive authorization was revoked. Connect again."
          : null));
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

  const syncDisabled = busy || setupRequired || reauth;
  const pickerLabel = setupRequired
    ? "Choose folders or files"
    : "Browse";

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
        <span
          className={`kern-source-status${reauth || setupRequired ? " is-muted" : ""}${setupRequired ? " is-setup" : ""}`}
        >
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

      <div className="kern-source-metrics kern-source-metrics--three">
        <div>
          <span className="kern-metric-label">Account</span>
          <span className="kern-metric-value">
            {status?.account_email ?? "Connected account"}
          </span>
        </div>
        <div>
          <span className="kern-metric-label">Documents</span>
          <span className="kern-metric-value">
            {status?.document_count ?? 0}
          </span>
        </div>
        <div>
          <span className="kern-metric-label">Sync scope</span>
          <span className="kern-metric-value">
            {status?.sync_scope ?? "Not selected"}
          </span>
        </div>
      </div>
      <div className="kern-sync-section" role="status">
        <div className="kern-sync-heading">
          <h3>Last sync</h3>
          <time className="kern-sync-time" dateTime={lastSync?.synced_at}>
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
              <span className="kern-metric-value">
                {lastSync.updated_count}
              </span>
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
        <div className="kern-action-group">
          {reauth ? (
            connectControl
          ) : (
            <>
              <Button
                type="button"
                disabled={busy}
                onClick={() => void openPicker()}
              >
                {pickerLabel}
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={syncDisabled}
                onClick={() => void onSync()}
              >
                {busy && !pickerOpen ? "Syncing…" : "Sync"}
              </Button>
            </>
          )}
        </div>
        <Button
          type="button"
          variant="danger"
          disabled={busy}
          onClick={() => setConfirmOpen(true)}
        >
          Disconnect
        </Button>
      </div>

      <GoogleDrivePicker
        open={pickerOpen}
        apiBaseUrl={apiBaseUrl}
        initialSelection={selection}
        busy={busy}
        listItems={listItems}
        onConfirm={(next) => void onAddSelection(next)}
        onCancel={() => setPickerOpen(false)}
      />

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
