import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GoogleDrivePanel } from "@/components/documents/GoogleDrivePanel";
import { ApiError } from "@/lib/api/errors";
import type { GoogleDriveSyncResponse } from "@/lib/api/connectors";

const CONFIGURED = { configured: true, available: true };

function syncResult(
  overrides: Partial<GoogleDriveSyncResponse> = {},
): GoogleDriveSyncResponse {
  return {
    ingested_count: 1,
    skipped_count: 2,
    failed_count: 0,
    outcomes: [],
    ...overrides,
  };
}

describe("GoogleDrivePanel", () => {
  it("shows loading status then Sync now when configured", async () => {
    let resolveStatus: (value: typeof CONFIGURED) => void = () => {};
    const getStatus = vi.fn(
      () =>
        new Promise<typeof CONFIGURED>((resolve) => {
          resolveStatus = resolve;
        }),
    );

    render(
      <GoogleDrivePanel apiBaseUrl="http://api.test" getStatus={getStatus} />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
    expect(
      screen.queryByRole("button", { name: /sync now/i }),
    ).not.toBeInTheDocument();

    resolveStatus(CONFIGURED);

    expect(
      await screen.findByRole("button", { name: /sync now/i }),
    ).toBeEnabled();
  });

  it("explains unconfigured backend env and hides Sync now", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => ({ configured: false, available: true })}
      />,
    );

    expect(
      await screen.findByText(/backend environment variables/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/GOOGLE_DRIVE_FOLDER_ID/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /sync now/i }),
    ).not.toBeInTheDocument();
    expect(document.querySelector("input")).toBeNull();
  });

  it("shows extra unavailable copy and hides Sync now", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => ({ configured: true, available: false })}
      />,
    );

    expect(
      await screen.findByRole("heading", {
        name: /google drive extra unavailable/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/uv sync --extra google-drive/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /sync now/i }),
    ).not.toBeInTheDocument();
  });

  it("shows ingested skipped failed after a successful sync", async () => {
    const user = userEvent.setup();
    const syncNow = vi.fn().mockResolvedValue(syncResult());
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONFIGURED}
        syncNow={syncNow}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /sync now/i }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      /ingested 1/i,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/skipped 2/i);
    expect(screen.getByRole("status")).toHaveTextContent(/failed 0/i);
  });

  it("shows empty state when a sync changes nothing", async () => {
    const user = userEvent.setup();
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONFIGURED}
        syncNow={async () =>
          syncResult({
            ingested_count: 0,
            skipped_count: 0,
            failed_count: 0,
          })
        }
      />,
    );

    await user.click(await screen.findByRole("button", { name: /sync now/i }));

    expect(
      await screen.findByRole("heading", { name: /no drive changes/i }),
    ).toBeInTheDocument();
  });

  it("ignores overlapping Sync now clicks", async () => {
    const user = userEvent.setup();
    let resolveSync: (value: GoogleDriveSyncResponse) => void = () => {};
    const syncNow = vi.fn(
      () =>
        new Promise<GoogleDriveSyncResponse>((resolve) => {
          resolveSync = resolve;
        }),
    );
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONFIGURED}
        syncNow={syncNow}
      />,
    );

    const button = await screen.findByRole("button", { name: /sync now/i });
    await user.click(button);
    await user.click(button);

    expect(syncNow).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /syncing/i })).toBeDisabled();

    resolveSync(syncResult());
    expect(await screen.findByText(/ingested 1/i)).toBeInTheDocument();
  });

  it("shows ApiError detail on sync failure", async () => {
    const user = userEvent.setup();
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONFIGURED}
        syncNow={async () => {
          throw new ApiError({
            status: 502,
            title: "Connector sync failed",
            detail: "The Google Drive connector sync failed.",
            code: "connector_sync_failed",
          });
        }}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /sync now/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The Google Drive connector sync failed.");
  });

  it("says an aborted sync may still be running and re-fetches status", async () => {
    const user = userEvent.setup();
    const getStatus = vi.fn().mockResolvedValue(CONFIGURED);
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={getStatus}
        syncNow={async () => {
          throw ApiError.aborted();
        }}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /sync now/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /may still be in progress on the server/i,
    );
    await waitFor(() => {
      expect(getStatus).toHaveBeenCalledTimes(2);
    });
  });
});
