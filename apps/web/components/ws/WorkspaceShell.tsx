"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { safeDecodeURIComponent } from "../../lib/routing";

type NavItem = {
  href: string;
  label: string;
  exact?: boolean;
};

const GLOBAL_NAV: NavItem[] = [{ href: "/workspace", label: "作品", exact: true }, { href: "/config", label: "设置", exact: true }];

function projectIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/projects\/([^/]+)/);
  if (!match || !match[1]) return null;
  return safeDecodeURIComponent(match[1]);
}

function projectNav(projectId: string): NavItem[] {
  const book = encodeURIComponent(projectId);
  return [
    { href: `/workspace?book=${book}&page=planning`, label: "全书规划" },
    { href: `/workspace?book=${book}&page=writing`, label: "写作" },
    { href: `/workspace?book=${book}&page=story`, label: "故事设定" },
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
