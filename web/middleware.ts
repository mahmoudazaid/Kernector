import { NextResponse, type NextRequest } from "next/server";
import { loadPublicEnv } from "@/lib/env";

function buildNonceCsp(nonce: string, apiOrigin: string): string {
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "frame-src 'self' blob:",
    `script-src 'self' 'nonce-${nonce}'`,
    // motion / next/font still emit inline styles without nonces.
    "style-src 'self' 'unsafe-inline'",
    `connect-src 'self' ${apiOrigin}`,
  ].join("; ");
}

export function middleware(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const apiOrigin = new URL(
    loadPublicEnv().NEXT_PUBLIC_API_BASE_URL,
  ).origin;
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set(
    "Content-Security-Policy",
    buildNonceCsp(nonce, apiOrigin),
  );
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
