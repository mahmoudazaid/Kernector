import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import {
  CONNECTOR_SYNC_TIMEOUT_MS,
  GOOGLE_DRIVE_OAUTH_START_PATH,
  GOOGLE_DRIVE_SELECTION_ITEM_MAX,
  GOOGLE_DRIVE_SELECTION_TIMEOUT_MS,
  disconnectGoogleDrive,
  getGoogleDriveSelection,
  getGoogleDriveStatus,
  googleDriveOAuthStartUrl,
  listGoogleDriveItems,
  putGoogleDriveSelection,
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

  it("keeps file and folder selection caps aligned", async () => {
    const spec = await import("../openapi/openapi.json");
    const request = spec.components.schemas.GoogleDriveSelectionRequest.properties;
    expect(request.folders.maxItems).toBe(100);
    expect(request.files.maxItems).toBe(100);
    expect(GOOGLE_DRIVE_SELECTION_ITEM_MAX).toBe(request.folders.maxItems);
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

  it("browses items without putting tokens in the path", async () => {
    const request = vi.fn().mockResolvedValue({
      items: [
        {
          id: "folder-1",
          name: "Specs",
          kind: "folder",
          mime_type: "application/vnd.google-apps.folder",
          supported: true,
          modified_at: null,
        },
      ],
      next_page_token: null,
    });

    await listGoogleDriveItems({
      baseUrl: "http://api.test",
      parentId: "root",
      kind: "folders",
      request,
    });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/connectors/google-drive/items?parent_id=root&kind=folders",
        method: "GET",
      }),
    );
    expect(String(request.mock.calls[0][0].path)).not.toMatch(/ya29|1\/\//);
  });

  it("loads and replaces selection by Drive ID", async () => {
    const request = vi.fn().mockResolvedValue({
      folders: [{ id: "folder-1", name: "Specs" }],
      files: [],
    });

    await getGoogleDriveSelection({
      baseUrl: "http://api.test",
      request,
    });
    await putGoogleDriveSelection({
      baseUrl: "http://api.test",
      selection: { folders: [{ id: "folder-1", name: "Specs" }], files: [] },
      request,
    });

    expect(request).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        path: "/api/v1/connectors/google-drive/selection",
        method: "GET",
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        path: "/api/v1/connectors/google-drive/selection",
        method: "PUT",
        body: {
          folders: [{ id: "folder-1", name: "Specs" }],
          files: [],
        },
        timeoutMs: GOOGLE_DRIVE_SELECTION_TIMEOUT_MS,
      }),
    );
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
