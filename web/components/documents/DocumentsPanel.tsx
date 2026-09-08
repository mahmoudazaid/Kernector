"use client";

import {
  useEffect,
  useRef,
  useState,
  startTransition,
  type ChangeEvent,
  type FormEvent,
} from "react";
import {
  GoogleDrivePanel,
  type GoogleDrivePanelProps,
} from "@/components/documents/GoogleDrivePanel";
import { EmptyState } from "@/components/states/EmptyState";
import { UnavailableState } from "@/components/states/UnavailableState";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { SoftSelect } from "@/components/ui/SoftSelect";
import {
  deleteDocument,
  listDocuments,
  replaceDocument,
  uploadDocument,
  type CatalogDocumentResponse,
  type DeleteDocumentOptions,
  type DocumentListResponse,
  type ListDocumentsOptions,
  type ReplaceDocumentOptions,
  type UploadDocumentOptions,
} from "@/lib/api/documents";
import { ApiError } from "@/lib/api/errors";
import { validateUpload } from "@/lib/documents/upload";
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

const SOURCE_FILTERS = [
  "All sources",
  "File uploads",
  "Google Drive",
] as const;

function formatUploadedAt(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatRelative(value: string): string {
  const then = Date.parse(value);
  if (Number.isNaN(then)) {
    return value;
  }
  const deltaMs = Date.now() - then;
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 1) {
    return "Just now";
  }
  if (minutes < 60) {
    return `${minutes} min ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  }
  const days = Math.floor(hours / 24);
  if (days === 1) {
    return "Yesterday";
  }
  return `${days} days ago`;
}

function isDriveDocument(doc: CatalogDocumentResponse): boolean {
  return doc.source_type === GOOGLE_DRIVE_SOURCE;
}

function sourceLabel(sourceType: string): string {
  return sourceType === GOOGLE_DRIVE_SOURCE ? "Google Drive" : "File upload";
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

function PlannedIcon({ name }: { name: (typeof PLANNED_CONNECTORS)[number]["icon"] }) {
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

export function DocumentsPanel({
  apiBaseUrl,
  list = listDocuments,
  upload = uploadDocument,
  replace = replaceDocument,
  remove = deleteDocument,
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
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] =
    useState<(typeof SOURCE_FILTERS)[number]>("All sources");
  const [driveConnected, setDriveConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<ActionFeedback>({ kind: "idle" });
  const [refreshing, setRefreshing] = useState(false);
  const refreshSeqRef = useRef(0);
  const refreshAbortRef = useRef<AbortController | null>(null);

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
      if (error instanceof ApiError && error.status === 0) {
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

  const dialogOpen = pendingDelete !== null || uploadOpen;
  const documents =
    catalog.kind === "ready" || catalog.kind === "error"
      ? catalog.documents
      : [];
  const selected =
    documents.find((doc) => doc.source_id === selectedId) ?? null;
  const accept = constraints?.supported_upload_suffixes.join(",");

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
    clearReplaceInput();
  }

  async function onUpload(event: FormEvent) {
    event.preventDefault();
    if (!constraints) {
      return;
    }
    const validated = validateUpload(uploadFile, constraints);
    if (!validated.ok) {
      setFeedback({ kind: "error", message: validated.message });
      return;
    }
    setBusy(true);
    setFeedback({ kind: "idle" });
    try {
      const document = await upload({
        baseUrl: apiBaseUrl,
        file: uploadFile!,
      });
      setFeedback({
        kind: "success",
        message: `Uploaded ${document.file_name} (${document.chunk_count} chunk(s)). Source ID: ${document.source_id}`,
      });
      clearUploadInput();
      setUploadOpen(false);
      setHubTab("documents");
      await refresh();
      setSelectedId(document.source_id);
    } catch (error) {
      setFeedback({ kind: "error", message: actionErrorMessage(error) });
    } finally {
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
      setFeedback({ kind: "error", message: validated.message });
      return;
    }
    setBusy(true);
    setFeedback({ kind: "idle" });
    try {
      const document = await replace({
        baseUrl: apiBaseUrl,
        sourceId: selected.source_id,
        file: replaceFile!,
      });
      setFeedback({
        kind: "success",
        message: `Replaced ${document.file_name} (${document.chunk_count} chunk(s)). Source ID unchanged: ${document.source_id}`,
      });
      clearReplaceInput();
      await refresh();
    } catch (error) {
      setFeedback({ kind: "error", message: actionErrorMessage(error) });
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(document: CatalogDocumentResponse) {
    setBusy(true);
    setFeedback({ kind: "idle" });
    try {
      await remove({
        baseUrl: apiBaseUrl,
        sourceId: document.source_id,
      });
      setFeedback({
        kind: "success",
        message: `Deleted document ${document.source_id}.`,
      });
      setSelectedId((current) =>
        current === document.source_id ? null : current,
      );
      await refresh();
    } catch (error) {
      setFeedback({ kind: "error", message: actionErrorMessage(error) });
    } finally {
      setPendingDelete(null);
      setBusy(false);
    }
  }

  const documentsRetryable =
    catalog.kind === "error" || catalog.kind === "unavailable";
  const retryBusy =
    (Boolean(settingsError) && settingsLoading) ||
    (documentsRetryable && refreshing);

  const uploadedDocuments = documents.filter((doc) => !isDriveDocument(doc));
  const latestUpload = uploadedDocuments.reduce<string | null>((latest, doc) => {
    if (!latest || Date.parse(doc.uploaded_at) > Date.parse(latest)) {
      return doc.uploaded_at;
    }
    return latest;
  }, null);
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
  const connectedCount = 1 + (driveConnected ? 1 : 0);

  if (catalog.kind === "loading") {
    return (
      <section className="kern-documents">
        <header className="kern-hub-head">
          <h1>Knowledge Hub</h1>
          <p className="kern-documents-lead" role="status">
            Loading uploaded documents…
          </p>
        </header>
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
        <UnavailableState
          title="Backend unavailable"
          description="The documents API could not be reached. Start the FastAPI server and try again."
        />
        <Button variant="secondary" disabled={retryBusy} onClick={retryAll}>
          {retryBusy ? "Checking…" : "Retry"}
        </Button>
      </section>
    );
  }

  return (
    <section className="kern-documents">
      <header className="kern-hub-head">
        <h1>Knowledge Hub</h1>
        <p className="kern-documents-lead">{HUB_LEDE}</p>
      </header>

      <div className="kern-hub-tabs" role="tablist" aria-label="Knowledge Hub sections">
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
          className={`kern-settings-callout kern-settings-callout--${feedback.kind === "success" ? "ok" : "error"}`}
          role="status"
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
          <p className="kern-hub-section-note">
            Each connector owns its setup and sync actions; documents stay in
            the shared catalog.
          </p>
        </div>
        <div className="kern-source-grid">
          <article className="kern-source-card">
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
                <span className="kern-metric-value">{uploadedDocuments.length}</span>
              </div>
              <div>
                <span className="kern-metric-label">Latest upload</span>
                <span className="kern-metric-value">
                  {latestUpload ? formatRelative(latestUpload) : "None yet"}
                </span>
              </div>
            </div>
            <div className="kern-source-actions">
              <Button
                type="button"
                disabled={busy || !constraints}
                onClick={() => setUploadOpen(true)}
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
            <EmptyState title="No uploaded documents" description={EMPTY_COPY} />
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
                  const selectedRow = doc.source_id === selectedId;
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
                            {isDriveDocument(doc) ? <DriveIcon /> : <UploadIcon />}
                          </span>
                          {sourceLabel(doc.source_type)}
                        </span>
                      </td>
                      <td>
                        <span
                          className={
                            doc.status === "ready" ? "kern-doc-ready" : undefined
                          }
                        >
                          {doc.status}
                        </span>
                      </td>
                      <td>{doc.chunk_count}</td>
                      <td>{formatUploadedAt(doc.uploaded_at)}</td>
                      <td className="kern-documents-actions">
                        {isDriveDocument(doc) ? null : (
                        <button
                          type="button"
                          className="kern-documents-delete"
                          aria-label={`Delete ${doc.file_name}`}
                          disabled={busy || dialogOpen}
                          onClick={(event) => {
                            event.stopPropagation();
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
                        )}
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
                ? `Managed by Google Drive sync. Status: ${selected.status} · chunks: ${selected.chunk_count} · synced: ${formatUploadedAt(selected.uploaded_at)}`
                : `Catalog identity is the source ID, not the file name. Status: ${selected.status} · chunks: ${selected.chunk_count} · uploaded: ${formatUploadedAt(selected.uploaded_at)}`}
            </p>
            {selected.error_summary ? (
              <div
                className="kern-settings-callout kern-settings-callout--warn"
                role="status"
              >
                <p>{selected.error_summary}</p>
              </div>
            ) : null}
          </div>
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

      {uploadOpen ? (
        <div className="kern-dialog-root">
          <button
            type="button"
            className="kern-dialog-backdrop"
            aria-label="Dismiss dialog"
            onClick={() => {
              if (!busy) {
                setUploadOpen(false);
                clearUploadInput();
              }
            }}
          />
          <div
            className="kern-dialog kern-hub-upload-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="hub-upload-title"
          >
            <h2 id="hub-upload-title" className="kern-dialog-title">
              Upload files
            </h2>
            <p className="kern-dialog-body">
              Files become part of the shared document catalog. A system-managed
              source ID is assigned automatically.
            </p>
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
              </label>
              <div className="kern-dialog-actions">
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => {
                    setUploadOpen(false);
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
          </div>
        </div>
      ) : null}

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
