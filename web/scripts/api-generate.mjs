#!/usr/bin/env node
/**
 * OpenAPI -> TypeScript generation for #127.
 *
 * Single source of truth for the pipeline: `npm run api:generate` writes the
 * committed artifacts, and `scripts/api-check.mjs` runs the same steps into a
 * temp directory to detect drift. Keeping one implementation means the two
 * sides of the drift diff can never be generated differently.
 */

import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const WEB_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const REPO_ROOT = join(WEB_ROOT, "..");

/**
 * Prettier resolves config from the *file's* path, not the cwd. The temp
 * copies the drift check writes live outside the repo, so the config must be
 * passed explicitly or they would be formatted with Prettier's defaults while
 * the committed artifacts use this project's settings.
 */
export const PRETTIER_CONFIG = join(WEB_ROOT, ".prettierrc.json");

export const COMMITTED_SPEC = join(WEB_ROOT, "openapi", "openapi.json");
export const COMMITTED_TYPES = join(
  WEB_ROOT,
  "lib",
  "api",
  "generated",
  "schema.d.ts",
);

export function fail(message) {
  console.error(message);
  process.exit(1);
}

export function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    ...options,
  });
  if (result.error) {
    fail(`${command} failed to start: ${result.error.message}`);
  }
  if (result.status !== 0) {
    fail(
      `${command} ${args.join(" ")} exited ${result.status}\n${result.stderr || result.stdout}`,
    );
  }
  return result;
}

export function requireUv() {
  const probe = spawnSync("uv", ["--version"], { encoding: "utf8" });
  if (probe.error || probe.status !== 0) {
    fail(
      "`uv` is required to export the Python OpenAPI document. Install uv and retry.",
    );
  }
}

/**
 * Export OpenAPI from FastAPI, generate types, and format both artifacts.
 *
 * `--no-install` keeps the run hermetic: without it npx would silently fetch a
 * package from the registry when node_modules is stale, defeating the pinned
 * `openapi-typescript` version and producing spurious drift.
 */
export function generate({ specPath, typesPath }) {
  requireUv();
  mkdirSync(dirname(specPath), { recursive: true });
  mkdirSync(dirname(typesPath), { recursive: true });

  run(
    "uv",
    [
      "run",
      "python",
      "-m",
      "presentation.cli.export_openapi",
      "--output",
      specPath,
    ],
    { cwd: REPO_ROOT },
  );

  run(
    "npx",
    ["--no-install", "openapi-typescript", specPath, "-o", typesPath],
    {
      cwd: WEB_ROOT,
    },
  );

  run(
    "npx",
    [
      "--no-install",
      "prettier",
      "--config",
      PRETTIER_CONFIG,
      "--write",
      specPath,
      typesPath,
    ],
    { cwd: WEB_ROOT },
  );
}

const invokedDirectly =
  process.argv[1] !== undefined &&
  fileURLToPath(import.meta.url) === process.argv[1];

if (invokedDirectly) {
  generate({ specPath: COMMITTED_SPEC, typesPath: COMMITTED_TYPES });
  console.log(`wrote ${COMMITTED_SPEC}`);
  console.log(`wrote ${COMMITTED_TYPES}`);
}
