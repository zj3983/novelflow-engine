"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { PromptCallsView } from "../../../../components/prompts/PromptCallsView";
import { PromptContextView } from "../../../../components/prompts/PromptContextView";
import { PromptTemplatesView } from "../../../../components/prompts/PromptTemplatesView";
import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";

type PromptView = "templates" | "context" | "calls";

const VIEWS: Array<{ id: PromptView; label: string }> = [
  { id: "templates", label: "提示词模板" },
  { id: "context", label: "上下文模块" },
  { id: "calls", label: "实际调用" },
];

function promptView(value: string | null): PromptView {
  return value === "context" || value === "calls" ? value : "templates";
}

export default function PromptsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { project, story, error, encodedProjectId, projectId } = useProjectWorkspace();
  const activeView = promptView(searchParams?.get("view") ?? null);
  const history = story?.history ?? [];
  const requestedChapter = Number(searchParams?.get("chapter") || story?.current_chapter || history.at(-1)?.chapter_number || 1);
  const selectedChapter = useMemo(
    () => history.find((bundle) => bundle.chapter_number === requestedChapter) ?? history.at(-1) ?? null,
    [history, requestedChapter],
  );
  const targetChapter = selectedChapter?.chapter_number ?? requestedChapter;

  function switchView(view: PromptView) {
    router.replace(`${pathname}?view=${view}&chapter=${targetChapter}`);
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="提示词"
        subtitle="分别查看可编辑模板、本章动态上下文和真实模型调用。"
      />

      {error ? <p className="ws-inline-error" role="alert">项目加载失败：{error}</p> : null}

      <div className="ws-prompt-tabs" role="tablist" aria-label="提示词工作台视图">
        {VIEWS.map((view) => (
          <button
            key={view.id}
            type="button"
            role="tab"
            aria-selected={activeView === view.id}
            onClick={() => switchView(view.id)}
          >
            {view.label}
          </button>
        ))}
      </div>

      <div className="ws-prompt-layout">
        <aside className="ws-sidepanel ws-chapter-index" aria-label="章节目录">
          <section className="ws-card">
            <div className="ws-section-head">
              <p className="ws-card__title">章节</p>
              <span className="ws-toolbar__meta">{history.length} 章</span>
            </div>
            <div className="ws-chapter-list">
              {history.length ? [...history].reverse().map((bundle) => (
                <Link
                  key={bundle.chapter_number}
                  href={`/projects/${encodedProjectId}/prompts?view=${activeView}&chapter=${bundle.chapter_number}`}
                  className={`ws-chapter-list__item${bundle.chapter_number === targetChapter ? " ws-chapter-list__item--active" : ""}`}
                >
                  <span>第 {bundle.chapter_number} 章</span>
                  <strong>{bundle.chapter_title || "未命名"}</strong>
                </Link>
              )) : <p className="ws-card__hint">暂无正文，先显示第 1 章配置。</p>}
            </div>
          </section>
        </aside>

        <main className="ws-prompt-main" role="tabpanel">
          {activeView === "templates" ? <PromptTemplatesView projectId={projectId} /> : null}
          {activeView === "context" ? <PromptContextView projectId={projectId} chapterNumber={targetChapter} /> : null}
          {activeView === "calls" ? <PromptCallsView projectId={projectId} chapterNumber={targetChapter} /> : null}
        </main>
      </div>
    </div>
  );
}
