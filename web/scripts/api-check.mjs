#!/usr/bin/env node
/**
 * Local OpenAPI contract-drift check for #127 (CI wiring is #128).
 *
 * Regenerates OpenAPI + TypeScript types into a temp directory using the exact
 * pipeline from `scripts/api-generate.mjs`, then diffs against the committed
 * artifacts. Exit 1 on mismatch.
 */

import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  COMMITTED_SPEC,
  COMMITTED_TYPES,
  fail,
  generate,
} from "./api-generate.mjs";

function digest(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

if (!existsSync(COMMITTED_SPEC) || !existsSync(COMMITTED_TYPES)) {
  fail(
    "Committed OpenAPI artifacts are missing. Run `npm run api:generate` first.",
  );
}

const tempRoot = mkdtempSync(join(tmpdir(), "kernector-api-check-"));
const tempSpec = join(tempRoot, "openapi", "openapi.json");
const tempTypes = join(tempRoot, "generated", "schema.d.ts");

try {
  generate({ specPath: tempSpec, typesPath: tempTypes });

  const specMatch = digest(COMMITTED_SPEC) === digest(tempSpec);
  const typesMatch = digest(COMMITTED_TYPES) === digest(tempTypes);

  if (!specMatch || !typesMatch) {
    fail(
      [
        "OpenAPI contract drift detected.",
        !specMatch ? `- ${COMMITTED_SPEC} is stale` : null,
        !typesMatch ? `- ${COMMITTED_TYPES} is stale` : null,
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
