import { readFileSync } from "node:fs";
import { relative } from "node:path";
import { describe, expect, it } from "vitest";
import { SCAN_DIRS, WEB_ROOT, walk } from "./support/scan";

/** Direct infrastructure / provider client seams — not denylist mentions. */
const FORBIDDEN = [
  /from\s+["']chromadb["']/,
  /require\(["']chromadb["']\)/,
  /from\s+["']openai["']/,
  /require\(["']openai["']\)/,
  /api\.openai\.com/,
  /openrouter\.ai/,
  /from\s+["']ollama["']/,
  /require\(["']ollama["']\)/,
  /chroma\.cloud/,
  /from\s+["']googleapis["']/,
  /require\(["']googleapis["']\)/,
  /google-auth-library/,
  /www\.googleapis\.com/,
  /accounts\.google\.com/,
];

describe("frontend isolation", () => {
  it("does not call infrastructure providers from lib or components", () => {
    const hits: string[] = [];
    for (const root of SCAN_DIRS) {
      for (const file of walk(root)) {
        const text = readFileSync(file, "utf8");
        for (const pattern of FORBIDDEN) {
          if (pattern.test(text)) {
            hits.push(`${relative(WEB_ROOT, file)} matches ${pattern}`);
          }
        }
      }
    }
    expect(hits).toEqual([]);
  });
});
