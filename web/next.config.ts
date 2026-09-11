import type { NextConfig } from "next";
import { loadPublicEnv } from "./lib/env";

const publicEnv = loadPublicEnv();
const API_ORIGIN = new URL(publicEnv.NEXT_PUBLIC_API_BASE_URL).origin;

/** CSP directives shared by next.config headers and middleware tests. */
export function buildDocumentCsp(apiOrigin: string = API_ORIGIN): string {
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "frame-src 'self' blob:",
    // Nonce is injected per-request in middleware; config keeps a build-time
    // fallback that still allows App Router + next-themes until middleware runs.
    "script-src 'self' 'unsafe-inline'",
    // motion / next/font still emit inline styles without nonces.
    "style-src 'self' 'unsafe-inline'",
    `connect-src 'self' ${apiOrigin}`,
  ].join("; ");
}

const nextConfig: NextConfig = {
  experimental: {
    optimizePackageImports: ["motion"],
  },
  async rewrites() {
    return [
      { source: "/favicon.ico", destination: "/brand/favicon.ico" },
      {
        source: "/apple-touch-icon.png",
        destination: "/brand/apple-touch-icon.png",
      },
      {
        source: "/apple-touch-icon-precomposed.png",
        destination: "/brand/apple-touch-icon.png",
      },
    ];
  },
  async headers() {
    return [
      {
        source:
          "/:file(favicon.ico|apple-touch-icon.png|apple-touch-icon-precomposed.png)",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=0, must-revalidate",
          },
        ],
      },
      {
        source: "/brand/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=3600, stale-while-revalidate=86400",
          },
        ],
      },
      {
        source: "/:path*",
        headers: [
          {
            key: "Content-Security-Policy",
            value: buildDocumentCsp(),
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "Referrer-Policy",
            value: "no-referrer",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
