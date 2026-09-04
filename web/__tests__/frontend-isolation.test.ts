import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const WEB_ROOT = join(__dirname, "..");
const SCAN_DIRS = [join(WEB_ROOT, "lib"), join(WEB_ROOT, "components")];

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
];

function walk(dir: string): string[] {
  const entries = readdirSync(dir);
  const files: string[] = [];
  for (const entry of entries) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      if (entry === "generated" || entry === "node_modules") {
        continue;
      }
      files.push(...walk(full));
      continue;
    }
    if (/\.(ts|tsx|js|jsx|mjs|cjs)$/.test(entry)) {
      files.push(full);
    }
  }
  return files;
}

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
