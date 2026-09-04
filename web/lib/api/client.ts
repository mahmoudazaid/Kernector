import { ApiError, isProblemPayload } from "@/lib/api/errors";

export { ApiError } from "@/lib/api/errors";

export type ApiRequestOptions = {
  baseUrl: string;
  path: string;
  method?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  headers?: HeadersInit;
};

const DEFAULT_TIMEOUT_MS = 10_000;

function joinUrl(baseUrl: string, path: string): string {
  const base = baseUrl.replace(/\/+$/, "");
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${base}${suffix}`;
}

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

/**
 * Perform an HTTP request against the Kernector API base URL.
 *
 * Success responses are parsed as JSON. Problem Details and other failures
 * become {@link ApiError} without retaining raw bodies or stack traces.
 */
export async function apiRequest<T>(options: ApiRequestOptions): Promise<T> {
  const {
    baseUrl,
    path,
    method = "GET",
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    fetchImpl = fetch,
    headers,
  } = options;

  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const combinedSignal =
    signal !== undefined
      ? AbortSignal.any([signal, timeoutSignal])
      : timeoutSignal;

  let response: Response;
  try {
    response = await fetchImpl(joinUrl(baseUrl, path), {
      method,
      headers,
      signal: combinedSignal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw ApiError.aborted();
    }
    throw ApiError.generic(0);
  }

  const contentType = response.headers.get("content-type") ?? "";
  const isProblem = contentType.includes("application/problem+json");

  if (!response.ok) {
    if (isProblem) {
      let payload: unknown;
      try {
        payload = await response.json();
      } catch {
        throw ApiError.generic(response.status);
      }
      if (isProblemPayload(payload)) {
        throw ApiError.fromProblem(payload);
      }
      throw ApiError.generic(response.status);
    }
    // Drain body so the connection can close; never surface the text.
    await response.text().catch(() => undefined);
    throw ApiError.generic(response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
