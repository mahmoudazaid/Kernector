"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  startTransition,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { DocumentViewer } from "@/components/documents/DocumentViewer";
import {
  GoogleDrivePanel,
  type GoogleDrivePanelProps,
} from "@/components/documents/GoogleDrivePanel";
import {
  captureDriveCallback,
  peekDriveCallback,
} from "@/lib/documents/drive-callback";
import { triggerBrowserDownload } from "@/lib/documents/download";
import { EmptyState } from "@/components/states/EmptyState";
import { LoadingState } from "@/components/states/LoadingState";
import { UnavailableState } from "@/components/states/UnavailableState";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { DialogFrame } from "@/components/ui/DialogFrame";
import { Loader } from "@/components/ui/Loader";
import { SoftSelect } from "@/components/ui/SoftSelect";
import {
  deleteDocument,
  downloadDocument,
  getDocumentContent,
  listDocuments,
  replaceDocument,
  uploadDocument,
  type CatalogDocumentResponse,
  type DeleteDocumentOptions,
  type DocumentBlobOptions,
  type DocumentListResponse,
  type ListDocumentsOptions,
  type ReplaceDocumentOptions,
  type UploadDocumentOptions,
} from "@/lib/api/documents";
import type { ApiBlobResult } from "@/lib/api/client";
import { ApiError, isBackendUnavailable } from "@/lib/api/errors";
import { validateUpload } from "@/lib/documents/upload";
import { formatTimestamp } from "@/lib/format/timestamp";
import {
  useRuntimeCatalog,
  type RuntimeCatalogLoader,
} from "@/lib/settings/use-runtime-catalog";

export type DocumentsPanelProps = {
  apiBaseUrl: string;
  list?: (options: ListDocumentsOptions) => Promise<DocumentListResponse>;
  upload?: (options: UploadDocumentOptions) => Promise<CatalogDocumentResponse>;
  replace?: (
    options: ReplaceDocumentOptions,
  ) => Promise<CatalogDocumentResponse>;
  remove?: (options: DeleteDocumentOptions) => Promise<void>;
  getContent?: (options: DocumentBlobOptions) => Promise<ApiBlobResult>;
  download?: (options: DocumentBlobOptions) => Promise<ApiBlobResult>;
  loadSettings?: RuntimeCatalogLoader;
  getDriveStatus?: GoogleDrivePanelProps["getStatus"];
  syncDrive?: GoogleDrivePanelProps["syncNow"];
  disconnectDrive?: GoogleDrivePanelProps["disconnect"];
};

const GOOGLE_DRIVE_SOURCE = "google_drive";

type CatalogView =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | {
      kind: "error";
      message: string;
      documents: CatalogDocumentResponse[];
    }
  | {
      kind: "ready";
      documents: CatalogDocumentResponse[];
    };

type ActionFeedback =
  | { kind: "idle" }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string };

const EMPTY_COPY =
  "No uploaded documents yet. Seed-corpus documents are managed separately and do not appear here.";

const HUB_LEDE =
  "Connect knowledge sources, control synchronization, and browse every indexed document in one place.";

const PLANNED_CONNECTORS = [
  { name: "GitHub", kind: "Repository knowledge", icon: "github" },
  { name: "Jira", kind: "Issues and stories", icon: "jira" },
  { name: "Confluence", kind: "Team documentation", icon: "book" },
] as const;

const SOURCE_FILTERS = ["All sources", "File uploads", "Google Drive"] as const;

function isDriveDocument(doc: CatalogDocumentResponse): boolean {
  return doc.source_type === GOOGLE_DRIVE_SOURCE;
}

function sourceLabel(sourceType: string): string {
  return sourceType === GOOGLE_DRIVE_SOURCE ? "Google Drive" : "File upload";
}

