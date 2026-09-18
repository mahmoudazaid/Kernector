import { ApiError, isProblemPayload } from "@/lib/api/errors";

export { ApiError } from "@/lib/api/errors";

export type ApiRequestOptions = {
  baseUrl: string;
  path: string;
  method?: string;
  /**
   * Request body. Plain objects are JSON-encoded with
   * ``Content-Type: application/json``. ``FormData`` / ``Blob`` / ``string``
   * pass through as ``BodyInit`` — never set ``Content-Type`` for ``FormData``
   * so the browser can attach the multipart boundary.
   */
  body?: BodyInit | Record<string, unknown>;
  signal?: AbortSignal;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  headers?: HeadersInit;
};

export type ApiBlobResult = {
  blob: Blob;
  contentType: string | null;
  fileName: string | null;
};

const DEFAULT_TIMEOUT_MS = 10_000;

function joinUrl(baseUrl: string, path: string): string {
  const base = baseUrl.replace(/\/+$/, "");
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${base}${suffix}`;
}

/**
 * Cancellation covers both names: `fetch` rejects with the aborting signal's
 * reason. Our timeout path aborts with `TimeoutError`; a caller-supplied
 * `AbortController` produces `AbortError`.
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
 * Build a request signal that aborts when ``timeoutMs`` elapses and/or when
 * the caller signal aborts.
 *
 * Prefer ``AbortController`` + ``setTimeout`` over ``AbortSignal.timeout``:
 * the timer is cleared when the request finishes, and the abort reason is a
 * stable ``TimeoutError`` across Chromium/Safari/Firefox.
 *
 * ``AbortSignal.any`` is unavailable before Safari 17.4 / Firefox 124, so the
 * caller-signal path always forwards via the same controller.
 */
function createRequestSignal(
  timeoutMs: number,
  signal?: AbortSignal,
): { signal: AbortSignal; clear: () => void } {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;

  const abortFromCaller = () => {
    if (!controller.signal.aborted) {
      controller.abort(signal?.reason);
    }
  };

  if (signal !== undefined) {
    if (signal.aborted) {
      abortFromCaller();
      return { signal: controller.signal, clear: () => undefined };
    }
    signal.addEventListener("abort", abortFromCaller, { once: true });
  }

  if (timeoutMs > 0) {
    timer = setTimeout(() => {
      if (!controller.signal.aborted) {
        const reason =
          typeof DOMException === "function"
            ? new DOMException("The operation was aborted due to timeout", "TimeoutError")
            : new Error("The operation was aborted due to timeout");
        if (reason && !(reason instanceof DOMException)) {
          (reason as Error & { name: string }).name = "TimeoutError";
        }
        controller.abort(reason);
      }
    }, timeoutMs);
  }

  return {
    signal: controller.signal,
    clear: () => {
      if (timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
      }
      if (signal !== undefined) {
        signal.removeEventListener("abort", abortFromCaller);
      }
    },
  };
}

function parseContentDispositionFileName(
  header: string | null,
): string | null {
  if (!header) {
    return null;
  }
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1].trim());
    } catch {
      return utf8[1].trim();
    }
  }
  const quoted = /filename="((?:\\.|[^"\\])*)"/i.exec(header);
  if (quoted?.[1]) {
    return quoted[1].replace(/\\(.)/g, "$1");
  }
  const plain = /filename=([^;]+)/i.exec(header);
  return plain?.[1]?.trim().replace(/^["']|["']$/g, "") ?? null;
}

/**
 * Shared fetch seam: URL join, timeout/cancel, problem+json → ApiError.
 * On success, the timeout/caller signal stays live until the caller finishes
 * reading the body (``clear``); clearing after headers alone would leave
 * ``response.json()`` / ``.blob()`` uncovered.
 */
async function apiRequestResponse(
  options: ApiRequestOptions,
): Promise<{ response: Response; clear: () => void }> {
  const {
    baseUrl,
    path,
    method = "GET",
    body,
    signal,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    fetchImpl = fetch,
    headers,
  } = options;

  // Coerce invalid / missing values to the default so long-running callers
  // (chat ask, test-design create) never silently fall through to a short
  // AbortSignal window. ``timeoutMs: 0`` means no timeout.
  const effectiveTimeoutMs =
    typeof timeoutMs === "number" && Number.isFinite(timeoutMs) && timeoutMs >= 0
      ? timeoutMs
      : DEFAULT_TIMEOUT_MS;
  const requestSignal = createRequestSignal(effectiveTimeoutMs, signal);

  const requestHeaders = new Headers(headers);
  let requestBody: BodyInit | undefined;
  if (body !== undefined) {
    if (
      typeof body === "string" ||
      body instanceof FormData ||
      body instanceof Blob ||
      body instanceof ArrayBuffer ||
      ArrayBuffer.isView(body)
    ) {
      requestBody = body as BodyInit;
      // FormData must keep Content-Type unset so the boundary is set by fetch.
    } else if (body instanceof URLSearchParams) {
      requestBody = body;
      if (!requestHeaders.has("Content-Type")) {
        requestHeaders.set(
          "Content-Type",
          "application/x-www-form-urlencoded;charset=UTF-8",
        );
      }
    } else {
      requestBody = JSON.stringify(body);
      if (!requestHeaders.has("Content-Type")) {
        requestHeaders.set("Content-Type", "application/json");
      }
    }
  }

  let response: Response;
  try {
    response = await fetchImpl(joinUrl(baseUrl, path), {
      method,
      headers: requestHeaders,
      body: requestBody,
      signal: requestSignal.signal,
    });
  } catch (error) {
    requestSignal.clear();
    if (isCancellation(error)) {
      throw ApiError.aborted();
    }
    throw ApiError.generic(0);
  }

  const contentType = response.headers.get("content-type") ?? "";
  const isProblem = contentType.includes("application/problem+json");

  if (!response.ok) {
    try {
      if (isProblem) {
        let payload: unknown;
        try {
          payload = await response.json();
        } catch (error) {
          if (isCancellation(error)) {
            throw ApiError.aborted();
          }
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
    } finally {
      requestSignal.clear();
    }
  }

  return { response, clear: requestSignal.clear };
}

/**
 * Perform an HTTP request against the Kernector API base URL.
 *
 * Success responses are parsed as JSON. Problem Details and other failures
 * become {@link ApiError} without retaining raw bodies or stack traces.
 */
export async function apiRequest<T>(options: ApiRequestOptions): Promise<T> {
  const { response, clear } = await apiRequestResponse(options);
  try {
    if (response.status === 204) {
      return undefined as T;
    }

    try {
      return (await response.json()) as T;
    } catch (error) {
      if (isCancellation(error)) {
        throw ApiError.aborted();
      }
      // A malformed success body (proxy error page, truncated stream) must not
      // escape as a SyntaxError — its message embeds a snippet of the body.
      throw ApiError.generic(response.status);
    }
  } finally {
    clear();
  }
}

/**
 * Perform an HTTP request and return the success body as a Blob.
 *
 * Shares the same fetch seam as {@link apiRequest} (timeouts, cancellation,
 * problem+json mapping). Never surfaces raw error bodies.
 */
export async function apiRequestBlob(
  options: ApiRequestOptions,
): Promise<ApiBlobResult> {
  const { response, clear } = await apiRequestResponse(options);
  try {
    try {
      const blob = await response.blob();
      return {
        blob,
        contentType: response.headers.get("content-type"),
        fileName: parseContentDispositionFileName(
          response.headers.get("content-disposition"),
        ),
      };
    } catch (error) {
      if (isCancellation(error)) {
        throw ApiError.aborted();
      }
      throw ApiError.generic(response.status);
    }
  } finally {
    clear();
  }
}
