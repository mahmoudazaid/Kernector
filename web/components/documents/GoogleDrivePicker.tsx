"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { KernectorLoaderMark } from "@/components/shell/KernectorLoaderMark";
import { ApiError } from "@/lib/api/errors";
import {
  listGoogleDriveItems,
  type GoogleDriveBrowseItemResponse,
  type GoogleDriveSelectionResponse,
  type ListGoogleDriveItemsOptions,
} from "@/lib/api/connectors";

export type GoogleDrivePickerProps = {
  open: boolean;
  apiBaseUrl: string;
  initialSelection: GoogleDriveSelectionResponse;
  busy?: boolean;
  listItems?: (options: ListGoogleDriveItemsOptions) => Promise<{
    items: GoogleDriveBrowseItemResponse[];
    next_page_token?: string | null;
  }>;
  onConfirm: (selection: GoogleDriveSelectionResponse) => void;
  onCancel: () => void;
};

type Crumb = { id: string; name: string };

type BrowseView =
  | { kind: "loading" }
  | { kind: "error"; message: string; code?: string }
  | {
      kind: "ready";
      folders: GoogleDriveBrowseItemResponse[];
      files: GoogleDriveBrowseItemResponse[];
      nextFolderToken: string | null;
      nextFileToken: string | null;
    };

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

const ROOT: Crumb = { id: "root", name: "My Drive" };

function selectedMap(
  selection: GoogleDriveSelectionResponse,
): Map<string, { id: string; name: string; kind: "folder" | "file" }> {
  const map = new Map<
    string,
    { id: string; name: string; kind: "folder" | "file" }
  >();
  for (const item of selection.folders ?? []) {
    map.set(item.id, { id: item.id, name: item.name, kind: "folder" });
  }
  for (const item of selection.files ?? []) {
    map.set(item.id, { id: item.id, name: item.name, kind: "file" });
  }
  return map;
}

function toSelection(
  map: Map<string, { id: string; name: string; kind: "folder" | "file" }>,
): GoogleDriveSelectionResponse {
  const folders: { id: string; name: string }[] = [];
  const files: { id: string; name: string }[] = [];
  for (const item of map.values()) {
    if (item.kind === "folder") {
      folders.push({ id: item.id, name: item.name });
    } else {
      files.push({ id: item.id, name: item.name });
    }
  }
  return { folders, files };
}

function sameSelection(
  map: Map<string, { id: string; name: string; kind: "folder" | "file" }>,
  selection: GoogleDriveSelectionResponse,
): boolean {
  const baseline = selectedMap(selection);
  if (map.size !== baseline.size) {
    return false;
  }
  for (const [id, item] of map) {
    const other = baseline.get(id);
    if (!other || other.kind !== item.kind) {
      return false;
    }
  }
  return true;
}

function browseErrorMessage(error: unknown): {
  message: string;
  code?: string;
} {
  if (error instanceof ApiError) {
    return { message: error.detail, code: error.code };
  }
  return { message: "The request failed. Please try again later." };
}

function mixedRows(
  folders: GoogleDriveBrowseItemResponse[],
  files: GoogleDriveBrowseItemResponse[],
): GoogleDriveBrowseItemResponse[] {
  const seen = new Set(folders.map((item) => item.id));
  return [
    ...folders,
    ...files.filter((item) => !seen.has(item.id)),
  ];
}

