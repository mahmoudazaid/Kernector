import { loadPublicEnv } from "@/lib/env";

const publicEnv = loadPublicEnv();
export const API_ORIGIN = new URL(publicEnv.NEXT_PUBLIC_API_BASE_URL).origin;

export type CspScriptSrc = `'self' 'unsafe-inline'` | `'self' 'nonce-${string}'`;

/** Shared CSP directive list for middleware, next.config, and boundary tests. */
export function buildDocumentCsp(options: {
  apiOrigin?: string;
  scriptSrc: CspScriptSrc | string;
}): string {
  const apiOrigin = options.apiOrigin ?? API_ORIGIN;
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "frame-src 'none'",
    `script-src ${options.scriptSrc}`,
    // motion / next/font still emit inline styles without nonces.
    "style-src 'self' 'unsafe-inline'",
    `connect-src 'self' ${apiOrigin}`,
  ].join("; ");
}
