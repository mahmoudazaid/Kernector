import { describe, expect, it } from "vitest";
import {
  adjustSetCookieForBrowser,
  browserRequestIsHttps,
  redactAuthSecrets,
} from "@/lib/server/auth-proxy";

describe("auth-proxy", () => {
  it("redacts passwords, session cookies, and CSRF tokens", () => {
    const redacted = redactAuthSecrets(
      "password=super-secret kernector_session=opaque-session-id X-CSRF-Token: csrf-val",
    );
    expect(redacted).not.toContain("super-secret");
    expect(redacted).not.toContain("opaque-session-id");
    expect(redacted).not.toContain("csrf-val");
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
});
