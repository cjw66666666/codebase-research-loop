/**
 * 全站根布局：加载全局样式、站点元数据和跨页面导航。
 */
import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Codebase Research Loop",
  description: "可验证的代码库调研助手",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="shell">
          <header className="topbar">
            <div className="topbar__inner">
              <Link className="brand" href="/projects">
                <span className="brand-mark">
                  <img src="/brand/AI.png" alt="" />
                </span>
                <span>
                  <strong>Codebase Research Loop</strong>
                  <small>工程调研助手</small>
                </span>
              </Link>
            </div>
          </header>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
