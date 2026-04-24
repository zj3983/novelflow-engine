"use client";

import Link from "next/link";

type WorkbenchTopBarProps = {
  projectTitle: string;
  storyId: string | null;
  currentChapter: number;
  lastUpdatedLabel: string;
  statusSummary: string;
  canStartGeneration: boolean;
  isGenerating: boolean;
  onGenerateNextChapter: () => void;
};

export function WorkbenchTopBar({
  projectTitle,
  storyId,
  currentChapter,
  lastUpdatedLabel,
  statusSummary,
  canStartGeneration,
  isGenerating,
  onGenerateNextChapter,
}: WorkbenchTopBarProps) {
  const actionLabel = currentChapter > 0 ? "继续生成下一章" : "开始生成第一章";

  return (
    <div className="workbench-topbar panel">
      <div className="panel__body workbench-topbar__body">
        <div className="workbench-topbar__copy">
          <p className="workbench-topbar__eyebrow">小说项目</p>
          <h2 className="workbench-topbar__title">{projectTitle || "未命名小说项目"}</h2>
          <p className="workbench-topbar__meta">
            当前主分支 {storyId ?? "未创建"} · 第 {currentChapter} 章 · 最近更新 {lastUpdatedLabel}
          </p>
          <p className="workbench-topbar__summary">{statusSummary}</p>
        </div>

        <div className="workbench-topbar__actions">
          <button
            className="btn btn--primary"
            type="button"
            onClick={onGenerateNextChapter}
            disabled={isGenerating || !canStartGeneration}
          >
            {actionLabel}
          </button>
          <Link className="btn btn--ghost" href="/config">
            查看配置
          </Link>
        </div>
      </div>
    </div>
  );
}
