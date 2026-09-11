import { readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { buildDocumentCsp } from "../next.config";
import { loadPublicEnv } from "@/lib/env";
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

  it("pins the exact CSP policy string including the validated API origin", () => {
    const apiOrigin = new URL(
      loadPublicEnv().NEXT_PUBLIC_API_BASE_URL,
    ).origin;
    const expected = [
      "default-src 'self'",
      "base-uri 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
      "object-src 'none'",
      "frame-src 'self' blob:",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      `connect-src 'self' ${apiOrigin}`,
    ].join("; ");

    expect(buildDocumentCsp(apiOrigin)).toBe(expected);
    expect(expected).not.toContain("*");
    expect(expected).not.toContain(" null");

    const configText = readFileSync(NEXT_CONFIG, "utf8");
    expect(configText).toContain("buildDocumentCsp");
    expect(configText).toContain("loadPublicEnv");
    expect(configText).toContain("X-Content-Type-Options");
    expect(configText).toContain("nosniff");
    expect(configText).toContain("Referrer-Policy");
  });

  it("ships middleware that nonces script-src and reuses env validation", () => {
    const text = readFileSync(MIDDLEWARE, "utf8");
    expect(text).toContain("loadPublicEnv");
    expect(text).toContain("script-src 'self' 'nonce-${nonce}'");
    expect(text).toContain("base-uri 'self'");
    expect(text).toContain("form-action 'self'");
    expect(text).toContain("frame-ancestors 'none'");
    expect(text).toContain("x-nonce");
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
