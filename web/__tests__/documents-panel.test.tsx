import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DocumentsPanel } from "@/components/documents/DocumentsPanel";
import { ApiError } from "@/lib/api/errors";
import type {
  CatalogDocumentResponse,
  DocumentListResponse,
  ListDocumentsOptions,
} from "@/lib/api/documents";
import type { RuntimeSettingsResponse } from "@/lib/api/settings";

vi.mock("@/lib/api/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/documents")>();
  return {
    ...actual,
    listDocumentChunks: vi.fn().mockResolvedValue({ chunks: [], has_more: false }),
  };
});

vi.mock("@/lib/api/connectors", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/connectors")>();
  return {
    ...actual,
    getGoogleDriveStatus: vi.fn().mockResolvedValue({
      configured: false,
      available: true,
      connected: false,
      oauth_ready: true,
      account_email: null,
      document_count: 0,
      folder_count: null,
      last_sync: null,
      reauthorization_required: false,
    }),
    syncGoogleDrive: vi.fn(),
    disconnectGoogleDrive: vi.fn(),
    getGoogleDriveSelection: vi
      .fn()
      .mockResolvedValue({ folders: [], files: [] }),
    putGoogleDriveSelection: vi.fn(),
    listGoogleDriveItems: vi
      .fn()
      .mockResolvedValue({ items: [], next_page_token: null }),
    googleDriveOAuthStartUrl: (baseUrl: string) =>
      `${baseUrl.replace(/\/$/, "")}/api/v1/connectors/google-drive/oauth/start`,
  };
});

const SETTINGS: RuntimeSettingsResponse = {
  providers: ["openrouter"],
  default_provider: "openrouter",
  openrouter: { models: [], default_model: null },
  ollama: { default_base_url: null, default_model: null },
  model_settings: [],
  enabled_packs: [],
  constraints: {
    max_input_length: 10_000,
    max_upload_bytes: 5_242_880,
    supported_upload_suffixes: [".md", ".txt", ".pdf", ".markdown"],
  },
};

const loadSettings = async () => SETTINGS;

function doc(
  overrides: Partial<CatalogDocumentResponse> = {},
): CatalogDocumentResponse {
  return {
    source_id: "src-1",
    source_type: "knowledge_document",
    file_name: "spec.md",
    title: "Spec",
    content_format: "markdown",
    status: "ready",
    uploaded_at: "2026-09-05T09:12:44+00:00",
    chunk_count: 7,
    has_error: false,
    error_summary: null,
    ...overrides,
  };
}

function listResponse(
  documents: CatalogDocumentResponse[] = [doc()],
): DocumentListResponse {
  return { documents };
}

async function openDocumentsTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("tab", { name: /documents/i }));
}

async function openUploadModal(user: ReturnType<typeof userEvent.setup>) {
  const addFiles = await screen.findByRole("button", { name: /add files/i });
  await waitFor(() => expect(addFiles).toBeEnabled());
  await user.click(addFiles);
}

