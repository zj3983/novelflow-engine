"use client";

import type { ReactNode } from "react";

import { AppSidebarNav } from "./AppSidebarNav";

type AppShellProps = {
  title: string;
  description?: string;
  children: ReactNode;
};

export function AppShell({ title, description, children }: AppShellProps) {
  return (
    <div className="app-shell">
      <aside className="app-shell__sidebar">
        <div className="app-shell__brand">
          <p className="app-shell__eyebrow">Novel Autogrowth Engine</p>
          <h2 className="app-shell__brand-title">双页写作工作区</h2>
          <p className="app-shell__brand-copy">统一导航，分离创作和配置。</p>
        </div>
        <AppSidebarNav />
      </aside>

      <main className="app-shell__main">
        <header className="app-shell__header">
          <p className="app-shell__eyebrow">当前页面</p>
          <h1 className="app-shell__title">{title}</h1>
          {description ? <p className="app-shell__description">{description}</p> : null}
        </header>

        <div className="app-shell__content">{children}</div>
      </main>
    </div>
  );
}
