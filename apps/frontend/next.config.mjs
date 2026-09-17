/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  // The Backend.AI app proxy serves the dev server under this host; without it
  // Next blocks the page's own /_next/* requests as cross-origin.
  allowedDevOrigins: ["siriuscluster.skku.edu"],
  transpilePackages: ["@skku-course-agent/shared"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*"
      }
    ];
  }
};

export default nextConfig;
