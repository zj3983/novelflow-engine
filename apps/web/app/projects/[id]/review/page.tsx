"use client";

import { useMemo } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";

function formatAiScore(score: number | undefined): string {
  return typeof score === "number" ? `${score}/8` : "未检测";
}

function formatAiMetric(metrics: Record<string, number> | undefined, key: string): number {
  const value = metrics?.[key];
  return typeof value === "number" ? value : 0;
}

function formatConcreteDensity(metrics: Record<string, number> | undefined): string {
  const value = metrics?.concrete_density;
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—";
}

function formatReviewIssue(issue: unknown): string {
  if (!issue) return "";
  if (typeof issue === "string") return issue;
  if (typeof issue === "object" && "reason" in issue) {
    return String((issue as { reason?: unknown }).reason || "");
  }
  return String(issue);
}

export default function ReviewPage() {
  const searchParams = useSearchParams();
  const { project, story, error, encodedProjectId } = useProjectWorkspace();
  const requestedChapter = Number(searchParams?.get("chapter") || story?.current_chapter || 0);
  const chapter = useMemo(() => {
    const history = story?.history ?? [];
    return history.find((bundle) => bundle.chapter_number === requestedChapter) ?? history.at(-1) ?? null;
  }, [requestedChapter, story?.history]);
  const quality = chapter?.quality_report;
  const writingReview = quality?.writing_review;
  const aiFlavorReview = quality?.ai_flavor_review ?? writingReview?.ai_flavor_review;
  const aiFlavorMetrics = aiFlavorReview?.metrics;
  const aiFlavorScore = aiFlavorReview?.scores?.ai_flavor;
  const aiFlavorIssues = aiFlavorReview?.issues ?? [];
  const aiFlavorCuts = aiFlavorReview?.cuts ?? [];
  const readerAgentReview = quality?.reader_agent_review ?? writingReview?.reader_agent_review;
  const editorAgentReview = quality?.editor_agent_review ?? writingReview?.editor_agent_review;
  const reviewerAgentReview = quality?.reviewer_agent_review ?? writingReview?.reviewer_agent_review;
  const issues = Array.from(
    new Set([...(quality?.issues ?? []), ...(writingReview?.issues ?? []), ...aiFlavorIssues].map(formatReviewIssue).filter(Boolean))
  );

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title={chapter ? `审稿：第 ${chapter.chapter_number} 章` : "审稿"}
        subtitle={chapter?.chapter_title || "查看章节质量、复审意见和修改建议。"}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : chapter ? (
        <div className="ws-stat-row">
          <div className="ws-card">
            <p className="ws-card__title">质量状态</p>
            <p className="ws-card__value">{quality?.ok ? "通过" : "待修"}</p>
            <p className="ws-card__hint">基础质量检查</p>
          </div>
          <div className="ws-card">
            <p className="ws-card__title">写作复审</p>
            <p className="ws-card__value">{writingReview?.pass ? "通过" : "待修"}</p>
            <p className="ws-card__hint">结构、规则和连续性</p>
          </div>
          <div className="ws-card">
            <p className="ws-card__title">问题数</p>
            <p className="ws-card__value">{issues.length}</p>
            <p className="ws-card__hint">合并质量报告与写作复审</p>
          </div>
          <div className="ws-card">
            <p className="ws-card__title">AI味</p>
            <p className="ws-card__value">{formatAiScore(aiFlavorScore)}</p>
            <p className="ws-card__hint">
              公式句 {formatAiMetric(aiFlavorMetrics, "formula_count")} · 抽象词 {formatAiMetric(aiFlavorMetrics, "abstract_count")} ·
              具体度 {formatConcreteDensity(aiFlavorMetrics)}
            </p>
          </div>
          <div className="ws-card">
            <p className="ws-card__title">读者 Agent</p>
            <p className="ws-card__value">{readerAgentReview?.pass ? "通过" : "待修"}</p>
            <p className="ws-card__hint">{readerAgentReview?.verdict || "暂无读者报告"}</p>
          </div>
          <div className="ws-card">
            <p className="ws-card__title">编辑 Agent</p>
            <p className="ws-card__value">{editorAgentReview?.pass ? "通过" : "待修"}</p>
            <p className="ws-card__hint">{editorAgentReview?.verdict || "暂无编辑报告"}</p>
          </div>
          <div className="ws-card">
            <p className="ws-card__title">审稿 Agent</p>
            <p className="ws-card__value">{reviewerAgentReview?.pass ? "通过" : "待修"}</p>
            <p className="ws-card__hint">{reviewerAgentReview?.verdict || "暂无审稿报告"}</p>
          </div>
          <section className="ws-card" style={{ gridColumn: "1 / -1" }}>
            <p className="ws-card__title">Agent 分工意见</p>
            <ul className="ws-plain-list">
              <li>读者：{readerAgentReview?.issues?.[0] ? formatReviewIssue(readerAgentReview.issues[0]) : readerAgentReview?.verdict || "暂无"}</li>
              <li>编辑：{editorAgentReview?.issues?.[0] ? formatReviewIssue(editorAgentReview.issues[0]) : editorAgentReview?.verdict || "暂无"}</li>
              <li>审稿：{reviewerAgentReview?.issues?.[0] ? formatReviewIssue(reviewerAgentReview.issues[0]) : reviewerAgentReview?.verdict || "暂无"}</li>
            </ul>
          </section>
          <section className="ws-card" style={{ gridColumn: "1 / -1" }}>
            <p className="ws-card__title">审稿意见</p>
            {issues.length > 0 ? (
              <ul className="ws-plain-list">
                {issues.map((issue, index) => (
                  <li key={`${issue}-${index}`}>{issue}</li>
                ))}
              </ul>
            ) : (
              <p className="ws-card__hint">当前章节没有必须处理的问题。</p>
            )}
          </section>
          {aiFlavorReview ? (
            <section className="ws-card" style={{ gridColumn: "1 / -1" }}>
              <p className="ws-card__title">AI味命中</p>
              {aiFlavorCuts.length > 0 ? (
                <ul className="ws-plain-list">
                  {aiFlavorCuts.slice(0, 8).map((cut, index) => (
                    <li key={`${cut.type}-${cut.target_text}-${index}`}>
                      {cut.target_text ? `“${cut.target_text}”` : cut.reason || "模型腔命中"}：{cut.suggestion || cut.reason}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="ws-card__hint">没有明显模型腔。</p>
              )}
            </section>
          ) : null}
        </div>
      ) : (
        <div className="ws-empty">
          <p className="ws-empty__title">还没有可审稿章节</p>
        </div>
      )}
    </div>
  );
}
