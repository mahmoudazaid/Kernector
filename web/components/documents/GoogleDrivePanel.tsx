"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { GoogleDrivePicker } from "@/components/documents/GoogleDrivePicker";
import { Loader } from "@/components/ui/Loader";
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
import { formatTimestamp } from "@/lib/format/timestamp";
import { consumeDriveCallback } from "@/lib/documents/drive-callback";

export type GoogleDrivePanelProps = {
  apiBaseUrl: string;
  oauthCallback?: string | null;
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
  pickerOpen?: boolean;
  onPickerOpenChange?: (open: boolean) => void;
  onOAuthCallbackConsumed?: () => void;
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
  oauthCallback = null,
  pickerOpen: pickerOpenProp,
  onPickerOpenChange,
  onOAuthCallbackConsumed,
}: GoogleDrivePanelProps) {
  const [view, setView] = useState<StatusView>({ kind: "loading" });
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [internalPickerOpen, setInternalPickerOpen] = useState(false);
  const pickerOpen = onPickerOpenChange
    ? (pickerOpenProp ?? false)
    : internalPickerOpen;
  const setPickerOpen = onPickerOpenChange ?? setInternalPickerOpen;
  const [selection, setSelection] =
    useState<GoogleDriveSelectionResponse>(EMPTY_SELECTION);
  const [selectionReady, setSelectionReady] = useState(false);
  const busyRef = useRef(false);
  const aliveRef = useRef(true);
  const selectionSeqRef = useRef(0);
  const selectionAbortRef = useRef<AbortController | null>(null);
  const pickerOpenRef = useRef(pickerOpen);
  pickerOpenRef.current = pickerOpen;
  const onConnectionChangeRef = useRef(onConnectionChange);
  onConnectionChangeRef.current = onConnectionChange;
  const onCatalogChangeRef = useRef(onCatalogChange);
  onCatalogChangeRef.current = onCatalogChange;
  const onOAuthCallbackConsumedRef = useRef(onOAuthCallbackConsumed);
  onOAuthCallbackConsumedRef.current = onOAuthCallbackConsumed;

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      selectionAbortRef.current?.abort();
    };
  }, []);

  async function loadStatus() {
    try {
      const status = await getStatus({ baseUrl: apiBaseUrl });
      if (!aliveRef.current) {
        return status;
      }
      setView({ kind: "ready", status });
      return status;
    } catch (error) {
      if (!aliveRef.current) {
        return null;
      }
      setView({ kind: "error", message: actionErrorMessage(error) });
      return null;
    }
  }

  async function refreshSelection(options?: { forPicker?: boolean }) {
    selectionAbortRef.current?.abort();
    const controller = new AbortController();
    selectionAbortRef.current = controller;
    const seq = ++selectionSeqRef.current;
    const forPicker = options?.forPicker === true;
    try {
      const current = await loadSelection({
        baseUrl: apiBaseUrl,
        signal: controller.signal,
      });
      if (
        seq !== selectionSeqRef.current ||
        controller.signal.aborted ||
        !aliveRef.current
      ) {
        return null;
      }
      setSelection(current);
      if (pickerOpenRef.current) {
        setSelectionReady(true);
      }
      return current;
    } catch (error) {
      if (
        seq !== selectionSeqRef.current ||
        controller.signal.aborted ||
        !aliveRef.current
      ) {
        return null;
      }
      if (forPicker) {
        setActionError(actionErrorMessage(error));
        setPickerOpen(false);
      }
      return null;
    }
  }

  useEffect(() => {
    let ignore = false;
    void (async () => {
      const status = await loadStatus();
      if (ignore) {
        return;
      }
      if (status?.connected) {
        await refreshSelection();
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
    const drive = oauthCallback;
    consumeDriveCallback();
    onOAuthCallbackConsumedRef.current?.();
    if (drive === "connected") {
      setPickerOpen(true);
    } else {
      setActionError(CALLBACK_ERRORS[drive] ?? CALLBACK_ERRORS.error);
    }
  }, [oauthCallback, setPickerOpen]);

  useEffect(() => {
    if (!pickerOpen) {
      setSelectionReady(false);
      return;
    }
    void refreshSelection({ forPicker: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- picker open
  }, [pickerOpen]);

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
    setPickerOpen(false);
    setBusy(true);
    setActionError(null);
    try {
      const saved = await saveSelection({
        baseUrl: apiBaseUrl,
        selection: next,
      });
      selectionSeqRef.current += 1;
      selectionAbortRef.current?.abort();
      setSelection(saved);
      const hasScope =
        (saved.folders?.length ?? 0) > 0 || (saved.files?.length ?? 0) > 0;
      if (hasScope) {
        await syncNow({ baseUrl: apiBaseUrl });
      }
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
    setPickerOpen(true);
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
  const failedCount = lastSync?.failed_count ?? 0;
  const alertMessage =
    view.kind === "error"
      ? view.message
      : (actionError ??
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

  const syncDisabled = busy || reauth;
  const cardBusy = busy && !pickerOpen;
  return (
    <article
      className="kern-source-card"
      aria-busy={cardBusy}
    >
      {cardBusy ? (
        <div className="kern-drive-sync-overlay">
          <Loader label="Syncing Google Drive" size="sm" />
        </div>
      ) : null}
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
          className={`kern-source-status${reauth ? " is-muted" : ""}`}
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

      <div className="kern-source-metrics">
        <div>
          <span className="kern-metric-label">Account</span>
          <span className="kern-metric-value">
            {status?.account_email ?? "Connected account"}
          </span>
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
              ? "1 file failed to index. See Documents."
              : `${failedCount} files failed to index. See Documents.`}
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
                onClick={() => void openPicker()}
              >
                Browse
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={syncDisabled}
                onClick={() => void onSync()}
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
          onClick={() => setConfirmOpen(true)}
        >
          Disconnect
        </Button>
      </div>

      {pickerOpen ? (
        <GoogleDrivePicker
          open
          apiBaseUrl={apiBaseUrl}
          initialSelection={selection}
          selectionLoading={!selectionReady}
          busy={busy}
          listItems={listItems}
          onConfirm={(next) => void onAddSelection(next)}
          onCancel={() => setPickerOpen(false)}
        />
      ) : null}

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
