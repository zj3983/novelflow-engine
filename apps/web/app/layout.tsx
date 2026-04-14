import "./globals.css";

import type { ReactNode } from "react";

export const metadata = {
  title: "小说自动演化工作台",
  description: "用于连续生成、分支管理和多代理协作的小说工作台。",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
