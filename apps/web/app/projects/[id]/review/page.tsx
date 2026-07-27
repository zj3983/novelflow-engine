"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { SimplifiedReview } from "../../../../components/ws/SimplifiedReview";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { useChapterDetail } from "../../../../components/ws/useChapterDetail";

export default function ReviewPage() {
  const searchParams = useSearchParams();
  const { project, story, chapterIndex, error, encodedProjectId, projectId, refreshVersion } = useProjectWorkspace();
  const requestedChapter = Number(searchParams?.get("chapter") || story?.current_chapter || chapterIndex.at(-1)?.chapter_number || 0);
  const { chapter, loading: chapterLoading, error: chapterError } = useChapterDetail({
    projectId,
    story: story ?? null,
    chapterNumber: requestedChapter,
    refreshVersion,
  });

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
      ) : chapterIndex.length ? (
        <div className="ws-editor-layout">
          <aside className="ws-sidepanel ws-chapter-index" aria-label="章节目录">
            <section className="ws-card">
              <p className="ws-card__title">章节</p>
              <div className="ws-chapter-list">
                {[...chapterIndex].reverse().map((entry) => (
                  <Link
                    key={entry.chapter_number}
                    href={`/projects/${encodedProjectId}/review?chapter=${entry.chapter_number}`}
                    className={`ws-chapter-list__item${entry.chapter_number === requestedChapter ? " ws-chapter-list__item--active" : ""}`}
                  >
                    <span>第 {entry.chapter_number} 章</span>
                    <strong>{entry.chapter_title || "未命名"}</strong>
                  </Link>
                ))}
              </div>
            </section>
          </aside>
          <main>
            {chapterError ? <p className="ws-inline-error" role="alert">章节加载失败：{chapterError}</p> : null}
            {chapter ? <SimplifiedReview report={chapter.quality_report?.simplified_review} /> : null}
            {chapterLoading && !chapter ? <p className="ws-card__hint">正在加载章节...</p> : null}
          </main>
        </div>
      ) : (
        <div className="ws-empty">
          <p className="ws-empty__title">还没有可审稿章节</p>
        </div>
      )}
    </div>
  );
}
