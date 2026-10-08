import { describe, expect, it, vi } from "vitest";
import {
  createTestDesignDraft,
  exportTestDesignXray,
  getTestDesignXrayStatus,
  TEST_DESIGN_TIMEOUT_MS,
} from "@/lib/api/test-design";

describe("Xray export client", () => {
  it("GETs the draft's Xray status", async () => {
    const request = vi.fn().mockResolvedValue({ available: true });

    await getTestDesignXrayStatus({
      baseUrl: "http://127.0.0.1:8000",
      draftId: "draft 1",
      request,
    });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/test-design/drafts/draft%201/export/xray",
        method: "GET",
      }),
    );
  });

  it("POSTs the expected version and link choice", async () => {
    const request = vi.fn().mockResolvedValue({ created_keys: [] });

    await exportTestDesignXray({
      baseUrl: "http://127.0.0.1:8000",
      draftId: "draft-1",
      body: { expected_version: 3, link_source_issue: false },
      request,
    });

    expect(request).toHaveBeenCalledWith({
      baseUrl: "http://127.0.0.1:8000",
      path: "/api/v1/test-design/drafts/draft-1/export/xray",
      method: "POST",
      body: { expected_version: 3, link_source_issue: false },
      signal: undefined,
      timeoutMs: TEST_DESIGN_TIMEOUT_MS,
    });
  });
});

describe("createTestDesignDraft", () => {
  it("POSTs with a long default timeout so LLM create is not cut off", async () => {
    const request = vi.fn().mockResolvedValue({
      draft_id: "draft-1",
      workspace_id: "local",
      conversation_id: "conv-1",
      source_reference: { source_id: "issue:1", source_type: "github" },
      ticket_identifier: "acme/widgets#1",
      status: "coverage_review",
      candidates: [],
      coverage_gaps: [],
      generated_cases: [],
      skipped_edited_candidate_ids: [],
      version: 1,
      selected_candidate_ids: [],
    });

    await createTestDesignDraft({
      baseUrl: "http://127.0.0.1:8000",
      body: {
        conversation_id: "conv-1",
        source_locator: { provider: "github", locator: "acme/widgets#1" },
      },
      request,
    });

    expect(request).toHaveBeenCalledWith({
      baseUrl: "http://127.0.0.1:8000",
      path: "/api/v1/test-design/drafts",
      method: "POST",
      body: {
        conversation_id: "conv-1",
        source_locator: { provider: "github", locator: "acme/widgets#1" },
      },
      signal: undefined,
      timeoutMs: TEST_DESIGN_TIMEOUT_MS,
    });
    expect(TEST_DESIGN_TIMEOUT_MS).toBeGreaterThanOrEqual(180_000);
  });
});
