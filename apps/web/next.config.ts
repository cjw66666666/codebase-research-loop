/**
 * Next.js 构建配置。当前只启用严格模式，避免开发期隐藏 React 副作用问题。
 */
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
