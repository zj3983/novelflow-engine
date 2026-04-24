import "./globals.css";

import type { ReactNode } from "react";

export const metadata = {
  title: "小说自动演化工作台",
  description: "双页写作工作区，统一左侧导航、工作台与配置中心的页面结构。",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="app-root">{children}</body>
    </html>
  );
}
