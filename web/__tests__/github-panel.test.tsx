import { render, screen, waitFor } from "@testing-library/react";
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
};

const connected: GitHubStatusResponse = {
  ...disconnected,
  connected: true,
  account_login: "octocat",
  owner: "acme",
  repo: "docs",
  document_count: 3,
  connection_state: "connected",
  last_sync: {
    synced_at: "2026-09-13T12:00:00+00:00",
    new_count: 1,
    updated_count: 0,
    unchanged_count: 2,
    failed_count: 0,
    removed_count: 0,
  },
};

describe("GitHubPanel", () => {
  it("shows Connect when disconnected", async () => {
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

  it("syncs and disconnects when connected", async () => {
    const user = userEvent.setup();
    const syncNow = vi.fn().mockResolvedValue({});
    const disconnect = vi.fn().mockResolvedValue(undefined);
    let status = connected;
    render(
      <GitHubPanel
        apiBaseUrl="http://api"
        getStatus={async () => status}
        syncNow={syncNow}
        disconnect={async () => {
          await disconnect();
          status = disconnected;
        }}
      />,
    );
    expect(await screen.findByText("octocat")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sync" }));
    await waitFor(() => expect(syncNow).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Disconnect" }));
    const confirms = screen.getAllByRole("button", { name: "Disconnect" });
    await user.click(confirms[confirms.length - 1]!);
    await waitFor(() => expect(disconnect).toHaveBeenCalled());
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
