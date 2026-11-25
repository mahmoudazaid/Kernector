/**
 * Same-origin BFF proxy for auth and preferences (#182).
 * Forwards Cookie / Set-Cookie / X-CSRF-Token only on these routes.
 */

import { apiBaseUrl } from "@/lib/server/api-proxy";

export const AUTH_COOKIE_NAME = "kernector_session";
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
    .replace(/(password|passwd|pwd)\s*[:=]\s*([^\s,;]+)/gi, "$1=[REDACTED]")
    .replace(/(kernector_session)=([^;\s]+)/gi, "$1=[REDACTED]")
    .replace(/(x-csrf-token|csrf_token)\s*[:=]\s*([^\s,;]+)/gi, "$1=[REDACTED]");
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

  const body = await upstream.arrayBuffer();
  return new Response(body, {
    status: upstream.status,
    headers: outHeaders,
  });
}
