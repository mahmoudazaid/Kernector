"use client";

import {
  useEffect,
  useState,
  startTransition,
  type ChangeEvent,
  type FormEvent,
} from "react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/states/EmptyState";
import { UnavailableState } from "@/components/states/UnavailableState";
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

export type DocumentsPanelProps = {
  apiBaseUrl: string;
  list?: (options: ListDocumentsOptions) => Promise<DocumentListResponse>;
  upload?: (
    options: UploadDocumentOptions,
  ) => Promise<CatalogDocumentResponse>;
  replace?: (
    options: ReplaceDocumentOptions,
  ) => Promise<CatalogDocumentResponse>;
  remove?: (options: DeleteDocumentOptions) => Promise<void>;
};

type CatalogView =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | {
      kind: "error";
      message: string;
      documents: CatalogDocumentResponse[];
      constraints: DocumentListResponse["constraints"] | null;
    }
  | {
      kind: "ready";
      documents: CatalogDocumentResponse[];
      constraints: DocumentListResponse["constraints"];
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
    return error.errors?.[0]?.detail ?? error.detail;
  }
  return "The request failed. Please try again later.";
}

export function DocumentsPanel({
  apiBaseUrl,
  list = listDocuments,
  upload = uploadDocument,
  replace = replaceDocument,
  remove = deleteDocument,
}: DocumentsPanelProps) {
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

  async function refresh() {
    try {
      const response = await list({ baseUrl: apiBaseUrl });
      startTransition(() => {
        setCatalog({
          kind: "ready",
          documents: response.documents,
          constraints: response.constraints,
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
          constraints:
            prev.kind === "ready" || prev.kind === "error"
              ? prev.constraints
              : null,
        })),
      );
    }
  }

  useEffect(() => {
    void refresh();
    // Initial load only — actions call refresh explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount once
  }, []);

  useEffect(() => {
    setReplaceFile(null);
    setReplaceInputKey((key) => key + 1);
  }, [selectedId]);

  const documents =
    catalog.kind === "ready" || catalog.kind === "error"
      ? catalog.documents
      : [];
  const constraints =
    catalog.kind === "ready"
      ? catalog.constraints
      : catalog.kind === "error"
        ? catalog.constraints
        : null;
  const selected =
    documents.find((doc) => doc.source_id === selectedId) ?? null;
  const accept = constraints
    ? constraints.supported_suffixes.join(",")
    : ".md,.markdown,.txt,.pdf";

  function clearUploadInput() {
    setUploadFile(null);
    setUploadInputKey((key) => key + 1);
  }

  function clearReplaceInput() {
    setReplaceFile(null);
    setReplaceInputKey((key) => key + 1);
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
        <Button variant="secondary" onClick={() => void refresh()}>
          Retry
        </Button>
      </section>
    );
  }

  return (
    <section className="kern-documents">
      <h1>Knowledge Hub</h1>
      <p className="kern-documents-lead">{IDENTITY_HELP}</p>

      {catalog.kind === "error" ? (
        <div className="kern-settings-callout kern-settings-callout--error" role="alert">
          <p>{catalog.message}</p>
          <Button variant="secondary" onClick={() => void refresh()}>
            Retry
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
                      setSelectedId(doc.source_id);
                    }}
                  >
                    <td>
                      <button
                        type="button"
                        className="kern-documents-row-button"
                        aria-pressed={selectedRow}
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
                        disabled={busy}
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
        <fieldset className="kern-settings-fieldset" disabled={busy || !constraints}>
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
          <fieldset className="kern-settings-fieldset" disabled={busy}>
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
          if (!busy) {
            setPendingDelete(null);
          }
        }}
        onConfirm={() => {
          if (pendingDelete) {
            void onDelete(pendingDelete);
          }
        }}
      />
    </section>
  );
}
