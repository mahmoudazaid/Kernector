import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";

export const WEB_ROOT = join(__dirname, "..", "..");
export const SCAN_DIRS = [join(WEB_ROOT, "lib"), join(WEB_ROOT, "components")];

export function walk(dir: string): string[] {
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
