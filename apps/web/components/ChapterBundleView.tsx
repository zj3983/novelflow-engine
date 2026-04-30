"use client";

import type { BookImportBootstrapResponse, ChapterBundle, CodexWritingPacket, StoryResponse } from "../lib/api";

type ChapterBundleViewProps = {
  story: StoryResponse | null;
  bundle: ChapterBundle | null;
  importedDraft: BookImportBootstrapResponse["draft"] | null;
  canStartGeneration: boolean;
  isGenerating: boolean;
  isReviewing: boolean;
  isRevising: boolean;
  isPreparingManualDraft: boolean;
  isSubmittingManualDraft: boolean;
  isSubmittingManualSegmentDraft: boolean;
  generationStatus?: string | null;
  reviewStatus?: string | null;
  revisionStatus?: string | null;
  manualDraftStatus?: string | null;
  error: string | null;
  canReviseChapter: boolean;
  writingPacket: CodexWritingPacket | null;
  manualDraftBody: string;
  manualSegmentIndex: number | null;
  manualSegmentBody: string;
  onStartGeneration: (draft?: BookImportBootstrapResponse["draft"]) => Promise<void>;
  onRollbackChapter: () => Promise<void>;
  onReviewChapter: () => Promise<void>;
  onReviseChapter: () => Promise<void>;
  onPrepareManualDraft: () => Promise<void>;
  onManualDraftBodyChange: (body: string) => void;
  onSubmitManualDraft: (body: string) => Promise<void>;
  onSelectManualSegment: (index: number, body: string) => void;
  onManualSegmentBodyChange: (body: string) => void;
  onSubmitManualSegmentDraft: (index: number, body: string) => Promise<void>;
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

function safetyReasonLabel(reason?: string): string {
  if (reason === "candidate_worse_than_original") {
    return "候选改稿更差，已保留原稿";
  }
  if (reason === "candidate_not_worse") {
    return "候选改稿不差于原稿，已接受";
  }
  return reason || "暂无原因";
}

function safetySelectedLabel(selected?: string): string {
  if (selected === "original") {
    return "保留原稿";
  }
  if (selected === "candidate") {
    return "采用改稿";
  }
  return selected || "未记录";
}

function scoreDeltaText(original?: number, candidate?: number): string {
  if (typeof original !== "number" || typeof candidate !== "number") {
    return "暂无分数对比";
  }
  const delta = candidate - original;
  const sign = delta > 0 ? "+" : "";
  return `原稿 ${original} / 候选 ${candidate} / 差值 ${sign}${delta.toFixed(2)}`;
}

export function ChapterBundleView({
  story,
  bundle,
  importedDraft,
  canStartGeneration,
  isGenerating,
  isReviewing,
  isRevising,
  isPreparingManualDraft,
  isSubmittingManualDraft,
  isSubmittingManualSegmentDraft,
  generationStatus,
  reviewStatus,
  revisionStatus,
  manualDraftStatus,
  error,
  canReviseChapter,
  writingPacket,
  manualDraftBody,
  manualSegmentIndex,
  manualSegmentBody,
  onStartGeneration,
  onRollbackChapter,
  onReviewChapter,
  onReviseChapter,
  onPrepareManualDraft,
  onManualDraftBodyChange,
  onSubmitManualDraft,
  onSelectManualSegment,
  onManualSegmentBodyChange,
  onSubmitManualSegmentDraft,
}: ChapterBundleViewProps) {
  const hasStory = Boolean(story);
  const isBusy =
    isGenerating || isReviewing || isRevising || isPreparingManualDraft || isSubmittingManualDraft || isSubmittingManualSegmentDraft;
  const introText =
    importedDraft?.summary?.trim() ||
    importedDraft?.outline?.trim() ||
    "导入书籍后，这里会成为当前章节的主工作区。";
  const writingReview = bundle?.quality_report?.writing_review;
  const reviewScores = writingReview?.scores ? Object.entries(writingReview.scores) : [];
  const revisionSafety = bundle?.quality_report?.revision_safety;
  const segmentSafetyReports = (bundle?.quality_report?.segment_pipeline?.segments ?? [])
    .map((segment, index) => ({
      index,
      title: segment.segment_title || segment.segment_key || `第 ${index + 1} 段`,
      safety: segment.segment_revision_safety,
      issues: segment.issues ?? [],
    }))
    .filter((item) => item.safety);
  const manualSegments = (bundle?.body ?? "")
    .split("\n\n")
    .map((segment) => segment.trim())
    .filter(Boolean);

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
                disabled={isBusy || !canStartGeneration}
              >
                {isGenerating ? generationStatus ?? "生成中..." : mainActionLabel(story)}
              </button>
              <button className="btn btn--ghost" type="button" onClick={() => void onRollbackChapter()} disabled={isBusy || !hasStory}>
                回滚上一章
              </button>
            </div>
            <div className="chapter-panel__meta">
              <p className="hint">导入书籍后，中央区域会直接从这里开始第一章。</p>
              {!canStartGeneration ? (
                <p className="hint">先填写大纲，并至少补充 1 个有名称和目标的角色，才能开始第一章。</p>
              ) : null}
              {error ? <p className="hint">错误：{error}</p> : null}
              {isGenerating && generationStatus ? <p className="hint">生成进度：{generationStatus}</p> : null}
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

              <section className="chapter-panel__summary">
                <p className="character-card__title">背景节拍</p>
                <div className="chapter-panel__list">
                  {(bundle.event_plan?.exposition_beats ?? []).slice(0, 4).map((beat, index) => (
                    <article key={`${beat}-${index}`} className="chapter-panel__list-item">
                      <strong>节拍 {index + 1}</strong>
                      <p className="chapter-panel__summary-text">{beat}</p>
                    </article>
                  ))}
                  {!bundle.event_plan?.exposition_beats?.length ? (
                    <p className="chapter-panel__summary-text">暂无本章背景节拍。</p>
                  ) : null}
                </div>
              </section>
            </div>

            <article className="chapter-panel__article">
              <div className="chapter-panel__article-head">
                <p className="character-card__title">小说正文</p>
                <span className="chapter-panel__article-badge">结果视图</span>
              </div>
              <pre className="chapter-panel__prose">{bundle.body}</pre>
            </article>

            <section className="chapter-panel__summary chapter-panel__manual">
              <p className="character-card__title">Codex 手写通道</p>
              <p className="chapter-panel__summary-text">
                这里把推演结果整理成写作包：世界事实、角色面板、硬性约束和场景卡先固定，再由 Codex/人工重写正文并提交回项目。
              </p>
              <div className="chapter-panel__actions">
                <button
                  className="btn btn--ghost"
                  type="button"
                  onClick={() => void onPrepareManualDraft()}
                  disabled={isBusy || !bundle}
                >
                  {isPreparingManualDraft ? manualDraftStatus ?? "正在生成写作包..." : "生成 Codex 写作包"}
                </button>
                <button
                  className="btn btn--secondary"
                  type="button"
                  onClick={() => void onSubmitManualDraft(manualDraftBody)}
                  disabled={isBusy || !canReviseChapter || !manualDraftBody.trim()}
                >
                  {isSubmittingManualDraft ? manualDraftStatus ?? "正在提交手写正文..." : "提交手写正文"}
                </button>
              </div>
              {manualDraftStatus ? <p className="hint">{manualDraftStatus}</p> : null}
              {writingPacket ? (
                <div className="chapter-panel__packet">
                  <p className="hint">
                    目标字数：{writingPacket.target_chars?.min ?? 4200}-{writingPacket.target_chars?.max ?? 5500} 字
                  </p>
                  {writingPacket.hard_locks?.length ? (
                    <div className="chapter-panel__list">
                      {writingPacket.hard_locks.slice(0, 6).map((lock, index) => (
                        <article key={`${lock}-${index}`} className="chapter-panel__list-item">
                          <strong>硬约束 {index + 1}</strong>
                          <p className="chapter-panel__summary-text">{lock}</p>
                        </article>
                      ))}
                    </div>
                  ) : null}
                  {writingPacket.scene_cards?.length ? (
                    <div className="chapter-panel__list">
                      {writingPacket.scene_cards.slice(0, 4).map((scene, index) => (
                        <article key={`${String(scene.id ?? scene.name ?? index)}-${index}`} className="chapter-panel__list-item">
                          <strong>{String(scene.title ?? scene.name ?? `场景 ${index + 1}`)}</strong>
                          <p className="chapter-panel__summary-text">
                            {String(scene.purpose ?? scene.summary ?? scene.goal ?? "按场景卡推进正文。")}
                          </p>
                        </article>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              <textarea
                className="chapter-panel__manual-draft"
                value={manualDraftBody}
                onChange={(event) => onManualDraftBodyChange(event.target.value)}
                placeholder="把 Codex/人工重写后的完整正文放在这里。提交后会替换当前最新章节，并重新生成审稿报告与角色状态。"
                disabled={isBusy || !canReviseChapter}
              />
              <div className="chapter-panel__segment-editor">
                <div>
                  <p className="character-card__title">局部段落改稿</p>
                  <p className="chapter-panel__summary-text">
                    选择一个段落，只替换这一段。适合处理审稿指出的 AI 味、对话、逻辑小问题，不必整章重交。
                  </p>
                </div>
                {manualSegments.length ? (
                  <div className="chapter-panel__segments">
                    {manualSegments.map((segment, index) => (
                      <button
                        key={`${index}-${segment.slice(0, 24)}`}
                        className={`chapter-panel__segment-btn${
                          manualSegmentIndex === index ? " chapter-panel__segment-btn--active" : ""
                        }`}
                        type="button"
                        onClick={() => onSelectManualSegment(index, segment)}
                        disabled={isBusy || !canReviseChapter}
                      >
                        <span>第 {index + 1} 段</span>
                        <small>{segment.slice(0, 72)}</small>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="hint">当前章节还没有可拆分段落。</p>
                )}
                <textarea
                  className="chapter-panel__manual-draft chapter-panel__manual-draft--segment"
                  value={manualSegmentBody}
                  onChange={(event) => onManualSegmentBodyChange(event.target.value)}
                  placeholder="选择上面的段落后，在这里改写局部正文。"
                  disabled={isBusy || !canReviseChapter || manualSegmentIndex == null}
                />
                <div className="chapter-panel__actions">
                  <button
                    className="btn btn--secondary"
                    type="button"
                    onClick={() => {
                      if (manualSegmentIndex != null) {
                        void onSubmitManualSegmentDraft(manualSegmentIndex, manualSegmentBody);
                      }
                    }}
                    disabled={isBusy || !canReviseChapter || manualSegmentIndex == null || !manualSegmentBody.trim()}
                  >
                    {isSubmittingManualSegmentDraft ? manualDraftStatus ?? "正在提交局部改稿..." : "提交局部改稿"}
                  </button>
                </div>
              </div>
              {!canReviseChapter ? <p className="hint">手写正文只能替换当前最新章节，历史章节需要先回滚到对应位置。</p> : null}
            </section>

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
                <p className="character-card__title">章节审稿 Agent</p>
                <p className="chapter-panel__summary-text">
                  {writingReview?.pass
                    ? "审稿通过：本章已覆盖网文钩子、背景融入、主角动机、类型规则、世界反应和章末钩子。"
                    : writingReview?.issues?.length
                      ? writingReview.issues.join("；")
                      : bundle.quality_report.ok
                        ? "本章状态正常。"
                        : bundle.quality_report.issues.join("；")}
                </p>
                {reviewScores.length ? (
                  <div className="chapter-panel__list">
                    {reviewScores.map(([name, score]) => (
                      <article key={name} className="chapter-panel__list-item">
                        <strong>{name}</strong>
                        <p className="chapter-panel__summary-text">{score}/10</p>
                      </article>
                    ))}
                  </div>
                ) : null}
                {writingReview?.revision_plan?.length ? (
                  <p className="hint">改稿计划：{writingReview.revision_plan.join("；")}</p>
                ) : null}
                <div className="chapter-panel__actions">
                  <button
                    className="btn btn--ghost"
                    type="button"
                    onClick={() => void onReviewChapter()}
                    disabled={isBusy || !bundle}
                  >
                    {isReviewing ? reviewStatus ?? "单章审核中..." : "单独审核本章"}
                  </button>
                  <button
                    className="btn btn--secondary"
                    type="button"
                    onClick={() => void onReviseChapter()}
                    disabled={isBusy || !canReviseChapter}
                  >
                    {isRevising ? revisionStatus ?? "自动改稿中..." : "按审稿意见自动改稿"}
                  </button>
                </div>
                {!canReviseChapter ? <p className="hint">自动改稿只会修改当前最新章，历史章节请先回滚到对应位置。</p> : null}
              </section>
            ) : null}

            {revisionSafety || segmentSafetyReports.length ? (
              <section className="chapter-panel__summary chapter-panel__summary--safety">
                <p className="character-card__title">改稿安全报告</p>
                {revisionSafety ? (
                  <article className="chapter-panel__list-item">
                    <strong>整章快照：{safetySelectedLabel(revisionSafety.selected)}</strong>
                    <p className="chapter-panel__summary-text">{safetyReasonLabel(revisionSafety.reason)}</p>
                    <p className="hint">
                      {scoreDeltaText(revisionSafety.original_score, revisionSafety.candidate_score)}
                      {typeof revisionSafety.original_chars === "number" && typeof revisionSafety.candidate_chars === "number"
                        ? `；字数 ${revisionSafety.original_chars} -> ${revisionSafety.candidate_chars}`
                        : ""}
                    </p>
                  </article>
                ) : null}
                {segmentSafetyReports.length ? (
                  <div className="chapter-panel__list">
                    {segmentSafetyReports.map((item) => (
                      <article key={`${item.title}-${item.index}`} className="chapter-panel__list-item">
                        <strong>
                          {item.title}：{safetySelectedLabel(item.safety?.selected)}
                        </strong>
                        <p className="chapter-panel__summary-text">{safetyReasonLabel(item.safety?.reason)}</p>
                        <p className="hint">{scoreDeltaText(item.safety?.original_score, item.safety?.candidate_score)}</p>
                        {item.issues.length ? <p className="hint">段落问题：{item.issues.slice(0, 3).join("；")}</p> : null}
                      </article>
                    ))}
                  </div>
                ) : null}
              </section>
            ) : null}

            <div className="chapter-panel__actions">
              <button className="btn" type="button" onClick={() => void onStartGeneration()} disabled={isBusy}>
                {isGenerating ? generationStatus ?? "生成中..." : mainActionLabel(story)}
              </button>
              <button className="btn btn--ghost" type="button" onClick={() => void onRollbackChapter()} disabled={isBusy || !hasStory}>
                回滚上一章
              </button>
            </div>

            {error ? <p className="hint chapter-panel__error">错误：{error}</p> : null}
            {isGenerating && generationStatus ? <p className="hint">生成进度：{generationStatus}</p> : null}
            {isRevising && revisionStatus ? <p className="hint">改稿进度：{revisionStatus}</p> : null}
          </div>
        )}
      </div>
    </section>
  );
}
