import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { GoogleDrivePicker } from "@/components/documents/GoogleDrivePicker";
import { ApiError } from "@/lib/api/errors";
import type { GoogleDriveBrowseItemResponse } from "@/lib/api/connectors";

const FOLDER: GoogleDriveBrowseItemResponse = {
  id: "folder-1",
  name: "Specs",
  kind: "folder",
  mime_type: "application/vnd.google-apps.folder",
  supported: true,
  modified_at: "2026-09-08T12:00:00.000Z",
};

const FILE: GoogleDriveBrowseItemResponse = {
  id: "file-9",
  name: "guide.md",
  kind: "file",
  mime_type: "text/markdown",
  supported: true,
  modified_at: null,
};

const EMPTY = { folders: [], files: [] };

async function listByKind(options: { kind?: string; pageToken?: string | null }) {
  if (options.kind === "files") {
    return { items: [FILE], next_page_token: null };
  }
  if (options.pageToken === "page-2") {
    return {
      items: [{ ...FOLDER, id: "folder-2", name: "More" }],
      next_page_token: null,
    };
  }
  return { items: [FOLDER], next_page_token: null };
}

function renderPicker(
  overrides: Partial<ComponentProps<typeof GoogleDrivePicker>> = {},
) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <GoogleDrivePicker
      open
      apiBaseUrl="http://api.test"
      initialSelection={EMPTY}
      listItems={listByKind}
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onConfirm, onCancel };
}

