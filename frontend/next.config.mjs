/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Proxy API calls to the FastAPI core in dev so the dashboard and core can run
  // on separate ports without CORS friction. Override the target with
  // TITAN_API_URL (defaults to the local core).
  async rewrites() {
    const target = process.env.TITAN_API_URL || "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
  },
};

export default nextConfig;
