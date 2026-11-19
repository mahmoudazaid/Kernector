/**
 * Shared Admin MCP BFF error responses (#324).
 * Distinguishes missing server config from upstream auth failures.
 */

import { NextResponse } from "next/server";

const PROBLEM_JSON = { "Content-Type": "application/problem+json" } as const;

export function isMissingAdminApiToken(error: unknown): boolean {
  return (
    error instanceof Error &&
    error.message.includes("ADMIN_API_TOKEN is required")
  );
}

/** Problem+JSON for Admin MCP BFF route catch blocks. */
export function adminMcpBffError(error: unknown): NextResponse {
  if (isMissingAdminApiToken(error)) {
    return NextResponse.json(
      {
        type: "https://kernector.dev/problems/misconfigured",
        title: "Misconfigured",
        status: 503,
        detail:
          "ADMIN_API_TOKEN is not set for the Next.js server. Set it in the repo-root .env (or web/.env.local) and restart npm run dev.",
        code: "admin_api_token_missing",
      },
      { status: 503, headers: PROBLEM_JSON },
    );
  }
  return NextResponse.json(
    {
      type: "https://kernector.dev/problems/unauthorized",
      title: "Unauthorized",
      status: 401,
      detail: "Authentication is required.",
      code: "unauthorized",
    },
    { status: 401, headers: PROBLEM_JSON },
  );
}
