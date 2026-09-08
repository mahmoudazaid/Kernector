import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import {
  CONNECTOR_SYNC_TIMEOUT_MS,
  GOOGLE_DRIVE_OAUTH_START_PATH,
  disconnectGoogleDrive,
  getGoogleDriveStatus,
  googleDriveOAuthStartUrl,
  syncGoogleDrive,
} from "@/lib/api/connectors";

describe("google drive connector wrappers", () => {
  it("loads status via GET /api/v1/connectors/google-drive", async () => {
    const request = vi.fn().mockResolvedValue({
      configured: false,
      available: true,
      connected: false,
      oauth_ready: true,
    });

    const result = await getGoogleDriveStatus({
      baseUrl: "http://api.test",
      request,
    });

    expect(result.connected).toBe(false);
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        baseUrl: "http://api.test",
        path: "/api/v1/connectors/google-drive",
        method: "GET",
      }),
    );
  });

  it("builds the backend OAuth start URL without Google hosts", () => {
    expect(googleDriveOAuthStartUrl("http://api.test/")).toBe(
      `http://api.test${GOOGLE_DRIVE_OAUTH_START_PATH}`,
    );
    expect(GOOGLE_DRIVE_OAUTH_START_PATH).toBe(
      "/api/v1/connectors/google-drive/oauth/start",
    );
  });

  it("syncs with POST and a whole-folder timeout", async () => {
    const request = vi.fn().mockResolvedValue({
      ingested_count: 1,
      skipped_count: 2,
      failed_count: 0,
      outcomes: [],
    });

    await syncGoogleDrive({
      baseUrl: "http://api.test",
      request,
    });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/connectors/google-drive/sync",
        method: "POST",
        timeoutMs: CONNECTOR_SYNC_TIMEOUT_MS,
      }),
    );
    expect(CONNECTOR_SYNC_TIMEOUT_MS).toBe(300_000);
  });

  it("disconnects via DELETE /api/v1/connectors/google-drive", async () => {
    const request = vi.fn().mockResolvedValue(undefined);

    await disconnectGoogleDrive({
      baseUrl: "http://api.test",
      request,
    });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/connectors/google-drive",
        method: "DELETE",
      }),
    );
  });

  it("propagates ApiError from the transport", async () => {
    const request = vi.fn().mockRejectedValue(
      new ApiError({
        status: 409,
        title: "Google Drive not connected",
        detail: "Google Drive is not connected.",
        code: "google_drive_not_connected",
      }),
    );

    await expect(
      syncGoogleDrive({
        baseUrl: "http://api.test",
        request,
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      code: "google_drive_not_connected",
    });
  });
});
