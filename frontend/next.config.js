/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,   // Disable to prevent double API calls in dev
  output: 'standalone',
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    NEXT_PUBLIC_WS_URL:  process.env.NEXT_PUBLIC_WS_URL  || 'ws://localhost:8000',
  },
  images: {
    domains: ['localhost'],
  },
}

module.exports = nextConfig
