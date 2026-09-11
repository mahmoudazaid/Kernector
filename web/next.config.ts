import type { NextConfig } from "next";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

function apiConnectSrc(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;
  try {
    return new URL(raw).origin;
  } catch {
    return DEFAULT_API_BASE_URL;
  }
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
    const connectSrc = apiConnectSrc();
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
            // 'unsafe-inline' for script/style is required until a nonce
            // pipeline exists: App Router RSC bootstrap and next-themes
            // inject inline scripts; motion/next-font emit inline styles.
            value: [
              "default-src 'self'",
              "object-src 'none'",
              "frame-src 'self' blob:",
              "script-src 'self' 'unsafe-inline'",
              "style-src 'self' 'unsafe-inline'",
              `connect-src 'self' ${connectSrc}`,
            ].join("; "),
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
