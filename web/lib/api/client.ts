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

/**
 * Cancellation covers both names: `fetch` rejects with the aborting signal's
 * reason, and `AbortSignal.timeout` aborts with `TimeoutError` — not
 * `AbortError`, which only a caller-supplied `AbortController` produces.
 */
function isCancellation(error: unknown): boolean {
  if (typeof error !== "object" || error === null) {
    return false;
  }
  // Name-based: jsdom's DOMException does not extend Error, and thrown values
  // may cross realms, so `instanceof` is unreliable here.
  const { name } = error as { name?: unknown };
  return name === "AbortError" || name === "TimeoutError";
}

/**
 * Combine the caller signal with the timeout signal.
 *
 * `AbortSignal.any` is unavailable before Safari 17.4 / Firefox 124, so fall
 * back to forwarding whichever signal aborts first.
 */
function combineSignals(
  signal: AbortSignal,
  timeoutSignal: AbortSignal,
): AbortSignal {
  if (typeof AbortSignal.any === "function") {
    return AbortSignal.any([signal, timeoutSignal]);
  }

  const controller = new AbortController();
  for (const source of [signal, timeoutSignal]) {
    if (source.aborted) {
      controller.abort(source.reason);
      return controller.signal;
    }
    source.addEventListener("abort", () => controller.abort(source.reason), {
      once: true,
    });
  }
  return controller.signal;
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
      ? combineSignals(signal, timeoutSignal)
      : timeoutSignal;

  let response: Response;
  try {
    response = await fetchImpl(joinUrl(baseUrl, path), {
      method,
      headers,
      signal: combinedSignal,
    });
  } catch (error) {
    if (isCancellation(error)) {
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

  try {
    return (await response.json()) as T;
  } catch {
    // A malformed success body (proxy error page, truncated stream) must not
    // escape as a SyntaxError — its message embeds a snippet of the body.
    throw ApiError.generic(response.status);
  }
}
