import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { JiraPanel } from "@/components/documents/JiraPanel";
import type { JiraStatusResponse } from "@/lib/api/connectors";

const ACME = {
  instance_id: "cloud-acme",
  cloud_id: "cloud-acme",
  name: "Acme",
  url: "https://acme.atlassian.net",
};
const BETA = {
  instance_id: "cloud-beta",
  cloud_id: "cloud-beta",
  name: "Beta",
  url: "https://beta.atlassian.net",
};
const DC_SERVER = {
  instance_id: "SRV-1",
  cloud_id: null,
  name: "Example Jira",
  url: "https://jira.example.com",
};

const disconnected: JiraStatusResponse = {
  mode: "cloud",
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
  describe("Data Center mode", () => {
    const dcUnconfigured: JiraStatusResponse = {
      ...disconnected,
      mode: "data_center",
      oauth_ready: false,
      setup_required: true,
      connection_state: "setup_required",
    };
    const dcNoProjects: JiraStatusResponse = {
      ...dcUnconfigured,
      connected: true,
    };
    const dcReady: JiraStatusResponse = {
      ...dcNoProjects,
      site: DC_SERVER,
      project_keys: ["ENG", "OPS"],
      document_count: 4,
      setup_required: false,
      connection_state: "ready",
      sync_scope: "Example Jira · ENG, OPS",
    };
    const dcRejected: JiraStatusResponse = {
      ...dcReady,
      reauthorization_required: true,
      setup_required: true,
      connection_state: "reauthorization_required",
    };

    it("shows a server setup hint and no Connect link when unconfigured", async () => {
      render(<JiraPanel {...panelProps(dcUnconfigured)} />);

      expect(await screen.findByText(/Personal Access Token on the server/)).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Jira Data Center" })).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Connect" })).not.toBeInTheDocument();
    });

    it("opens the project picker without a site step", async () => {
      const user = userEvent.setup();
      const props = panelProps(dcNoProjects);
      render(<JiraPanel {...props} />);

      await user.click(await screen.findByRole("button", { name: "Browse" }));

      expect(await screen.findByRole("checkbox", { name: /ENG/ })).toBeInTheDocument();
      expect(props.listSites).not.toHaveBeenCalled();
      expect(screen.queryByRole("button", { name: "Change site" })).not.toBeInTheDocument();
    });

    it("shows the server without a Site row or Connect link and syncs", async () => {
      const user = userEvent.setup();
      const props = panelProps(dcReady);
      render(<JiraPanel {...props} />);

      expect(await screen.findByText("Example Jira")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Site" })).not.toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Connect" })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Sync" }));

      await waitFor(() => expect(props.syncNow).toHaveBeenCalledTimes(1));
    });

    it("explains a rejected token and keeps Browse available", async () => {
      const user = userEvent.setup();
      const props = panelProps(dcRejected);
      render(<JiraPanel {...props} />);

      expect(await screen.findByRole("alert")).toHaveTextContent(
        /rejected the server's Personal Access Token/,
      );
      expect(screen.queryByRole("link", { name: "Connect" })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Browse" }));

      expect(await screen.findByRole("checkbox", { name: /ENG/ })).toBeInTheDocument();
    });

    it("confirms before purging a deselected project", async () => {
      const user = userEvent.setup();
      const props = panelProps(dcReady);
      render(<JiraPanel {...props} />);

      await user.click(await screen.findByRole("button", { name: "Browse" }));
      await user.click(await screen.findByRole("checkbox", { name: /OPS/ }));
      await user.click(screen.getByRole("button", { name: "Save" }));

      const dialog = await screen.findByRole("dialog", {
        name: "Remove synced Jira documents?",
      });
      await user.click(within(dialog).getByRole("button", { name: "Remove" }));
      await waitFor(() =>
        expect(props.saveSelection).toHaveBeenCalledWith(
          expect.objectContaining({ projectKeys: ["ENG"] }),
        ),
      );
    });

    it("removes the saved connection and says the server token is unchanged", async () => {
      const user = userEvent.setup();
      const props = panelProps(dcReady);
      render(<JiraPanel {...props} />);

      await user.click(await screen.findByRole("button", { name: "Remove" }));
      const dialog = await screen.findByRole("dialog", {
        name: "Remove Jira Data Center connection?",
      });
      expect(dialog).toHaveTextContent(/Personal Access Token is not changed/);
      await user.click(within(dialog).getByRole("button", { name: "Remove" }));

      await waitFor(() => expect(props.disconnect).toHaveBeenCalledTimes(1));
    });
  });
});
