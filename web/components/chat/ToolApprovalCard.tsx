"use client";

import { useState } from "react";

import {
  decideToolApproval,
  putChatExportDestination,
  type PendingToolApprovalResponse,
} from "@/lib/api/chat";
import { ApiError } from "@/lib/api/errors";
import { GoogleDrivePicker } from "@/components/documents/GoogleDrivePicker";
import { Button } from "@/components/ui/Button";

export type ApprovalResolution = {
  status: "approved" | "rejected";
  fileName?: string | null;
  fileId?: string | null;
};

type ToolApprovalCardProps = {
  baseUrl: string;
  conversationId: string;
  pending: PendingToolApprovalResponse;
  resolution?: ApprovalResolution | null;
  onResolved: (result: {
    answer: string;
    cancelled: boolean;
    resolution: ApprovalResolution;
  }) => void;
};

function maskFileId(fileId: string): string {
  const trimmed = fileId.trim();
  if (trimmed.length <= 6) {
    return trimmed;
  }
  return `·····${trimmed.slice(-3)}`;
}

function folderDisplayLabel(folderId: string, folderName: string): string {
  if (folderId === "root") {
    return "Home";
  }
  const trimmed = folderName.trim();
  if (!trimmed) {
    return "Google Drive";
  }
  const lowered = trimmed.toLowerCase();
  if (lowered === "my drive" || lowered === "home") {
    return "Home";
  }
  if (lowered.startsWith("my drive /")) {
    return `Home${trimmed.slice("My Drive".length)}`;
  }
  return trimmed;
}

