import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const TOKENS_PATH = path.resolve(__dirname, "../styles/tokens.css");

const COLOR_TOKENS = [
  "--kern-bg",
  "--kern-surface",
  "--kern-surface-2",
  "--kern-ink",
  "--kern-muted",
  "--kern-line",
  "--kern-accent",
  "--kern-accent-soft",
  "--kern-focus",
  "--kern-danger",
  "--kern-control-highlight",
  "--kern-control-shade",
  "--kern-control-sheen",
  "--kern-control-sheen-fill",
] as const;

const ROOT_TOKENS = [
  ...COLOR_TOKENS,
  "--kern-radius",
  "--kern-radius-sm",
  "--kern-radius-pill",
  "--kern-sidebar-width",
  "--kern-font-sans",
  "--kern-font-mono",
  "--kern-text-xs",
  "--kern-text-sm",
  "--kern-text-md",
  "--kern-text-lg",
  "--kern-text-xl",
  "--kern-space-1",
  "--kern-space-2",
  "--kern-space-3",
  "--kern-space-4",
  "--kern-space-5",
  "--kern-space-6",
  "--kern-space-7",
  "--kern-shadow-1",
  "--kern-shadow-2",
  "--kern-icon-sm",
  "--kern-icon-md",
  "--kern-duration",
  "--kern-duration-emphasis",
  "--kern-ease",
  "--kern-ease-out",
  "--kern-control-emboss",
  "--kern-control-emboss-press",
] as const;

function extractBlock(css: string, selector: string): string {
  const marker = `${selector} {`;
  const start = css.indexOf(marker);
  expect(start, `missing selector ${selector}`).toBeGreaterThanOrEqual(0);

  let depth = 0;
  let i = start + marker.length - 1;
  for (; i < css.length; i += 1) {
    const ch = css[i];
    if (ch === "{") depth += 1;
    if (ch === "}") {
      depth -= 1;
      if (depth === 0) {
        return css.slice(start + marker.length, i);
      }
    }
  }

  throw new Error(`unclosed block for ${selector}`);
}

function declaredCustomProperties(block: string): Set<string> {
  const names = new Set<string>();
  for (const match of block.matchAll(/(--kern-[\w-]+)\s*:/g)) {
    names.add(match[1]);
  }
  return names;
}

describe("design token contract", () => {
  const css = readFileSync(TOKENS_PATH, "utf8");

  it("declares the required semantic tokens on :root", () => {
    const rootProps = declaredCustomProperties(extractBlock(css, ":root"));

    for (const token of ROOT_TOKENS) {
      expect(rootProps.has(token), `missing :root token ${token}`).toBe(true);
    }
  });

  it("overrides color tokens for explicit light and dark themes", () => {
    const lightProps = declaredCustomProperties(
      extractBlock(css, ':root[data-theme="light"]'),
    );
    const darkProps = declaredCustomProperties(
      extractBlock(css, ':root[data-theme="dark"]'),
    );

    for (const token of COLOR_TOKENS) {
      expect(lightProps.has(token), `missing light token ${token}`).toBe(true);
      expect(darkProps.has(token), `missing dark token ${token}`).toBe(true);
    }
  });
});
