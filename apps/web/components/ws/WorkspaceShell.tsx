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

type NavGroup = {
  label: string;
  items: NavItem[];
  openByDefault?: boolean;
};

const GLOBAL_NAV: NavItem[] = [
  { href: "/projects", label: "作品", exact: true },
  { href: "/novel-types", label: "小说类型", exact: true },
  { href: "/config", label: "配置", exact: true },
];

function projectIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/projects\/([^/]+)/);
  if (!match || !match[1] || match[1] === "new") return null;
  return safeDecodeURIComponent(match[1]);
}

function projectNavGroups(projectId: string): NavGroup[] {
  const base = projectHref(projectId);
  return [
    {
      label: "作品",
      openByDefault: true,
      items: [
        { href: base, label: "总览", exact: true },
        { href: `${base}/outline`, label: "大纲" },
        { href: `${base}/write`, label: "章节" },
      ],
    },
    {
      label: "设定",
      openByDefault: true,
      items: [
        { href: `${base}/world`, label: "世界观" },
        { href: `${base}/characters`, label: "角色卡" },
        { href: `${base}/relationships`, label: "人物关系" },
      ],
    },
    {
      label: "创作工具",
      items: [
        { href: `${base}/setup`, label: "开书构建" },
        { href: `${base}/dissection`, label: "拆书" },
        { href: `${base}/sim`, label: "世界状态" },
        { href: `${base}/prompts`, label: "提示词" },
        { href: `${base}/skills`, label: "Skills" },
      ],
    },
    {
      label: "项目",
      items: [
        { href: `${base}/settings`, label: "项目设置" },
        { href: `${base}/log`, label: "运行记录" },
      ],
    },
  ];
}

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() || "";
  const projectId = projectIdFromPath(pathname);
  const groups: NavGroup[] = projectId
    ? [...projectNavGroups(projectId), { label: "全局", items: GLOBAL_NAV }]
    : [{ label: "全局", items: GLOBAL_NAV, openByDefault: true }];

  const isActive = (item: NavItem) => {
    if (item.exact) return pathname === item.href;
    return pathname === item.href || pathname.startsWith(`${item.href}/`);
  };

  return (
    <div className="ws-shell">
      <nav className="ws-nav" aria-label="主导航">
        <div className="ws-nav__brand">小说工作台</div>
        {groups.map((group) => (
          <details
            className="ws-nav__group"
            key={group.label}
            aria-label={group.label}
            open={group.openByDefault || group.items.some(isActive)}
          >
            <summary className="ws-nav__group-title">{group.label}</summary>
            <div className="ws-nav__group-items">
              {group.items.map((item) => {
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
            </div>
          </details>
        ))}
      </nav>
      <main className="ws-main">{children}</main>
    </div>
  );
}
