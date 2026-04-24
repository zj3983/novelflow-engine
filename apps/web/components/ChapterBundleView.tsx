"use client";

import type { BookImportBootstrapResponse, ChapterBundle, StoryResponse } from "../lib/api";

type ChapterBundleViewProps = {
  story: StoryResponse | null;
  bundle: ChapterBundle | null;
  importedDraft: BookImportBootstrapResponse["draft"] | null;
  canStartGeneration: boolean;
  isGenerating: boolean;
  error: string | null;
  onStartGeneration: (draft?: BookImportBootstrapResponse["draft"]) => Promise<void>;
  onRollbackChapter: () => Promise<void>;
};

function mainActionLabel(story: StoryResponse | null): string {
  if (story?.history.length) {
    return "继续生成下一章";
  }
  return "开始生成第一章";
}

function readableAgentLabel(agent: string): string {
  return agent === "character"
    ? "角色代理"
    : agent === "director"
      ? "导演代理"
      : agent === "writer"
        ? "写作代理"
        : agent === "memory"
          ? "记忆代理"
          : agent;
}

export function ChapterBundleView({
  story,
  bundle,
  importedDraft,
  canStartGeneration,
  isGenerating,
  error,
  onStartGeneration,
  onRollbackChapter,
}: ChapterBundleViewProps) {
  const hasStory = Boolean(story);
  const introText =
    importedDraft?.summary?.trim() ||
    importedDraft?.outline?.trim() ||
    "导入书籍后，这里会成为当前章节的主工作区。";

  return (
    <section className="panel chapter-panel" aria-label="章节主区域">
      <header className="panel__header chapter-panel__header">当前章节</header>
      <div className="panel__body chapter-panel__body">
        {!bundle ? (
          <div className="chapter-panel__hero">
            <p className="chapter-panel__eyebrow">{hasStory ? "故事已就绪" : "等待导入或直接起笔"}</p>
            <h2 className="chapter-panel__title">{mainActionLabel(story)}</h2>
            <p className="chapter-panel__lead">{introText}</p>
            <div className="chapter-panel__actions">
              <button
                className="btn"
                type="button"
                onClick={() => void onStartGeneration(importedDraft ?? undefined)}
                disabled={isGenerating || !canStartGeneration}
              >
                {mainActionLabel(story)}
              </button>
              <button className="btn btn--ghost" type="button" onClick={() => void onRollbackChapter()} disabled={isGenerating || !hasStory}>
                回滚上一章
              </button>
            </div>
            <div className="chapter-panel__meta">
              <p className="hint">导入书籍后，中央区域会直接从这里开始第一章。</p>
              {!canStartGeneration ? (
                <p className="hint">先填写大纲，并至少补充 1 个有名称和目标的角色，才能开始第一章。</p>
              ) : null}
              {error ? <p className="hint">错误：{error}</p> : null}
            </div>
          </div>
        ) : (
          <div className="chapter-panel__content">
            <div className="chapter-panel__content-head">
              <div>
                <p className="chapter-panel__eyebrow">正在查看</p>
                <h2 className="chapter-panel__title">第 {bundle.chapter_number} 章</h2>
              </div>
              <div className="chapter-panel__status">
                <span className="chapter-panel__status-item">当前故事：{story?.story_id ?? "未命名"}</span>
                <span className="chapter-panel__status-item">当前章节：{story?.current_chapter ?? bundle.chapter_number}</span>
              </div>
            </div>

            <div className="chapter-panel__insights">
              <section className="chapter-panel__summary chapter-panel__summary--spotlight">
                <p className="character-card__title">本章意图</p>
                <p className="chapter-panel__summary-text">
                  {bundle.chapter_intent?.primary_conflict?.collision
                    ? String(bundle.chapter_intent.primary_conflict.collision)
                    : "本章意图尚未整理。"}
                </p>
                {bundle.chapter_intent?.next_focus ? (
                  <p className="hint">下一焦点：{bundle.chapter_intent.next_focus}</p>
                ) : null}
              </section>

              <section className="chapter-panel__summary">
                <p className="character-card__title">事件推进</p>
                <p className="chapter-panel__summary-text">
                  {bundle.event_plan?.pivot || bundle.event_beat?.pivot || "暂无事件推进摘要。"}
                </p>
                {bundle.event_plan?.stakes ? <p className="hint">风险与代价：{bundle.event_plan.stakes}</p> : null}
              </section>

              <section className="chapter-panel__summary">
                <p className="character-card__title">状态回写</p>
                <p className="chapter-panel__summary-text">
                  {bundle.memory_constraints?.must_keep_facts?.[0] || "暂无状态回写信息。"}
                </p>
                {bundle.memory_constraints?.unresolved_threads?.length ? (
                  <p className="hint">未收束线索：{bundle.memory_constraints.unresolved_threads.join("；")}</p>
                ) : null}
              </section>

              <section className="chapter-panel__summary">
                <p className="character-card__title">角色行动</p>
                <div className="chapter-panel__list">
                  {(bundle.character_moves ?? []).slice(0, 4).map((move) => (
                    <article key={`${move.name}-${move.action}`} className="chapter-panel__list-item">
                      <strong>{move.name ?? "未知角色"}</strong>
                      <p className="chapter-panel__summary-text">{move.action || move.goal || "暂无行动说明"}</p>
                    </article>
                  ))}
                  {!bundle.character_moves?.length ? <p className="chapter-panel__summary-text">暂无角色行动信息。</p> : null}
                </div>
              </section>

              <section className="chapter-panel__summary">
                <p className="character-card__title">章节摘要</p>
                <p className="chapter-panel__summary-text">{bundle.chapter_summary?.summary || "暂无章节摘要"}</p>
              </section>

              <section className="chapter-panel__summary">
                <p className="character-card__title">下一步</p>
                <p className="chapter-panel__summary-text">{bundle.next_outline || "暂无下一步计划"}</p>
              </section>
            </div>

            <article className="chapter-panel__article">
              <div className="chapter-panel__article-head">
                <p className="character-card__title">小说正文</p>
                <span className="chapter-panel__article-badge">结果视图</span>
              </div>
              <pre className="chapter-panel__prose">{bundle.body}</pre>
            </article>

            {bundle.simulation_status ? (
              <section className="chapter-panel__summary">
                <p className="character-card__title">推演状态</p>
                <p className="chapter-panel__summary-text">
                  {bundle.simulation_status.ok
                    ? "本章已完成完整推演。"
                    : `本章为降级推演：${(bundle.simulation_status.fallback_agents ?? [])
                        .map(readableAgentLabel)
                        .join("、")} 进入回退。`}
                </p>
              </section>
            ) : null}

            {bundle.quality_report ? (
              <section className="chapter-panel__summary">
                <p className="character-card__title">质量检查</p>
                <p className="chapter-panel__summary-text">
                  {bundle.quality_report.ok ? "本章状态正常。" : bundle.quality_report.issues.join("；")}
                </p>
              </section>
            ) : null}

            <div className="chapter-panel__actions">
              <button className="btn" type="button" onClick={() => void onStartGeneration()} disabled={isGenerating}>
                {mainActionLabel(story)}
              </button>
              <button className="btn btn--ghost" type="button" onClick={() => void onRollbackChapter()} disabled={isGenerating || !hasStory}>
                回滚上一章
              </button>
            </div>

            {error ? <p className="hint chapter-panel__error">错误：{error}</p> : null}
          </div>
        )}
      </div>
    </section>
  );
}
