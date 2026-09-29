import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { JiraPicker } from "@/components/documents/JiraPicker";
import type { JiraSiteResponse } from "@/lib/api/connectors";

const ACME: JiraSiteResponse = {
  instance_id: "cloud-acme",
  cloud_id: "cloud-acme",
  name: "Acme",
  url: "https://acme.atlassian.net",
};
const BETA: JiraSiteResponse = {
  instance_id: "cloud-beta",
  cloud_id: "cloud-beta",
  name: "Beta",
  url: "https://beta.atlassian.net",
};

function renderPicker(overrides: Partial<Parameters<typeof JiraPicker>[0]> = {}) {
  const props = {
    open: true,
    apiBaseUrl: "http://api",
    site: ACME,
    initialProjectKeys: ["ENG"],
    listSites: vi.fn().mockResolvedValue({ items: [ACME, BETA] }),
    listProjects: vi.fn().mockResolvedValue({
      items: [
        { key: "ENG", name: "Engineering" },
        { key: "OPS", name: "Operations" },
      ],
      next_start_at: null,
    }),
    onSelectSite: vi.fn(),
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  render(<JiraPicker {...props} />);
  return props;
}

describe("JiraPicker", () => {
  it("asks for a site first when none is selected", async () => {
    const user = userEvent.setup();
    const props = renderPicker({ site: null, initialProjectKeys: [] });

    await user.click(await screen.findByRole("radio", { name: /Beta/ }));
    await user.click(screen.getByRole("button", { name: "Use this site" }));

    expect(props.onSelectSite).toHaveBeenCalledWith("cloud-beta");
    expect(props.listProjects).not.toHaveBeenCalled();
  });

  it("multi-selects projects and saves the keys", async () => {
    const user = userEvent.setup();
    const props = renderPicker();

    const eng = await screen.findByRole("checkbox", { name: /ENG/ });
    expect(eng).toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /OPS/ }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onConfirm).toHaveBeenCalledWith(["ENG", "OPS"]);
  });

  it("loads more projects with the next offset", async () => {
    const user = userEvent.setup();
    const listProjects = vi
      .fn()
      .mockResolvedValueOnce({ items: [{ key: "ENG", name: "Eng" }], next_start_at: 1 })
      .mockResolvedValueOnce({ items: [{ key: "OPS", name: "Ops" }], next_start_at: null });
    renderPicker({ listProjects });

    await user.click(await screen.findByRole("button", { name: "Load more" }));

    expect(await screen.findByRole("checkbox", { name: /OPS/ })).toBeInTheDocument();
    expect(listProjects).toHaveBeenLastCalledWith(
      expect.objectContaining({ startAt: 1 }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument(),
    );
  });

  it("offers a site switch from the project step", async () => {
    const user = userEvent.setup();
    renderPicker();

    await user.click(await screen.findByRole("button", { name: "Change site" }));

    expect(await screen.findByRole("radio", { name: /Acme/ })).toBeChecked();
  });
  it("lists projects without a site in Data Center mode", async () => {
    const user = userEvent.setup();
    const props = renderPicker({
      dataCenter: true,
      site: null,
      initialProjectKeys: [],
    });

    await user.click(await screen.findByRole("checkbox", { name: /OPS/ }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(props.onConfirm).toHaveBeenCalledWith(["OPS"]);
    expect(props.listSites).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Change site" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Jira Cloud/)).not.toBeInTheDocument();
  });
});
