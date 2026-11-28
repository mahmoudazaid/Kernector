/**
 * Same-origin BFF proxy for Hub→FastAPI (#182 / #447 / ADR 0014).
 * Forwards Cookie / Set-Cookie / X-CSRF-Token (and Location) for auth,
 * preferences, and product `/api/v1/*` routes that need the session cookie.
 */

import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { apiBaseUrl } from "@/lib/server/api-proxy";

export { AUTH_COOKIE_NAME };
export const CSRF_HEADER = "X-CSRF-Token";

const NO_STORE = "no-store";

export function browserRequestIsHttps(request: Request): boolean {
  const forwarded = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim();
  if (forwarded) {
    return forwarded.toLowerCase() === "https";
  }
  try {
    return new URL(request.url).protocol === "https:";
  } catch {
    return false;
  }
}

/** Rewrite Set-Cookie Secure from the browser-facing HTTPS determination. */
export function adjustSetCookieForBrowser(
  setCookie: string,
  options: { secure: boolean },
): string {
  const { secure } = options;
  let out = setCookie.replace(/;\s*Secure/gi, "");
  if (secure && !/;\s*Secure/i.test(out)) {
    out = `${out}; Secure`;
  }
  return out;
}

export function redactAuthSecrets(text: string): string {
  return text
    .replace(
      /(["']?(?:password|passwd|pwd)["']?\s*[:=]\s*)(?:"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)'|([^\s,;]+))/gi,
      (_match, prefix: string, dq?: string, sq?: string) => {
        if (dq !== undefined) {
          return `${prefix}"[REDACTED]"`;
        }
        if (sq !== undefined) {
          return `${prefix}'[REDACTED]'`;
        }
        return `${prefix}[REDACTED]`;
      },
    )
    .replace(/(kernector_session)=([^;\s]+)/gi, "$1=[REDACTED]")
    .replace(
      /(["']?(?:x-csrf-token|csrf_token)["']?\s*[:=]\s*)(?:"([^"\\]*(?:\\.[^"\\]*)*)"|'([^'\\]*(?:\\.[^'\\]*)*)'|([^\s,;]+))/gi,
      (_match, prefix: string, dq?: string, sq?: string) => {
        if (dq !== undefined) {
          return `${prefix}"[REDACTED]"`;
        }
        if (sq !== undefined) {
          return `${prefix}'[REDACTED]'`;
        }
        return `${prefix}[REDACTED]`;
      },
    );
}

/** Clear HttpOnly session cookie (stale /me or logout 401). */
export function clearSessionCookieHeader(secure: boolean): string {
  const parts = [
    `${AUTH_COOKIE_NAME}=`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    "Max-Age=0",
  ];
  if (secure) {
    parts.push("Secure");
  }
  return parts.join("; ");
}

export async function proxyAuthApi(
  request: Request,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = `${apiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init.headers);

  const cookie = request.headers.get("cookie");
  if (cookie) {
    headers.set("cookie", cookie);
  }
  const csrf = request.headers.get(CSRF_HEADER);
  if (csrf) {
    headers.set(CSRF_HEADER, csrf);
  }
  const origin = request.headers.get("origin");
  if (origin) {
    headers.set("origin", origin);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const upstream = await fetch(url, {
    ...init,
    headers,
    cache: "no-store",
    redirect: "manual",
  });

  const secure = browserRequestIsHttps(request);
  const outHeaders = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType) {
    outHeaders.set("Content-Type", contentType);
  }
  const location = upstream.headers.get("location");
  if (location) {
    outHeaders.set("Location", location);
  }
  outHeaders.set("Cache-Control", NO_STORE);

  const getSetCookie = (
    upstream.headers as Headers & { getSetCookie?: () => string[] }
  ).getSetCookie?.();
  if (getSetCookie && getSetCookie.length > 0) {
    for (const raw of getSetCookie) {
      outHeaders.append(
        "Set-Cookie",
        adjustSetCookieForBrowser(raw, { secure }),
      );
    }
  } else {
    const single = upstream.headers.get("set-cookie");
    if (single) {
      outHeaders.set(
        "Set-Cookie",
        adjustSetCookieForBrowser(single, { secure }),
      );
    }
  }

  const status = upstream.status;
  // Stale cookies must be cleared so middleware/AuthGate cannot lock /login.
  if (
    status === 401 &&
    (path === "/api/v1/auth/me" || path === "/api/v1/auth/logout")
  ) {
    outHeaders.append("Set-Cookie", clearSessionCookieHeader(secure));
  }
  // 204/205/304 must not carry a body — even an empty ArrayBuffer throws.
  const nullBody = status === 204 || status === 205 || status === 304;
  const body = nullBody ? null : await upstream.arrayBuffer();
  return new Response(body, {
    status,
    headers: outHeaders,
  });
}
