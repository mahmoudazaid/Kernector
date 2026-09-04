import type { components } from "@/lib/api/generated/schema";

type Problem = components["schemas"]["Problem"];
type ProblemError = components["schemas"]["ProblemError"];

const SAFE_GENERIC_DETAIL = "The request failed. Please try again later.";

/**
 * Normalized RFC 9457 Problem Details for UI and callers.
 *
 * Fields are taken from the generated OpenAPI ``Problem`` schema; raw HTTP
 * bodies and stack traces are never retained.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string;
  readonly code: string;
  readonly requestId: string | null;
  readonly errors: ProblemError[] | null;

  constructor(problem: {
    status: number;
    title: string;
    detail: string;
    code: string;
    requestId?: string | null;
    errors?: ProblemError[] | null;
  }) {
    super(problem.detail);
    this.name = "ApiError";
    this.status = problem.status;
    this.title = problem.title;
    this.detail = problem.detail;
    this.code = problem.code;
    this.requestId = problem.requestId ?? null;
    this.errors = problem.errors ?? null;
  }

  static fromProblem(problem: Problem): ApiError {
    return new ApiError({
      status: problem.status,
      title: problem.title,
      detail: problem.detail,
      code: problem.code,
      requestId: problem.request_id ?? null,
      errors: problem.errors ?? null,
    });
  }

  static generic(status: number): ApiError {
    return new ApiError({
      status,
      title: "Request failed",
      detail: SAFE_GENERIC_DETAIL,
      code: "request_failed",
    });
  }

  static aborted(): ApiError {
    return new ApiError({
      status: 0,
      title: "Request aborted",
      detail: "The request was cancelled or timed out.",
      code: "aborted",
    });
  }
}

export function isProblemPayload(value: unknown): value is Problem {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.status === "number" &&
    typeof candidate.title === "string" &&
    typeof candidate.detail === "string" &&
    typeof candidate.code === "string" &&
    typeof candidate.type === "string"
  );
}