function FolderGlyph() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M3.5 6.2c0-.7.6-1.2 1.2-1.2h3.1c.3 0 .6.1.8.4l.7.8h6c.7 0 1.2.6 1.2 1.2v6.6c0 .7-.5 1.2-1.2 1.2H4.7c-.6 0-1.2-.5-1.2-1.2V6.2Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function FileGlyph() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M6 3.5h5.2L16 8.3V16c0 .8-.6 1.5-1.5 1.5h-8C5.7 17.5 5 16.8 5 16V5c0-.8.7-1.5 1.5-1.5H6Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path
        d="M11.2 3.6V8h4.6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CloseGlyph() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M5 5l10 10M15 5 5 15"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function GoogleDrivePicker({
  open,
  apiBaseUrl,
  initialSelection,
  busy = false,
  listItems = listGoogleDriveItems,
  onConfirm,
  onCancel,
}: GoogleDrivePickerProps) {
  const titleId = useId();
  const descriptionId = useId();
  const searchId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const onCancelRef = useRef(onCancel);
  onCancelRef.current = onCancel;

  const [crumbs, setCrumbs] = useState<Crumb[]>([ROOT]);
  const [search, setSearch] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [view, setView] = useState<BrowseView>({ kind: "loading" });
  const [selected, setSelected] = useState(() => selectedMap(initialSelection));

  const parentId = crumbs[crumbs.length - 1]?.id ?? "root";
  const query = submittedQuery.trim();

  async function loadPage(options?: {
    pageToken?: string | null;
    pageKind?: "folders" | "files";
  }) {
    const pageToken = options?.pageToken ?? null;
    const pageKind = options?.pageKind;
    if (!pageToken) {
      setView({ kind: "loading" });
    }
    try {
      if (pageToken && pageKind) {
        const page = await listItems({
          baseUrl: apiBaseUrl,
          parentId,
          kind: pageKind,
          query: query || undefined,
          pageToken,
        });
        setView((current) => {
          if (current.kind !== "ready") {
            return current;
          }
          return {
            kind: "ready",
            folders:
              pageKind === "folders"
                ? [...current.folders, ...page.items]
                : current.folders,
            files:
              pageKind === "files"
                ? [...current.files, ...page.items]
                : current.files,
            nextFolderToken:
              pageKind === "folders"
                ? (page.next_page_token ?? null)
                : current.nextFolderToken,
            nextFileToken:
              pageKind === "files"
                ? (page.next_page_token ?? null)
                : current.nextFileToken,
          };
        });
        return;
      }
      const [folderPage, filePage] = await Promise.all([
        listItems({
          baseUrl: apiBaseUrl,
          parentId,
          kind: "folders",
          query: query || undefined,
        }),
        listItems({
          baseUrl: apiBaseUrl,
          parentId,
          kind: "files",
          query: query || undefined,
        }),
      ]);
      setView({
        kind: "ready",
        folders: folderPage.items,
        files: filePage.items,
        nextFolderToken: folderPage.next_page_token ?? null,
        nextFileToken: filePage.next_page_token ?? null,
      });
    } catch (error) {
      setView({ kind: "error", ...browseErrorMessage(error) });
    }
  }

  const initialSelectionRef = useRef(initialSelection);
  initialSelectionRef.current = initialSelection;

  useEffect(() => {
    if (!open) {
      return;
    }
    setCrumbs([ROOT]);
    setSearch("");
    setSubmittedQuery("");
    setSelected(selectedMap(initialSelectionRef.current));
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    void loadPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload on browse identity
  }, [open, parentId, submittedQuery]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    searchRef.current?.focus();

    function focusableNodes(): HTMLElement[] {
      const root = dialogRef.current;
      if (!root) {
        return [];
      }
      return Array.from(
        root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter(
        (node) => !node.hasAttribute("disabled") && node.tabIndex !== -1,
      );
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const nodes = focusableNodes();
      if (nodes.length === 0) {
        event.preventDefault();
        return;
      }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const active = document.activeElement;
      if (event.shiftKey) {
        if (active === first || !dialogRef.current?.contains(active)) {
          event.preventDefault();
          last.focus();
        }
        return;
      }
      if (active === last || !dialogRef.current?.contains(active)) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previous?.focus();
    };
  }, [open]);

  if (!open) {
    return null;
  }

  const countLabel =
    selected.size === 0 ? "No items selected" : `${selected.size} selected`;
  const selectionUnchanged = sameSelection(selected, initialSelection);

  function toggle(item: GoogleDriveBrowseItemResponse) {
    const kind = item.kind === "folder" ? "folder" : "file";
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(item.id)) {
        next.delete(item.id);
      } else {
        next.set(item.id, { id: item.id, name: item.name, kind });
      }
      return next;
    });
  }

  const rows =
    view.kind === "ready" ? mixedRows(view.folders, view.files) : [];
  const nextPageKind =
    view.kind === "ready" && view.nextFolderToken
      ? "folders"
      : view.kind === "ready" && view.nextFileToken
        ? "files"
        : null;
  const nextPageToken =
    view.kind === "ready"
      ? (view.nextFolderToken ?? view.nextFileToken)
      : null;

  return (
    <div className="kern-dialog-root">
      <button
        type="button"
        className="kern-dialog-backdrop"
        aria-label="Dismiss dialog"
        onClick={onCancel}
      />
      <div
        ref={dialogRef}
        className="kern-dialog kern-picker-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <div className="kern-picker-head">
          <div className="kern-picker-title-row">
            <div>
              <h2 id={titleId} className="kern-dialog-title">
                Choose from Google Drive
              </h2>
              <p id={descriptionId} className="kern-dialog-body">
                Select the files or folders Kernector should keep synchronized.
              </p>
            </div>
            <Button
              variant="ghost"
              className="kern-picker-close"
              aria-label="Close"
              onClick={onCancel}
            >
              <CloseGlyph />
            </Button>
          </div>
          <form
            className="kern-picker-search"
            onSubmit={(event) => {
              event.preventDefault();
              setSubmittedQuery(search);
            }}
          >
            <label htmlFor={searchId} className="visually-hidden">
              Search Google Drive
            </label>
            <input
              ref={searchRef}
              id={searchId}
              type="search"
              className="kern-settings-input"
              placeholder="Search in Drive"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <Button type="submit" variant="secondary">
              Search
            </Button>
          </form>
        </div>

        {query || view.kind === "loading" ? null : (
          <nav className="kern-picker-crumbs" aria-label="Current Drive folder">
            {crumbs.map((crumb, index) => (
              <span key={crumb.id}>
                {index > 0 ? <span aria-hidden="true"> / </span> : null}
                {index === crumbs.length - 1 ? (
                  <strong>{crumb.name}</strong>
                ) : (
                  <button
                    type="button"
                    className="kern-picker-crumb"
                    onClick={() => setCrumbs(crumbs.slice(0, index + 1))}
                  >
                    {crumb.name}
                  </button>
                )}
              </span>
            ))}
          </nav>
        )}

        <div
          className={
            view.kind === "loading"
              ? "kern-picker-list is-loading"
              : "kern-picker-list"
          }
        >
          {view.kind === "loading" ? (
            <div className="kern-picker-loading" role="status">
              <KernectorLoaderMark className="kern-picker-loader" />
              <span className="visually-hidden">Loading Google Drive…</span>
            </div>
          ) : null}
          {view.kind === "error" ? (
            <div
              className="kern-settings-callout kern-settings-callout--error"
              role="alert"
            >
              <p>
                {view.code === "google_drive_reauthorization_required"
                  ? "Google Drive authorization was revoked. Connect again."
                  : view.message}
              </p>
              <Button variant="secondary" onClick={() => void loadPage()}>
                Retry
              </Button>
            </div>
          ) : null}
          {view.kind === "ready" && rows.length === 0 ? (
            <p role="status">
              {query
                ? "No matching Drive items."
                : "This folder has no items you can select."}
            </p>
          ) : null}
          {view.kind === "ready"
            ? rows.map((item) => {
                const itemKind = item.kind === "folder" ? "folder" : "file";
                const navigable = itemKind === "folder" && !query;
                const checked = selected.has(item.id);
                return (
                  <div
                    className={
                      checked ? "kern-drive-item is-checked" : "kern-drive-item"
                    }
                    key={item.id}
                  >
                    <label className="kern-drive-item-select">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={
                          itemKind === "file" && item.supported === false
                        }
                        onChange={() => toggle(item)}
                      />
                      <span className="kern-drive-item-icon">
                        {itemKind === "folder" ? <FolderGlyph /> : <FileGlyph />}
                      </span>
                      <span className="kern-drive-item-copy">
                        <strong>{item.name}</strong>
                        <span className="kern-drive-item-meta">
                          {itemKind === "folder"
                            ? "Includes future files and updates"
                            : (item.mime_type ?? "File")}
                        </span>
                      </span>
                    </label>
                    {navigable ? (
                      <Button
                        variant="ghost"
                        onClick={() =>
                          setCrumbs((current) => [
                            ...current,
                            { id: item.id, name: item.name },
                          ])
                        }
                      >
                        Open
                      </Button>
                    ) : null}
                  </div>
                );
              })
            : null}
          {nextPageKind && nextPageToken ? (
            <Button
              variant="secondary"
              onClick={() =>
                void loadPage({
                  pageToken: nextPageToken,
                  pageKind: nextPageKind,
                })
              }
            >
              Load more
            </Button>
          ) : null}
        </div>

        <div className="kern-picker-foot">
          <span aria-live="polite">{countLabel}</span>
          <div className="kern-dialog-actions">
            <Button variant="secondary" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button
              disabled={busy || selectionUnchanged}
              onClick={() => onConfirm(toSelection(selected))}
            >
              {busy ? "Saving…" : "Save"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
