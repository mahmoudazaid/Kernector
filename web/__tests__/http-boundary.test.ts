import { readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { API_ORIGIN, buildDocumentCsp } from "@/lib/csp";
import { SCAN_DIRS, WEB_ROOT, walk } from "./support/scan";

const CLIENT_SEAM = join(WEB_ROOT, "lib", "api", "client.ts");
const API_DIR = join(WEB_ROOT, "lib", "api");
const NEXT_CONFIG = join(WEB_ROOT, "next.config.ts");
const MIDDLEWARE = join(WEB_ROOT, "middleware.ts");

const FORBIDDEN_TRANSPORT = [
  /\bfetch\s*\(/,
  /\bXMLHttpRequest\b/,
  /\bnew\s+EventSource\b/,
  /\bnew\s+Request\(\s*["'`]https?:\/\//,
  /\.open\(\s*["'`](?:GET|POST|PUT|PATCH|DELETE)["'`]\s*,\s*["'`]https?:\/\//,
  /\bnew\s+EventSource\(\s*["'`]https?:\/\//,
];

const PATH_LITERAL = /\bpath:\s*(["'`])([^"'`]+)\1/g;

describe("http boundary", () => {
  it("keeps a single fetch seam in lib/api/client.ts", () => {
    const hits: string[] = [];
    for (const root of SCAN_DIRS) {
      for (const file of walk(root)) {
        if (file === CLIENT_SEAM) {
          continue;
        }
        const text = readFileSync(file, "utf8");
        for (const pattern of FORBIDDEN_TRANSPORT) {
          if (pattern.test(text)) {
            hits.push(`${relative(WEB_ROOT, file)} matches ${pattern}`);
          }
        }
      }
    }
    expect(hits).toEqual([]);
  });

  it("uses versioned /api/v1 paths under lib/api", () => {
    const hits: string[] = [];
    for (const file of walk(API_DIR)) {
      const text = readFileSync(file, "utf8");
      for (const match of text.matchAll(PATH_LITERAL)) {
        const path = match[2];
        if (path === "/health") {
          continue;
        }
        if (!path.startsWith("/api/v1")) {
          hits.push(`${relative(WEB_ROOT, file)} path ${path}`);
        }
      }
    }
    expect(hits).toEqual([]);
  });

  it("pins the exact CSP policy string including the validated API origin", async () => {
    const expected = [
      "default-src 'self'",
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
      "object-src 'none'",
      "frame-src 'none'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      `connect-src 'self' ${API_ORIGIN}`,
    ].join("; ");

    expect(buildDocumentCsp({ scriptSrc: "'self' 'unsafe-inline'" })).toBe(
      expected,
    );
    expect(expected).not.toContain("*");
    expect(expected).not.toContain(" null");

    const nextConfig = (await import("../next.config")).default;
    const headerEntries = await nextConfig.headers!();
    expect(
      headerEntries.some((entry) =>
        entry.headers.some((header) => header.key === "Content-Security-Policy"),
      ),
    ).toBe(false);

    const referrerSources = headerEntries
      .filter((entry) =>
        entry.headers.some((header) => header.key === "Referrer-Policy"),
      )
      .map((entry) => entry.source);
    expect(referrerSources).toEqual(
      expect.arrayContaining([
        "/_next/static/:path*",
        "/_next/image",
        "/brand/:path*",
      ]),
    );
    expect(referrerSources).not.toContain("/:path*");
  });

  it("ships middleware that nonces script-src and reuses shared CSP builder", () => {
    const text = readFileSync(MIDDLEWARE, "utf8");
    expect(text).toContain('from "@/lib/csp"');
    expect(text).toContain("buildDocumentCsp");
    expect(text).toContain("API_ORIGIN");
    expect(text).toContain("scriptSrc: `'self' 'nonce-${nonce}'`");
    expect(text).toContain('requestHeaders.set("content-security-policy", csp)');
    expect(text).toContain("x-nonce");
    expect(text).toContain("Content-Security-Policy");
    expect(text).toContain("Referrer-Policy");
  });

  it("does not build viewer media URLs by concatenating apiBaseUrl", () => {
    const hits: string[] = [];
    for (const file of [
      join(WEB_ROOT, "components", "documents", "DocumentViewer.tsx"),
      join(WEB_ROOT, "components", "documents", "DocumentsPanel.tsx"),
    ]) {
      const text = readFileSync(file, "utf8");
      if (
        /<(?:a|iframe|embed)\b[^>]*(?:href|src)=\{[^}]*apiBaseUrl/.test(text) ||
        /(?:href|src)=\{[`"'].*\$\{[^}]*apiBaseUrl/.test(text)
      ) {
        hits.push(relative(WEB_ROOT, file));
      }
    }
    expect(hits).toEqual([]);
  });
});
