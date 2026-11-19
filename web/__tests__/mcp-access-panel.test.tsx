import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { McpAccessPanel } from "@/components/settings/McpAccessPanel";
import {
  claudeCodeMcpConfig,
  cursorMcpConfig,
} from "@/lib/api/mcp-profiles";

describe("McpAccessPanel", () => {
  it("shows server status, one-time token, client configs, and confirm revoke", async () => {
    const user = userEvent.setup();
    const loadServer = vi.fn().mockResolvedValue({
      endpoint: "/mcp",
      transport: "streamable-http",
      auth_mode: "profile-bearer",
      status: "configured",
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
        allowlist: [],
        status: "active",
        expires_at: null,
        created_at: "t0",
        updated_at: "t0",
        disabled_at: null,
        revoked_at: null,
      },
    });
    const revokeProfile = vi.fn().mockResolvedValue({
      profile_id: "mcp_1",
      project_id: "prj_a",
      name: "cursor",
      allowlist: [],
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
        apiBaseUrl="http://127.0.0.1:8000"
        loadServer={loadServer}
        loadTools={loadTools}
        loadProfiles={loadProfiles}
        loadProjects={loadProjects}
        createProfile={createProfile}
        revokeProfile={revokeProfile}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/profile-bearer/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/isolation blocked/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/remote mcp url/i)).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /project/i })).toHaveTextContent(
      /Alpha \(alpha\)/,
    );

    await user.type(screen.getByLabelText(/profile name/i), "cursor");
    await user.click(screen.getByRole("button", { name: /create profile/i }));

    await waitFor(() => {
      expect(screen.getByText("once-only-token")).toBeInTheDocument();
    });
    expect(createProfile).toHaveBeenCalledWith({
      project_id: "prj_a",
      name: "cursor",
    });
    const cursorSnippet = cursorMcpConfig(
      "http://127.0.0.1:8100/mcp",
      "once-only-token",
    );
    const claudeSnippet = claudeCodeMcpConfig(
      "http://127.0.0.1:8100/mcp",
      "once-only-token",
    );
    const tokenStatus = screen.getByRole("status");
    expect(tokenStatus.textContent).toContain(cursorSnippet);
    expect(tokenStatus.textContent).toContain(claudeSnippet);

    await user.click(screen.getByRole("button", { name: /revoke profile/i }));
    expect(
      screen.getByRole("heading", { name: /revoke mcp access profile/i }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^revoke$/i }));
    await waitFor(() => {
      expect(revokeProfile).toHaveBeenCalledWith("mcp_1");
    });
  });

  it("blocks create when the workspace has no projects", async () => {
    const loadServer = vi.fn().mockResolvedValue({
      endpoint: "/mcp",
      transport: "streamable-http",
      auth_mode: "profile-bearer",
      status: "configured",
    });
    const loadTools = vi.fn().mockResolvedValue({ tools: [] });
    const loadProfiles = vi.fn().mockResolvedValue([]);
    const loadProjects = vi.fn().mockResolvedValue([]);
    const createProfile = vi.fn();

    render(
      <McpAccessPanel
        mcpPublicEndpoint="http://127.0.0.1:8100/mcp"
        apiBaseUrl="http://127.0.0.1:8000"
        loadServer={loadServer}
        loadTools={loadTools}
        loadProfiles={loadProfiles}
        loadProjects={loadProjects}
        createProfile={createProfile}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByText(/no projects in this workspace yet/i),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: /create profile/i }),
    ).toBeDisabled();
    expect(createProfile).not.toHaveBeenCalled();
  });
});
