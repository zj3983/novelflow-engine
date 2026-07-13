"use client";

import { useMemo } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { SimplifiedReview } from "../../../../components/ws/SimplifiedReview";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";

export default function ReviewPage() {
  const searchParams = useSearchParams();
  const { project, story, error, encodedProjectId } = useProjectWorkspace();
  const requestedChapter = Number(searchParams?.get("chapter") || story?.current_chapter || 0);
  const chapter = useMemo(() => {
    const history = story?.history ?? [];
    return history.find((bundle) => bundle.chapter_number === requestedChapter) ?? history.at(-1) ?? null;
  }, [requestedChapter, story?.history]);

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title={chapter ? `审稿：第 ${chapter.chapter_number} 章` : "审稿"}
        subtitle={chapter?.chapter_title || "查看必须修复的问题和局部修改建议。"}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : chapter ? (
        <SimplifiedReview report={chapter.quality_report?.simplified_review} />
      ) : (
        <div className="ws-empty">
          <p className="ws-empty__title">还没有可审稿章节</p>
        </div>
      )}
    </div>
  );
}
