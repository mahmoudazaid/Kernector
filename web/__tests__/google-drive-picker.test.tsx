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
      listItems={async () => ({ items: [FOLDER], next_page_token: null })}
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onConfirm, onCancel };
}

describe("GoogleDrivePicker", () => {
  it("defaults to Folders as the recommended mode", async () => {
    renderPicker();
    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    expect(
      within(dialog).getByRole("tab", { name: /folders/i }),
    ).toHaveAttribute("aria-selected", "true");
    expect(within(dialog).getByText(/recommended/i)).toBeInTheDocument();
    expect(
      within(dialog).getByRole("tab", { name: /individual files/i }),
    ).toHaveAttribute("aria-selected", "false");
    expect(await within(dialog).findByText("Specs")).toBeInTheDocument();
  });

  it("searches through backend DTOs without exposing tokens", async () => {
    const user = userEvent.setup();
    const listItems = vi
      .fn()
      .mockResolvedValueOnce({ items: [FOLDER], next_page_token: null })
      .mockResolvedValueOnce({
        items: [{ ...FOLDER, id: "folder-2", name: "Specs v2" }],
        next_page_token: null,
      });
    renderPicker({ listItems });

    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    await user.type(within(dialog).getByRole("searchbox"), "Specs");
    await user.click(within(dialog).getByRole("button", { name: /^search$/i }));

    expect(await within(dialog).findByText("Specs v2")).toBeInTheDocument();
    expect(listItems).toHaveBeenLastCalledWith(
      expect.objectContaining({
        parentId: "root",
        kind: "folders",
        query: "Specs",
      }),
    );
    expect(JSON.stringify(listItems.mock.calls)).not.toMatch(
      /ya29|1\/\/|refresh/,
    );
  });

  it("paginates with Load more using the backend page token", async () => {
    const user = userEvent.setup();
    const listItems = vi
      .fn()
      .mockResolvedValueOnce({
        items: [FOLDER],
        next_page_token: "page-2",
      })
      .mockResolvedValueOnce({
        items: [{ ...FOLDER, id: "folder-2", name: "More" }],
        next_page_token: null,
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
      .mockResolvedValueOnce({ items: [FOLDER], next_page_token: null });
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

  it("browses individual files from backend DTOs", async () => {
    const user = userEvent.setup();
    const listItems = vi.fn(async (options: { kind?: string }) => ({
      items: options.kind === "files" ? [FILE] : [FOLDER],
      next_page_token: null,
    }));
    renderPicker({ listItems });

    const dialog = await screen.findByRole("dialog", {
      name: /choose from google drive/i,
    });
    await user.click(
      within(dialog).getByRole("tab", { name: /individual files/i }),
    );
    expect(await within(dialog).findByText("guide.md")).toBeInTheDocument();
    expect(listItems).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "files" }),
    );
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
    expect(await within(dialog).findByRole("checkbox")).toBeChecked();
    await user.click(
      within(dialog).getByRole("button", { name: /add 1 folder & sync/i }),
    );
    expect(onConfirm).toHaveBeenCalledWith({
      folders: [{ id: "folder-1", name: "Old" }],
      files: [],
    });
  });
});
