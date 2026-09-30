import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // Explicit loopback target; never a user-controlled proxy or provider app.
    return process.env.NEXT_PUBLIC_PCOS_SYNTHETIC_RUNTIME === "1"
      ? [{ source:"/runtime-api/:path*", destination:"http://127.0.0.1:8017/:path*" }]
      : [];
  },
};
export default nextConfig;
