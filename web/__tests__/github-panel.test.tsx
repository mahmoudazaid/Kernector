import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GitHubPanel } from "@/components/documents/GitHubPanel";
import type { GitHubStatusResponse } from "@/lib/api/connectors";

const disconnected: GitHubStatusResponse = {
  configured: true,
  available: true,
  connected: false,
  oauth_ready: true,
  account_login: null,
  document_count: 0,
  owner: null,
  repo: null,
  last_sync: null,
  reauthorization_required: false,
  connection_state: "disconnected",
  setup_required: false,
};

const connected: GitHubStatusResponse = {
  ...disconnected,
  connected: true,
  account_login: "octocat",
  owner: "acme",
  repo: "docs",
  document_count: 3,
  connection_state: "ready",
  setup_required: false,
  last_sync: {
    synced_at: "2026-09-13T12:00:00+00:00",
    new_count: 1,
    updated_count: 0,
    unchanged_count: 2,
    failed_count: 0,
    removed_count: 0,
  },
};

const needsSetup: GitHubStatusResponse = {
  ...disconnected,
  connected: true,
  account_login: "octocat",
  owner: null,
  repo: null,
  connection_state: "ready",
  setup_required: true,
};

describe("GitHubPanel", () => {
  it("shows Connect when disconnected without requiring env owner/repo", async () => {
    render(
      <GitHubPanel
        apiBaseUrl="http://api"
        getStatus={async () => disconnected}
      />,
    );
    expect(await screen.findByRole("link", { name: "Connect" })).toHaveAttribute(
      "href",
      "http://api/api/v1/connectors/github/oauth/start",
    );
  });

  it("opens picker when setup is required", async () => {
    const user = userEvent.setup();
    render(
      <GitHubPanel
        apiBaseUrl="http://api"
        getStatus={async () => needsSetup}
        loadSelection={async () => ({
          owner: null,
          repo: null,
          project_owner: null,
          project_number: null,
        })}
        listRepos={async () => ({
          items: [
            {
              owner: "acme",
              name: "docs",
              full_name: "acme/docs",
              private: false,
            },
          ],
          has_next: false,
        })}
        listProjects={async () => ({ items: [], next_cursor: null })}
      />,
    );
    expect(
      await screen.findByText(/choose a repository to sync before indexing/i),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Browse" }));
    expect(
      await screen.findByRole("dialog", {
        name: /choose github sources/i,
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("radio", { name: /acme\/docs/i }),
    ).toBeInTheDocument();
  });

  it("syncs and disconnects when connected", async () => {
    const user = userEvent.setup();
    const syncNow = vi.fn().mockResolvedValue({});
    const disconnect = vi.fn().mockResolvedValue(undefined);
    let status = connected;
    render(
      <GitHubPanel
        apiBaseUrl="http://api"
        getStatus={async () => status}
        loadSelection={async () => ({
          owner: "acme",
          repo: "docs",
          project_owner: null,
          project_number: null,
        })}
        syncNow={syncNow}
        disconnect={async () => {
          await disconnect();
          status = disconnected;
        }}
      />,
    );
    expect(await screen.findByText("octocat")).toBeInTheDocument();
    expect(screen.getByText("acme/docs")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sync" }));
    await waitFor(() => expect(syncNow).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Disconnect" }));
    const confirms = screen.getAllByRole("button", { name: "Disconnect" });
    await user.click(confirms[confirms.length - 1]!);
    await waitFor(() => expect(disconnect).toHaveBeenCalled());
  });

  it("dismisses the picker on Save and shows the card busy overlay", async () => {
    const user = userEvent.setup();
    let resolveSave: (value: {
      owner: string;
      repo: string;
      project_owner: string | null;
      project_number: number | null;
    }) => void = () => {};
    const saveSelection = vi.fn(
      () =>
        new Promise<{
          owner: string;
          repo: string;
          project_owner: string | null;
          project_number: number | null;
        }>((resolve) => {
          resolveSave = resolve;
        }),
    );
    const syncNow = vi.fn().mockResolvedValue({});
    const getStatus = vi
      .fn()
      .mockResolvedValueOnce(needsSetup)
      .mockResolvedValue(connected);

    render(
      <GitHubPanel
        apiBaseUrl="http://api"
        getStatus={getStatus}
        loadSelection={async () => ({
          owner: null,
          repo: null,
          project_owner: null,
          project_number: null,
        })}
        listRepos={async () => ({
          items: [
            {
              owner: "acme",
              name: "docs",
              full_name: "acme/docs",
              private: false,
            },
          ],
          has_next: false,
        })}
        listProjects={async () => ({ items: [], next_cursor: null })}
        saveSelection={saveSelection}
        syncNow={syncNow}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "Browse" }));
    const dialog = await screen.findByRole("dialog", {
      name: /choose github sources/i,
    });
    await user.click(await within(dialog).findByRole("radio", { name: /acme\/docs/i }));
    await user.click(
      within(dialog).getByRole("button", { name: /save sources/i }),
    );

    expect(
      screen.queryByRole("dialog", { name: /choose github sources/i }),
    ).not.toBeInTheDocument();
    expect(
      screen
        .getByText(/syncing github/i)
        .closest(".kern-source-busy-overlay"),
    ).toBeInTheDocument();

    resolveSave({
      owner: "acme",
      repo: "docs",
      project_owner: null,
      project_number: null,
    });
    await waitFor(() => expect(syncNow).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByText(/syncing github/i)).not.toBeInTheDocument(),
    );
  });

  it("surfaces oauth callback errors without storing a token", async () => {
    render(
      <GitHubPanel
        apiBaseUrl="http://api"
        getStatus={async () => disconnected}
        oauthCallback="denied"
      />,
    );
    expect(
      await screen.findByText(/authorization was cancelled/i),
    ).toBeInTheDocument();
  });
});
