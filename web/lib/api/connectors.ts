import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type GoogleDriveStatusResponse =
  components["schemas"]["GoogleDriveStatusResponse"];
export type GoogleDriveSyncResponse =
  components["schemas"]["GoogleDriveSyncResponse"];

/** A first whole-folder sync fetches, extracts, and embeds every file. */
export const CONNECTOR_SYNC_TIMEOUT_MS = 300_000;

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
