"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { DialogFrame } from "@/components/ui/DialogFrame";
import { Loader } from "@/components/ui/Loader";
import { ApiError, isAbortError } from "@/lib/api/errors";
import {
  createGoogleDriveFolder,
  listGoogleDriveItems,
  GOOGLE_DRIVE_SELECTION_ITEM_MAX,
  type CreateGoogleDriveFolderOptions,
  type GoogleDriveBrowseItemResponse,
  type GoogleDriveSelectionResponse,
  type ListGoogleDriveItemsOptions,
} from "@/lib/api/connectors";

export type GoogleDrivePickerProps = {
  open: boolean;
  apiBaseUrl: string;
  initialSelection: GoogleDriveSelectionResponse;
  selectionLoading?: boolean;
  busy?: boolean;
  foldersOnly?: boolean;
  singleSelect?: boolean;
  title?: string;
  description?: string;
  confirmLabel?: string;
  listItems?: (options: ListGoogleDriveItemsOptions) => Promise<{
    items: GoogleDriveBrowseItemResponse[];
    next_page_token?: string | null;
  }>;
  createFolder?: (
    options: CreateGoogleDriveFolderOptions,
  ) => Promise<GoogleDriveBrowseItemResponse>;
  onConfirm: (selection: GoogleDriveSelectionResponse) => void;
  onCancel: () => void;
  notice?: string | null;
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

function countKind(
  map: Map<string, { kind: "folder" | "file" }>,
  kind: "folder" | "file",
): number {
  let count = 0;
  for (const item of map.values()) {
    if (item.kind === kind) {
      count += 1;
    }
  }
  return count;
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
  return [...folders, ...files.filter((item) => !seen.has(item.id))];
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

function ChevronGlyph() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M7.5 4.5 13 10l-5.5 5.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function GoogleDrivePicker({
  open,
  apiBaseUrl,
  initialSelection,
  selectionLoading = false,
  busy = false,
  foldersOnly = false,
  singleSelect = false,
  title = "Choose from Google Drive",
  description = "Select the files or folders Kernector should keep synchronized.",
  confirmLabel = "Save",
  listItems = listGoogleDriveItems,
  createFolder = createGoogleDriveFolder,
  onConfirm,
  onCancel,
  notice = null,
}: GoogleDrivePickerProps) {
  const titleId = useId();
  const descriptionId = useId();
  const searchId = useId();
  const newFolderId = useId();
  const searchRef = useRef<HTMLInputElement>(null);
  const newFolderRef = useRef<HTMLInputElement>(null);

  const destinationMode = foldersOnly && singleSelect;

  const [crumbs, setCrumbs] = useState<Crumb[]>([ROOT]);
  const [search, setSearch] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [view, setView] = useState<BrowseView>({ kind: "loading" });
  const [selected, setSelected] = useState(() => selectedMap(initialSelection));
  const [destination, setDestination] = useState<Crumb>(ROOT);
  const [appliedKey, setAppliedKey] = useState("");
  const [creating, setCreating] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const dirtyRef = useRef(false);
  const loadSeqRef = useRef(0);
  const loadAbortRef = useRef<AbortController | null>(null);

  const parentId = crumbs[crumbs.length - 1]?.id ?? "root";
  const query = submittedQuery.trim();

  async function loadPage(options?: {
    pageToken?: string | null;
    pageKind?: "folders" | "files";
  }) {
    const pageToken = options?.pageToken ?? null;
    const pageKind = options?.pageKind;
    const seq = pageToken ? loadSeqRef.current : ++loadSeqRef.current;
    if (!pageToken) {
      loadAbortRef.current?.abort();
      loadAbortRef.current = new AbortController();
      setView({ kind: "loading" });
    }
    const signal = loadAbortRef.current?.signal;
    try {
      if (pageToken && pageKind) {
        const page = await listItems({
          baseUrl: apiBaseUrl,
          parentId,
          kind: pageKind,
          query: query || undefined,
          pageToken,
          signal,
        });
        if (seq !== loadSeqRef.current || signal?.aborted) {
          return;
        }
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
          signal,
        }),
        foldersOnly
          ? Promise.resolve({ items: [], next_page_token: null })
          : listItems({
              baseUrl: apiBaseUrl,
              parentId,
              kind: "files",
              query: query || undefined,
              signal,
            }),
      ]);
      if (seq !== loadSeqRef.current || signal?.aborted) {
        return;
      }
      setView({
        kind: "ready",
        folders: folderPage.items,
        files: filePage.items,
        nextFolderToken: folderPage.next_page_token ?? null,
        nextFileToken: filePage.next_page_token ?? null,
      });
    } catch (error) {
      if (seq !== loadSeqRef.current || signal?.aborted) {
        return;
      }
      if (isAbortError(error)) {
        return;
      }
      setView({ kind: "error", ...browseErrorMessage(error) });
    }
  }

  const initialSelectionRef = useRef(initialSelection);
  initialSelectionRef.current = initialSelection;
  const baselineKey = [
    ...(initialSelection.folders ?? []).map((item) => `folder:${item.id}`),
    ...(initialSelection.files ?? []).map((item) => `file:${item.id}`),
  ].join("|");
  if (open && !dirtyRef.current && appliedKey !== baselineKey) {
    setSelected(selectedMap(initialSelection));
    setAppliedKey(baselineKey);
  }

  useEffect(() => {
    if (!open) {
      dirtyRef.current = false;
      loadAbortRef.current?.abort();
      return;
    }
    setCrumbs([ROOT]);
    setSearch("");
    setSubmittedQuery("");
    setCreating(false);
    setNewFolderName("");
    setCreateError(null);
    setCreateBusy(false);
    setDestination(ROOT);
    setSelected(selectedMap(initialSelectionRef.current));
  }, [open]);

  useEffect(() => {
    if (!open || !destinationMode) {
      return;
    }
    const current = crumbs[crumbs.length - 1] ?? ROOT;
    setDestination(current);
  }, [open, destinationMode, crumbs]);

  useEffect(() => {
    if (!open) {
      return;
    }
    void loadPage();
    return () => {
      loadAbortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload on browse identity
  }, [open, parentId, submittedQuery]);

  useEffect(() => {
    if (creating) {
      newFolderRef.current?.focus();
    }
  }, [creating]);

  const countLabel =
    selected.size === 0
      ? foldersOnly
        ? "No folder selected"
        : "No items selected"
      : `${selected.size} selected`;

  const destinationPathParts = (() => {
    const currentId = crumbs[crumbs.length - 1]?.id ?? "root";
    const parts =
      destination.id === currentId
        ? crumbs.map((crumb) =>
            crumb.id === "root" ? "Home" : crumb.name,
          )
        : [
            ...crumbs.map((crumb) =>
              crumb.id === "root" ? "Home" : crumb.name,
            ),
            destination.name,
          ];
    return parts;
  })();

  const destinationPathLabel = `Exporting to: ${destinationPathParts.join(" / ")}`;
  const destinationConfirmName = destinationPathParts.join(" / ");

  const atListCap = singleSelect
    ? false
    : countKind(selected, "folder") >= GOOGLE_DRIVE_SELECTION_ITEM_MAX ||
      countKind(selected, "file") >= GOOGLE_DRIVE_SELECTION_ITEM_MAX;
  const selectionUnchanged = sameSelection(selected, initialSelection);
  const confirmDisabled = destinationMode
    ? busy || selectionLoading || createBusy || !destination.id
    : busy ||
      selectionLoading ||
      createBusy ||
      (singleSelect
        ? countKind(selected, "folder") !== 1
        : selectionUnchanged);

  function toggle(item: GoogleDriveBrowseItemResponse) {
    if (foldersOnly && item.kind !== "folder") {
      return;
    }
    const kind = item.kind === "folder" ? "folder" : "file";
    dirtyRef.current = true;
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(item.id)) {
        next.delete(item.id);
        return next;
      }
      if (singleSelect) {
        next.clear();
        next.set(item.id, { id: item.id, name: item.name, kind });
        return next;
      }
      if (countKind(next, kind) >= GOOGLE_DRIVE_SELECTION_ITEM_MAX) {
        return current;
      }
      next.set(item.id, { id: item.id, name: item.name, kind });
      return next;
    });
  }

  function selectDestination(item: Crumb) {
    dirtyRef.current = true;
    setDestination(item);
  }

  function openFolder(item: Crumb) {
    setSubmittedQuery("");
    setSearch("");
    setCreating(false);
    setCreateError(null);
    setCrumbs((current) => [...current, item]);
  }

  function goToCrumb(index: number) {
    setSubmittedQuery("");
    setSearch("");
    setCreating(false);
    setCreateError(null);
    setCrumbs((current) => {
      if (index < 0 || index >= current.length) {
        return current;
      }
      if (current.length === index + 1) {
        return current;
      }
      return current.slice(0, index + 1);
    });
  }

  async function submitNewFolder() {
    const name = newFolderName.trim();
    if (!name || createBusy) {
      return;
    }
    setCreateBusy(true);
    setCreateError(null);
    try {
      const created = await createFolder({
        baseUrl: apiBaseUrl,
        name,
        parentId,
      });
      setCreating(false);
      setNewFolderName("");
      dirtyRef.current = true;
      setDestination({ id: created.id, name: created.name });
      await loadPage();
    } catch (error) {
      setCreateError(browseErrorMessage(error).message);
    } finally {
      setCreateBusy(false);
    }
  }

  const listLoading = selectionLoading || view.kind === "loading";
  const rows =
    view.kind === "ready"
      ? foldersOnly
        ? view.folders
        : mixedRows(view.folders, view.files)
      : [];
  const nextPageKind =
    view.kind === "ready" && view.nextFolderToken
      ? "folders"
      : view.kind === "ready" && view.nextFileToken && !foldersOnly
        ? "files"
        : null;
  const nextPageToken =
    view.kind === "ready"
      ? (view.nextFolderToken ??
        (foldersOnly ? null : view.nextFileToken))
      : null;

  return (
    <DialogFrame
      open={open}
      titleId={titleId}
      descriptionId={descriptionId}
      panelClassName="kern-picker-dialog kern-drive-picker"
      initialFocusRef={searchRef}
      onDismiss={onCancel}
    >
      <div className="kern-picker-head">
        <div className="kern-picker-title-row">
          <div>
            <h2 id={titleId} className="kern-dialog-title">
              {title}
            </h2>
            <p id={descriptionId} className="kern-dialog-body">
              {description}
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

      {notice ? (
        <div
          className="kern-settings-callout kern-settings-callout--error"
          role="alert"
        >
          <p>{notice}</p>
        </div>
      ) : null}

      <div className="kern-drive-picker-body">
        <aside className="kern-drive-picker-rail" aria-label="Drive locations">
          <button
            type="button"
            className={
              crumbs.length === 1 && !query
                ? "kern-drive-rail-item is-active"
                : "kern-drive-rail-item"
            }
            onClick={() => goToCrumb(0)}
          >
            <span className="kern-drive-item-icon">
              <FolderGlyph />
            </span>
            <span>My Drive</span>
          </button>
        </aside>

        <div className="kern-drive-picker-main">
          {query ? null : (
            <div className="kern-drive-picker-toolbar">
              <nav
                className="kern-picker-crumbs"
                aria-label="Current Drive folder"
              >
                {crumbs.map((crumb, index) => (
                  <span key={`${crumb.id}-${index}`} className="kern-picker-crumb-segment">
                    {index > 0 ? (
                      <span className="kern-picker-crumb-sep" aria-hidden="true">
                        /
                      </span>
                    ) : null}
                    {index === crumbs.length - 1 ? (
                      <strong>{crumb.name}</strong>
                    ) : (
                      <button
                        type="button"
                        className="kern-picker-crumb"
                        onClick={() => goToCrumb(index)}
                      >
                        {crumb.name}
                      </button>
                    )}
                  </span>
                ))}
              </nav>
              {destinationMode ? (
                <Button
                  variant="secondary"
                  disabled={busy || createBusy || listLoading || creating}
                  onClick={() => {
                    setCreating(true);
                    setNewFolderName("Untitled folder");
                    setCreateError(null);
                  }}
                >
                  New folder
                </Button>
              ) : null}
            </div>
          )}

          {createError ? (
            <div
              className="kern-settings-callout kern-settings-callout--error"
              role="alert"
            >
              <p>{createError}</p>
            </div>
          ) : null}

          <div
            className={
              listLoading ? "kern-picker-list is-loading" : "kern-picker-list"
            }
          >
            {listLoading ? (
              <div className="kern-picker-loading">
                <Loader label="Loading Google Drive" />
              </div>
            ) : null}
            {view.kind === "error" && !selectionLoading ? (
              <div
                className="kern-settings-callout kern-settings-callout--error"
                role="status"
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
            {creating && !listLoading ? (
              <form
                className="kern-drive-item is-creating"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitNewFolder();
                }}
              >
                <span className="kern-drive-item-icon">
                  <FolderGlyph />
                </span>
                <label htmlFor={newFolderId} className="visually-hidden">
                  New folder name
                </label>
                <input
                  ref={newFolderRef}
                  id={newFolderId}
                  type="text"
                  className="kern-settings-input kern-drive-rename-input"
                  value={newFolderName}
                  maxLength={256}
                  disabled={createBusy}
                  aria-invalid={createError ? true : undefined}
                  onChange={(event) => setNewFolderName(event.target.value)}
                  onFocus={(event) => event.currentTarget.select()}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      event.preventDefault();
                      setCreating(false);
                      setNewFolderName("");
                      setCreateError(null);
                    }
                  }}
                />
                <Button
                  type="submit"
                  disabled={createBusy || !newFolderName.trim()}
                >
                  Save
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  disabled={createBusy}
                  onClick={() => {
                    setCreating(false);
                    setNewFolderName("");
                    setCreateError(null);
                  }}
                >
                  Cancel
                </Button>
              </form>
            ) : null}
            {view.kind === "ready" &&
            !selectionLoading &&
            !creating &&
            rows.length === 0 ? (
              <div className="kern-drive-empty" role="status">
                <p>
                  {query
                    ? "No matching Drive items."
                    : destinationMode
                      ? "No subfolders here. Export to this location, or use New folder above."
                      : foldersOnly
                        ? "This folder has no subfolders."
                        : "This folder has no items you can select."}
                </p>
              </div>
            ) : null}
            {view.kind === "ready" && !selectionLoading
              ? rows.map((item) => {
                  const itemKind = item.kind === "folder" ? "folder" : "file";
                  const navigable = itemKind === "folder" && !query;
                  const checked = destinationMode
                    ? destination.id === item.id
                    : selected.has(item.id);
                  return (
                    <div
                      className={
                        checked
                          ? "kern-drive-item is-checked"
                          : "kern-drive-item"
                      }
                      key={item.id}
                    >
                      {destinationMode && itemKind === "folder" ? (
                        <label className="kern-drive-item-select">
                          <input
                            type="radio"
                            name="kern-drive-destination"
                            checked={checked}
                            onChange={() =>
                              selectDestination({
                                id: item.id,
                                name: item.name,
                              })
                            }
                          />
                          <span className="kern-drive-item-icon">
                            <FolderGlyph />
                          </span>
                          <span className="kern-drive-item-copy">
                            <strong>{item.name}</strong>
                            {checked ? (
                              <span className="kern-drive-item-meta">
                                Selected destination
                              </span>
                            ) : null}
                          </span>
                        </label>
                      ) : (
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
                            {itemKind === "folder" ? (
                              <FolderGlyph />
                            ) : (
                              <FileGlyph />
                            )}
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
                      )}
                      {navigable ? (
                        <Button
                          variant="ghost"
                          className="kern-drive-open"
                          aria-label={`Open ${item.name}`}
                          onClick={() =>
                            openFolder({ id: item.id, name: item.name })
                          }
                        >
                          <span className="kern-drive-open-label">Open</span>
                          <ChevronGlyph />
                        </Button>
                      ) : null}
                    </div>
                  );
                })
              : null}
            {nextPageKind && nextPageToken && !selectionLoading ? (
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
        </div>
      </div>

      <div className="kern-picker-foot">
        <span aria-live="polite">
          {destinationMode ? destinationPathLabel : countLabel}
          {!destinationMode && atListCap
            ? ` · at most ${GOOGLE_DRIVE_SELECTION_ITEM_MAX} folders or files each`
            : ""}
        </span>
        <div className="kern-dialog-actions">
          <Button
            variant="secondary"
            onClick={onCancel}
            disabled={busy || createBusy}
          >
            Cancel
          </Button>
          <Button
            disabled={confirmDisabled}
            onClick={() => {
              if (destinationMode) {
                onConfirm({
                  folders: [
                    {
                      id: destination.id,
                      name: destinationConfirmName,
                    },
                  ],
                  files: [],
                });
                return;
              }
              onConfirm(toSelection(selected));
            }}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </DialogFrame>
  );
}
