#!/usr/bin/env node
/**
 * Local OpenAPI contract-drift check for #127 (CI wiring is #128).
 *
 * Regenerates OpenAPI + TypeScript types into a temp directory and diffs them
 * against the committed artifacts. Exit 1 on mismatch.
 */

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = join(webRoot, "..");

const committedSpec = join(webRoot, "openapi", "openapi.json");
const committedTypes = join(webRoot, "lib", "api", "generated", "schema.d.ts");

function fail(message) {
  console.error(message);
  process.exit(1);
}

function digest(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function run(command, args, options = {}) {
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

if (!existsSync(committedSpec) || !existsSync(committedTypes)) {
  fail(
    "Committed OpenAPI artifacts are missing. Run `npm run api:generate` first.",
  );
}

const uvCheck = spawnSync("uv", ["--version"], { encoding: "utf8" });
if (uvCheck.error || uvCheck.status !== 0) {
  fail(
    "`uv` is required for `npm run api:check` (Python OpenAPI export). Install uv and retry.",
  );
}

const tempRoot = mkdtempSync(join(tmpdir(), "kernector-api-check-"));
const tempOpenapiDir = join(tempRoot, "openapi");
const tempGeneratedDir = join(tempRoot, "generated");
mkdirSync(tempOpenapiDir, { recursive: true });
mkdirSync(tempGeneratedDir, { recursive: true });

const tempSpec = join(tempOpenapiDir, "openapi.json");
const tempTypes = join(tempGeneratedDir, "schema.d.ts");

try {
  run(
    "uv",
    [
      "run",
      "python",
      "-c",
      [
        "from pathlib import Path",
        "from presentation.cli.export_openapi import main",
        `raise SystemExit(main(output_path=Path(${JSON.stringify(tempSpec)})))`,
      ].join("; "),
    ],
    { cwd: repoRoot },
  );

  run("npx", ["openapi-typescript", tempSpec, "-o", tempTypes], {
    cwd: webRoot,
  });
  run("npx", ["prettier", "--write", tempSpec, tempTypes], { cwd: webRoot });

  const specMatch = digest(committedSpec) === digest(tempSpec);
  const typesMatch = digest(committedTypes) === digest(tempTypes);

  if (!specMatch || !typesMatch) {
    fail(
      [
        "OpenAPI contract drift detected.",
        !specMatch ? `- ${committedSpec} is stale` : null,
        !typesMatch ? `- ${committedTypes} is stale` : null,
        "Run `npm run api:generate` and commit the updated artifacts.",
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }

  console.log("OpenAPI contract artifacts are up to date.");
} finally {
  rmSync(tempRoot, { recursive: true, force: true });
}
