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

/** Presentation-safe GitHub OAuth connection status (mirrors Drive). */
export type GitHubLastSyncResponse = {
  synced_at: string;
  new_count: number;
  updated_count: number;
  unchanged_count: number;
  failed_count: number;
  removed_count?: number;
};

export type GitHubStatusResponse = {
  configured: boolean;
  available: boolean;
  connected: boolean;
  oauth_ready: boolean;
  account_login: string | null;
  document_count: number;
  owner: string | null;
  repo: string | null;
  project_owner?: string | null;
  project_number?: number | null;
  last_sync: GitHubLastSyncResponse | null;
  reauthorization_required: boolean;
  connection_state: string;
  sync_scope?: string | null;
  setup_required?: boolean;
};

export type GitHubSyncResponse = {
  ingested_count: number;
  updated_count: number;
  skipped_count: number;
  failed_count: number;
  removed_count: number;
  outcomes: Array<{
    source_id: string;
    status: "ingested" | "updated" | "skipped" | "failed" | "removed";
    chunk_count: number;
    error_type: string | null;
  }>;
};

export type GitHubRepoItemResponse = {
  owner: string;
  name: string;
  full_name: string;
  private: boolean;
};

export type GitHubRepoPageResponse = {
  items: GitHubRepoItemResponse[];
  has_next: boolean;
  page: number;
};

export type GitHubProjectItemResponse = {
  owner_login: string;
  number: number;
  title: string;
};

export type GitHubProjectPageResponse = {
  items: GitHubProjectItemResponse[];
  next_cursor: string | null;
};

export type GitHubSelectionResponse = {
  owner: string | null;
  repo: string | null;
  project_owner: string | null;
  project_number: number | null;
  connector_id?: string | null;
};

export const GITHUB_OAUTH_START_PATH =
  "/api/v1/connectors/github/oauth/start";

export function githubOAuthStartUrl(baseUrl: string): string {
  return `${baseUrl.replace(/\/$/, "")}${GITHUB_OAUTH_START_PATH}`;
}

export type GetGitHubStatusOptions = {
  baseUrl: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

export type SyncGitHubOptions = GetGitHubStatusOptions;
export type DisconnectGitHubOptions = GetGitHubStatusOptions;
export type GetGitHubSelectionOptions = GetGitHubStatusOptions;
export type ListGitHubReposOptions = GetGitHubStatusOptions & {
  page?: number;
};
export type ListGitHubProjectsOptions = GetGitHubStatusOptions & {
  ownerLogin: string;
  after?: string | null;
};
export type PutGitHubSelectionOptions = GetGitHubStatusOptions & {
  selection: {
    owner: string;
    repo: string;
    project_owner?: string | null;
    project_number?: number | null;
  };
};

/**
 * Load GitHub OAuth connection status from ``GET /api/v1/connectors/github``.
 */
export async function getGitHubStatus(
  options: GetGitHubStatusOptions,
): Promise<GitHubStatusResponse> {
  const request = options.request ?? apiRequest;
  return request<GitHubStatusResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/github",
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * List repositories for the Hub picker via
 * ``GET /api/v1/connectors/github/repos``.
 */
export async function listGitHubRepos(
  options: ListGitHubReposOptions,
): Promise<GitHubRepoPageResponse> {
  const request = options.request ?? apiRequest;
  const page = options.page ?? 1;
  return request<GitHubRepoPageResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/connectors/github/repos?page=${encodeURIComponent(String(page))}`,
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * List ProjectV2 projects for a login via
 * ``GET /api/v1/connectors/github/projects``.
 */
export async function listGitHubProjects(
  options: ListGitHubProjectsOptions,
): Promise<GitHubProjectPageResponse> {
  const request = options.request ?? apiRequest;
  const params = new URLSearchParams({
    owner_login: options.ownerLogin,
  });
  if (options.after) {
    params.set("after", options.after);
  }
  return request<GitHubProjectPageResponse>({
    baseUrl: options.baseUrl,
    path: `/api/v1/connectors/github/projects?${params.toString()}`,
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Load the saved GitHub selection via
 * ``GET /api/v1/connectors/github/selection``.
 */
export async function getGitHubSelection(
  options: GetGitHubSelectionOptions,
): Promise<GitHubSelectionResponse> {
  const request = options.request ?? apiRequest;
  return request<GitHubSelectionResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/github/selection",
    method: "GET",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Replace the saved GitHub selection via
 * ``PUT /api/v1/connectors/github/selection``.
 */
export async function putGitHubSelection(
  options: PutGitHubSelectionOptions,
): Promise<GitHubSelectionResponse> {
  const request = options.request ?? apiRequest;
  return request<GitHubSelectionResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/github/selection",
    method: "PUT",
    body: options.selection,
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}

/**
 * Synchronize the connected GitHub grant via
 * ``POST /api/v1/connectors/github/sync``.
 */
export async function syncGitHub(
  options: SyncGitHubOptions,
): Promise<GitHubSyncResponse> {
  const request = options.request ?? apiRequest;
  return request<GitHubSyncResponse>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/github/sync",
    method: "POST",
    signal: options.signal,
    timeoutMs: options.timeoutMs ?? CONNECTOR_SYNC_TIMEOUT_MS,
  } satisfies ApiRequestOptions);
}

/**
 * Revoke and delete the stored GitHub grant via
 * ``DELETE /api/v1/connectors/github``.
 */
export async function disconnectGitHub(
  options: DisconnectGitHubOptions,
): Promise<void> {
  const request = options.request ?? apiRequest;
  await request<undefined>({
    baseUrl: options.baseUrl,
    path: "/api/v1/connectors/github",
    method: "DELETE",
    signal: options.signal,
    timeoutMs: options.timeoutMs,
  } satisfies ApiRequestOptions);
}
