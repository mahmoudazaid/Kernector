import { describe, expect, it } from "vitest";
import {
  adminMcpBffError,
  isMissingAdminApiToken,
} from "@/lib/server/admin-mcp-bff";

describe("adminMcpBffError", () => {
  it("maps missing ADMIN_API_TOKEN to a 503 misconfiguration problem", async () => {
    const response = adminMcpBffError(
      new Error("ADMIN_API_TOKEN is required and must be non-blank"),
    );
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({
      code: "admin_api_token_missing",
      status: 503,
    });
    expect(
      isMissingAdminApiToken(
        new Error("ADMIN_API_TOKEN is required and must be non-blank"),
      ),
    ).toBe(true);
  });

  it("keeps unauthorized for other failures", async () => {
    const response = adminMcpBffError(new Error("fetch failed"));
    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({
      code: "unauthorized",
      detail: "Authentication is required.",
    });
  });
});
