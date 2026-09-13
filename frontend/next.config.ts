import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(process.env.KITE_DESKTOP_BUILD === "1" ? { output: "export" as const, distDir: ".next-desktop" } : {}),
};

export default nextConfig;
