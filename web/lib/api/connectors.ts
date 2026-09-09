import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type GoogleDriveStatusResponse =
  components["schemas"]["GoogleDriveStatusResponse"];
export type GoogleDriveSyncResponse =
  components["schemas"]["GoogleDriveSyncResponse"];
export type GoogleDriveBrowsePageResponse =
  components["schemas"]["GoogleDriveBrowsePageResponse"];
export type GoogleDriveBrowseItemResponse =
  components["schemas"]["GoogleDriveBrowseItemResponse"];
export type GoogleDriveSelectionResponse =
  components["schemas"]["GoogleDriveSelectionResponse"];
export type GoogleDriveSelectedItemResponse =
  components["schemas"]["GoogleDriveSelectedItemResponse"];

/** A first whole-folder sync fetches, extracts, and embeds every file. */
export const CONNECTOR_SYNC_TIMEOUT_MS = 300_000;

/** PUT selection validates each Drive ID; 200 items can exceed the default 10s. */
export const GOOGLE_DRIVE_SELECTION_TIMEOUT_MS = 120_000;

export const GOOGLE_DRIVE_SELECTION_ITEM_MAX = 100;

export const GOOGLE_DRIVE_OAUTH_START_PATH =
  "/api/v1/connectors/google-drive/oauth/start";

export function googleDriveOAuthStartUrl(baseUrl: string): string {
  return `${baseUrl.replace(/\/$/, "")}${GOOGLE_DRIVE_OAUTH_START_PATH}`;
}

export type GetGoogleDriveStatusOptions = {
  baseUrl: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

export type SyncGoogleDriveOptions = GetGoogleDriveStatusOptions;
export type DisconnectGoogleDriveOptions = GetGoogleDriveStatusOptions;
export type GetGoogleDriveSelectionOptions = GetGoogleDriveStatusOptions;

export type ListGoogleDriveItemsOptions = GetGoogleDriveStatusOptions & {
  parentId?: string;
  kind?: "folders" | "files";
  query?: string;
  pageToken?: string | null;
};

export type PutGoogleDriveSelectionOptions = GetGoogleDriveStatusOptions & {
  selection: GoogleDriveSelectionResponse;
};

function itemsPath(options: ListGoogleDriveItemsOptions): string {
  const params = new URLSearchParams();
  if (options.parentId) {
    params.set("parent_id", options.parentId);
  }
  if (options.kind) {
    params.set("kind", options.kind);
  }
  if (options.query) {
    params.set("query", options.query);
  }
  if (options.pageToken) {
    params.set("page_token", options.pageToken);
  }
  const query = params.toString();
  return `/api/v1/connectors/google-drive/items${query ? `?${query}` : ""}`;
}

/**
 * Load Drive SA flags and user OAuth connection from
 * ``GET /api/v1/connectors/google-drive``.
 */
export async function getGoogleDriveStatus(
  options: GetGoogleDriveStatusOptions,
): Promise<GoogleDriveStatusResponse> {
  const request = options.request ?? apiRequest;
  return request<GoogleDriveStatusResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/google-drive",
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Browse Drive folders or files via
 * ``GET /api/v1/connectors/google-drive/items``.
 */
export async function listGoogleDriveItems(
  options: ListGoogleDriveItemsOptions,
): Promise<GoogleDriveBrowsePageResponse> {
  const request = options.request ?? apiRequest;
  return request<GoogleDriveBrowsePageResponse>({
    baseUrl: options.baseUrl,
    path: itemsPath(options),
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Load saved Drive roots via
 * ``GET /api/v1/connectors/google-drive/selection``.
 */
export async function getGoogleDriveSelection(
  options: GetGoogleDriveSelectionOptions,
): Promise<GoogleDriveSelectionResponse> {
  const request = options.request ?? apiRequest;
  return request<GoogleDriveSelectionResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/google-drive/selection",
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Replace saved Drive roots via
 * ``PUT /api/v1/connectors/google-drive/selection``.
 */
export async function putGoogleDriveSelection(
  options: PutGoogleDriveSelectionOptions,
): Promise<GoogleDriveSelectionResponse> {
  const request = options.request ?? apiRequest;
  return request<GoogleDriveSelectionResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/google-drive/selection",
    method: "PUT",
    body: {
      folders: options.selection.folders ?? [],
      files: options.selection.files ?? [],
    },
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? GOOGLE_DRIVE_SELECTION_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

/**
 * Synchronize the connected user grant via
 * ``POST /api/v1/connectors/google-drive/sync``.
 */
export async function syncGoogleDrive(
  options: SyncGoogleDriveOptions,
): Promise<GoogleDriveSyncResponse> {
  const request = options.request ?? apiRequest;
  return request<GoogleDriveSyncResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/google-drive/sync",
    method: "POST",
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? CONNECTOR_SYNC_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

/**
 * Revoke and delete the stored user grant via
 * ``DELETE /api/v1/connectors/google-drive``.
 */
export async function disconnectGoogleDrive(
  options: DisconnectGoogleDriveOptions,
): Promise<void> {
  const request = options.request ?? apiRequest;
  await request<undefined>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/google-drive",
    method: "DELETE",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}
