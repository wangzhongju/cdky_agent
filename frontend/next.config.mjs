// Next dev blocks cross-origin access to internal dev resources by default.
// Docker publishes the app on 127.0.0.1, so we explicitly allow local browser origins.
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1", "localhost"]
};

export default nextConfig;
