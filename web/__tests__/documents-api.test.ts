import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import {
  DOCUMENT_MUTATION_TIMEOUT_MS,
  deleteDocument,
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
      request,
    });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/documents/doc%3A1%20with%20spaces/chunks?source_type=google_drive",
        method: "GET",
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
});
