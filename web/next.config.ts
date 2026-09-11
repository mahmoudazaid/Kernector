import type { NextConfig } from "next";

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
