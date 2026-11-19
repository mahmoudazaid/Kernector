import fs from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";

/**
 * Next only auto-loads `web/.env*`. The Admin MCP BFF needs
 * ``ADMIN_API_TOKEN`` from the repo-root `.env` used by FastAPI. Copy that
 * one key into ``process.env`` when unset (``web/.env.local`` still wins if
 * Next loads it afterward with a value).
 */
function loadRepoRootAdminApiToken(): void {
  if ((process.env.ADMIN_API_TOKEN ?? "").trim()) {
    return;
  }
  const candidates = [
    path.join(process.cwd(), "..", ".env"),
    path.join(process.cwd(), ".env"),
  ];
  for (const file of candidates) {
    if (!fs.existsSync(file)) {
      continue;
    }
    for (const line of fs.readFileSync(file, "utf8").split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) {
        continue;
      }
      const match = /^ADMIN_API_TOKEN\s*=\s*(.*)$/.exec(trimmed);
      if (!match) {
        continue;
      }
      let value = match[1].trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      if (value.trim()) {
        process.env.ADMIN_API_TOKEN = value.trim();
        return;
      }
    }
  }
}

loadRepoRootAdminApiToken();

const NOSNIFF_REFERRER = [
  {
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    key: "Referrer-Policy",
    value: "no-referrer",
  },
] as const;

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
          ...NOSNIFF_REFERRER,
        ],
      },
      {
        source: "/brand/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=3600, stale-while-revalidate=86400",
          },
          ...NOSNIFF_REFERRER,
        ],
      },
      // CSP is owned exclusively by middleware. nosniff / referrer are set here
      // only for paths the middleware matcher excludes.
      {
        source: "/_next/static/:path*",
        headers: [...NOSNIFF_REFERRER],
      },
      {
        source: "/_next/image",
        headers: [...NOSNIFF_REFERRER],
      },
      {
        source: "/:file(.*\\.(?:ico|png|svg|jpg|jpeg|gif|webp))",
        headers: [...NOSNIFF_REFERRER],
      },
    ];
  },
};

export default nextConfig;
