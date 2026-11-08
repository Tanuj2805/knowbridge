import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Every screen is per-user and permission-filtered, so we render dynamically
  // instead of opting into Cache Components.
  cacheComponents: false,
  output: "standalone",
  poweredByHeader: false,
  experimental: {
    // Source uploads (chat exports, PDFs) go through a server action; API caps files at 25 MB.
    serverActions: { bodySizeLimit: "26mb" },
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
