import { describe, expect, it, vi } from "vitest";
import {
  disconnectGitHub,
  getGitHubStatus,
  githubOAuthStartUrl,
  syncGitHub,
} from "@/lib/api/connectors";
import { apiRequest } from "@/lib/api/client";

describe("GitHub connectors API client", () => {
  it("builds the OAuth start URL without a trailing slash duplicate", () => {
    expect(githubOAuthStartUrl("http://localhost:8000/")).toBe(
      "http://localhost:8000/api/v1/connectors/github/oauth/start",
    );
  });

  it("GETs connector status", async () => {
    const request = vi.fn().mockResolvedValue({
      configured: true,
      available: true,
      connected: false,
      oauth_ready: true,
      account_login: null,
      document_count: 0,
      owner: null,
      repo: null,
      last_sync: null,
      reauthorization_required: false,
      connection_state: "disconnected",
    });
    await getGitHubStatus({ baseUrl: "http://api", request });
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/api/v1/connectors/github",
        method: "GET",
      }),
    );
  });

  it("POSTs sync and DELETEs disconnect", async () => {
    const request = vi.fn().mockResolvedValue({
      ingested_count: 0,
      updated_count: 0,
      skipped_count: 0,
      failed_count: 0,
      removed_count: 0,
      outcomes: [],
    });
    await syncGitHub({ baseUrl: "http://api", request });
    await disconnectGitHub({ baseUrl: "http://api", request });
    expect(request).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        path: "/api/v1/connectors/github/sync",
        method: "POST",
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        path: "/api/v1/connectors/github",
        method: "DELETE",
      }),
    );
  });

  it("never imports a token-bearing helper for the browser client", () => {
    expect(typeof apiRequest).toBe("function");
    expect(githubOAuthStartUrl("http://api")).not.toContain("token");
  });
});