export function ToolApprovalCard({
  baseUrl,
  conversationId,
  pending,
  resolution = null,
  onResolved,
}: ToolApprovalCardProps) {
  const [busy, setBusy] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [destinationLabel, setDestinationLabel] = useState(
    () => pending.destination_label?.trim() || "Home",
  );
  const [destNote, setDestNote] = useState<string | null>(null);
  const [localResolution, setLocalResolution] =
    useState<ApprovalResolution | null>(resolution);

  const resolved = localResolution ?? resolution;
  const titleId = `approval-${pending.approval_id}`;

  async function decide(decision: "approve" | "reject") {
    if (busy || resolved) {
      return;
    }
    setBusy(true);
    setDestNote(null);
    try {
      const result = await decideToolApproval({
        baseUrl,
        conversationId,
        approvalId: pending.approval_id,
        body: { decision },
      });
      const next: ApprovalResolution =
        decision === "reject"
          ? { status: "rejected" }
          : {
              status: "approved",
              fileName:
                result.tool_run?.drive_file_name ?? pending.file_name ?? null,
              fileId: result.tool_run?.drive_file_id ?? null,
            };
      setLocalResolution(next);
      onResolved({
        answer: result.answer,
        cancelled: result.cancelled,
        resolution: next,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setDestNote(
          "This approval was already decided differently. Refresh and try again.",
        );
      } else if (error instanceof ApiError && error.status === 404) {
        setDestNote("This approval is no longer available.");
      } else {
        setDestNote("Could not submit decision. Try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function saveDestination(folderId: string, folderName: string) {
    if (busy || resolved) {
      return;
    }
    setBusy(true);
    setDestNote(null);
    try {
      const label = folderDisplayLabel(folderId, folderName);
      const saved = await putChatExportDestination({
        baseUrl,
        conversationId,
        body: {
          folder_id: folderId,
          destination_label: label,
        },
      });
      setDestinationLabel(saved.destination_label);
      setPickerOpen(false);
      setDestNote(
        "Saved. Reject this request and ask to export again to use this folder.",
      );
    } catch {
      setDestNote("Could not save destination. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (resolved?.status === "rejected") {
    return (
      <div className="kern-approval-card" role="status">
        <p className="kern-approval-card__resolved kern-approval-card__resolved--cancel">
          Export cancelled.
        </p>
      </div>
    );
  }

  if (resolved?.status === "approved") {
    const fileName = resolved.fileName || pending.file_name || "file";
    return (
      <div className="kern-approval-card" role="status">
        <p className="kern-approval-card__resolved kern-approval-card__resolved--ok">
          Exported <strong>{fileName}</strong>
          {resolved.fileId ? (
            <>
              {" "}
              <span aria-hidden="true">·</span>{" "}
              <code>file_id {maskFileId(resolved.fileId)}</code>
            </>
          ) : null}
        </p>
      </div>
    );
  }

  return (
    <>
      <div
        className={`kern-approval-card${busy ? "" : " kern-approval-card--pending"}`}
        role="region"
        aria-labelledby={titleId}
        data-busy={busy ? "true" : "false"}
      >
        <p className="kern-approval-card__eyebrow">Needs approval</p>
        <h2 className="kern-approval-card__title" id={titleId}>
          {pending.title}
        </h2>
        <p className="kern-approval-card__summary">{pending.summary}</p>
        <dl className="kern-approval-card__details">
          <dt>Destination</dt>
          <dd className="kern-approval-card__destination">
            <span className="kern-approval-card__folder">{destinationLabel}</span>
            <Button
              type="button"
              variant="secondary"
              className="kern-approval-card__change-dest"
              disabled={busy}
              onClick={() => {
                setDestNote(null);
                setPickerOpen(true);
              }}
            >
              Change
            </Button>
          </dd>
          <dt>File</dt>
          <dd>
            {pending.file_name ? (
              <code>{pending.file_name}</code>
            ) : (
              <span className="kern-approval-card__missing">Not set</span>
            )}
          </dd>
          {typeof pending.selected_title_count === "number" ? (
            <>
              <dt>Selected</dt>
              <dd>
                {pending.selected_title_count}{" "}
                {pending.selected_title_count === 1 ? "title" : "titles"}
              </dd>
            </>
          ) : null}
        </dl>
        {destNote ? (
          <p className="kern-approval-card__dest-note" role="status">
            {destNote}
          </p>
        ) : null}
        <div className="kern-approval-card__actions">
          <Button
            type="button"
            disabled={busy}
            onClick={() => void decide("approve")}
          >
            {busy ? "Approving…" : "Approve"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => void decide("reject")}
          >
            Reject
          </Button>
        </div>
      </div>
      <GoogleDrivePicker
        open={pickerOpen}
        apiBaseUrl={baseUrl}
        initialSelection={{ folders: [], files: [] }}
        busy={busy}
        foldersOnly
        singleSelect
        title="Choose export destination"
        description="Pick the Google Drive folder for this conversation’s exports. You stay in Chat."
        confirmLabel="Save destination"
        onCancel={() => {
          if (!busy) {
            setPickerOpen(false);
          }
        }}
        onConfirm={(selection) => {
          const folder = selection.folders?.[0];
          if (!folder) {
            return;
          }
          void saveDestination(folder.id, folder.name);
        }}
      />
    </>
  );
}

type ExportDestinationRequiredPanelProps = {
  testDesignHref: string | null;
  apiBaseUrl?: string;
  conversationId?: string | null;
  onDestinationSaved?: (label: string) => void;
};

/** Legacy gate panel — opens Drive picker on Chat when possible. */
export function ExportDestinationRequiredPanel({
  testDesignHref,
  apiBaseUrl,
  conversationId,
  onDestinationSaved,
}: ExportDestinationRequiredPanelProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canPickInPlace =
    typeof apiBaseUrl === "string" &&
    apiBaseUrl.trim() !== "" &&
    typeof conversationId === "string" &&
    conversationId.trim() !== "";

  async function saveDestination(folderId: string, folderName: string) {
    if (!canPickInPlace || !apiBaseUrl || !conversationId) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const label = folderDisplayLabel(folderId, folderName);
      const saved = await putChatExportDestination({
        baseUrl: apiBaseUrl,
        conversationId,
        body: {
          folder_id: folderId,
          destination_label: label,
        },
      });
      setPickerOpen(false);
      onDestinationSaved?.(saved.destination_label);
    } catch {
      setError("Could not save destination. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="kern-dest-required" role="status">
        <p>
          Choose a Google Drive export destination before the agent can prepare
          this write.
        </p>
        {canPickInPlace ? (
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              setError(null);
              setPickerOpen(true);
            }}
          >
            Choose destination
          </Button>
        ) : testDesignHref ? (
          <p className="kern-dest-required__hint">
            Open Test Design to pick a folder, then ask again.
          </p>
        ) : null}
        {error ? <p role="alert">{error}</p> : null}
      </div>
      {canPickInPlace ? (
        <GoogleDrivePicker
          open={pickerOpen}
          apiBaseUrl={apiBaseUrl}
          initialSelection={{ folders: [], files: [] }}
          busy={busy}
          foldersOnly
          singleSelect
          title="Choose export destination"
          description="Pick the Google Drive folder for this conversation’s exports."
          confirmLabel="Save destination"
          onCancel={() => {
            if (!busy) {
              setPickerOpen(false);
            }
          }}
          onConfirm={(selection) => {
            const folder = selection.folders?.[0];
            if (!folder) {
              return;
            }
            void saveDestination(folder.id, folder.name);
          }}
        />
      ) : null}
    </>
  );
}
