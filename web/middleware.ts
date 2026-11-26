import { NextResponse, type NextRequest } from "next/server";
import { AUTH_COOKIE_NAME } from "@/lib/auth/constants";
import { API_ORIGIN, buildDocumentCsp } from "@/lib/csp";

function isPublicPath(pathname: string): boolean {
  if (pathname === "/login") {
    return true;
  }
  // Auth BFF must stay reachable without a session (login / me probe).
  if (
    pathname === "/api/v1/auth/login" ||
    pathname === "/api/v1/auth/me" ||
    pathname === "/api/v1/auth/logout"
  ) {
    return true;
  }
  return false;
}

function isApiPath(pathname: string): boolean {
  return pathname.startsWith("/api/");
}

export function middleware(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = buildDocumentCsp({
    apiOrigin: API_ORIGIN,
    scriptSrc: `'self' 'nonce-${nonce}'`,
  });
  const requestHeaders = new Headers(request.headers);
  // Next App Router reads the request CSP to stamp nonce onto its scripts.
  requestHeaders.set("content-security-policy", csp);
  requestHeaders.set("x-nonce", nonce);

  const { pathname, search } = request.nextUrl;
  const hasSession = Boolean(request.cookies.get(AUTH_COOKIE_NAME)?.value);

  // Cookie presence only — AuthGate validates via /me. Never bounce /login away
  // here: a stale cookie would otherwise lock the user out of the form.
  if (!hasSession && !isPublicPath(pathname) && !isApiPath(pathname)) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    const next = `${pathname}${search}`;
    loginUrl.search = `?next=${encodeURIComponent(next)}`;
    const redirect = NextResponse.redirect(loginUrl);
    redirect.headers.set("Content-Security-Policy", csp);
    redirect.headers.set("X-Content-Type-Options", "nosniff");
    redirect.headers.set("Referrer-Policy", "no-referrer");
    return redirect;
  }

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

export const config = {
  matcher: [
    /*
     * Apply to all paths except Next static assets and image optimization.
     */
    "/((?!_next/static|_next/image|brand/|.*\\.(?:ico|png|svg|jpg|jpeg|gif|webp)$).*)",
  ],
};
