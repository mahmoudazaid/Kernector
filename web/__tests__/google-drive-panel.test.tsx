import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GoogleDrivePanel } from "@/components/documents/GoogleDrivePanel";
import { ApiError } from "@/lib/api/errors";
import {
  GOOGLE_DRIVE_OAUTH_START_PATH,
  type GoogleDriveStatusResponse,
} from "@/lib/api/connectors";

function status(
  overrides: Partial<GoogleDriveStatusResponse> = {},
): GoogleDriveStatusResponse {
  return {
    configured: false,
    available: true,
    connected: false,
    oauth_ready: true,
    account_email: null,
    document_count: 0,
    folder_count: null,
    last_sync: null,
    reauthorization_required: false,
    ...overrides,
  };
}

const CONNECTED = status({
  connected: true,
  account_email: "ada@example.com",
  document_count: 4,
  folder_count: 1,
  last_sync: {
    synced_at: "2026-09-08T12:00:00+00:00",
    new_count: 1,
    updated_count: 2,
    unchanged_count: 3,
    failed_count: 0,
  },
});

describe("GoogleDrivePanel", () => {
  it("shows Connect to the backend OAuth start URL before authorization", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => status()}
      />,
    );

    const connect = await screen.findByRole("link", { name: /^connect$/i });
    expect(connect).toHaveAttribute(
      "href",
      `http://api.test${GOOGLE_DRIVE_OAUTH_START_PATH}`,
    );
    expect(
      screen.queryByRole("button", { name: /sync now/i }),
    ).not.toBeInTheDocument();
    expect(document.querySelector("input")).toBeNull();
    expect(document.body.textContent).not.toMatch(/GOOGLE_DRIVE_SERVICE_ACCOUNT/);
    expect(screen.getByText(/sign in with your google account/i)).toBeInTheDocument();
    expect(connect.closest(".kern-available-card")).not.toBeNull();
    expect(connect.closest(".kern-source-card")).toBeNull();
  });

  it("keeps Connect on the Hub when OAuth is not configured", async () => {
    const user = userEvent.setup();
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => status({ oauth_ready: false })}
      />,
    );

    const connect = await screen.findByRole("link", { name: /^connect$/i });
    await user.click(connect);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/oauth is not configured on the server/i);
    expect(alert.closest(".kern-available-card")).toBeNull();
    expect(
      screen.queryByRole("link", { name: /redirecting to google/i }),
    ).not.toBeInTheDocument();
    expect(connect).toBeInTheDocument();
  });

  it("shows an accessible error after unconfigured callback", async () => {
    window.history.pushState({}, "", "/documents?drive=unconfigured");
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => status({ oauth_ready: false })}
      />,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/oauth is not configured on the server/i);
    expect(alert.closest(".kern-available-card")).toBeNull();
    expect(screen.getByRole("link", { name: /^connect$/i })).toBeInTheDocument();
    expect(window.location.search).not.toContain("drive=");
  });

  it("marks redirecting after Connect is activated", async () => {
    const user = userEvent.setup();
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => status()}
      />,
    );

    const connect = await screen.findByRole("link", { name: /^connect$/i });
    connect.addEventListener("click", (event) => event.preventDefault());
    await user.click(connect);
    expect(
      screen.getByRole("link", { name: /redirecting to google/i }),
    ).toBeInTheDocument();
  });

  it("moves to Connected sources data after a successful status reload", async () => {
    const { unmount } = render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => status()}
      />,
    );
    expect(await screen.findByRole("link", { name: /^connect$/i })).toBeTruthy();
    unmount();

    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONNECTED}
      />,
    );

    expect(
      await screen.findByRole("button", { name: /sync now/i }),
    ).toBeEnabled();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^connect$/i })).toBeNull();
    expect(document.body.textContent).not.toMatch(/ya29\.|1\/\/|client-secret/);
  });

  it("shows an accessible error after denial and stays available", async () => {
    window.history.pushState({}, "", "/documents?drive=denied");
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => status()}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /authorization was cancelled/i,
    );
    expect(screen.getByRole("link", { name: /^connect$/i })).toBeInTheDocument();
    expect(window.location.search).not.toContain("drive=");
  });

  it("shows an accessible error after invalid_state", async () => {
    window.history.pushState({}, "", "/documents?drive=invalid_state");
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => status()}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /no longer valid/i,
    );
    expect(screen.getByRole("link", { name: /^connect$/i })).toBeInTheDocument();
  });

  it("shows Never when connected but not yet synced", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () =>
          status({
            connected: true,
            account_email: "ada@example.com",
            last_sync: null,
          })
        }
      />,
    );

    expect(await screen.findByText(/^never$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^new$/i)).toBeNull();
  });

  it("updates last-sync counts from a status refetch after Sync now", async () => {
    const user = userEvent.setup();
    const getStatus = vi
      .fn()
      .mockResolvedValueOnce(
        status({
          connected: true,
          account_email: "ada@example.com",
          last_sync: null,
        }),
      )
      .mockResolvedValueOnce(CONNECTED);
    const syncNow = vi.fn().mockResolvedValue({
      ingested_count: 1,
      skipped_count: 2,
      failed_count: 0,
      outcomes: [],
    });

    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={getStatus}
        syncNow={syncNow}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /sync now/i }));

    expect(await screen.findByText(/^new$/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/new\s*1/i);
    expect(screen.getByRole("status")).toHaveTextContent(/updated\s*2/i);
    expect(screen.getByRole("status")).toHaveTextContent(/unchanged\s*3/i);
    expect(screen.getByRole("status")).toHaveTextContent(/failed\s*0/i);
  });

  it("disables Sync now while a run is in progress", async () => {
    const user = userEvent.setup();
    let resolveSync: (value: unknown) => void = () => {};
    const syncNow = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveSync = resolve;
        }),
    );
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONNECTED}
        syncNow={syncNow}
      />,
    );

    const button = await screen.findByRole("button", { name: /sync now/i });
    await user.click(button);
    await user.click(button);
    expect(syncNow).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /syncing/i })).toBeDisabled();
    resolveSync({});
  });

  it("shows ApiError detail on sync failure", async () => {
    const user = userEvent.setup();
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONNECTED}
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
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The Google Drive connector sync failed.",
    );
  });

  it("says an aborted sync may still be running and re-fetches status", async () => {
    const user = userEvent.setup();
    const getStatus = vi.fn().mockResolvedValue(CONNECTED);
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

  it("requires disconnect confirmation and then returns to Connect", async () => {
    const user = userEvent.setup();
    const disconnect = vi.fn().mockResolvedValue(undefined);
    const getStatus = vi
      .fn()
      .mockResolvedValueOnce(CONNECTED)
      .mockResolvedValueOnce(status());

    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={getStatus}
        disconnect={disconnect}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /disconnect/i }));
    expect(disconnect).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(/indexed documents stay/i);
    await user.click(within(dialog).getByRole("button", { name: /disconnect/i }));

    await waitFor(() => {
      expect(disconnect).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByRole("link", { name: /^connect$/i })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /sync now/i }),
    ).not.toBeInTheDocument();
  });

  it("offers Connect again when reauthorization is required", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () =>
          status({
            connected: true,
            oauth_ready: true,
            reauthorization_required: true,
            account_email: "ada@example.com",
          })
        }
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/revoked/i);
    expect(screen.getByRole("link", { name: /^connect$/i })).toHaveAttribute(
      "href",
      `http://api.test${GOOGLE_DRIVE_OAUTH_START_PATH}`,
    );
    expect(
      screen.queryByRole("button", { name: /sync now/i }),
    ).not.toBeInTheDocument();
  });
});
