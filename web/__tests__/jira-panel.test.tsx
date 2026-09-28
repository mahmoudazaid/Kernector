import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { JiraPanel } from "@/components/documents/JiraPanel";
import type { JiraStatusResponse } from "@/lib/api/connectors";

const ACME = { cloud_id: "cloud-acme", name: "Acme", url: "https://acme.atlassian.net" };
const BETA = { cloud_id: "cloud-beta", name: "Beta", url: "https://beta.atlassian.net" };

const disconnected: JiraStatusResponse = {
  available: true,
  oauth_ready: true,
  connected: false,
  account_name: null,
  site: null,
  project_keys: [],
  document_count: 0,
  last_sync: null,
  reauthorization_required: false,
  setup_required: false,
  connection_state: "disconnected",
  sync_scope: null,
};

const ready: JiraStatusResponse = {
  ...disconnected,
  connected: true,
  account_name: "Ada",
  site: ACME,
  project_keys: ["ENG", "OPS"],
  document_count: 4,
  connection_state: "ready",
  sync_scope: "Acme · ENG, OPS",
};

function panelProps(status: JiraStatusResponse) {
  return {
    apiBaseUrl: "http://api",
    getStatus: vi.fn().mockResolvedValue(status),
    listSites: vi.fn().mockResolvedValue({ items: [ACME, BETA] }),
    selectSite: vi.fn().mockResolvedValue({ site: BETA, project_keys: [] }),
    listProjects: vi.fn().mockResolvedValue({
      items: [
        { key: "ENG", name: "Engineering" },
        { key: "OPS", name: "Operations" },
      ],
      next_start_at: null,
    }),
    saveSelection: vi.fn().mockResolvedValue({ site: ACME, project_keys: ["ENG"] }),
    syncNow: vi.fn().mockResolvedValue({}),
    disconnect: vi.fn().mockResolvedValue(undefined),
  };
}

describe("JiraPanel", () => {
  it("shows Connect when disconnected", async () => {
    render(<JiraPanel {...panelProps(disconnected)} />);

    expect(await screen.findByRole("link", { name: "Connect" })).toHaveAttribute(
      "href",
      "http://api/api/v1/connectors/jira/oauth/start",
    );
  });

  it("explains a callback with no accessible Jira site", async () => {
    render(<JiraPanel {...panelProps(disconnected)} oauthCallback="no_site" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/no Jira Cloud site/i);
  });

  it("shows the site and projects and syncs", async () => {
    const user = userEvent.setup();
    const props = panelProps(ready);
    render(<JiraPanel {...props} />);

    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("ENG, OPS")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sync" }));

    await waitFor(() => expect(props.syncNow).toHaveBeenCalledTimes(1));
  });

  it("confirms before deselecting a project with synced documents", async () => {
    const user = userEvent.setup();
    const props = panelProps(ready);
    render(<JiraPanel {...props} />);

    await user.click(await screen.findByRole("button", { name: "Browse" }));
    await user.click(await screen.findByRole("checkbox", { name: /OPS/ }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    const dialog = await screen.findByRole("dialog", {
      name: /remove synced jira documents/i,
    });
    expect(dialog).toHaveTextContent(/OPS/);
    expect(props.saveSelection).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() =>
      expect(props.saveSelection).toHaveBeenCalledWith(
        expect.objectContaining({ projectKeys: ["ENG"] }),
      ),
    );
  });

  it("confirms before switching sites with synced documents", async () => {
    const user = userEvent.setup();
    const props = panelProps(ready);
    render(<JiraPanel {...props} />);

    await user.click(await screen.findByRole("button", { name: "Browse" }));
    await user.click(await screen.findByRole("button", { name: "Change site" }));
    await user.click(await screen.findByRole("radio", { name: /Beta/ }));
    await user.click(screen.getByRole("button", { name: "Use this site" }));

    const dialog = await screen.findByRole("dialog", { name: /switch jira site/i });
    expect(dialog).toHaveTextContent(/Acme/);
    await user.click(within(dialog).getByRole("button", { name: "Switch site" }));

    await waitFor(() =>
      expect(props.selectSite).toHaveBeenCalledWith(
        expect.objectContaining({ cloudId: "cloud-beta" }),
      ),
    );
  });

  it("confirms before disconnecting", async () => {
    const user = userEvent.setup();
    const props = panelProps(ready);
    render(<JiraPanel {...props} />);

    await user.click(await screen.findByRole("button", { name: "Disconnect" }));
    const dialog = await screen.findByRole("dialog", { name: /disconnect jira/i });
    await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));

    await waitFor(() => expect(props.disconnect).toHaveBeenCalledTimes(1));
  });

  it("shows a reconnect card when reauthorization is required", async () => {
    render(
      <JiraPanel
        {...panelProps({
          ...ready,
          reauthorization_required: true,
          connection_state: "reauthorization_required",
        })}
      />,
    );

    expect(await screen.findByText("Reconnect required")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();
  });

  it("opens the site step when the grant needs a site", async () => {
    render(
      <JiraPanel
        {...panelProps({
          ...ready,
          site: null,
          project_keys: [],
          setup_required: true,
          connection_state: "site_selection_required",
        })}
        oauthCallback="connected"
      />,
    );

    expect(await screen.findByRole("radio", { name: /Acme/ })).toBeInTheDocument();
  });
});
