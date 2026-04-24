"use client";

import type { ReactNode } from "react";

type WorkbenchShellProps = {
  topBar: ReactNode;
  nav: ReactNode;
  overview: ReactNode;
  history: ReactNode;
  detail: ReactNode;
  side: ReactNode;
};

export function WorkbenchShell({ topBar, nav, overview, history, detail, side }: WorkbenchShellProps) {
  return (
    <div className="creative-workbench">
      <header className="creative-workbench__topbar" role="banner">
        {topBar}
      </header>

      <div className="creative-workbench__body">
        <aside className="creative-workbench__nav" role="navigation" aria-label="工作台导航">
          {nav}
        </aside>

        <main className="creative-workbench__main">
          <section className="creative-workbench__section" aria-label="故事总览">
            {overview}
          </section>
          <section className="creative-workbench__section" aria-label="章节历史">
            {history}
          </section>
          <section className="creative-workbench__section" aria-label="章节详情">
            {detail}
          </section>
        </main>

        <aside className="creative-workbench__side" role="complementary" aria-label="创作侧栏">
          {side}
        </aside>
      </div>
    </div>
  );
}
