import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "",
  },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "images.unsplash.com" },
      { protocol: "http",  hostname: "localhost" },
      { protocol: "http",  hostname: "127.0.0.1" },
    ],
  },
  async rewrites() {
    return [
      { source: '/ask',                    destination: 'http://127.0.0.1:8000/ask' },
      { source: '/health',                 destination: 'http://127.0.0.1:8000/health' },
      { source: '/api/threads/:path*',     destination: 'http://127.0.0.1:8000/api/threads/:path*' },
      { source: '/api/upload',             destination: 'http://127.0.0.1:8000/api/upload' },
      { source: '/api/greeting',           destination: 'http://127.0.0.1:8000/greeting' },
      { source: '/auth/me',                destination: 'http://127.0.0.1:8000/auth/me' },
      { source: '/auth/logout',            destination: 'http://127.0.0.1:8000/auth/logout' },
      // Proxy static files (FLUX-generated greeting images) from the FastAPI backend
      { source: '/static/:path*',          destination: 'http://127.0.0.1:8000/static/:path*' },
    ];
  },
};

export default nextConfig;

