"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  {
    href: "/",
    label: "小说工作台",
    description: "创作、导入、章节与回滚",
  },
  {
    href: "/config",
    label: "配置中心",
    description: "全局 API 与运行时设置",
  },
] as const;

export function AppSidebarNav() {
  const pathname = usePathname();

  return (
    <nav className="app-sidebar-nav" aria-label="页面导航">
      {NAV_ITEMS.map((item) => {
        const isActive = pathname === item.href;

        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isActive ? "page" : undefined}
            className={`app-sidebar-nav__item${isActive ? " app-sidebar-nav__item--active" : ""}`}
          >
            <span className="app-sidebar-nav__label">{item.label}</span>
            <span className="app-sidebar-nav__description">{item.description}</span>
          </Link>
        );
      })}
    </nav>
  );
}
