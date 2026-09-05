import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DocumentsPanel } from "@/components/documents/DocumentsPanel";
import { ApiError } from "@/lib/api/errors";
import type {
  CatalogDocumentResponse,
  DocumentListResponse,
} from "@/lib/api/documents";

const constraints = {
  supported_suffixes: [".md", ".txt", ".pdf", ".markdown"],
  max_upload_bytes: 5_242_880,
};

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
  return { documents, constraints };
}

describe("DocumentsPanel", () => {
  it("lists uploaded documents in a table", async () => {
    const list = vi.fn().mockResolvedValue(
      listResponse([
        doc(),
        doc({ source_id: "src-2", file_name: "guide.txt", status: "failed", has_error: true, error_summary: "Ingestion failed for this document. Delete it and upload again." }),
      ]),
    );
    render(<DocumentsPanel apiBaseUrl="http://api.test" list={list} />);

    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByText("spec.md")).toBeInTheDocument();
    expect(screen.getByText("guide.txt")).toBeInTheDocument();
    expect(
      screen.getByText(/catalog identity is the source id/i),
    ).toBeInTheDocument();
  });

  it("shows empty catalog copy including seed-corpus note", async () => {
    const list = vi.fn().mockResolvedValue(listResponse([]));
    render(<DocumentsPanel apiBaseUrl="http://api.test" list={list} />);

    expect(
      await screen.findByText(/no uploaded documents yet/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/seed-corpus/i)).toBeInTheDocument();
  });

  it("keeps the panel when listing fails", async () => {
    const list = vi
      .fn()
      .mockRejectedValue(
        new ApiError({
          status: 500,
          title: "Operational error",
          detail: "Something went wrong while processing your request.",
          code: "operational_error",
        }),
      );
    render(<DocumentsPanel apiBaseUrl="http://api.test" list={list} />);

    expect(
      await screen.findByText(/something went wrong while processing/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Knowledge Hub" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload new/i })).toBeInTheDocument();
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
      />,
    );

    await screen.findByText(/no uploaded documents yet/i);
    const file = new File(["# hello"], "spec.md", { type: "text/markdown" });
    await user.upload(screen.getByLabelText(/document file/i), file);
    await user.click(screen.getByRole("button", { name: /^upload new$/i }));

    expect(upload).toHaveBeenCalledWith(
      expect.objectContaining({
        baseUrl: "http://api.test",
        file,
      }),
    );
    expect(
      await screen.findByText(/source id: new-id/i),
    ).toBeInTheDocument();
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
      />,
    );

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

  it("requires delete confirmation before enabling Delete", async () => {
    const user = userEvent.setup();
    const list = vi.fn().mockResolvedValue(listResponse([doc()]));
    const remove = vi.fn().mockResolvedValue(undefined);
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        remove={remove}
      />,
    );

    await screen.findByText("spec.md");
    const deleteButton = screen.getByRole("button", { name: /^delete$/i });
    expect(deleteButton).toBeDisabled();

    await user.click(
      screen.getByLabelText(/i confirm deletion of this document/i),
    );
    expect(deleteButton).toBeEnabled();
    await user.click(deleteButton);

    expect(remove).toHaveBeenCalledWith(
      expect.objectContaining({ sourceId: "src-1" }),
    );
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
    render(<DocumentsPanel apiBaseUrl="http://api.test" list={list} />);

    expect(
      await screen.findByText(/ingestion failed for this document/i),
    ).toBeInTheDocument();
  });

  it("shows unavailable state when the backend cannot be reached", async () => {
    const list = vi.fn().mockRejectedValue(ApiError.generic(0));
    render(<DocumentsPanel apiBaseUrl="http://api.test" list={list} />);

    expect(
      await screen.findByRole("heading", { name: /backend unavailable/i }),
    ).toBeInTheDocument();
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
    const upload = vi.fn().mockResolvedValue(doc({ source_id: "id-a", file_name: "dup.md" }));
    render(
      <DocumentsPanel
        apiBaseUrl="http://api.test"
        list={list}
        upload={upload}
      />,
    );

    await screen.findByText(/no uploaded documents yet/i);
    const file = new File(["a"], "dup.md");
    await user.upload(screen.getByLabelText(/document file/i), file);
    await user.click(screen.getByRole("button", { name: /^upload new$/i }));

    const table = await screen.findByRole("table");
    expect(within(table).getAllByText("dup.md")).toHaveLength(2);
    expect(within(table).getByText("id-a")).toBeInTheDocument();
    expect(within(table).getByText("id-b")).toBeInTheDocument();
  });
});
