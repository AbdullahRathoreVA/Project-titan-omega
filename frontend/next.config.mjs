/** @type {import('next').NextConfig} */

// Two modes:
// - Dev (default): Next runs its own server and proxies /api/* to the FastAPI
//   core, so the dashboard and core can run on separate ports.
// - Static (TITAN_STATIC=1): export a static site into `out/` that the FastAPI
//   core serves itself, so a single container/URL serves UI + API (deploy).
const isStatic = process.env.TITAN_STATIC === "1";

const nextConfig = isStatic
  ? {
      reactStrictMode: true,
      output: "export",
      images: { unoptimized: true },
    }
  : {
      reactStrictMode: true,
      async rewrites() {
        const target = process.env.TITAN_API_URL || "http://localhost:8000";
        return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
      },
    };

export default nextConfig;
