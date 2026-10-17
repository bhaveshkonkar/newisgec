import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // pg reaches for node builtins (fs, net, tls) and for 'pg-native', an
  // optional native binding that is not installed. Keep the whole package out
  // of the bundler so those requires stay runtime `require`s.
  serverExternalPackages: ["pg"],
  experimental: {
    // PDF uploads go through a route handler, not the server actions limit.
    serverActions: { bodySizeLimit: "64mb" },
  },

  webpack: (config, { isServer }) => {
    if (isServer) {
      // Belt and braces: if pg is ever pulled into a graph, do not try to
      // resolve the optional native binding at build time.
      config.resolve = config.resolve ?? {};
      config.resolve.fallback = {
        ...config.resolve.fallback,
        "pg-native": false as const,
        fs: false as const,
        net: false as const,
        tls: false as const,
      };
    }
    return config;
  },
};

export default nextConfig;