describe("GoogleDrivePicker", () => {
  it("shows the brand loader while Drive items are loading", async () => {
    let resolveFolders: (value: {
      items: GoogleDriveBrowseItemResponse[];
      next_page_token: null;
    }) => void = () => undefined;
    const folders = new Promise<{
      items: GoogleDriveBrowseItemResponse[];
      next_page_token: null;
    }>((resolve) => {
      resolveFolders = resolve;
    });
    renderPicker({
      listItems: async (options) => {
        if (options.kind === "files") {
          return { items: [], next_page_token: null };
        }
        return folders;
      },
    });

    const dialog = screen.getByRole("dialog", {
      name: /choose from google drive/i,
    });
    const status = within(dialog).getByRole("status");
    expect(status).toHaveTextContent(/loading google drive/i);
    expect(status.querySelector("svg.kern-picker-loader")).toBeInTheDocument();
    expect(
      status.querySelector(".kern-chat-thinking-mark"),
    ).not.toBeInTheDocument();

    resolveFolders({ items: [FOLDER], next_page_token: null });
    expect(await within(dialog).findByText("Specs")).toBeInTheDocument();
  });

  it("shows folders and files in one Drive view", async () => {
    renderPicker();
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(
      within(dialog).queryByRole("tab", { name: /folders/i }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).queryByRole("tab", { name: /individual files/i }),
    ).not.toBeInTheDocument();
    expect(await within(dialog).findByText("Specs")).toBeInTheDocument();
    expect(within(dialog).getByText("guide.md")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /^close$/i }),
    ).toHaveAccessibleName("Close");
    expect(within(dialog).queryByText(/^close$/i)).not.toBeInTheDocument();
  });

  it("searches folders and files through backend DTOs without exposing tokens", async () => {
    const user = userEvent.setup();
    const listItems = vi.fn(async (options: { kind?: string; query?: string }) => {
      if (options.query === "Specs") {
        return {
          items:
            options.kind === "files"
              ? []
              : [{ ...FOLDER, id: "folder-2", name: "Specs v2" }],
          next_page_token: null,
        };
      }
      return listByKind(options);
    });
    renderPicker({ listItems });

    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    await user.type(within(dialog).getByRole("searchbox"), "Specs");
    await user.click(within(dialog).getByRole("button", { name: /^search$/i }));

    expect(await within(dialog).findByText("Specs v2")).toBeInTheDocument();
    expect(listItems).toHaveBeenCalledWith(
      expect.objectContaining({
        parentId: "root",
        kind: "folders",
        query: "Specs",
      }),
    );
    expect(listItems).toHaveBeenCalledWith(
      expect.objectContaining({
        parentId: "root",
        kind: "files",
        query: "Specs",
      }),
    );
    expect(JSON.stringify(listItems.mock.calls)).not.toMatch(
      /ya29|1\/\/|refresh/,
    );
  });

  it("paginates with Load more using the backend page token", async () => {
    const user = userEvent.setup();
    const listItems = vi.fn(async (options: { kind?: string; pageToken?: string | null }) => {
      if (options.kind === "files") {
        return { items: [], next_page_token: null };
      }
      if (options.pageToken === "page-2") {
        return {
          items: [{ ...FOLDER, id: "folder-2", name: "More" }],
          next_page_token: null,
        };
      }
      return { items: [FOLDER], next_page_token: "page-2" };
    });
    renderPicker({ listItems });

    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(await within(dialog).findByText("Specs")).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole("button", { name: /load more/i }),
    );
    expect(await within(dialog).findByText("More")).toBeInTheDocument();
    expect(listItems).toHaveBeenLastCalledWith(
      expect.objectContaining({ pageToken: "page-2", kind: "folders" }),
    );
  });

  it("shows an empty state when the folder has no selectable items", async () => {
    renderPicker({
      listItems: async () => ({ items: [], next_page_token: null }),
    });
    expect(
      await screen.findByText(/this folder has no items you can select/i),
    ).toBeInTheDocument();
  });

  it("retries after a permission error", async () => {
    const user = userEvent.setup();
    const listItems = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError({
          status: 403,
          title: "Permission denied",
          detail: "You do not have access to this Drive folder.",
          code: "google_drive_request_failed",
        }),
      )
      .mockImplementation(listByKind);
    renderPicker({ listItems });

    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /do not have access/i,
    );
    await user.click(within(dialog).getByRole("button", { name: /^retry$/i }));
    expect(await within(dialog).findByText("Specs")).toBeInTheDocument();
  });

  it("explains expired authorization and offers retry", async () => {
    renderPicker({
      listItems: async () => {
        throw new ApiError({
          status: 409,
          title: "Reauthorization required",
          detail: "Google Drive authorization was revoked.",
          code: "google_drive_reauthorization_required",
        });
      },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(/revoked/i);
    expect(screen.getByRole("button", { name: /^retry$/i })).toBeEnabled();
  });

  it("confirms selected Drive IDs rather than names", async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderPicker({
      initialSelection: {
        folders: [{ id: "folder-1", name: "Old" }],
        files: [],
      },
    });
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(await within(dialog).findByRole("checkbox", { name: /specs/i })).toBeChecked();
    await user.click(within(dialog).getByRole("checkbox", { name: /guide.md/i }));
    await user.click(within(dialog).getByRole("button", { name: /^save$/i }));
    expect(onConfirm).toHaveBeenCalledWith({
      folders: [{ id: "folder-1", name: "Old" }],
      files: [{ id: "file-9", name: "guide.md" }],
    });
  });

  it("enables Save after deselecting the last item and keeps it dimmed when unchanged", async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderPicker({
      initialSelection: {
        folders: [{ id: "folder-1", name: "Specs" }],
        files: [],
      },
    });
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    const save = within(dialog).getByRole("button", { name: /^save$/i });
    expect(await within(dialog).findByRole("checkbox", { name: /specs/i })).toBeChecked();
    expect(save).toBeDisabled();

    await user.click(within(dialog).getByRole("checkbox", { name: /specs/i }));
    expect(save).toBeEnabled();
    expect(within(dialog).getByText(/no items selected/i)).toBeInTheDocument();

    await user.click(save);
    expect(onConfirm).toHaveBeenCalledWith({ folders: [], files: [] });
  });
});
