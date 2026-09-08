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
};

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

const IDENTITY_HELP =
  "Catalog identity is the source ID, not the file name. Matching file names stay separate documents until you explicitly Replace.";

function formatUploadedAt(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
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

  const dialogOpen = pendingDelete !== null;
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

  if (catalog.kind === "loading") {
    return (
      <section className="kern-documents">
        <h1>Knowledge Hub</h1>
        <p className="kern-documents-lead" role="status">
          Loading uploaded documents…
        </p>
      </section>
    );
  }

  if (catalog.kind === "unavailable") {
    return (
      <section className="kern-documents">
        <h1>Knowledge Hub</h1>
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
      <h1>Knowledge Hub</h1>
      <p className="kern-documents-lead">{IDENTITY_HELP}</p>
      <GoogleDrivePanel
        apiBaseUrl={apiBaseUrl}
        getStatus={getDriveStatus}
        syncNow={syncDrive}
      />

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

      {documents.length === 0 && catalog.kind === "ready" ? (
        <EmptyState title="No uploaded documents" description={EMPTY_COPY} />
      ) : documents.length > 0 ? (
        <div className="kern-documents-table-wrap">
          <table className="kern-documents-table">
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Status</th>
                <th scope="col">Source ID</th>
                <th scope="col">Chunks</th>
                <th scope="col">Uploaded</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => {
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
                        {doc.file_name}
                      </button>
                    </td>
                    <td>{doc.status}</td>
                    <td>
                      <code>{doc.source_id}</code>
                    </td>
                    <td>{doc.chunk_count}</td>
                    <td>{formatUploadedAt(doc.uploaded_at)}</td>
                    <td className="kern-documents-actions">
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
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {selected ? (
        <div className="kern-documents-detail">
          <p className="kern-settings-hint">
            Status: {selected.status} · chunks: {selected.chunk_count} ·
            uploaded: {formatUploadedAt(selected.uploaded_at)}
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

      <form className="kern-documents-form" onSubmit={onUpload}>
        <fieldset
          className="kern-settings-fieldset"
          disabled={busy || dialogOpen || !constraints}
        >
          <legend>Upload new</legend>
          <p className="kern-settings-help">
            A system-managed source ID is assigned automatically.
          </p>
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
          <Button type="submit" disabled={busy || !uploadFile}>
            Upload new
          </Button>
        </fieldset>
      </form>

      {selected ? (
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
