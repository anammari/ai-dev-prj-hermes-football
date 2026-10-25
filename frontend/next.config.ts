import type { NextConfig } from "next";

/**
 * The dashboard is a server-rendered client of the Hermes API.
 *
 * `standalone` is what the container runs: Next traces the files it needs, so the runtime image is a
 * node binary and the app, not a node_modules tree. Nothing here holds a token - the API token is read
 * from the server environment by `src/lib/api/client.ts`, which is marked `server-only`.
 */
const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
