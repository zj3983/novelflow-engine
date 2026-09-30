import "./globals.css";

import type { ReactNode } from "react";

export const metadata = {
  title: "长篇小说工作台",
  description: "规划、创作、修改与逐章确认，在一个工作区持续写下你的故事。",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="app-root">{children}</body>
    </html>
  );
}
