import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GitHubPicker } from "@/components/documents/GitHubPicker";

const repos = {
  items: [
    {
      owner: "acme",
      name: "docs",
      full_name: "acme/docs",
      private: false,
    },
    {
      owner: "acme",
      name: "api",
      full_name: "acme/api",
      private: true,
    },
  ],
  has_next: false,
};

const projects = {
  items: [
    {
      owner_login: "octocat",
      number: 18,
      title: "AI Course",
    },
    {
      owner_login: "octocat",
      number: 19,
      title: "AI Course Lessons",
    },
  ],
  next_cursor: null,
};

const emptySelection = {
  owner: null,
  repo: null,
  project_owner: null,
  project_number: null,
};

describe("GitHubPicker", () => {
  it("shows repository and project panels together without tabs", async () => {
    render(
      <GitHubPicker
        open
        apiBaseUrl="http://api"
        accountLogin="octocat"
        initialSelection={emptySelection}
        listRepos={async () => repos}
        listProjects={async () => projects}
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );

    const dialog = await screen.findByRole("dialog", {
      name: /choose github sources/i,
    });
    expect(
      within(dialog).getByRole("radiogroup", { name: /repository code/i }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("radiogroup", { name: /project issues/i }),
    ).toBeInTheDocument();
    expect(within(dialog).queryByRole("tab")).not.toBeInTheDocument();
    expect(
      await within(dialog).findByRole("radio", { name: /acme\/docs/i }),
    ).toBeInTheDocument();
    expect(
      await within(dialog).findByRole("radio", { name: /#19 ai course lessons/i }),
    ).toBeInTheDocument();
  });

  it("requires a repository and reports one or two sources in the footer", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <GitHubPicker
        open
        apiBaseUrl="http://api"
        accountLogin="octocat"
        initialSelection={emptySelection}
        listRepos={async () => repos}
        listProjects={async () => projects}
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );

    const dialog = await screen.findByRole("dialog", {
      name: /choose github sources/i,
    });
    const save = within(dialog).getByRole("button", { name: /save sources/i });
    expect(save).toBeDisabled();
    expect(within(dialog).getByText(/0 sources selected/i)).toBeInTheDocument();

    await user.click(
      await within(dialog).findByRole("radio", { name: /acme\/docs/i }),
    );
    expect(within(dialog).getByText(/1 source selected/i)).toBeInTheDocument();
    expect(save).toBeEnabled();

    await user.click(
      await within(dialog).findByRole("radio", {
        name: /#19 ai course lessons/i,
      }),
    );
    expect(within(dialog).getByText(/2 sources selected/i)).toBeInTheDocument();

    await user.click(save);
    expect(onConfirm).toHaveBeenCalledWith({
      owner: "acme",
      repo: "docs",
      project_owner: "octocat",
      project_number: 19,
    });
  });

  it("clears the project without closing and restores existing selection", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <GitHubPicker
        open
        apiBaseUrl="http://api"
        accountLogin="octocat"
        initialSelection={{
          owner: "acme",
          repo: "api",
          project_owner: "octocat",
          project_number: 18,
        }}
        listRepos={async () => repos}
        listProjects={async () => projects}
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );

    const dialog = await screen.findByRole("dialog", {
      name: /choose github sources/i,
    });
    expect(
      await within(dialog).findByRole("radio", { name: /acme\/api/i }),
    ).toBeChecked();
    expect(
      await within(dialog).findByRole("radio", { name: /#18 ai course/i }),
    ).toBeChecked();
    expect(within(dialog).getByText(/2 sources selected/i)).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: /clear project/i }),
    );
    expect(
      within(dialog).getByRole("radio", { name: /#18 ai course/i }),
    ).not.toBeChecked();
    expect(within(dialog).getByText(/1 source selected/i)).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: /choose github sources/i }),
    ).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: /save sources/i }),
    );
    expect(onConfirm).toHaveBeenCalledWith({
      owner: "acme",
      repo: "api",
      project_owner: null,
      project_number: null,
    });
  });

  it("filters repository and project lists independently", async () => {
    const user = userEvent.setup();
    render(
      <GitHubPicker
        open
        apiBaseUrl="http://api"
        accountLogin="octocat"
        initialSelection={emptySelection}
        listRepos={async () => repos}
        listProjects={async () => projects}
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );

    const dialog = await screen.findByRole("dialog", {
      name: /choose github sources/i,
    });
    await within(dialog).findByRole("radio", { name: /acme\/docs/i });

    await user.type(
      within(dialog).getByRole("searchbox", { name: /search repositories/i }),
      "api",
    );
    expect(
      within(dialog).queryByRole("radio", { name: /acme\/docs/i }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("radio", { name: /acme\/api/i }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("radio", { name: /#18 ai course/i }),
    ).toBeInTheDocument();

    await user.type(
      within(dialog).getByRole("searchbox", { name: /search projects/i }),
      "Lessons",
    );
    expect(
      within(dialog).queryByRole("radio", { name: /#18 ai course$/i }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("radio", { name: /#19 ai course lessons/i }),
    ).toBeInTheDocument();
  });
});
