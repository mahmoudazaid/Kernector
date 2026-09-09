import { readFileSync } from "node:fs";
import { relative } from "node:path";
import { describe, expect, it } from "vitest";
import { SCAN_DIRS, WEB_ROOT, walk } from "./support/scan";

const SANCTIONED = "lib/format/timestamp.ts";
const ALLOW_LOCALE_NUMBER = /\/\/\s*allow-locale-number/;

const FORBIDDEN_TIMESTAMPS = [
  /\.toLocaleString\(/,
  /\.toLocaleDateString\(/,
  /\.toLocaleTimeString\(/,
  /Intl\.DateTimeFormat/,
  /["'`]\s*Just now\s*["'`]/i,
  /["'`]\s*Yesterday\s*["'`]/i,
  /\b(min|mins|minute|minutes|hour|hours|day|days)\s+ago\b/i,
];

describe("timestamp format guardrail", () => {
  it("does not use locale-default or relative timestamps outside formatTimestamp", () => {
    const hits: string[] = [];
    for (const root of SCAN_DIRS) {
      for (const file of walk(root)) {
        if (relative(WEB_ROOT, file) === SANCTIONED) {
          continue;
        }
        const lines = readFileSync(file, "utf8").split("\n");
        for (const line of lines) {
          if (ALLOW_LOCALE_NUMBER.test(line)) {
            continue;
          }
          for (const pattern of FORBIDDEN_TIMESTAMPS) {
            if (pattern.test(line)) {
              hits.push(`${relative(WEB_ROOT, file)} matches ${pattern}`);
            }
          }
        }
      }
    }
    expect(hits).toEqual([]);
  });
});
