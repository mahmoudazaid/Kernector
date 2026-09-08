import { apiRequest, type ApiRequestOptions } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

export type GoogleDriveStatusResponse =
  components["schemas"]["GoogleDriveStatusResponse"];
export type GoogleDriveSyncResponse =
  components["schemas"]["GoogleDriveSyncResponse"];

/** A first whole-folder sync fetches, extracts, and embeds every file. */
export const CONNECTOR_SYNC_TIMEOUT_MS = 300_000;

export type GetGoogleDriveStatusOptions = {
  baseUrl: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  request?: typeof apiRequest;
};

export type SyncGoogleDriveOptions = GetGoogleDriveStatusOptions;

/**
 * Load Drive configuration presence from ``GET /api/v1/connectors/google-drive``.
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
 * Synchronize the configured Drive folder via ``POST /api/v1/connectors/google-drive/sync``.
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
