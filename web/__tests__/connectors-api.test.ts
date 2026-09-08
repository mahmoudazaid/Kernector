import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import {
  CONNECTOR_SYNC_TIMEOUT_MS,
  getGoogleDriveStatus,
  syncGoogleDrive,
} from "@/lib/api/connectors";

describe("google drive connector wrappers", () => {
  it("loads status via GET /api/v1/connectors/google-drive", async () => {
    const request = vi.fn().mockResolvedValue({
      configured: true,
      available: true,
    });

    const result = await getGoogleDriveStatus({
      baseUrl: "http://api.test",
      request,
    });

    expect(result).toEqual({ configured: true, available: true });
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        baseUrl: "http://api.test",
        path: "/api/v1/connectors/google-drive",
        method: "GET",
      }),
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

  it("propagates ApiError from the transport", async () => {
    const request = vi.fn().mockRejectedValue(
      new ApiError({
        status: 409,
        title: "Google Drive not configured",
        detail: "Google Drive is not configured on the server.",
        code: "google_drive_unconfigured",
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
      code: "google_drive_unconfigured",
    });
  });
});
