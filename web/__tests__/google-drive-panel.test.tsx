import { act, render, screen, waitFor, within } from "@testing-library/react";
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
      screen.queryByRole("button", { name: /Sync/i }),
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
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        oauthCallback="unconfigured"
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

    expect(await screen.findByRole("button", { name: /Sync/i })).toBeEnabled();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText(/^indexed$/i)).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.queryByText(/^sync scope$/i)).toBeNull();
    expect(screen.queryByRole("link", { name: /^connect$/i })).toBeNull();
    expect(document.body.textContent).not.toMatch(/ya29\.|1\/\/|client-secret/);
  });

  it("shows an accessible error after denial and stays available", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        oauthCallback="denied"
        getStatus={async () => status()}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /authorization was cancelled/i,
    );
    expect(
      screen.getByRole("link", { name: /^connect$/i }),
    ).toBeInTheDocument();
  });

  it("shows an accessible error after invalid_state", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        oauthCallback="invalid_state"
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

  it("shows Connected and enables Sync when no files are selected", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={emptySelection}
      />,
    );

    expect(await screen.findByText(/^never$/i)).toBeInTheDocument();
    expect(screen.getByText(/^connected$/i)).toBeInTheDocument();
    expect(screen.queryByText(/setup required/i)).toBeNull();
    expect(screen.getByRole("button", { name: /Sync/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Browse/i })).toBeEnabled();
    expect(screen.getByText(/^indexed$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^sync scope$/i)).toBeNull();
    expect(screen.queryByText(/^new$/i)).toBeNull();
  });

  it("updates last-synced time from a status refetch after Sync", async () => {
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

    await user.click(await screen.findByRole("button", { name: /Sync/i }));

    const lastSynced = await screen.findByRole("status");
    expect(
      screen.getByRole("heading", { name: /last synced/i }),
    ).toBeInTheDocument();
    expect(lastSynced.querySelector("time")).toHaveAttribute(
      "dateTime",
      "2026-09-08T12:00:00+00:00",
    );
    expect(screen.queryByText(/^new$/i)).toBeNull();
    expect(screen.queryByText(/^updated$/i)).toBeNull();
    expect(screen.queryByText(/^unchanged$/i)).toBeNull();
    expect(screen.queryByText(/^failed$/i)).toBeNull();
  });

  it("notifies the catalog after Sync succeeds", async () => {
    const user = userEvent.setup();
    const onCatalogChange = vi.fn();
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONNECTED}
        loadSelection={emptySelection}
        syncNow={async () => ({
          ingested_count: 1,
          skipped_count: 0,
          failed_count: 0,
          outcomes: [],
        })}
        onCatalogChange={onCatalogChange}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /Sync/i }));
    await waitFor(() => expect(onCatalogChange).toHaveBeenCalledTimes(1));
  });

  it("disables Sync while a run is in progress", async () => {
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

    const button = await screen.findByRole("button", { name: /Sync/i });
    await user.click(button);
    await user.click(button);
    expect(syncNow).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /^sync$/i })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /syncing/i }),
    ).not.toBeInTheDocument();
    const overlay = screen
      .getByText(/syncing google drive/i)
      .closest(".kern-source-busy-overlay");
    expect(overlay).toBeInTheDocument();
    expect(overlay?.querySelector(".kern-loader-mark")).toBeInTheDocument();
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

    await user.click(await screen.findByRole("button", { name: /Sync/i }));
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

    await user.click(await screen.findByRole("button", { name: /Sync/i }));
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
    // Busy must clear before the confirm closes so restore can target the opener.
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(
      await screen.findByRole("link", { name: /^connect$/i }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /Sync/i }),
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
        loadSelection={emptySelection}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/revoked/i);
    expect(screen.getByRole("link", { name: /^connect$/i })).toHaveAttribute(
      "href",
      `http://api.test${GOOGLE_DRIVE_OAUTH_START_PATH}`,
    );
    expect(
      screen.queryByRole("button", { name: /Sync/i }),
    ).not.toBeInTheDocument();
  });

  it("opens the folder picker after a successful OAuth callback", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        oauthCallback="connected"
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={emptySelection}
        listItems={folderPage}
      />,
    );

    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(within(dialog).queryByRole("tab")).not.toBeInTheDocument();
    expect(await within(dialog).findByText("Specs")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/ya29\.|1\/\/|client-secret/);
  });

  it("does not seed the picker from an empty selection while roots are loading", async () => {
    let resolveSelection: (value: {
      folders: { id: string; name: string }[];
      files: { id: string; name: string }[];
    }) => void = () => {};
    const pending = new Promise<{
      folders: { id: string; name: string }[];
      files: { id: string; name: string }[];
    }>((resolve) => {
      resolveSelection = resolve;
    });
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        oauthCallback="connected"
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={async () => pending}
        listItems={folderPage}
      />,
    );

    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(within(dialog).queryByText("Specs")).not.toBeInTheDocument();
    resolveSelection({
      folders: [{ id: "folder-1", name: "Specs" }],
      files: [],
    });
    await waitFor(() => {
      expect(
        within(dialog).getByRole("checkbox", { name: /specs/i }),
      ).toBeChecked();
    });
  });

  it("does not open the picker when saved selection cannot be loaded", async () => {
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        oauthCallback="connected"
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={async () => {
          throw new ApiError({
            status: 502,
            title: "Google Drive request failed",
            detail: "The Google Drive request failed.",
            code: "google_drive_request_failed",
          });
        }}
        listItems={folderPage}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The Google Drive request failed.",
    );
    expect(
      screen.queryByRole("dialog", { name: /choose from google drive/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps an open picker when a later selection refresh fails", async () => {
    const user = userEvent.setup();
    let calls = 0;
    const loadSelection = async () => {
      calls += 1;
      if (calls === 3) {
        throw new ApiError({
          status: 502,
          title: "Google Drive request failed",
          detail: "The Google Drive request failed.",
          code: "google_drive_request_failed",
        });
      }
      return EMPTY_SELECTION;
    };
    const { rerender } = render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        reloadToken={0}
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={loadSelection}
        listItems={folderPage}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /Browse/i }));
    expect(
      await screen.findByRole("dialog", { name: /choose from google drive/i }),
    ).toBeInTheDocument();

    rerender(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        reloadToken={1}
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={loadSelection}
        listItems={folderPage}
      />,
    );

    const dialog = screen.getByRole("dialog", {
      name: /choose from google drive/i,
    });
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("The Google Drive request failed.");
    expect(alert.closest(".kern-picker-list")).toBeNull();

    rerender(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        reloadToken={2}
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={loadSelection}
        listItems={folderPage}
      />,
    );
    await waitFor(() => {
      expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(
      screen.getByRole("dialog", { name: /choose from google drive/i }),
    ).toBeInTheDocument();
  });

  it("does not show a card error when the picker is closed during selection load", async () => {
    const user = userEvent.setup();
    let rejectLoad: (error: unknown) => void = () => {};
    const loadSelection = () =>
      new Promise<never>((_resolve, reject) => {
        rejectLoad = reject;
      });
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => SETUP_REQUIRED}
        loadSelection={loadSelection}
        listItems={folderPage}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /Browse/i }));
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    await user.click(within(dialog).getByRole("button", { name: /^close$/i }));
    expect(
      screen.queryByRole("dialog", { name: /choose from google drive/i }),
    ).not.toBeInTheDocument();

    await act(async () => {
      rejectLoad(
        new ApiError({
          status: 502,
          title: "Google Drive request failed",
          detail: "The Google Drive request failed.",
          code: "google_drive_request_failed",
        }),
      );
      await Promise.resolve();
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("saves the selection by Drive ID and starts one initial sync", async () => {
    const user = userEvent.setup();
    let resolveSave: (value: {
      folders: { id: string; name: string }[];
      files: { id: string; name: string }[];
    }) => void = () => {};
    const saveSelection = vi.fn(
      () =>
        new Promise<{
          folders: { id: string; name: string }[];
          files: { id: string; name: string }[];
        }>((resolve) => {
          resolveSave = resolve;
        }),
    );
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

    await user.click(await screen.findByRole("button", { name: /Browse/i }));
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    await user.click(await within(dialog).findByRole("checkbox"));
    await user.click(within(dialog).getByRole("button", { name: /^save$/i }));
    expect(
      screen.queryByRole("dialog", { name: /choose from google drive/i }),
    ).not.toBeInTheDocument();
    expect(
      screen
        .getByText(/syncing google drive/i)
        .closest(".kern-source-busy-overlay"),
    ).toBeInTheDocument();

    resolveSave({
      folders: [{ id: "folder-1", name: "Specs" }],
      files: [],
    });

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
    expect(await screen.findByRole("button", { name: /Sync/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Browse/i })).toBeInTheDocument();
  });

  it("saves an empty Drive selection without starting a sync", async () => {
    const user = userEvent.setup();
    const saveSelection = vi.fn().mockResolvedValue({
      folders: [],
      files: [],
    });
    const syncNow = vi.fn();
    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={async () => CONNECTED}
        loadSelection={async () => ({
          folders: [{ id: "folder-1", name: "Specs" }],
          files: [],
        })}
        listItems={folderPage}
        saveSelection={saveSelection}
        syncNow={syncNow}
      />,
    );

    await user.click(await screen.findByRole("button", { name: /Browse/i }));
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    await user.click(
      await within(dialog).findByRole("checkbox", { name: /specs/i }),
    );
    await user.click(within(dialog).getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(saveSelection).toHaveBeenCalledTimes(1);
    });
    expect(saveSelection).toHaveBeenCalledWith(
      expect.objectContaining({
        selection: { folders: [], files: [] },
      }),
    );
    expect(syncNow).not.toHaveBeenCalled();
  });

  it("reopens the picker from Browse", async () => {
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

    await user.click(await screen.findByRole("button", { name: /Browse/i }));
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(await within(dialog).findByRole("checkbox")).toBeChecked();
  });

  it("renders a Documents callout when the last sync had failures", async () => {
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

    expect(
      await screen.findByText(/3 files failed to index\. see documents\./i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^new$/i)).toBeNull();
    expect(screen.queryByLabelText(/last synchronization result/i)).toBeNull();
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
    expect(screen.getByRole("button", { name: /Browse/i })).toBeInTheDocument();
    unmount();

    render(
      <GoogleDrivePanel
        apiBaseUrl="http://api.test"
        getStatus={getStatus}
        loadSelection={loadSelection}
      />,
    );

    expect(await screen.findByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText(/^indexed$/i)).toBeInTheDocument();
    expect(screen.getByRole("status").querySelector("time")).toHaveAttribute(
      "dateTime",
      "2026-09-08T12:00:00+00:00",
    );
    expect(screen.getByRole("button", { name: /Browse/i })).toBeInTheDocument();
    expect(getStatus).toHaveBeenCalledTimes(2);
    expect(loadSelection).toHaveBeenCalledTimes(2);
  });
});
