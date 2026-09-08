import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
        source: "/brand/:path*",
        headers: [{ key: "Cache-Control", value: "no-store, must-revalidate" }],
      },
    ];
  },
};

export default nextConfig;
