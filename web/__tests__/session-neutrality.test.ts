import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const WEB_ROOT = join(__dirname, "..");
const SCAN_ROOTS = [
  join(WEB_ROOT, "lib", "session"),
  join(WEB_ROOT, "lib", "settings", "runtime-settings-storage.ts"),
  join(WEB_ROOT, "lib", "chat", "sanitize.ts"),
];

/**
 * Pack / Story / Compare vocabulary must not appear on the shared session
 * contract. Split camelCase before matching so `storyComparison` is caught
 * (a trailing `\b` after `story` does not fire against the hump).
 */
const FORBIDDEN = [
  /\bstor(y|ies)\b/i,
  /compare/i,
  /gherkin/i,
  /acceptance_criteria/i,
  /packs?\//,
];

/** Documentation may name the rule; strip those phrases before scanning. */
const DOC_WHITELIST = [
  /Story\/Compare/g,
  /Pack \/ Story \/ Compare vocabulary/g,
  /Story vocabulary/g,
  /pack payloads/g,
  /pack-presentation-owned/g,
  /`kernector:pack:…`/g,
  /kernector:pack:…/g,
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

/**
 * Prepare source for vocabulary scanning without naive comment stripping.
 * Comment strippers that ignore string literals can swallow real declarations;
 * whitelist known documentation phrases and scan the remaining raw text.
 */
function prepareForScan(source: string): string {
  let text = source;
  for (const pattern of DOC_WHITELIST) {
    text = text.replace(pattern, " ");
  }
  return text;
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
        const text = splitCamelCase(prepareForScan(readFileSync(file, "utf8")));
        for (const pattern of FORBIDDEN) {
          if (pattern.test(text)) {
            hits.push(`${relative(WEB_ROOT, file)} matches ${pattern}`);
          }
        }
      }
    }
    expect(hits).toEqual([]);
  });

  it("does not treat history as Story vocabulary", () => {
    const sample = splitCamelCase(
      'import { historyForModel } from "@/lib/chat/turn";',
    );
    expect(/\bstor(y|ies)\b/i.test(sample)).toBe(false);
  });
});
