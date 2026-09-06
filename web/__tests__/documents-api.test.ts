import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import {
  DOCUMENT_MUTATION_TIMEOUT_MS,
  deleteDocument,
  listDocuments,
  replaceDocument,
  uploadDocument,
} from "@/lib/api/documents";

describe("documents api wrappers", () => {
  it("lists documents via GET /api/v1/documents", async () => {
    const request = vi.fn().mockResolvedValue({
      documents: [],
      constraints: { supported_suffixes: [".md"], max_upload_bytes: 10 },
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
