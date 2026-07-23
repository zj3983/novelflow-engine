"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { projectHref, safeDecodeURIComponent } from "../../lib/routing";

type NavItem = {
  href: string;
  label: string;
  exact?: boolean;
};

const GLOBAL_NAV: NavItem[] = [
  { href: "/projects", label: "作品", exact: true },
  { href: "/novel-types", label: "小说类型", exact: true },
  { href: "/config", label: "配置", exact: true },
];

function projectIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/projects\/([^/]+)/);
  if (!match || !match[1]) return null;
  return safeDecodeURIComponent(match[1]);
}

function projectNav(projectId: string): NavItem[] {
  const base = projectHref(projectId);
  return [
    { href: base, label: "概览", exact: true },
    { href: `${base}/write`, label: "章节" },
    { href: `${base}/dissection`, label: "拆书" },
    { href: `${base}/sim`, label: "世界响应" },
    { href: `${base}/prompts`, label: "提示词" },
    { href: `${base}/skills`, label: "Skills" },
    { href: `${base}/outline`, label: "大纲" },
    { href: `${base}/world`, label: "世界观" },
    { href: `${base}/relationships`, label: "人物关系" },
    { href: `${base}/characters`, label: "角色卡" },
    { href: `${base}/settings`, label: "项目设置" },
    { href: `${base}/log`, label: "日志" },
  ];
}

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "";
  const projectId = projectIdFromPath(pathname);
  const items = projectId ? [...GLOBAL_NAV, ...projectNav(projectId)] : GLOBAL_NAV;

  const isActive = (item: NavItem) => {
    if (item.exact) return pathname === item.href;
    return pathname === item.href || pathname.startsWith(`${item.href}/`);
  };

  return (
    <div className="ws-shell">
      <nav className="ws-nav" aria-label="主导航">
        <div className="ws-nav__brand">小说工作台</div>
        {items.map((item) => {
          const active = isActive(item);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`ws-nav__item${active ? " ws-nav__item--active" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
      <main className="ws-main">{children}</main>
    </div>
  );
}
