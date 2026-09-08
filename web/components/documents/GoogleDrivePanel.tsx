"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/states/EmptyState";
import { UnavailableState } from "@/components/states/UnavailableState";
import {
  getGoogleDriveStatus,
  syncGoogleDrive,
  type GetGoogleDriveStatusOptions,
  type GoogleDriveStatusResponse,
  type GoogleDriveSyncResponse,
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
  ) => Promise<GoogleDriveSyncResponse>;
};

type StatusView =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; status: GoogleDriveStatusResponse };

type SyncView =
  | { kind: "idle" }
  | { kind: "success"; result: GoogleDriveSyncResponse }
  | { kind: "empty" }
  | { kind: "error"; message: string };

const ABORT_COPY =
  "The sync request was cancelled or timed out. The run may still be in progress on the server.";

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  return "The request failed. Please try again later.";
}

export function GoogleDrivePanel({
  apiBaseUrl,
  getStatus = getGoogleDriveStatus,
  syncNow = syncGoogleDrive,
}: GoogleDrivePanelProps) {
  const [view, setView] = useState<StatusView>({ kind: "loading" });
  const [syncView, setSyncView] = useState<SyncView>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  async function loadStatus() {
    try {
      const status = await getStatus({ baseUrl: apiBaseUrl });
      setView({ kind: "ready", status });
    } catch (error) {
      setView({ kind: "error", message: actionErrorMessage(error) });
    }
  }

  useEffect(() => {
    void loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, []);

  async function onSync() {
    if (busyRef.current) {
      return;
    }
    busyRef.current = true;
    setBusy(true);
    setSyncView({ kind: "idle" });
    try {
      const result = await syncNow({ baseUrl: apiBaseUrl });
      const empty =
        result.ingested_count === 0 &&
        result.skipped_count === 0 &&
        result.failed_count === 0;
      setSyncView(empty ? { kind: "empty" } : { kind: "success", result });
    } catch (error) {
      if (error instanceof ApiError && error.code === "aborted") {
        setSyncView({ kind: "error", message: ABORT_COPY });
        void loadStatus();
      } else {
        setSyncView({ kind: "error", message: actionErrorMessage(error) });
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  if (view.kind === "loading") {
    return (
      <fieldset className="kern-settings-fieldset">
        <legend>Google Drive</legend>
        <p className="kern-settings-help" role="status">
          Loading Google Drive…
        </p>
      </fieldset>
    );
  }

  if (view.kind === "error") {
    return (
      <fieldset className="kern-settings-fieldset">
        <legend>Google Drive</legend>
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{view.message}</p>
        </div>
      </fieldset>
    );
  }

  const { status } = view;

  if (!status.configured) {
    return (
      <fieldset className="kern-settings-fieldset">
        <legend>Google Drive</legend>
        <p className="kern-settings-help">
          Google Drive sync requires backend environment variables
          GOOGLE_DRIVE_FOLDER_ID and GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE.
          Credentials are not entered here.
        </p>
      </fieldset>
    );
  }

  if (!status.available) {
    return (
      <fieldset className="kern-settings-fieldset">
        <legend>Google Drive</legend>
        <UnavailableState
          title="Google Drive extra unavailable"
          description="Install the Google Drive extra on the server with uv sync --extra google-drive."
        />
      </fieldset>
    );
  }

  return (
    <fieldset className="kern-settings-fieldset" disabled={busy}>
      <legend>Google Drive</legend>
      <p className="kern-settings-help">
        Synchronize the configured Drive folder into the knowledge base.
      </p>
      {syncView.kind === "success" ? (
        <div
          className="kern-settings-callout kern-settings-callout--ok"
          role="status"
        >
          <p>
            Ingested {syncView.result.ingested_count} · skipped{" "}
            {syncView.result.skipped_count} · failed{" "}
            {syncView.result.failed_count}
          </p>
        </div>
      ) : null}
      {syncView.kind === "empty" ? (
        <EmptyState
          title="No Drive changes"
          description="The folder had no documents to ingest, skip, or fail."
        />
      ) : null}
      {syncView.kind === "error" ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{syncView.message}</p>
        </div>
      ) : null}
      <Button type="button" disabled={busy} onClick={() => void onSync()}>
        {busy ? "Syncing…" : "Sync now"}
      </Button>
    </fieldset>
  );
}
