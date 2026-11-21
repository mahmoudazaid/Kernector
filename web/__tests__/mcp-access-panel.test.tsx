import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { McpAccessPanel } from "@/components/settings/McpAccessPanel";
import {
  claudeCodeMcpConfig,
  mcpClientConfig,
} from "@/lib/api/mcp-profiles";

async function openCreate(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => {
    expect(
      screen.getByRole("button", { name: /generate new token/i }),
    ).toBeInTheDocument();
  });
  await user.click(screen.getByRole("button", { name: /generate new token/i }));
  await waitFor(() => {
    expect(screen.getByLabelText(/token name/i)).toBeInTheDocument();
  });
}

describe("McpAccessPanel", () => {
  it("follows GitHub-style create once, then list with delete only", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const loadTools = vi.fn().mockResolvedValue({
      tools: [
        {
          tool_id: "core.project_list",
          name: "core_project_list",
          kind: "core",
          pack_id: null,
          allowlistable: true,
          side_effecting: false,
          unavailable_reason: null,
        },
        {
          tool_id: "core.search_knowledge",
          name: "core_search_knowledge",
          kind: "core",
          pack_id: null,
          allowlistable: false,
          side_effecting: false,
          unavailable_reason: "isolation blocked",
        },
      ],
    });
    const loadProfiles = vi.fn().mockResolvedValue([]);
    const loadProjects = vi.fn().mockResolvedValue([
      {
        project_id: "prj_a",
        name: "Alpha",
        slug: "alpha",
        version: 1,
      },
    ]);
    const createProfile = vi.fn().mockResolvedValue({
      plaintext_token: "once-only-token",
      profile: {
        profile_id: "mcp_1",
        project_id: "prj_a",
        name: "cursor",
        description: "CI agent",
        allowlist: [],
        status: "active",
        expires_at: null,
        created_at: "t0",
        updated_at: "t0",
        disabled_at: null,
        revoked_at: null,
      },
    });
    const saveAllowlist = vi.fn().mockResolvedValue({
      profile_id: "mcp_1",
      project_id: "prj_a",
      name: "cursor",
      description: "CI agent",
      allowlist: ["core.project_list"],
      status: "active",
      expires_at: null,
      created_at: "t0",
      updated_at: "t0",
      disabled_at: null,
      revoked_at: null,
    });
    const revokeProfile = vi.fn().mockResolvedValue({
      profile_id: "mcp_1",
      project_id: "prj_a",
      name: "cursor",
      description: "CI agent",
      allowlist: ["core.project_list"],
      status: "revoked",
      expires_at: null,
      created_at: "t0",
      updated_at: "t1",
      disabled_at: null,
      revoked_at: "t1",
    });

    render(
      <McpAccessPanel
        mcpPublicEndpoint="http://127.0.0.1:8100/mcp"
        loadTools={loadTools}
        loadProfiles={loadProfiles}
        loadProjects={loadProjects}
        createProfile={createProfile}
        saveAllowlist={saveAllowlist}
        revokeProfile={revokeProfile}
      />,
    );

    await openCreate(user);
    expect(screen.getByRole("combobox", { name: /project/i })).toHaveTextContent(
      /Alpha \(alpha\)/,
    );
    expect(screen.getByRole("combobox", { name: /expiration/i })).toHaveTextContent(
      /30 days/,
    );
    expect(screen.getByLabelText("0 tools")).toBeInTheDocument();
    expect(screen.getByText("Tools")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: /expiration/i }));
    await user.click(screen.getByRole("option", { name: /no expiration/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/strongly recommends/i);

    await user.click(screen.getByRole("button", { name: /\+ add tools/i }));
    expect(screen.queryByRole("button", { name: /^done$/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /core\.project_list/i }));
    expect(screen.getByLabelText("1 tools")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /remove core\.project_list/i }),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText(/token name/i), "cursor");
    await user.type(screen.getByLabelText(/^description$/i), "CI agent");
    await user.click(screen.getByRole("button", { name: /^generate token$/i }));

    await waitFor(() => {
      expect(
        screen.getByLabelText(/one-time access token/i),
      ).toHaveValue("once-only-token");
    });
    expect(createProfile).toHaveBeenCalledWith({
      project_id: "prj_a",
      name: "cursor",
      expires_at: null,
      description: "CI agent",
    });
    expect(saveAllowlist).toHaveBeenCalledWith("mcp_1", ["core.project_list"]);
    const callout = screen.getByRole("status");
    expect(callout.textContent).toContain(
      mcpClientConfig("http://127.0.0.1:8100/mcp", "once-only-token"),
    );
    expect(callout.textContent).toContain(
      claudeCodeMcpConfig("http://127.0.0.1:8100/mcp", "once-only-token"),
    );
    expect(within(callout).getByText("CI agent")).toBeInTheDocument();
    expect(screen.queryByText(/^active$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/tools:/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^copy token$/i }));
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("once-only-token");
    });

    const cursorConfig = mcpClientConfig(
      "http://127.0.0.1:8100/mcp",
      "once-only-token",
    );
    const claudeConfig = claudeCodeMcpConfig(
      "http://127.0.0.1:8100/mcp",
      "once-only-token",
    );
    expect(cursorConfig).toContain("http://127.0.0.1:8100/mcp");
    expect(cursorConfig).toContain("Bearer once-only-token");
    expect(cursorConfig).not.toContain('"type"');
    expect(claudeConfig).toContain('"type": "http"');
    await user.click(
      screen.getByRole("button", { name: /^copy cursor config$/i }),
    );
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(cursorConfig);
    });
    await user.click(
      screen.getByRole("button", { name: /^copy claude code config$/i }),
    );
    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(claudeConfig);
    });

    await user.click(screen.getByRole("button", { name: /^done$/i }));
    expect(screen.queryByLabelText(/one-time access token/i)).not.toBeInTheDocument();
    expect(screen.getByText("cursor")).toBeInTheDocument();
    expect(screen.getByText("CI agent")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^delete cursor$/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));
    await waitFor(() => {
      expect(revokeProfile).toHaveBeenCalledWith("mcp_1");
    });
    expect(screen.queryByText("cursor")).not.toBeInTheDocument();
    expect(screen.getByText(/no tokens yet/i)).toBeInTheDocument();
  });

  it("hides already-revoked tokens on load", async () => {
    const loadTools = vi.fn().mockResolvedValue({ tools: [] });
    const loadProfiles = vi.fn().mockResolvedValue([
      {
        profile_id: "mcp_dead",
        project_id: "prj_a",
        name: "gone",
        allowlist: [],
        status: "revoked",
        expires_at: null,
        created_at: "t0",
        updated_at: "t1",
        disabled_at: null,
        revoked_at: "t1",
      },
      {
        profile_id: "mcp_live",
        project_id: "prj_a",
        name: "alive",
        allowlist: [],
        status: "active",
        expires_at: null,
        created_at: "t0",
        updated_at: "t0",
        disabled_at: null,
        revoked_at: null,
      },
    ]);
    const loadProjects = vi.fn().mockResolvedValue([
      {
        project_id: "prj_a",
        name: "Alpha",
        slug: "alpha",
        version: 1,
      },
    ]);

    render(
      <McpAccessPanel
        mcpPublicEndpoint="http://127.0.0.1:8100/mcp"
        loadTools={loadTools}
        loadProfiles={loadProfiles}
        loadProjects={loadProjects}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("alive")).toBeInTheDocument();
    });
    expect(screen.queryByText("gone")).not.toBeInTheDocument();
  });

  it("shows SoftDatePicker beside Custom under the Select date field", async () => {
    const user = userEvent.setup();
    const loadTools = vi.fn().mockResolvedValue({ tools: [] });
    const loadProfiles = vi.fn().mockResolvedValue([]);
    const loadProjects = vi.fn().mockResolvedValue([
      {
        project_id: "prj_a",
        name: "Alpha",
        slug: "alpha",
        version: 1,
      },
    ]);

    render(
      <McpAccessPanel
        mcpPublicEndpoint="http://127.0.0.1:8100/mcp"
        loadTools={loadTools}
        loadProfiles={loadProfiles}
        loadProjects={loadProjects}
      />,
    );

    await openCreate(user);
    await user.click(screen.getByRole("combobox", { name: /expiration/i }));
    await user.click(screen.getByRole("option", { name: /custom/i }));
    expect(screen.getByText(/select date \*/i)).toBeInTheDocument();
    const dateTrigger = screen.getByRole("combobox", { name: /select date/i });
    await user.click(dateTrigger);
    const dialog = screen.getByRole("dialog", { name: /select date/i });
    expect(dialog).toBeInTheDocument();
    const enabledDay = dialog.querySelector(
      ".kern-date-cell[data-ymd]:not([disabled])",
    );
    expect(enabledDay).toBeTruthy();
    await user.click(enabledDay as HTMLElement);
    expect(screen.queryByRole("dialog", { name: /select date/i })).not.toBeInTheDocument();
  });

  it("sends expiry from preset days when creating a token", async () => {
    const user = userEvent.setup();
    const loadTools = vi.fn().mockResolvedValue({ tools: [] });
    const loadProfiles = vi.fn().mockResolvedValue([]);
    const loadProjects = vi.fn().mockResolvedValue([
      {
        project_id: "prj_a",
        name: "Alpha",
        slug: "alpha",
        version: 1,
      },
    ]);
    const createProfile = vi.fn().mockResolvedValue({
      plaintext_token: "expiring-token",
      profile: {
        profile_id: "mcp_2",
        project_id: "prj_a",
        name: "claude",
        allowlist: [],
        status: "active",
        expires_at: "2099-12-31T00:00:00.000Z",
        created_at: "t0",
        updated_at: "t0",
        disabled_at: null,
        revoked_at: null,
      },
    });

    render(
      <McpAccessPanel
        mcpPublicEndpoint="http://127.0.0.1:8100/mcp"
        loadTools={loadTools}
        loadProfiles={loadProfiles}
        loadProjects={loadProjects}
        createProfile={createProfile}
      />,
    );

    await openCreate(user);
    const expected = (() => {
      const date = new Date();
      date.setHours(0, 0, 0, 0);
      date.setDate(date.getDate() + 30);
      const ymd = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
      return new Date(`${ymd}T00:00:00`).toISOString();
    })();
    await user.type(screen.getByLabelText(/token name/i), "claude");
    await user.click(screen.getByRole("button", { name: /^generate token$/i }));

    await waitFor(() => {
      expect(createProfile).toHaveBeenCalled();
    });
    const body = createProfile.mock.calls[0]?.[0] as {
      project_id: string;
      name: string;
      expires_at: string | null;
    };
    expect(body.project_id).toBe("prj_a");
    expect(body.name).toBe("claude");
    expect(body.expires_at).toBe(expected);
  });

  it("keeps the one-time token when allowlist save fails", async () => {
    const user = userEvent.setup();
    const loadTools = vi.fn().mockResolvedValue({
      tools: [
        {
          tool_id: "core.project_list",
          name: "core_project_list",
          kind: "core",
          pack_id: null,
          allowlistable: true,
          side_effecting: false,
          unavailable_reason: null,
        },
      ],
    });
    const loadProfiles = vi.fn().mockResolvedValue([]);
    const loadProjects = vi.fn().mockResolvedValue([
      {
        project_id: "prj_a",
        name: "Alpha",
        slug: "alpha",
        version: 1,
      },
    ]);
    const createProfile = vi.fn().mockResolvedValue({
      plaintext_token: "kept-token",
      profile: {
        profile_id: "mcp_keep",
        project_id: "prj_a",
        name: "cursor",
        description: "",
        allowlist: [],
        status: "active",
        expires_at: null,
        created_at: "t0",
        updated_at: "t0",
        disabled_at: null,
        revoked_at: null,
      },
    });
    const saveAllowlist = vi
      .fn()
      .mockRejectedValue(new Error("isolation blocked"));

    render(
      <McpAccessPanel
        mcpPublicEndpoint="http://127.0.0.1:8100/mcp"
        loadTools={loadTools}
        loadProfiles={loadProfiles}
        loadProjects={loadProjects}
        createProfile={createProfile}
        saveAllowlist={saveAllowlist}
      />,
    );

    await openCreate(user);
    await user.click(screen.getByRole("combobox", { name: /expiration/i }));
    await user.click(screen.getByRole("option", { name: /no expiration/i }));
    await user.click(screen.getByRole("button", { name: /\+ add tools/i }));
    await user.click(screen.getByRole("checkbox", { name: /core\.project_list/i }));
    await user.type(screen.getByLabelText(/token name/i), "cursor");
    await user.click(screen.getByRole("button", { name: /^generate token$/i }));

    await waitFor(() => {
      expect(screen.getByLabelText(/one-time access token/i)).toHaveValue(
        "kept-token",
      );
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      /token created, but tools could not be granted/i,
    );
    expect(
      screen.getByRole("button", { name: /^delete cursor$/i }),
    ).toBeInTheDocument();
  });

  it("blocks create when the workspace has no projects", async () => {
    const user = userEvent.setup();
    const loadTools = vi.fn().mockResolvedValue({ tools: [] });
    const loadProfiles = vi.fn().mockResolvedValue([]);
    const loadProjects = vi.fn().mockResolvedValue([]);
    const createProfile = vi.fn();

    render(
      <McpAccessPanel
        mcpPublicEndpoint="http://127.0.0.1:8100/mcp"
        loadTools={loadTools}
        loadProfiles={loadProfiles}
        loadProjects={loadProjects}
        createProfile={createProfile}
      />,
    );

    await openCreate(user);
    expect(
      screen.getByText(/no projects in this workspace yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^generate token$/i }),
    ).toBeDisabled();
    expect(createProfile).not.toHaveBeenCalled();
  });
});
