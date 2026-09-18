import { describe, expect, it, vi } from "vitest";
import {
  createTestDesignDraft,
  TEST_DESIGN_TIMEOUT_MS,
} from "@/lib/api/test-design";

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
