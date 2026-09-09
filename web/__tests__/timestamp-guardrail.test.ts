import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const WEB_ROOT = join(__dirname, "..");
const SCAN_DIRS = [join(WEB_ROOT, "lib"), join(WEB_ROOT, "components")];
const SANCTIONED = "lib/format/timestamp.ts";

const FORBIDDEN_TIMESTAMPS = [
  /\.toLocaleString\(/,
  /\.toLocaleDateString\(/,
  /\.toLocaleTimeString\(/,
  /Intl\.DateTimeFormat/,
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

describe("timestamp format guardrail", () => {
  it("does not use locale-default date formatters outside formatTimestamp", () => {
    const hits: string[] = [];
    for (const root of SCAN_DIRS) {
      for (const file of walk(root)) {
        if (relative(WEB_ROOT, file) === SANCTIONED) {
          continue;
        }
        const text = readFileSync(file, "utf8");
        for (const pattern of FORBIDDEN_TIMESTAMPS) {
          if (pattern.test(text)) {
            hits.push(`${relative(WEB_ROOT, file)} matches ${pattern}`);
          }
        }
      }
    }
    expect(hits).toEqual([]);
  });
});
