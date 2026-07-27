import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  compress: false,
  // Next's dev-server lock file lives at `${distDir}/lock`, keyed on this directory —
  // not the port. Playwright's e2e webServer runs `next dev` from this same project
  // dir, so without a distinct distDir it collides with a manually-run `pnpm dev` and
  // refuses to start. Isolate it so `make test-ui` works alongside a running dev server.
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    const backendUrl =
      process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
    return {
      fallback: [
        {
          source: "/api/:path*",
          destination: `${backendUrl}/api/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;
