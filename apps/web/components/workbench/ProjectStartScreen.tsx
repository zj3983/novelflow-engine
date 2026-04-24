"use client";

import { useMemo, useState } from "react";

import { BookImportPanel } from "../BookImportPanel";
import type { BookImportBootstrapResponse, BookLibraryCatalogResponse } from "../../lib/api";

type StartProjectDraft = {
  title: string;
  premise: string;
  mainGoal: string;
  charactersText: string;
};

type ProjectStartScreenProps = {
  importDraft: BookImportBootstrapResponse["draft"] | null;
  startDraft: StartProjectDraft;
  onStartDraftChange: (next: StartProjectDraft) => void;
  onBootstrapDraft: (draft: BookImportBootstrapResponse["draft"]) => void;
  onCatalogLoaded: (catalog: BookLibraryCatalogResponse | null) => void;
  onLoadImportedWorld: (draft?: BookImportBootstrapResponse["draft"]) => Promise<void>;
  onCreateBlankProject: () => Promise<void>;
  isGenerating: boolean;
};

function importedHighlights(importDraft: BookImportBootstrapResponse["draft"] | null): string[] {
  if (!importDraft) {
    return [];
  }

  const highlights: string[] = [];
  if (importDraft.world_summary?.trim()) {
    highlights.push(importDraft.world_summary.trim());
  } else if (importDraft.summary?.trim()) {
    highlights.push(importDraft.summary.trim());
  }
  if (importDraft.current_focus?.trim()) {
    highlights.push(`当前焦点：${importDraft.current_focus.trim()}`);
  }
  if (importDraft.author_constraints?.length) {
    highlights.push(`作者约束：${importDraft.author_constraints.slice(0, 3).join(" / ")}`);
  }
  return highlights.slice(0, 3);
}

export function ProjectStartScreen({
  importDraft,
  startDraft,
  onStartDraftChange,
  onBootstrapDraft,
  onCatalogLoaded,
  onLoadImportedWorld,
  onCreateBlankProject,
  isGenerating,
}: ProjectStartScreenProps) {
  const [activeMode, setActiveMode] = useState<"blank" | "import">("blank");

  const importedSummary = useMemo(() => importedHighlights(importDraft), [importDraft]);
  const blankReady = Boolean(
    startDraft.title.trim() &&
      startDraft.premise.trim() &&
      startDraft.mainGoal.trim() &&
      startDraft.charactersText.trim(),
  );

  return (
    <section className="project-start">
      <div className="project-start__hero">
        <p className="project-start__eyebrow">开始项目</p>
        <h1 className="project-start__title">先选开始方式，再进入小说工作台</h1>
        <p className="project-start__lead">
          这里先只做一件事：把项目真正开起来。导入已有书稿时，系统会先提炼世界背景、当前焦点和作者约束；从零开始时，只填最少信息就能直接开写。
        </p>
        <div className="project-start__mode-switch">
          <button
            className={`project-start__mode${activeMode === "blank" ? " project-start__mode--active" : ""}`}
            type="button"
            onClick={() => setActiveMode("blank")}
          >
            新建空白项目
          </button>
          <button
            className={`project-start__mode${activeMode === "import" ? " project-start__mode--active" : ""}`}
            type="button"
            onClick={() => setActiveMode("import")}
          >
            导入已有项目
          </button>
        </div>
      </div>

      <div className="project-start__grid">
        <article className={`project-start__card${activeMode === "blank" ? " project-start__card--active" : ""}`}>
          <div className="project-start__card-head">
            <p className="project-start__card-eyebrow">从零开始</p>
            <h2 className="project-start__card-title">新建小说项目</h2>
            <p className="project-start__card-copy">只填最关键的 4 项，让系统先建立项目、世界背景和核心角色，再直接生成第一章。</p>
          </div>

          <div className="project-start__form">
            <label className="project-start__field">
              <span>小说名</span>
              <input
                className="project-start__input"
                value={startDraft.title}
                onChange={(event) => onStartDraftChange({ ...startDraft, title: event.target.value })}
                placeholder="例如：雾城账本"
              />
            </label>

            <label className="project-start__field">
              <span>一句世界设定</span>
              <textarea
                className="project-start__textarea project-start__textarea--compact"
                value={startDraft.premise}
                onChange={(event) => onStartDraftChange({ ...startDraft, premise: event.target.value })}
                placeholder="例如：证词会改变现实的宫廷都市里，一本账本决定了所有人的命运。"
              />
            </label>

            <label className="project-start__field">
              <span>一句主线目标</span>
              <textarea
                className="project-start__textarea project-start__textarea--compact"
                value={startDraft.mainGoal}
                onChange={(event) => onStartDraftChange({ ...startDraft, mainGoal: event.target.value })}
                placeholder="例如：主角必须在三天内找到账本真正的第一页。"
              />
            </label>

            <label className="project-start__field">
              <span>1-3 个核心角色</span>
              <textarea
                className="project-start__textarea"
                value={startDraft.charactersText}
                onChange={(event) => onStartDraftChange({ ...startDraft, charactersText: event.target.value })}
                placeholder={"每行一个，格式：角色名｜目标\n例如：林越｜找到账本\n苏晚｜保护证人"}
              />
            </label>
          </div>

          <div className="project-start__actions">
            <button className="btn" type="button" disabled={isGenerating || !blankReady} onClick={() => void onCreateBlankProject()}>
              创建并生成第一章
            </button>
            <p className="hint">不会先把你扔进复杂工作台，创建成功后再进入项目界面。</p>
          </div>
        </article>

        <article className={`project-start__card${activeMode === "import" ? " project-start__card--active" : ""}`}>
          <div className="project-start__card-head">
            <p className="project-start__card-eyebrow">承接已有工程</p>
            <h2 className="project-start__card-title">导入已有小说项目</h2>
            <p className="project-start__card-copy">导入后不只回填草稿，还会自动提炼可直接进入项目的世界摘要、当前焦点和作者约束。</p>
          </div>

          <BookImportPanel
            onBootstrapDraft={onBootstrapDraft}
            onCatalogLoaded={onCatalogLoaded}
            onLoadWorld={onLoadImportedWorld}
          />

          {importDraft ? (
            <div className="project-start__import-preview">
              <p className="project-start__preview-title">导入结果预览</p>
              <div className="project-start__preview-meta">
                <span className="project-chip">项目名：{importDraft.title || "未识别"}</span>
                <span className="project-chip">角色数：{importDraft.characters.length}</span>
                <span className="project-chip">约束数：{importDraft.author_constraints?.length ?? 0}</span>
              </div>
              <div className="project-start__preview-list">
                {importedSummary.map((item) => (
                  <p key={item} className="project-start__preview-item">
                    {item}
                  </p>
                ))}
              </div>
              <div className="project-start__actions">
                <button className="btn" type="button" disabled={isGenerating} onClick={() => void onLoadImportedWorld(importDraft)}>
                  以导入结果继续演化
                </button>
              </div>
            </div>
          ) : null}
        </article>
      </div>
    </section>
  );
}

export type { StartProjectDraft };