function documentStatusClass(status: string): string | undefined {
  if (status === "ready") {
    return "kern-doc-ready";
  }
  if (status === "failed") {
    return "kern-doc-failed";
  }
  if (status === "degraded") {
    return "kern-doc-degraded";
  }
  return undefined;
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M10 13.5V4.5M10 4.5 6.5 8M10 4.5 13.5 8M4 13.5v1.2c0 .7.6 1.3 1.3 1.3h9.4c.7 0 1.3-.6 1.3-1.3v-1.2"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DriveIcon() {
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

function PlannedIcon({
  name,
}: {
  name: (typeof PLANNED_CONNECTORS)[number]["icon"];
}) {
  if (name === "github") {
    return (
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path
          d="M10 2.8a7.2 7.2 0 0 0-2.28 14.03c.36.07.5-.16.5-.35v-1.23c-2.03.44-2.46-.87-2.46-.87-.33-.84-.8-1.07-.8-1.07-.66-.45.05-.44.05-.44.73.05 1.11.75 1.11.75.65 1.11 1.7.79 2.12.6.06-.47.25-.79.46-.97-1.62-.18-3.32-.81-3.32-3.6 0-.8.28-1.45.75-1.96-.08-.18-.33-.92.07-1.91 0 0 .61-.2 2 0.75a6.9 6.9 0 0 1 3.64 0c1.39-.95 2-.75 2-.75.4 1 .15 1.73.07 1.91.47.51.75 1.16.75 1.96 0 2.8-1.7 3.42-3.33 3.6.26.22.5.67.5 1.35v2c0 .2.13.42.5.35A7.2 7.2 0 0 0 10 2.8Z"
          fill="currentColor"
        />
      </svg>
    );
  }
  if (name === "jira") {
    return (
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path
          d="M4.5 5.5h6.2v2.2H6.7v6.8H4.5V5.5Zm4.8 4.8h6.2v6.2h-2.2v-4H9.3V10.3Zm2.2-4.8h4v4h-4v-4Z"
          fill="currentColor"
        />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M4.5 5.2c1.8-.8 3.6-.8 5.5 0s3.7.8 5.5 0v9.1c-1.8.8-3.6.8-5.5 0s-3.7-.8-5.5 0V5.2Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M10 5.4v8.7"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.detail;
  }
  return "The request failed. Please try again later.";
}

const BACKEND_UNAVAILABLE_MESSAGE =
  "Backend unavailable. Start the FastAPI server and try again.";

export function DocumentsPanel({
  apiBaseUrl,
  list = listDocuments,
  upload = uploadDocument,
  replace = replaceDocument,
  remove = deleteDocument,
  getContent = getDocumentContent,
  download = downloadDocument,
  loadSettings,
  getDriveStatus,
  syncDrive,
  disconnectDrive,
}: DocumentsPanelProps) {
  const {
    catalog: runtimeCatalog,
    error: settingsError,
    loading: settingsLoading,
    reload: reloadSettings,
  } = useRuntimeCatalog(apiBaseUrl, loadSettings);
  const constraints = runtimeCatalog?.constraints ?? null;
  const [catalog, setCatalog] = useState<CatalogView>({ kind: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [replaceFile, setReplaceFile] = useState<File | null>(null);
  const [uploadInputKey, setUploadInputKey] = useState(0);
  const [replaceInputKey, setReplaceInputKey] = useState(0);
  const [pendingDelete, setPendingDelete] =
    useState<CatalogDocumentResponse | null>(null);
  const [hubTab, setHubTab] = useState<"sources" | "documents">("sources");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] =
    useState<(typeof SOURCE_FILTERS)[number]>("All sources");
  const [driveConnected, setDriveConnected] = useState(false);
  const [driveReloadToken, setDriveReloadToken] = useState(0);
  const [oauthCallback, setOauthCallback] = useState<string | null>(
    peekDriveCallback,
  );
  const [drivePickerOpen, setDrivePickerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<ActionFeedback>({ kind: "idle" });
  const [feedbackSeq, setFeedbackSeq] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadErrorSeq, setUploadErrorSeq] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [previewSourceId, setPreviewSourceId] = useState<string | null>(null);
  const [previewRefreshToken, setPreviewRefreshToken] = useState(0);
  const [downloadPendingId, setDownloadPendingId] = useState<string | null>(
    null,
  );
  const refreshSeqRef = useRef(0);
  const refreshAbortRef = useRef<AbortController | null>(null);
  const uploadErrorRef = useRef<HTMLDivElement>(null);
  const feedbackRef = useRef<HTMLDivElement>(null);
  const deleteRestoreRef = useRef<HTMLElement | null>(null);
  const dialogOpen = pendingDelete !== null || uploadOpen || drivePickerOpen;

  useEffect(() => {
    captureDriveCallback();
  }, []);

  useEffect(() => {
    if (feedback.kind === "idle" || dialogOpen) {
      return;
    }
    feedbackRef.current?.focus();
  }, [feedbackSeq, dialogOpen, feedback.kind]);

  useEffect(() => {
    if (uploadOpen && uploadError) {
      uploadErrorRef.current?.focus();
    }
  }, [uploadOpen, uploadError, uploadErrorSeq]);

  function announce(next: Exclude<ActionFeedback, { kind: "idle" }>) {
    setFeedback(next);
    setFeedbackSeq((seq) => seq + 1);
  }

  const clearFeedback = useCallback(() => {
    setFeedback({ kind: "idle" });
  }, []);

  function announceUploadError(message: string) {
    setUploadError(message);
    setUploadErrorSeq((seq) => seq + 1);
  }

  const openUploadDialog = useCallback(() => {
    clearFeedback();
    setUploadError(null);
    setUploadOpen(true);
  }, [clearFeedback]);

  const setPickerOpen = useCallback(
    (next: boolean) => {
      if (next) {
        clearFeedback();
      }
      setDrivePickerOpen(next);
    },
    [clearFeedback],
  );

  function retryAll() {
    if (settingsError) {
      reloadSettings();
    }
    if (catalog.kind === "error" || catalog.kind === "unavailable") {
      void refresh();
    }
  }

  async function refresh() {
    refreshAbortRef.current?.abort();
    const controller = new AbortController();
    refreshAbortRef.current = controller;
    const seq = ++refreshSeqRef.current;
    setRefreshing(true);
    try {
      const response = await list({
        baseUrl: apiBaseUrl,
        signal: controller.signal,
      });
      if (seq !== refreshSeqRef.current || controller.signal.aborted) {
        return;
      }
      startTransition(() => {
        setCatalog({
          kind: "ready",
          documents: response.documents,
        });
        setSelectedId((current) => {
          if (
            current &&
            response.documents.some((doc) => doc.source_id === current)
          ) {
            return current;
          }
          return response.documents[0]?.source_id ?? null;
        });
      });
    } catch (error) {
      if (seq !== refreshSeqRef.current || controller.signal.aborted) {
        return;
      }
      if (isBackendUnavailable(error)) {
        startTransition(() => setCatalog({ kind: "unavailable" }));
        return;
      }
      startTransition(() =>
        setCatalog((prev) => ({
          kind: "error",
          message: actionErrorMessage(error),
          documents:
            prev.kind === "ready" || prev.kind === "error"
              ? prev.documents
              : [],
        })),
      );
    } finally {
      if (seq === refreshSeqRef.current && !controller.signal.aborted) {
        setRefreshing(false);
      }
    }
  }

  // Initial load only — actions call refresh explicitly; the cleanup aborts an
  // in-flight list() so an unmount writes no state.
  useEffect(() => {
    void refresh();
    return () => {
      refreshAbortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, []);

  const documents =
    catalog.kind === "ready" || catalog.kind === "error"
      ? catalog.documents
      : [];
  const uploadedDocuments = documents.filter((doc) => !isDriveDocument(doc));
  const visibleDocuments = documents.filter((doc) => {
    if (sourceFilter === "Google Drive" && !isDriveDocument(doc)) {
      return false;
    }
    if (sourceFilter === "File uploads" && isDriveDocument(doc)) {
      return false;
    }
    if (!query.trim()) {
      return true;
    }
    const needle = query.trim().toLowerCase();
    return (
      doc.file_name.toLowerCase().includes(needle) ||
      doc.source_id.toLowerCase().includes(needle)
    );
  });
  const selected =
    visibleDocuments.find((doc) => doc.source_id === selectedId) ?? null;
  const accept = constraints?.supported_upload_suffixes.join(",");
  const selectedSourceId = selected?.source_id ?? null;

  useEffect(() => {
    setReplaceFile(null);
    setReplaceInputKey((key) => key + 1);
  }, [selectedSourceId]);

  function clearUploadInput() {
    setUploadFile(null);
    setUploadInputKey((key) => key + 1);
  }

  function clearReplaceInput() {
    setReplaceFile(null);
    setReplaceInputKey((key) => key + 1);
  }

  function selectDocument(sourceId: string) {
    if (sourceId === selectedId) {
      return;
    }
    setSelectedId(sourceId);
    setPreviewSourceId(null);
  }

  const setActionError = useCallback((error: unknown) => {
    if (isBackendUnavailable(error)) {
      setFeedback({ kind: "error", message: BACKEND_UNAVAILABLE_MESSAGE });
      return;
    }
    setFeedback({ kind: "error", message: actionErrorMessage(error) });
  }, []);

  async function onUpload(event: FormEvent) {
    event.preventDefault();
    if (!constraints || !uploadFile) {
      return;
    }
    const file = uploadFile;
    setUploadError(null);
    const validated = validateUpload(file, constraints);
    if (!validated.ok) {
      announceUploadError(validated.message);
      return;
    }
    setUploadOpen(false);
    setUploading(true);
    setBusy(true);
    clearFeedback();
    try {
      const document = await upload({
        baseUrl: apiBaseUrl,
        file,
      });
      clearUploadInput();
      announce({
        kind: "success",
        message: `Uploaded ${document.file_name} (${document.chunk_count} chunk(s)). Source ID: ${document.source_id}`,
      });
      setHubTab("documents");
      await refresh();
      setSelectedId(document.source_id);
    } catch (error) {
      announceUploadError(
        isBackendUnavailable(error)
          ? BACKEND_UNAVAILABLE_MESSAGE
          : actionErrorMessage(error),
      );
      setUploadOpen(true);
    } finally {
      setUploading(false);
      setBusy(false);
    }
  }

  async function onReplace(event: FormEvent) {
    event.preventDefault();
    if (!constraints || !selected) {
      return;
    }
    const validated = validateUpload(replaceFile, constraints);
    if (!validated.ok) {
      announce({ kind: "error", message: validated.message });
      return;
    }
    setBusy(true);
    clearFeedback();
    try {
      const document = await replace({
        baseUrl: apiBaseUrl,
        sourceId: selected.source_id,
        file: replaceFile!,
      });
      announce({
        kind: "success",
        message: `Replaced ${document.file_name} (${document.chunk_count} chunk(s)). Source ID unchanged: ${document.source_id}`,
      });
      clearReplaceInput();
      setPreviewRefreshToken((token) => token + 1);
      await refresh();
    } catch (error) {
      announce({
        kind: "error",
        message: isBackendUnavailable(error)
          ? BACKEND_UNAVAILABLE_MESSAGE
          : actionErrorMessage(error),
      });
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(document: CatalogDocumentResponse) {
    setBusy(true);
    clearFeedback();
    try {
      await remove({
        baseUrl: apiBaseUrl,
        sourceId: document.source_id,
      });
      setPendingDelete(null);
      announce({
        kind: "success",
        message: `Deleted document ${document.source_id}.`,
      });
      setSelectedId((current) =>
        current === document.source_id ? null : current,
      );
      if (isDriveDocument(document)) {
        setDriveReloadToken((token) => token + 1);
      }
      await refresh();
    } catch (error) {
      setPendingDelete(null);
      announce({
        kind: "error",
        message: isBackendUnavailable(error)
          ? BACKEND_UNAVAILABLE_MESSAGE
          : actionErrorMessage(error),
      });
    } finally {
      setBusy(false);
    }
  }

  async function onDownloadDocument(document: CatalogDocumentResponse) {
    if (downloadPendingId !== null) {
      return;
    }
    setDownloadPendingId(document.source_id);
    setFeedback({ kind: "idle" });
    try {
      const response = await download({
        baseUrl: apiBaseUrl,
        sourceId: document.source_id,
      });
      triggerBrowserDownload(
        response.blob,
        response.fileName ?? document.file_name,
      );
    } catch (error) {
      setActionError(error);
    } finally {
      setDownloadPendingId(null);
    }
  }

  const documentsRetryable =
    catalog.kind === "error" || catalog.kind === "unavailable";
  const retryBusy =
    (Boolean(settingsError) && settingsLoading) ||
    (documentsRetryable && refreshing);

  const latestUpload = uploadedDocuments.reduce<string | null>(
    (latest, doc) => {
      if (!latest || Date.parse(doc.uploaded_at) > Date.parse(latest)) {
        return doc.uploaded_at;
      }
      return latest;
    },
    null,
  );
  const connectedCount = 1 + (driveConnected ? 1 : 0);

  if (catalog.kind === "loading") {
    return (
      <section className="kern-documents" aria-busy="true">
        <header className="kern-hub-head">
          <h1>Knowledge Hub</h1>
        </header>
        <div className="kern-content-state">
          <LoadingState label="Loading documents" />
        </div>
      </section>
    );
  }

  if (catalog.kind === "unavailable") {
    return (
      <section className="kern-documents">
        <header className="kern-hub-head">
          <h1>Knowledge Hub</h1>
          <p className="kern-documents-lead">{HUB_LEDE}</p>
        </header>
        <div className="kern-content-state">
          <UnavailableState
            title="Backend unavailable"
            description="The documents API could not be reached. Start the FastAPI server and try again."
          >
            <Button variant="secondary" disabled={retryBusy} onClick={retryAll}>
              {retryBusy ? "Checking…" : "Retry"}
            </Button>
          </UnavailableState>
        </div>
      </section>
    );
  }

  return (
    <section className="kern-documents">
      <header className="kern-hub-head">
        <h1>Knowledge Hub</h1>
        <p className="kern-documents-lead">{HUB_LEDE}</p>
      </header>

      <div
        className="kern-hub-tabs"
        role="tablist"
        aria-label="Knowledge Hub sections"
      >
        <button
          className="kern-hub-tab"
          type="button"
          role="tab"
          id="hub-sources-tab"
          aria-selected={hubTab === "sources"}
          aria-controls="hub-sources-panel"
          onClick={() => setHubTab("sources")}
        >
          Sources
          <span className="kern-hub-tab-count">{connectedCount} connected</span>
        </button>
        <button
          className="kern-hub-tab"
          type="button"
          role="tab"
          id="hub-documents-tab"
          aria-selected={hubTab === "documents"}
          aria-controls="hub-documents-panel"
          onClick={() => setHubTab("documents")}
        >
          Documents
          <span className="kern-hub-tab-count">{documents.length}</span>
        </button>
      </div>

      {catalog.kind === "error" || settingsError ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
          hidden={dialogOpen}
        >
          {catalog.kind === "error" ? <p>{catalog.message}</p> : null}
          {settingsError ? <p>{settingsError}</p> : null}
          <Button variant="secondary" disabled={retryBusy} onClick={retryAll}>
            {retryBusy ? "Checking…" : "Retry"}
          </Button>
        </div>
      ) : null}

      {feedback.kind !== "idle" ? (
        <div
          ref={feedbackRef}
          className={`kern-settings-callout kern-settings-callout--${feedback.kind === "success" ? "ok" : "error"}`}
          role={feedback.kind === "error" ? "alert" : "status"}
          tabIndex={-1}
          hidden={dialogOpen}
        >
          <p>{feedback.message}</p>
        </div>
      ) : null}

      <section
        className="kern-hub-panel"
        id="hub-sources-panel"
        role="tabpanel"
        aria-labelledby="hub-sources-tab"
        hidden={hubTab !== "sources"}
      >
        <div className="kern-hub-section-head">
          <h2>Connected sources</h2>
        </div>
        <div className="kern-source-grid">
          <article className="kern-source-card" aria-busy={uploading}>
            {uploading ? (
              <div className="kern-source-busy-overlay">
                <Loader label="Uploading files" size="sm" />
              </div>
            ) : null}
            <div className="kern-source-card-title">
              <div className="kern-source-name">
                <span className="kern-source-icon">
                  <UploadIcon />
                </span>
                <div>
                  <h3>File uploads</h3>
                  <p className="kern-source-kind">Local files</p>
                </div>
              </div>
              <span className="kern-source-status">Ready</span>
            </div>
            <div className="kern-source-metrics">
              <div>
                <span className="kern-metric-label">Documents</span>
                <span className="kern-metric-value">
                  {uploadedDocuments.length}
                </span>
              </div>
              <div>
                <span className="kern-metric-label">Latest upload</span>
                <span className="kern-metric-value">
                  {latestUpload ? (
                    <time dateTime={latestUpload}>
                      {formatTimestamp(latestUpload)}
                    </time>
                  ) : (
                    "None yet"
                  )}
                </span>
              </div>
            </div>
            <div className="kern-source-actions">
              <Button
                type="button"
                disabled={busy || !constraints}
                onClick={openUploadDialog}
              >
                <UploadIcon />
                Add files
              </Button>
            </div>
          </article>
          {driveConnected ? (
            <GoogleDrivePanel
              apiBaseUrl={apiBaseUrl}
              getStatus={getDriveStatus}
              syncNow={syncDrive}
              disconnect={disconnectDrive}
              onConnectionChange={setDriveConnected}
              onCatalogChange={() => {
                void refresh();
              }}
              reloadToken={driveReloadToken}
              oauthCallback={oauthCallback}
              onOAuthCallbackConsumed={() => {
                setOauthCallback(null);
              }}
              pickerOpen={drivePickerOpen}
              onPickerOpenChange={setPickerOpen}
            />
          ) : null}
        </div>
        <div className="kern-hub-section-head">
          <h2>Available connectors</h2>
          <p className="kern-hub-section-note">
            The card pattern scales without adding new page sections or forms.
          </p>
        </div>
        <div className="kern-available-grid">
          {!driveConnected ? (
            <GoogleDrivePanel
              apiBaseUrl={apiBaseUrl}
              getStatus={getDriveStatus}
              syncNow={syncDrive}
              disconnect={disconnectDrive}
              onConnectionChange={setDriveConnected}
              onCatalogChange={() => {
                void refresh();
              }}
              reloadToken={driveReloadToken}
              oauthCallback={oauthCallback}
              onOAuthCallbackConsumed={() => {
                setOauthCallback(null);
              }}
              pickerOpen={drivePickerOpen}
              onPickerOpenChange={setPickerOpen}
            />
          ) : null}
          {PLANNED_CONNECTORS.map((connector) => (
            <article className="kern-available-card" key={connector.name}>
              <span className="kern-source-icon">
                <PlannedIcon name={connector.icon} />
              </span>
              <div className="kern-available-copy">
                <h3>{connector.name}</h3>
                <p className="kern-source-kind">{connector.kind}</p>
              </div>
              <span className="kern-planned">Planned</span>
            </article>
          ))}
        </div>
      </section>

      <section
        className="kern-hub-panel"
        id="hub-documents-panel"
        role="tabpanel"
        aria-labelledby="hub-documents-tab"
        hidden={hubTab !== "documents"}
      >
        <div className="kern-hub-toolbar">
          <label className="kern-settings-field kern-hub-search-field">
            <span>Search</span>
            <input
              type="search"
              className="kern-settings-input"
              placeholder="Search documents"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <SoftSelect
            id="hub-source-filter"
            label="Source"
            value={sourceFilter}
            options={[...SOURCE_FILTERS]}
            onChange={(value) =>
              setSourceFilter(value as (typeof SOURCE_FILTERS)[number])
            }
          />
        </div>

        {documents.length === 0 && catalog.kind === "ready" ? (
          <div className="kern-content-state">
            <EmptyState
              title="No uploaded documents"
              description={EMPTY_COPY}
            />
          </div>
        ) : visibleDocuments.length === 0 ? (
          <div className="kern-content-state">
            <EmptyState
              title="No matching documents"
              description="Try another search or source filter."
            />
          </div>
        ) : (
          <div className="kern-documents-table-wrap">
            <table className="kern-documents-table">
              <thead>
                <tr>
                  <th scope="col">Document</th>
                  <th scope="col">Source</th>
                  <th scope="col">Status</th>
                  <th scope="col">Chunks</th>
                  <th scope="col">Updated</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleDocuments.map((doc) => {
                  const selectedRow = doc.source_id === selected?.source_id;
                  return (
                    <tr
                      key={doc.source_id}
                      className={selectedRow ? "is-selected" : undefined}
                      onClick={() => {
                        if (!dialogOpen) {
                          selectDocument(doc.source_id);
                        }
                      }}
                    >
                      <td>
                        <button
                          type="button"
                          className="kern-documents-row-button"
                          aria-pressed={selectedRow}
                          disabled={dialogOpen}
                        >
                          <span className="kern-doc-name">{doc.file_name}</span>
                          <span className="kern-doc-id">{doc.source_id}</span>
                        </button>
                      </td>
                      <td>
                        <span className="kern-source-cell">
                          <span className="kern-mini-icon">
                            {isDriveDocument(doc) ? (
                              <DriveIcon />
                            ) : (
                              <UploadIcon />
                            )}
                          </span>
                          {sourceLabel(doc.source_type)}
                        </span>
                      </td>
                      <td>
                        <span className={documentStatusClass(doc.status)}>
                          {doc.status}
                        </span>
                      </td>
                      <td>{doc.chunk_count}</td>
                      <td>
                        <time dateTime={doc.uploaded_at}>
                          {formatTimestamp(doc.uploaded_at)}
                        </time>
                      </td>
                      <td className="kern-documents-actions">
                        <button
                          type="button"
                          className="kern-documents-delete"
                          aria-label={`Delete ${doc.file_name}`}
                          disabled={busy || dialogOpen}
                          onClick={(event) => {
                            event.stopPropagation();
                            clearFeedback();
                            deleteRestoreRef.current = event.currentTarget;
                            setPendingDelete(doc);
                          }}
                        >
                          <svg
                            className="kern-documents-delete-icon"
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
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {selected ? (
          <div className="kern-documents-detail">
            <p className="kern-settings-hint">
              {isDriveDocument(selected)
                ? `Managed by Google Drive sync. Status: ${selected.status} · chunks: ${selected.chunk_count} · synced: ${formatTimestamp(selected.uploaded_at)}`
                : `Catalog identity is the source ID, not the file name. Status: ${selected.status} · chunks: ${selected.chunk_count} · uploaded: ${formatTimestamp(selected.uploaded_at)}`}
            </p>
            {!isDriveDocument(selected) ? (
              <div className="kern-documents-detail-actions">
                <Button
                  type="button"
                  variant="secondary"
                  aria-label={`Preview ${selected.file_name}`}
                  disabled={dialogOpen}
                  onClick={() => {
                    setFeedback({ kind: "idle" });
                    setPreviewSourceId(selected.source_id);
                  }}
                >
                  Preview
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  aria-label={`Download ${selected.file_name}`}
                  disabled={downloadPendingId !== null || dialogOpen}
                  onClick={() => {
                    void onDownloadDocument(selected);
                  }}
                >
                  {downloadPendingId === selected.source_id
                    ? "Downloading…"
                    : "Download"}
                </Button>
              </div>
            ) : null}
            {selected.error_summary ? (
              <div
                className="kern-settings-callout kern-settings-callout--warn"
                role="status"
              >
                <p>{selected.error_summary}</p>
              </div>
            ) : null}
            {previewSourceId === selected.source_id && !isDriveDocument(selected) ? (
              <DocumentViewer
                sourceId={selected.source_id}
                fileName={selected.file_name}
                contentFormat={selected.content_format ?? ""}
                baseUrl={apiBaseUrl}
                refreshToken={previewRefreshToken}
                getContent={getContent}
                onError={setActionError}
              />
            ) : null}
          </div>
        ) : visibleDocuments.length > 0 ? (
          <p className="kern-settings-hint">
            Select a document to see details or replace it
          </p>
        ) : null}

        {selected && !isDriveDocument(selected) ? (
          <form className="kern-documents-form" onSubmit={onReplace}>
            <fieldset
              className="kern-settings-fieldset"
              disabled={busy || dialogOpen || !constraints}
            >
              <legend>Replace</legend>
              <p className="kern-settings-help">
                Keeps source ID {selected.source_id} and replaces stored chunks.
                File name is ignored for identity.
              </p>
              <label className="kern-settings-field">
                <span>Replacement file</span>
                <input
                  key={replaceInputKey}
                  type="file"
                  accept={accept}
                  className="kern-settings-input"
                  onChange={(event: ChangeEvent<HTMLInputElement>) => {
                    setReplaceFile(event.target.files?.[0] ?? null);
                  }}
                />
              </label>
              <Button type="submit" disabled={busy || !replaceFile}>
                Replace
              </Button>
            </fieldset>
          </form>
        ) : null}
      </section>

      <DialogFrame
        open={uploadOpen}
        titleId="hub-upload-title"
        descriptionId={uploadError ? "hub-upload-error" : undefined}
        panelClassName="kern-hub-upload-dialog"
        dismissDisabled={busy}
        onDismiss={() => {
          setUploadOpen(false);
          setUploadError(null);
          clearUploadInput();
        }}
      >
        <h2 id="hub-upload-title" className="kern-dialog-title">
          Upload files
        </h2>
        <p className="kern-dialog-body">
          Files become part of the shared document catalog. A system-managed
          source ID is assigned automatically.
        </p>
        {uploadError ? (
          <div
            ref={uploadErrorRef}
            id="hub-upload-error"
            className="kern-settings-callout kern-settings-callout--error"
            role="alert"
            tabIndex={-1}
          >
            <p>{uploadError}</p>
          </div>
        ) : null}
        <form className="kern-documents-form" onSubmit={onUpload}>
          <label className="kern-settings-field">
            <span>Document file</span>
            <input
              key={uploadInputKey}
              type="file"
              accept={accept}
              className="kern-settings-input"
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                setUploadFile(event.target.files?.[0] ?? null);
              }}
            />
            {uploadFile ? (
              <p className="kern-settings-hint">Selected: {uploadFile.name}</p>
            ) : null}
          </label>
          <div className="kern-dialog-actions">
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setUploadOpen(false);
                setUploadError(null);
                clearUploadInput();
              }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !uploadFile}>
              Upload new
            </Button>
          </div>
        </form>
      </DialogFrame>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete document"
        description={
          pendingDelete
            ? `Delete ${pendingDelete.file_name} (${pendingDelete.source_id})? This cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        tone="danger"
        busy={busy}
        restoreFocusRef={deleteRestoreRef}
        onCancel={() => {
          setPendingDelete(null);
        }}
        onConfirm={() => {
          if (pendingDelete && !busy) {
            void onDelete(pendingDelete);
          }
        }}
      />
    </section>
  );
}
