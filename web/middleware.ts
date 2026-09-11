import { NextResponse, type NextRequest } from "next/server";
import { API_ORIGIN, buildDocumentCsp } from "@/lib/csp";

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
