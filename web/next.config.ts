import type { NextConfig } from "next";

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
      // CSP is owned exclusively by middleware so browsers do not intersect
      // two independent policy headers. nosniff / referrer remain here for
      // paths the middleware matcher excludes.
      {
        source: "/:path*",
        headers: [
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
