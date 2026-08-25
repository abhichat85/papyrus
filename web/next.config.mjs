/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The engine runs as a separate service; the web app only proxies to it.
  env: {
    PAPYRUS_API_URL: process.env.PAPYRUS_API_URL ?? "http://127.0.0.1:8787",
  },
};

export default nextConfig;
