import { afterEach, describe, expect, it, vi } from "vitest";
import {
  adjustSetCookieForBrowser,
  browserRequestIsHttps,
  proxyAuthApi,
  redactAuthSecrets,
} from "@/lib/server/auth-proxy";

describe("auth-proxy", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("redacts passwords, session cookies, and CSRF tokens", () => {
    const redacted = redactAuthSecrets(
      'password=super-secret {"password": "hunter2", "csrf_token": "abc"} kernector_session=opaque-session-id X-CSRF-Token: csrf-val',
    );
    expect(redacted).not.toContain("super-secret");
    expect(redacted).not.toContain("hunter2");
    expect(redacted).not.toContain("opaque-session-id");
    expect(redacted).not.toContain("csrf-val");
    expect(redacted).not.toContain('"abc"');
    expect(redacted).toContain("[REDACTED]");
  });

  it("sets Secure from x-forwarded-proto or https URL", () => {
    const httpsReq = new Request("http://localhost/api", {
      headers: { "x-forwarded-proto": "https" },
    });
    expect(browserRequestIsHttps(httpsReq)).toBe(true);
    const httpReq = new Request("http://localhost/api");
    expect(browserRequestIsHttps(httpReq)).toBe(false);
    const secureUrl = new Request("https://example.com/api");
    expect(browserRequestIsHttps(secureUrl)).toBe(true);
  });

  it("preserves cookie attributes and toggles Secure", () => {
    const raw =
      "kernector_session=abc; HttpOnly; Path=/; SameSite=Lax; Max-Age=3600";
    const secure = adjustSetCookieForBrowser(raw, { secure: true });
    expect(secure).toContain("HttpOnly");
    expect(secure).toContain("SameSite=Lax");
    expect(secure).toContain("Path=/");
    expect(secure).toMatch(/Secure/i);
    const clear = adjustSetCookieForBrowser(`${raw}; Secure`, {
      secure: false,
    });
    expect(clear).not.toMatch(/;\s*Secure/i);
  });

  it("proxies 204 logout with null body and Set-Cookie", async () => {
    const clearCookie =
      "kernector_session=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        const headers = new Headers({
          "cache-control": "no-store",
        });
        headers.append("set-cookie", clearCookie);
        return new Response(null, { status: 204, headers });
      }),
    );

    const response = await proxyAuthApi(
      new Request("http://localhost:3000/api/v1/auth/logout", {
        method: "POST",
      }),
      "/api/v1/auth/logout",
      { method: "POST" },
    );

    expect(response.status).toBe(204);
    expect(response.headers.get("set-cookie")).toContain("kernector_session=");
    expect(await response.text()).toBe("");
  });

  it("clears the session cookie on /me 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(JSON.stringify({ detail: "Authentication is required." }), {
          status: 401,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    const response = await proxyAuthApi(
      new Request("http://localhost:3000/api/v1/auth/me"),
      "/api/v1/auth/me",
      { method: "GET" },
    );

    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toMatch(
      /kernector_session=.*Max-Age=0/i,
    );
  });
});
