"use client";

import { useMemo } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";

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
  const issues = [...(quality?.issues ?? []), ...(writingReview?.issues ?? [])];

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
        </div>
      ) : (
        <div className="ws-empty">
          <p className="ws-empty__title">还没有可审稿章节</p>
        </div>
      )}
    </div>
  );
}
