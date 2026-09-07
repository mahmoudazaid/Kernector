import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const WEB_ROOT = join(__dirname, "..");
const SCAN_ROOTS = [
  join(WEB_ROOT, "lib", "session"),
  join(WEB_ROOT, "lib", "runtime-settings-storage.ts"),
];

/**
 * Pack / Story / Compare vocabulary must not appear on the shared session
 * contract. Split camelCase before matching so `storyComparison` is caught
 * (a trailing `\b` after `story` does not fire against the hump).
 */
const FORBIDDEN = [
  /story/i,
  /compare/i,
  /gherkin/i,
  /acceptance_criteria/i,
  /packs?\//,
];

function walk(target: string): string[] {
  const stat = statSync(target);
  if (stat.isFile()) {
    return /\.(ts|tsx)$/.test(target) ? [target] : [];
  }
  const files: string[] = [];
  for (const entry of readdirSync(target)) {
    const full = join(target, entry);
    const entryStat = statSync(full);
    if (entryStat.isDirectory()) {
      files.push(...walk(full));
      continue;
    }
    if (/\.(ts|tsx)$/.test(entry)) {
      files.push(full);
    }
  }
  return files;
}

/** Strip line/block comments so the file can document its own rule. */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

/** Insert spaces at camelCase boundaries: storyComparison → story Comparison. */
function splitCamelCase(source: string): string {
  return source.replace(/([a-z0-9])([A-Z])/g, "$1 $2");
}

describe("active session pack neutrality", () => {
  it("carries no Story/Compare-named field and imports no pack-named module", () => {
    const hits: string[] = [];
    for (const root of SCAN_ROOTS) {
      for (const file of walk(root)) {
        const text = splitCamelCase(stripComments(readFileSync(file, "utf8")));
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