describe("DocumentsPanel", () => {
  it("shows the brand loader while the catalog is loading", async () => {
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={() => new Promise(() => {})}
        loadSettings={loadSettings}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "Knowledge Hub" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/loading documents/i);
    expect(screen.queryByText(/loading uploaded documents/i)).toBeNull();
  });

  it("lists uploaded documents in a table", async () => {
    const list = vi.fn().mockResolvedValue(
      listResponse([
        doc(),
        doc({
          source_id: "src-2",
          file_name: "guide.txt",
          status: "failed",
          has_error: true,
          error_summary:
            "Ingestion failed for this document. Delete it and upload again.",
        }),
      ]),
    );
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={loadSettings}
      />,
    );

    const user = userEvent.setup();
    await openDocumentsTab(user);
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByText("spec.md")).toBeInTheDocument();
    expect(screen.getByText("guide.txt")).toBeInTheDocument();
    expect(screen.getByText("failed")).toHaveClass("kern-doc-failed");
    expect(
      screen.getByText("spec.md").closest("tr")?.querySelector("time"),
    ).toHaveAttribute("dateTime", "2026-09-05T09:12:44+00:00");
    expect(
      screen.getByText(/catalog identity is the source id/i),
    ).toBeInTheDocument();
  });

  it("shows empty catalog copy including seed-corpus note", async () => {
    const list = vi.fn().mockResolvedValue(listResponse([]));
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={loadSettings}
      />,
    );

    expect(
      await screen.findByText(/no uploaded documents yet/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/seed-corpus/i)).toBeInTheDocument();
  });

  it("keeps the panel when listing fails", async () => {
    const list = vi.fn().mockRejectedValue(
      new ApiError({
        status: 500,
        title: "Operational error",
        detail: "Something went wrong while processing your request.",
        code: "operational_error",
      }),
    );
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={loadSettings}
      />,
    );

    expect(
      await screen.findByText(/something went wrong while processing/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Knowledge Hub" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /add files/i }),
    ).toBeInTheDocument();
  });

  it("keeps upload enabled after a transient list failure once settings constraints were loaded", async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockResolvedValueOnce(listResponse([doc()]))
      .mockRejectedValueOnce(
        new ApiError({
          status: 500,
          title: "Operational error",
          detail: "Something went wrong while processing your request.",
          code: "operational_error",
        }),
      );
    const upload = vi.fn().mockResolvedValue(doc({ source_id: "new-id" }));
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        upload={upload}
        loadSettings={loadSettings}
      />,
    );

    await screen.findByText("spec.md");
    await openUploadModal(user);
    const file = new File(["# hello"], "spec.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText(/document file/i), file);
    await user.click(screen.getByRole("button", { name: /^upload new$/i }));

    expect(
      await screen.findByText(/something went wrong while processing/i),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /sources/i }));
    await openUploadModal(user);
    expect(screen.getByLabelText(/document file/i)).toBeEnabled();
  });

  it("uploads a new document and never treats file name as identity", async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockResolvedValueOnce(listResponse([]))
      .mockResolvedValueOnce(listResponse([doc({ source_id: "new-id" })]));
    const upload = vi.fn().mockResolvedValue(doc({ source_id: "new-id" }));
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        upload={upload}
        loadSettings={loadSettings}
      />,
    );

    await screen.findByText(/no uploaded documents yet/i);
    await openUploadModal(user);
    const file = new File(["# hello"], "spec.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText(/document file/i), file);
    await user.click(screen.getByRole("button", { name: /^upload new$/i }));

    expect(upload).toHaveBeenCalledWith(
      expect.objectContaining({
        baseUrl: "http://api.test",
        file,
      }),
    );
    expect(await screen.findByText(/source id: new-id/i)).toBeInTheDocument();
  });

  it("replaces only the selected document's source id", async () => {
    const user = userEvent.setup();
    const list = vi.fn().mockResolvedValue(listResponse([doc()]));
    const replace = vi.fn().mockResolvedValue(doc({ file_name: "v2.md" }));
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        replace={replace}
        loadSettings={loadSettings}
      />,
    );

    await openDocumentsTab(user);
    await screen.findByText("spec.md");
    const file = new File(["# v2"], "v2.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText(/replacement file/i), file);
    await user.click(screen.getByRole("button", { name: /^replace$/i }));

    expect(replace).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceId: "src-1",
        file,
      }),
    );
    expect(
      await screen.findByText(/source id unchanged: src-1/i),
    ).toBeInTheDocument();
  });

  it("deletes from a row action after confirmation", async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockResolvedValueOnce(listResponse([doc()]))
      .mockResolvedValueOnce(listResponse([]));
    const remove = vi.fn().mockResolvedValue(undefined);
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        remove={remove}
        loadSettings={loadSettings}
      />,
    );

    await openDocumentsTab(user);
    await screen.findByText("spec.md");
    expect(
      screen.queryByRole("checkbox", {
        name: /i confirm deletion of this document/i,
      }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /delete spec\.md/i }));

    const dialog = await screen.findByRole("dialog", {
      name: /delete document/i,
    });
    expect(dialog).toHaveTextContent(/cannot be undone/i);
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    expect(remove).toHaveBeenCalledWith(
      expect.objectContaining({ sourceId: "src-1" }),
    );
    expect(
      await screen.findByText(/deleted document src-1/i),
    ).toBeInTheDocument();
  });

  it("does not delete when row confirmation is cancelled", async () => {
    const user = userEvent.setup();
    const list = vi.fn().mockResolvedValue(listResponse([doc()]));
    const remove = vi.fn().mockResolvedValue(undefined);
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        remove={remove}
        loadSettings={loadSettings}
      />,
    );

    await openDocumentsTab(user);
    await screen.findByText("spec.md");
    await user.click(screen.getByRole("button", { name: /delete spec\.md/i }));

    const dialog = await screen.findByRole("dialog", {
      name: /delete document/i,
    });
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));

    expect(remove).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows sanitized per-document warning from error_summary", async () => {
    const list = vi.fn().mockResolvedValue(
      listResponse([
        doc({
          status: "failed",
          has_error: true,
          error_summary:
            "Ingestion failed for this document. Delete it and upload again.",
        }),
      ]),
    );
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={loadSettings}
      />,
    );

    expect(
      await screen.findByText(/ingestion failed for this document/i),
    ).toBeInTheDocument();
  });

  it("shows Drive failed files with Google Drive source and sync guidance", async () => {
    const list = vi.fn().mockResolvedValue(
      listResponse([
        doc({
          source_id: "file-9",
          source_type: "google_drive",
          file_name: "guide.md",
          status: "failed",
          has_error: true,
          error_summary:
            "This Google Drive file could not be indexed. Sync again or remove it in Browse.",
        }),
      ]),
    );
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={loadSettings}
      />,
    );

    const user = userEvent.setup();
    await openDocumentsTab(user);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("guide.md")).toBeInTheDocument();
    expect(within(table).getByText("Google Drive")).toBeInTheDocument();
    expect(within(table).getByText("failed")).toHaveClass("kern-doc-failed");
    expect(
      screen.getByText(
        /this google drive file could not be indexed\. sync again or remove it in browse\./i,
      ),
    ).toBeInTheDocument();
  });

  it("shows unavailable state when the backend cannot be reached", async () => {
    const list = vi.fn().mockRejectedValue(ApiError.generic(0));
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={loadSettings}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: /backend unavailable/i }),
    ).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: /^retry$/i });
    expect(retry.closest(".kern-content-state")).not.toBeNull();
    expect(retry.closest(".kern-state")).not.toBeNull();
  });

  it("keeps two uploads of the same file name as separate rows after refresh", async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockResolvedValueOnce(listResponse([]))
      .mockResolvedValueOnce(
        listResponse([
          doc({ source_id: "id-a", file_name: "dup.md" }),
          doc({ source_id: "id-b", file_name: "dup.md" }),
        ]),
      );
    const upload = vi
      .fn()
      .mockResolvedValue(doc({ source_id: "id-a", file_name: "dup.md" }));
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        upload={upload}
        loadSettings={loadSettings}
      />,
    );

    await screen.findByText(/no uploaded documents yet/i);
    await openUploadModal(user);
    const file = new File(["a"], "dup.md");
    await user.upload(screen.getByLabelText(/document file/i), file);
    await user.click(screen.getByRole("button", { name: /^upload new$/i }));

    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("dup.md")).toHaveLength(2);
    expect(within(table).getByText("id-a")).toBeInTheDocument();
    expect(within(table).getByText("id-b")).toBeInTheDocument();
  });

  it("surfaces a settings-fetch failure, disables replace, and recovers on retry", async () => {
    const user = userEvent.setup();
    const list = vi.fn().mockResolvedValue(listResponse([doc()]));
    const failingLoadSettings = vi
      .fn()
      .mockRejectedValueOnce(new Error("settings down"))
      .mockResolvedValueOnce(SETTINGS);
    const replace = vi.fn();

    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        replace={replace}
        loadSettings={failingLoadSettings}
      />,
    );

    await screen.findByText("spec.md");
    expect(
      await screen.findByText(/settings catalog unavailable/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add files/i })).toBeDisabled();
    await openDocumentsTab(user);
    expect(screen.getByLabelText(/replacement file/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: /^replace$/i })).toBeDisabled();
    expect(replace).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /^retry$/i }));

    await user.click(screen.getByRole("tab", { name: /sources/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /add files/i })).toBeEnabled();
    });
    expect(
      screen.queryByText(/settings catalog unavailable/i),
    ).not.toBeInTheDocument();
    await openDocumentsTab(user);
    expect(screen.getByLabelText(/replacement file/i)).toBeEnabled();
    expect(failingLoadSettings).toHaveBeenCalledTimes(2);
    expect(list).toHaveBeenCalledTimes(1);
  });

  it("retries only settings when the document list is healthy", async () => {
    const user = userEvent.setup();
    const list = vi.fn().mockResolvedValue(listResponse([doc()]));
    const failingLoadSettings = vi
      .fn()
      .mockRejectedValueOnce(new Error("settings down"))
      .mockResolvedValueOnce(SETTINGS);

    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={failingLoadSettings}
      />,
    );

    await screen.findByText("spec.md");
    expect(
      await screen.findByText(/settings catalog unavailable/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^retry$/i }));

    await waitFor(() => {
      expect(
        screen.queryByText(/settings catalog unavailable/i),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByText("spec.md")).toBeInTheDocument();
    expect(failingLoadSettings).toHaveBeenCalledTimes(2);
    expect(list).toHaveBeenCalledTimes(1);
  });

  it("retries only the document list when settings are healthy", async () => {
    const user = userEvent.setup();
    const list = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError({
          status: 500,
          title: "Operational error",
          detail: "Something went wrong while processing your request.",
          code: "operational_error",
        }),
      )
      .mockResolvedValueOnce(listResponse([doc()]));
    const healthyLoadSettings = vi.fn().mockResolvedValue(SETTINGS);

    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={healthyLoadSettings}
      />,
    );

    expect(
      await screen.findByText(/something went wrong while processing/i),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /add files/i })).toBeEnabled();
    });

    await user.click(screen.getByRole("button", { name: /^retry$/i }));

    expect(await screen.findByText("spec.md")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add files/i })).toBeEnabled();
    expect(
      screen.queryByText(/settings catalog unavailable/i),
    ).not.toBeInTheDocument();
    expect(healthyLoadSettings).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("keeps the retry callout visible while settings reload", async () => {
    const user = userEvent.setup();
    let finishReload: (value: RuntimeSettingsResponse) => void = () => {
      throw new Error("reload was not started");
    };
    const loadSettings = vi
      .fn()
      .mockRejectedValueOnce(new Error("settings down"))
      .mockImplementationOnce(
        () =>
          new Promise<RuntimeSettingsResponse>((resolve) => {
            finishReload = resolve;
          }),
      );

    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([doc()]))}
        loadSettings={loadSettings}
      />,
    );

    expect(
      await screen.findByText(/settings catalog unavailable/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^retry$/i }));

    expect(
      await screen.findByRole("button", { name: /^checking/i }),
    ).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      /settings catalog unavailable/i,
    );

    finishReload(SETTINGS);

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /add files/i })).toBeEnabled();
  });

  it("leaves document retry enabled while settings are still loading", async () => {
    const list = vi.fn().mockRejectedValue(
      new ApiError({
        status: 500,
        title: "Operational error",
        detail: "Something went wrong while processing your request.",
        code: "operational_error",
      }),
    );
    const pendingSettings = vi.fn(
      () => new Promise<RuntimeSettingsResponse>(() => {}),
    );

    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={pendingSettings}
      />,
    );

    expect(
      await screen.findByText(/something went wrong while processing/i),
    ).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: /^retry$/i });
    expect(retry).toBeEnabled();
    expect(retry).toHaveTextContent(/^Retry$/);
  });

  it("ignores a stale document list response after a newer refresh", async () => {
    const user = userEvent.setup();
    let rejectRetry: (error: unknown) => void = () => {
      throw new Error("retry was not started");
    };
    const list = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError({
          status: 500,
          title: "Operational error",
          detail: "Something went wrong while processing your request.",
          code: "operational_error",
        }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<DocumentListResponse>((_resolve, reject) => {
            rejectRetry = reject;
          }),
      )
      .mockResolvedValueOnce(listResponse([doc()]));
    const upload = vi.fn().mockResolvedValue(doc());

    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        upload={upload}
        loadSettings={loadSettings}
      />,
    );

    expect(
      await screen.findByText(/something went wrong while processing/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^retry$/i }));
    expect(
      await screen.findByRole("button", { name: /^checking/i }),
    ).toBeDisabled();

    await openUploadModal(user);
    const file = new File(["# hello"], "spec.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText(/document file/i), file);
    await user.click(screen.getByRole("button", { name: /^upload new$/i }));

    expect(await screen.findByText("spec.md")).toBeInTheDocument();
    expect(
      screen.queryByText(/something went wrong while processing/i),
    ).not.toBeInTheDocument();

    rejectRetry(
      new ApiError({
        status: 500,
        title: "Operational error",
        detail: "Something went wrong while processing your request.",
        code: "operational_error",
      }),
    );

    await waitFor(() => {
      expect(list).toHaveBeenCalledTimes(3);
    });
    expect(list.mock.calls[1][0].signal?.aborted).toBe(true);
    expect(screen.getByText("spec.md")).toBeInTheDocument();
    expect(
      screen.queryByText(/something went wrong while processing/i),
    ).not.toBeInTheDocument();
  });

  it("cancels an in-flight document list on unmount", async () => {
    const list = vi.fn(
      (_options: ListDocumentsOptions) =>
        new Promise<DocumentListResponse>(() => {}),
    );

    const { unmount } = render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        loadSettings={loadSettings}
      />,
    );

    await waitFor(() => {
      expect(list).toHaveBeenCalledTimes(1);
    });
    const signal = list.mock.calls[0][0].signal;
    expect(signal?.aborted).toBe(false);

    unmount();

    expect(signal?.aborted).toBe(true);
  });

  it("leaves unavailable retry enabled while settings are still loading", async () => {
    const pendingSettings = vi.fn(
      () => new Promise<RuntimeSettingsResponse>(() => {}),
    );

    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockRejectedValue(ApiError.generic(0))}
        loadSettings={pendingSettings}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: /backend unavailable/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^retry$/i })).toBeEnabled();
  });

  it("filters the catalog with SoftSelect instead of a native select", async () => {
    const user = userEvent.setup();
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([doc()]))}
        loadSettings={loadSettings}
      />,
    );

    await openDocumentsTab(user);
    expect(document.querySelector("select")).toBeNull();
    expect(
      screen.getByRole("combobox", { name: /^source$/i }),
    ).toHaveTextContent("All sources");
    expect(
      screen.getByRole("searchbox", { name: /^search$/i }),
    ).toBeInTheDocument();
  });

  it("lists Google Drive documents in the shared catalog", async () => {
    const user = userEvent.setup();
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(
          listResponse([
            doc(),
            doc({
              source_id: "drive-1",
              source_type: "google_drive",
              file_name: "Mieterselbtstauskunft",
            }),
          ]),
        )}
        loadSettings={loadSettings}
      />,
    );

    await openDocumentsTab(user);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Mieterselbtstauskunft")).toBeInTheDocument();
    expect(within(table).getByText("Google Drive")).toBeInTheDocument();
    expect(within(table).getByText("File upload")).toBeInTheDocument();
    expect(
      within(table).getByRole("button", { name: /delete mieterselbtstauskunft/i }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: /^source$/i }));
    await user.click(screen.getByRole("option", { name: "Google Drive" }));
    expect(screen.getByText("Mieterselbtstauskunft")).toBeInTheDocument();
    expect(screen.queryByText("spec.md")).not.toBeInTheDocument();
    await user.click(within(table).getByText("Mieterselbtstauskunft"));
    expect(screen.getByText(/managed by google drive sync/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^replace$/i })).not.toBeInTheDocument();
  });

  it("prompts to select a document when the current row is filtered out", async () => {
    const user = userEvent.setup();
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(
          listResponse([
            doc(),
            doc({
              source_id: "drive-1",
              source_type: "google_drive",
              file_name: "Mieterselbtstauskunft",
            }),
          ]),
        )}
        loadSettings={loadSettings}
      />,
    );

    await openDocumentsTab(user);
    await screen.findByText("spec.md");
    await user.click(screen.getByRole("combobox", { name: /^source$/i }));
    await user.click(screen.getByRole("option", { name: "Google Drive" }));
    expect(
      screen.getByText(/select a document to see details or replace it/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^replace$/i }),
    ).not.toBeInTheDocument();
  });

  it("deletes a Google Drive document from the catalog", async () => {
    const user = userEvent.setup();
    const remove = vi.fn().mockResolvedValue(undefined);
    const list = vi
      .fn()
      .mockResolvedValueOnce(
        listResponse([
          doc({
            source_id: "drive-1",
            source_type: "google_drive",
            file_name: "notes.md",
          }),
        ]),
      )
      .mockResolvedValueOnce(listResponse([]));
    const getDriveStatus = vi.fn().mockResolvedValue({
      configured: false,
      available: true,
      connected: true,
      oauth_ready: true,
      account_email: "ada@example.com",
      document_count: 1,
      folder_count: 0,
      last_sync: null,
      reauthorization_required: false,
      setup_required: false,
      connection_state: "ready",
      sync_scope: "1 file",
    });

    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        remove={remove}
        loadSettings={loadSettings}
        getDriveStatus={getDriveStatus}
      />,
    );

    await openDocumentsTab(user);
    await user.click(
      await screen.findByRole("button", { name: /delete notes\.md/i }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: /delete document/i,
    });
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    expect(remove).toHaveBeenCalledWith(
      expect.objectContaining({ sourceId: "drive-1" }),
    );
    await waitFor(() => {
      expect(getDriveStatus.mock.calls.length).toBeGreaterThan(1);
    });
  });

  it("counts only file uploads on the File uploads card", async () => {
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(
          listResponse([
            doc(),
            doc({
              source_id: "drive-1",
              source_type: "google_drive",
              file_name: "notes.md",
            }),
          ]),
        )}
        loadSettings={loadSettings}
      />,
    );

    const card = (await screen.findByRole("heading", { name: "File uploads" }))
      .closest("article");
    expect(card?.querySelector(".kern-source-metrics")).toHaveTextContent(
      /documents\s*1/i,
    );
    expect(card?.querySelector("time")).toHaveAttribute(
      "dateTime",
      "2026-09-05T09:12:44+00:00",
    );
    expect(screen.getByRole("tab", { name: /documents/i })).toHaveTextContent("2");
  });

  it("renders File uploads as a full-width connected source", async () => {
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([]))}
        loadSettings={loadSettings}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "File uploads" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Latest upload")).toBeInTheDocument();
    expect(screen.getByText("None yet")).toBeInTheDocument();
    const card = screen
      .getByRole("heading", { name: "File uploads" })
      .closest("article");
    expect(card?.parentElement).toHaveClass("kern-source-grid");
    expect(
      card?.querySelector(".kern-source-metrics")?.lastElementChild,
    ).toHaveTextContent(/latest upload/i);
  });

  it("keeps Google Drive under Available connectors before authorization", async () => {
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([]))}
        loadSettings={loadSettings}
        getDriveStatus={async () => ({
          configured: false,
          available: true,
          connected: false,
          oauth_ready: true,
          account_email: null,
          document_count: 0,
          folder_count: null,
          last_sync: null,
          reauthorization_required: false,
          setup_required: false,
          connection_state: "disconnected",
          sync_scope: null,
        })}
      />,
    );

    expect(
      await screen.findByRole("link", { name: /^connect$/i }),
    ).toHaveAttribute(
      "href",
      "http://api.test/api/v1/connectors/google-drive/oauth/start",
    );
    const available = screen.getByRole("heading", {
      name: "Available connectors",
    }).parentElement?.nextElementSibling;
    expect(available?.textContent).toMatch(/google drive/i);
    expect(
      screen.queryByRole("button", { name: /Sync/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Knowledge Hub" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /sources/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /documents/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /add files/i }),
    ).toBeInTheDocument();
  });

  it("moves Google Drive to Connected sources after authorization", async () => {
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([]))}
        loadSettings={loadSettings}
        getDriveStatus={async () => ({
          configured: false,
          available: true,
          connected: true,
          oauth_ready: true,
          account_email: "ada@example.com",
          document_count: 2,
          folder_count: 1,
          last_sync: null,
          reauthorization_required: false,
          setup_required: false,
          connection_state: "ready",
          sync_scope: "1 folder",
        })}
      />,
    );

    await waitFor(() => {
      const connected = screen.getByRole("heading", {
        name: "Connected sources",
      }).parentElement?.nextElementSibling;
      expect(connected?.textContent).toMatch(/google drive/i);
    });
    expect(
      await screen.findByRole("button", { name: /Sync/i }),
    ).toBeInTheDocument();
    const available = screen.getByRole("heading", {
      name: "Available connectors",
    }).parentElement?.nextElementSibling;
    expect(available?.textContent).not.toMatch(/google drive/i);
  });

  it("opens the Drive picker after OAuth when the panel remounts as connected", async () => {
    window.history.pushState({}, "", "/documents?drive=connected");
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([]))}
        loadSettings={loadSettings}
        getDriveStatus={async () => ({
          configured: false,
          available: true,
          connected: true,
          oauth_ready: true,
          account_email: "ada@example.com",
          document_count: 0,
          folder_count: 0,
          last_sync: null,
          reauthorization_required: false,
          setup_required: true,
          connection_state: "setup_required",
          sync_scope: null,
        })}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByRole("dialog", {
          name: /choose from google drive/i,
        }),
      ).toBeInTheDocument();
    });
  });

  it("fetches chunks only for a ready selection with source_id and source_type", async () => {
    const listChunks = vi.fn().mockResolvedValue({
      chunks: [
        {
          index: 0,
          content: "first body",
          source_id: "src-1",
          source_type: "knowledge_document",
          title: "Spec",
          provider: "upload",
          content_format: "markdown",
          extra: {},
        },
      ],
      has_more: false,
    });
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(
          listResponse([
            doc({ status: "failed", has_error: true, error_summary: "boom" }),
            doc({
              source_id: "src-ready",
              file_name: "ready.md",
              status: "ready",
              chunk_count: 1,
            }),
          ]),
        )}
        listChunks={listChunks}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    await screen.findByText("spec.md");
    expect(listChunks).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /ready\.md\s*src-ready/i }));

    await waitFor(() => {
      expect(listChunks).toHaveBeenCalledWith(
        expect.objectContaining({
          sourceId: "src-ready",
          sourceType: "knowledge_document",
        }),
      );
    });
    expect(await screen.findByText("first body")).toBeInTheDocument();
    expect(screen.getByText("Chunk 0")).toBeInTheDocument();
  });

  it("shows empty chunk state for a ready document with no chunks", async () => {
    const empty = vi.fn().mockResolvedValue({ chunks: [], has_more: false });
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([doc()]))}
        listChunks={empty}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    expect(
      await screen.findByText(/no stored chunks for this document/i),
    ).toBeInTheDocument();
  });

  it("shows not-found chunk state and refreshes the catalog on 404", async () => {
    let resolveRefresh: ((value: DocumentListResponse) => void) | undefined;
    const list = vi
      .fn()
      .mockResolvedValueOnce(listResponse([doc()]))
      .mockImplementationOnce(
        () =>
          new Promise<DocumentListResponse>((resolve) => {
            resolveRefresh = resolve;
          }),
      );
    const notFound = vi
      .fn()
      .mockRejectedValue(
        new ApiError({
          status: 404,
          title: "Document not found",
          detail: "The requested document was not found.",
          code: "document_not_found",
        }),
      );
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        listChunks={notFound}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    expect(
      await screen.findByText(/document was not found in the catalog/i),
    ).toBeInTheDocument();
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    resolveRefresh?.(listResponse([]));
    await waitFor(() => {
      expect(screen.queryByText("spec.md")).not.toBeInTheDocument();
    });
  });

  it("shows error chunk state when the chunks request fails", async () => {
    const failing = vi
      .fn()
      .mockRejectedValue(
        new ApiError({
          status: 500,
          title: "Operational error",
          detail: "chunks boom",
          code: "operational_error",
        }),
      );
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([doc()]))}
        listChunks={failing}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    expect(await screen.findByText("chunks boom")).toBeInTheDocument();
  });

  it("aborts in-flight chunk fetch when selection changes", async () => {
    let resolveFirst:
      | ((value: { chunks: []; has_more: boolean }) => void)
      | undefined;
    const firstSignal = { current: null as AbortSignal | null };
    const listChunks = vi.fn().mockImplementation((options: { signal?: AbortSignal; sourceId: string }) => {
      if (options.sourceId === "src-1") {
        firstSignal.current = options.signal ?? null;
        return new Promise<{ chunks: []; has_more: boolean }>((resolve) => {
          resolveFirst = resolve;
        });
      }
      return Promise.resolve({
        chunks: [
          {
            index: 0,
            content: "second doc chunk",
            source_id: "src-2",
            source_type: "knowledge_document",
            title: null,
            provider: null,
            content_format: null,
            extra: {},
          },
        ],
        has_more: false,
      });
    });
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(
          listResponse([
            doc(),
            doc({ source_id: "src-2", file_name: "other.md", chunk_count: 1 }),
          ]),
        )}
        listChunks={listChunks}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    await waitFor(() => expect(listChunks).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: /other\.md\s*src-2/i }));

    await waitFor(() => {
      expect(firstSignal.current?.aborted).toBe(true);
    });
    expect(await screen.findByText("second doc chunk")).toBeInTheDocument();
    resolveFirst?.({ chunks: [], has_more: false });
    expect(screen.queryByText("first body")).not.toBeInTheDocument();
  });

  it("refetches chunks after replace when selection stays ready", async () => {
    const listChunks = vi.fn().mockResolvedValue({ chunks: [], has_more: false });
    const list = vi
      .fn()
      .mockResolvedValueOnce(
        listResponse([
          doc({
            chunk_count: 1,
            uploaded_at: "2026-09-05T09:12:44+00:00",
          }),
        ]),
      )
      .mockResolvedValueOnce(
        listResponse([
          doc({
            chunk_count: 1,
            uploaded_at: "2026-09-10T12:00:00+00:00",
          }),
        ]),
      );
    const replace = vi.fn().mockResolvedValue(
      doc({
        chunk_count: 1,
        uploaded_at: "2026-09-10T12:00:00+00:00",
      }),
    );
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        listChunks={listChunks}
        replace={replace}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    await waitFor(() => expect(listChunks).toHaveBeenCalledTimes(1));

    const file = new File(["# v2"], "v2.md", { type: "text/markdown" });
    const input = screen.getByLabelText(/replacement file/i);
    await user.upload(input, file);
    await user.click(screen.getByRole("button", { name: /^replace$/i }));

    await waitFor(() => expect(replace).toHaveBeenCalled());
    await waitFor(() => expect(listChunks).toHaveBeenCalledTimes(2));
    expect(listChunks.mock.calls[1][0]).toEqual(
      expect.objectContaining({
        sourceId: "src-1",
        sourceType: "knowledge_document",
      }),
    );
  });

  it("loads more chunks and hides the phantom button at exact page size", async () => {
    const page1 = Array.from({ length: 50 }, (_, index) => ({
      index,
      content: `body-${index}`,
      source_id: "src-1",
      source_type: "knowledge_document",
      title: "Spec",
      provider: "upload",
      content_format: "markdown",
      extra: {},
    }));
    const page2 = Array.from({ length: 10 }, (_, index) => ({
      index: index + 50,
      content: `body-${index + 50}`,
      source_id: "src-1",
      source_type: "knowledge_document",
      title: "Spec",
      provider: "upload",
      content_format: "markdown",
      extra: {},
    }));
    const listChunks = vi
      .fn()
      .mockResolvedValueOnce({ chunks: page1, has_more: true })
      .mockResolvedValueOnce({ chunks: page2, has_more: false });
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([doc({ chunk_count: 60 })]))}
        listChunks={listChunks}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    expect(await screen.findByText("body-0")).toBeInTheDocument();
    expect(screen.getByText(/showing 50 chunks \(more available\)/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /load more chunks/i }));

    await waitFor(() => expect(listChunks).toHaveBeenCalledTimes(2));
    expect(listChunks.mock.calls[1][0]).toEqual(
      expect.objectContaining({ offset: 50, limit: 50 }),
    );
    expect(await screen.findByText("body-59")).toBeInTheDocument();
    expect(screen.getByText(/^showing 60 chunks$/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /all chunks loaded/i }),
    ).toBeDisabled();
  });

  it("does not show load more when chunk_count equals the first page size", async () => {
    const page = Array.from({ length: 50 }, (_, index) => ({
      index,
      content: `exact-${index}`,
      source_id: "src-1",
      source_type: "knowledge_document",
      title: "Spec",
      provider: "upload",
      content_format: "markdown",
      extra: {},
    }));
    const listChunks = vi.fn().mockResolvedValue({ chunks: page, has_more: false });
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([doc({ chunk_count: 50 })]))}
        listChunks={listChunks}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    expect(await screen.findByText("exact-0")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /all chunks loaded/i }),
    ).toBeDisabled();
    expect(listChunks).toHaveBeenCalledTimes(1);
  });

  it("ignores a stale load-more response after selection changes", async () => {
    let resolveMore: ((value: { chunks: unknown[]; has_more: boolean }) => void) | undefined;
    const listChunks = vi.fn().mockImplementation(
      (options: { sourceId: string; offset?: number }) => {
        if (options.sourceId === "src-1" && (options.offset ?? 0) === 0) {
          return Promise.resolve({
            chunks: Array.from({ length: 50 }, (_, index) => ({
              index,
              content: `a-${index}`,
              source_id: "src-1",
              source_type: "knowledge_document",
              title: "A",
              provider: "upload",
              content_format: "markdown",
              extra: {},
            })),
            has_more: true,
          });
        }
        if (options.sourceId === "src-1" && options.offset === 50) {
          return new Promise<{ chunks: unknown[]; has_more: boolean }>((resolve) => {
            resolveMore = resolve;
          });
        }
        return Promise.resolve({
          chunks: [
            {
              index: 0,
              content: "b-only",
              source_id: "src-2",
              source_type: "knowledge_document",
              title: "B",
              provider: "upload",
              content_format: "markdown",
              extra: {},
            },
          ],
          has_more: false,
        });
      },
    );
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(
          listResponse([
            doc({ source_id: "src-1", file_name: "a.md", chunk_count: 60 }),
            doc({ source_id: "src-2", file_name: "b.md", chunk_count: 1 }),
          ]),
        )}
        listChunks={listChunks}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    expect(await screen.findByText("a-0")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /load more chunks/i }));
    await waitFor(() => expect(resolveMore).toBeDefined());

    await user.click(screen.getByRole("button", { name: /b\.md\s*src-2/i }));
    expect(await screen.findByText("b-only")).toBeInTheDocument();

    resolveMore?.({
      chunks: [
        {
          index: 50,
          content: "stale-a",
          source_id: "src-1",
          source_type: "knowledge_document",
          title: "A",
          provider: "upload",
          content_format: "markdown",
          extra: {},
        },
      ],
      has_more: false,
    });
    await waitFor(() => expect(screen.getByText("b-only")).toBeInTheDocument());
    expect(screen.queryByText("stale-a")).not.toBeInTheDocument();
  });

  it("keeps loaded chunks when load more fails", async () => {
    const listChunks = vi
      .fn()
      .mockResolvedValueOnce({
        chunks: Array.from({ length: 50 }, (_, index) => ({
          index,
          content: `keep-${index}`,
          source_id: "src-1",
          source_type: "knowledge_document",
          title: "Spec",
          provider: "upload",
          content_format: "markdown",
          extra: {},
        })),
        has_more: true,
      })
      .mockRejectedValueOnce(ApiError.aborted());
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(listResponse([doc({ chunk_count: 60 })]))}
        listChunks={listChunks}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    expect(await screen.findByText("keep-0")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /load more chunks/i }));
    expect(
      await screen.findByText(/cancelled or timed out/i),
    ).toBeInTheDocument();
    expect(screen.getByText("keep-0")).toBeInTheDocument();
    expect(screen.getByText(/showing 50 chunks \(more available\)/i)).toBeInTheDocument();
  });

  it("refetches chunks when only chunk_count changes", async () => {
    const listChunks = vi.fn().mockResolvedValue({ chunks: [], has_more: false });
    const list = vi
      .fn()
      .mockResolvedValueOnce(
        listResponse([
          doc({
            chunk_count: 1,
            uploaded_at: "2026-09-05T09:12:44+00:00",
          }),
        ]),
      )
      .mockResolvedValueOnce(
        listResponse([
          doc({
            chunk_count: 2,
            uploaded_at: "2026-09-05T09:12:44+00:00",
          }),
        ]),
      );
    const replace = vi.fn().mockResolvedValue(
      doc({
        chunk_count: 2,
        uploaded_at: "2026-09-05T09:12:44+00:00",
      }),
    );
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        listChunks={listChunks}
        replace={replace}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    await waitFor(() => expect(listChunks).toHaveBeenCalledTimes(1));

    const file = new File(["# v2"], "v2.md", { type: "text/markdown" });
    const input = screen.getByLabelText(/replacement file/i);
    await user.upload(input, file);
    await user.click(screen.getByRole("button", { name: /^replace$/i }));

    await waitFor(() => expect(replace).toHaveBeenCalled());
    await waitFor(() => expect(listChunks).toHaveBeenCalledTimes(2));
  });

  it("does not fetch chunks for a filter-hidden selection", async () => {
    const listChunks = vi.fn().mockResolvedValue({
      chunks: [
        {
          index: 0,
          content: "hidden-body",
          source_id: "src-1",
          source_type: "knowledge_document",
          title: "Spec",
          provider: "upload",
          content_format: "markdown",
          extra: {},
        },
      ],
      has_more: false,
    });
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={vi.fn().mockResolvedValue(
          listResponse([
            doc({ source_id: "src-1", file_name: "upload.md" }),
            doc({
              source_id: "drive-1",
              file_name: "drive.md",
              source_type: "google_drive",
            }),
          ]),
        )}
        listChunks={listChunks}
        loadSettings={loadSettings}
      />,
    );
    const user = userEvent.setup();
    await openDocumentsTab(user);
    await waitFor(() => expect(listChunks).toHaveBeenCalled());
    listChunks.mockClear();

    await user.click(screen.getByRole("combobox", { name: /^source$/i }));
    await user.click(screen.getByRole("option", { name: /google drive/i }));
    await waitFor(() => {
      expect(screen.queryByText("upload.md")).not.toBeInTheDocument();
    });
    expect(listChunks).not.toHaveBeenCalled();
    expect(screen.queryByText("hidden-body")).not.toBeInTheDocument();
  });
});
