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
    setup_required: false,
    connection_state: "disconnected",
    sync_scope: null,
    ...overrides,
  };
}

const EMPTY_SELECTION = { folders: [], files: [] };

const FOLDER_ITEM = {
  id: "folder-1",
  name: "Specs",
  kind: "folder" as const,
  mime_type: "application/vnd.google-apps.folder",
  supported: true,
  modified_at: "2026-09-08T12:00:00.000Z",
};

async function emptySelection() {
  return EMPTY_SELECTION;
}

async function folderPage() {
  return { items: [FOLDER_ITEM], next_page_token: null };
}

const CONNECTED = status({
  connected: true,
  account_email: "ada@example.com",
  document_count: 4,
  folder_count: 1,
  setup_required: false,
  connection_state: "ready",
  sync_scope: "1 folder",
  last_sync: {
    synced_at: "2026-09-08T12:00:00+00:00",
    new_count: 1,
    updated_count: 2,
    unchanged_count: 3,
    failed_count: 0,
  },
});

const SETUP_REQUIRED = status({
  connected: true,
  account_email: "ada@example.com",
  document_count: 0,
  folder_count: 0,
  setup_required: true,
  connection_state: "setup_required",
  sync_scope: null,
  last_sync: null,
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
    expect(document.body.textContent).not.toMatch(
      /GOOGLE_DRIVE_SERVICE_ACCOUNT/,
    );
    expect(
      screen.getByText(/sign in with your google account/i),
    ).toBeInTheDocument();
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
    expect(
      screen.getByRole("link", { name: /^connect$/i }),
    ).toBeInTheDocument();
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
    expect(
      await screen.findByRole("link", { name: /^connect$/i }),
    ).toBeTruthy();
    unmount();

    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONNECTED}
        loadSelection={emptySelection}
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
    expect(
      screen.getByRole("link", { name: /^connect$/i }),
    ).toBeInTheDocument();
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
    expect(
      screen.getByRole("link", { name: /^connect$/i }),
    ).toBeInTheDocument();
  });

  it("shows Never and disables Sync now when setup is required", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={emptySelection}
      />,
    );

    expect(await screen.findByText(/^never$/i)).toBeInTheDocument();
    expect(screen.getByText(/not selected/i)).toBeInTheDocument();
    expect(screen.getByText(/setup required/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sync now/i })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /choose folders or files/i }),
    ).toBeEnabled();
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
          setup_required: false,
          connection_state: "ready",
          sync_scope: "1 folder",
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
        loadSelection={emptySelection}
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
        loadSelection={emptySelection}
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
        loadSelection={emptySelection}
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
        loadSelection={emptySelection}
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
        loadSelection={emptySelection}
        disconnect={disconnect}
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: /disconnect/i }),
    );
    expect(disconnect).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(/indexed documents stay/i);
    await user.click(
      within(dialog).getByRole("button", { name: /disconnect/i }),
    );

    await waitFor(() => {
      expect(disconnect).toHaveBeenCalledTimes(1);
    });
    expect(
      await screen.findByRole("link", { name: /^connect$/i }),
    ).toBeTruthy();
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
            connection_state: "reauthorization_required",
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

  it("opens the folder picker after a successful OAuth callback", async () => {
    window.history.pushState({}, "", "/documents?drive=connected");
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={emptySelection}
        listItems={folderPage}
      />,
    );

    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(
      within(dialog).getByRole("tab", { name: /folders/i }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      within(dialog).getByRole("tab", { name: /individual files/i }),
    ).toHaveAttribute("aria-selected", "false");
    expect(await within(dialog).findByText("Specs")).toBeInTheDocument();
    expect(window.location.search).not.toContain("drive=");
    expect(document.body.textContent).not.toMatch(/ya29\.|1\/\/|client-secret/);
  });

  it("saves the selection by Drive ID and starts one initial sync", async () => {
    const user = userEvent.setup();
    const saveSelection = vi.fn().mockResolvedValue({
      folders: [{ id: "folder-1", name: "Specs" }],
      files: [],
    });
    const syncNow = vi.fn().mockResolvedValue({
      ingested_count: 1,
      skipped_count: 0,
      failed_count: 0,
      outcomes: [],
    });
    const getStatus = vi
      .fn()
      .mockResolvedValueOnce(SETUP_REQUIRED)
      .mockResolvedValue(CONNECTED);

    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={getStatus}
        loadSelection={emptySelection}
        listItems={folderPage}
        saveSelection={saveSelection}
        syncNow={syncNow}
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: /choose folders or files/i }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    await user.click(await within(dialog).findByRole("checkbox"));
    await user.click(
      within(dialog).getByRole("button", { name: /add 1 folder & sync/i }),
    );

    await waitFor(() => {
      expect(saveSelection).toHaveBeenCalledTimes(1);
    });
    expect(saveSelection).toHaveBeenCalledWith(
      expect.objectContaining({
        selection: {
          folders: [{ id: "folder-1", name: "Specs" }],
          files: [],
        },
      }),
    );
    expect(syncNow).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByRole("button", { name: /sync now/i }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: /change drive selection/i }),
    ).toBeInTheDocument();
  });

  it("reopens the picker from Change Drive selection", async () => {
    const user = userEvent.setup();
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONNECTED}
        loadSelection={async () => ({
          folders: [{ id: "folder-1", name: "Specs" }],
          files: [],
        })}
        listItems={folderPage}
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: /change drive selection/i }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(await within(dialog).findByRole("checkbox")).toBeChecked();
  });

  it("renders partial failure counts from the last backend sync", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () =>
          status({
            connected: true,
            account_email: "ada@example.com",
            setup_required: false,
            connection_state: "ready",
            sync_scope: "1 folder",
            last_sync: {
              synced_at: "2026-09-08T12:00:00+00:00",
              new_count: 1,
              updated_count: 0,
              unchanged_count: 2,
              failed_count: 3,
            },
          })
        }
        loadSelection={emptySelection}
      />,
    );

    const results = await screen.findByLabelText(
      /last synchronization result/i,
    );
    expect(results).toHaveTextContent(/failed\s*3/i);
    expect(results).toHaveTextContent(/new\s*1/i);
  });

  it("restores connector, selection, and sync state from the backend on remount", async () => {
    const getStatus = vi.fn().mockResolvedValue(CONNECTED);
    const loadSelection = vi.fn().mockResolvedValue({
      folders: [{ id: "folder-1", name: "Specs" }],
      files: [],
    });
    const { unmount } = render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={getStatus}
        loadSelection={loadSelection}
      />,
    );

    expect(await screen.findByText("ada@example.com")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /change drive selection/i }),
    ).toBeInTheDocument();
    unmount();

    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={getStatus}
        loadSelection={loadSelection}
      />,
    );

    expect(await screen.findByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/updated\s*2/i);
    expect(
      screen.getByRole("button", { name: /change drive selection/i }),
    ).toBeInTheDocument();
    expect(getStatus).toHaveBeenCalledTimes(2);
    expect(loadSelection).toHaveBeenCalledTimes(2);
  });
});
