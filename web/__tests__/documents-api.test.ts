import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import {
  DOCUMENT_CHUNKS_TIMEOUT_MS,
  DOCUMENT_MUTATION_TIMEOUT_MS,
  DOCUMENT_READ_TIMEOUT_MS,
  deleteDocument,
  downloadDocument,
  getDocumentContent,
  listDocumentChunks,
  listDocuments,
  replaceDocument,
  uploadDocument,
} from "@/lib/api/documents";

describe("documents api wrappers", () => {
  it("lists documents via GET /api/v1/documents", async () => {
    const request = vi.fn().mockResolvedValue({
      documents: [],
    });

    await listDocuments({ baseUrl: "http://api.test", request });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        baseUrl: "http://api.test",
        path: "/api/v1/documents",
        method: "GET",
      }),
    );
  });

  it("lists chunks with encoded source id and source_type query", async () => {
    const request = vi.fn().mockResolvedValue({ chunks: [] });

    await listDocumentChunks({
      baseUrl: "http://api.test",
      sourceId: "doc:1 with spaces",
      sourceType: "google_drive",
      limit: 10,
      offset: 5,
      request,
    });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/documents/doc%3A1%20with%20spaces/chunks?source_type=google_drive&limit=10&offset=5",
        method: "GET",
        timeoutMs: DOCUMENT_CHUNKS_TIMEOUT_MS,
      }),
    );
  });

  it("propagates ApiError from listDocumentChunks", async () => {
    const request = vi
      .fn()
      .mockRejectedValue(ApiError.generic(404));

    await expect(
      listDocumentChunks({
        baseUrl: "http://api.test",
        sourceId: "missing",
        sourceType: "knowledge_document",
        request,
      }),
    ).rejects.toMatchObject({ name: "ApiError", status: 404 });
  });

  it("uploads with FormData and a long timeout", async () => {
    const request = vi.fn().mockResolvedValue({ source_id: "new" });
    const file = new File(["# hi"], "spec.md", { type: "text/markdown" });

    await uploadDocument({
      baseUrl: "http://api.test",
      file,
      request,
    });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/documents",
        method: "POST",
        timeoutMs: DOCUMENT_MUTATION_TIMEOUT_MS,
      }),
    );
    const body = request.mock.calls[0][0].body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("file")).toBeTruthy();
  });

  it("replaces under the source id path", async () => {
    const request = vi.fn().mockResolvedValue({ source_id: "keep" });
    const file = new File(["# x"], "v2.md");

    await replaceDocument({
      baseUrl: "http://api.test",
      sourceId: "keep",
      file,
      request,
    });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/documents/keep",
        method: "PUT",
        timeoutMs: DOCUMENT_MUTATION_TIMEOUT_MS,
      }),
    );
  });

  it("deletes and propagates ApiError", async () => {
    const request = vi
      .fn()
      .mockRejectedValue(ApiError.generic(500));

    await expect(
      deleteDocument({
        baseUrl: "http://api.test",
        sourceId: "src-1",
        request,
      }),
    ).rejects.toMatchObject({ name: "ApiError", status: 500 });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/documents/src-1",
        method: "DELETE",
      }),
    );
  });

  it("fetches content via encoded /content path with 120s default", async () => {
    const requestBlob = vi.fn().mockResolvedValue({
      blob: new Blob(["hi"]),
      contentType: "text/plain; charset=utf-8",
      fileName: "notes.txt",
    });

    await getDocumentContent({
      baseUrl: "http://api.test",
      sourceId: "a/b",
      requestBlob,
    });

    expect(requestBlob).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/documents/a%2Fb/content",
        method: "GET",
        timeoutMs: DOCUMENT_READ_TIMEOUT_MS,
      }),
    );
    expect(DOCUMENT_READ_TIMEOUT_MS).toBe(120_000);
  });

  it("fetches download via encoded /download path", async () => {
    const requestBlob = vi.fn().mockResolvedValue({
      blob: new Blob(["pdf"]),
      contentType: "application/pdf",
      fileName: "doc.pdf",
    });

    await downloadDocument({
      baseUrl: "http://api.test",
      sourceId: "src-1",
      requestBlob,
    });

    expect(requestBlob).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/documents/src-1/download",
        method: "GET",
        timeoutMs: DOCUMENT_READ_TIMEOUT_MS,
      }),
    );
  });

  it("rejects content problem+json 404 with ApiError detail", async () => {
    const requestBlob = vi
      .fn()
      .mockRejectedValue(
        ApiError.fromProblem({
          type: "https://kernector.dev/problems/document_content_unavailable",
          title: "Document content unavailable",
          status: 404,
          detail: "no stored content for this document",
          code: "document_content_unavailable",
          errors: null,
          instance: null,
          request_id: null,
        }),
      );

    await expect(
      getDocumentContent({
        baseUrl: "http://api.test",
        sourceId: "missing-blob",
        requestBlob,
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      detail: "no stored content for this document",
    });
  });

  it("rejects aborted content requests as ApiError.aborted", async () => {
    const requestBlob = vi.fn().mockRejectedValue(ApiError.aborted());

    await expect(
      downloadDocument({
        baseUrl: "http://api.test",
        sourceId: "src-1",
        requestBlob,
      }),
    ).rejects.toMatchObject({ name: "ApiError", code: "aborted" });
  });

  it("rejects non-problem 5xx without leaking the body", async () => {
    const requestBlob = vi.fn().mockRejectedValue(ApiError.generic(502));

    await expect(
      getDocumentContent({
        baseUrl: "http://api.test",
        sourceId: "src-1",
        requestBlob,
      }),
    ).rejects.toMatchObject({ name: "ApiError", status: 502 });
  });
});
