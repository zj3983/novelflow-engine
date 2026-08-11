"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { ShuangwenReview, SimplifiedReview } from "../../../../components/ws/SimplifiedReview";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { useChapterDetail } from "../../../../components/ws/useChapterDetail";
import {
  runFileProjectShuangwenReview,
  type ShuangwenSkillReview,
} from "../../../../lib/api";

export default function ReviewPage() {
  const searchParams = useSearchParams();
  const { project, story, chapterIndex, error, encodedProjectId, projectId, refreshVersion } = useProjectWorkspace();
  const [shuangwenReport, setShuangwenReport] = useState<ShuangwenSkillReview | undefined>();
  const [shuangwenLoading, setShuangwenLoading] = useState(false);
  const [shuangwenError, setShuangwenError] = useState("");
  const shuangwenRequestSequence = useRef(0);
  const requestedChapter = Number(searchParams?.get("chapter") || story?.current_chapter || chapterIndex.at(-1)?.chapter_number || 0);
  const { chapter, loading: chapterLoading, error: chapterError } = useChapterDetail({
    projectId,
    story: story ?? null,
    chapterNumber: requestedChapter,
    refreshVersion,
  });
  const selectedIndex = chapterIndex.find((entry) => entry.chapter_number === requestedChapter) ?? null;
  const selectedChapter = chapter?.chapter_number === requestedChapter ? chapter : null;
  const storedShuangwenReport = selectedChapter?.quality_report?.skill_reviews?.["commercial-shuangwen"];
  const shuangwenPackEnabled = project?.enabled_skill_ids?.includes("commercial-shuangwen") ?? false;
  const reviewerModuleEnabled = project?.skill_module_selection_mode === "legacy_all"
    || project?.skill_module_selection_mode == null && project?.enabled_skill_module_ids == null
    || project?.enabled_skill_module_ids?.includes("commercial-shuangwen::review-checklist") === true;
  const shuangwenEnabled = Boolean(
    selectedChapter
    && shuangwenPackEnabled
    && reviewerModuleEnabled
    && (project?.storage_source === "file" || projectId.startsWith("file:")),
  );

  useEffect(() => {
    shuangwenRequestSequence.current += 1;
    setShuangwenReport(storedShuangwenReport);
    setShuangwenError("");
    setShuangwenLoading(false);
  }, [requestedChapter, storedShuangwenReport]);

  async function runShuangwenReview() {
    if (!shuangwenEnabled) return;
    const sequence = ++shuangwenRequestSequence.current;
    setShuangwenLoading(true);
    setShuangwenError("");
    try {
      const report = await runFileProjectShuangwenReview(projectId, requestedChapter);
      if (sequence === shuangwenRequestSequence.current) setShuangwenReport(report);
    } catch (reason) {
      const detail = reason instanceof Error ? reason.message : String(reason);
      if (sequence === shuangwenRequestSequence.current) {
        setShuangwenError(`爽文检查失败：${detail}`);
      }
    } finally {
      if (sequence === shuangwenRequestSequence.current) setShuangwenLoading(false);
    }
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title={requestedChapter > 0 ? `审稿：第 ${requestedChapter} 章` : "审稿"}
        subtitle={selectedIndex?.chapter_title || "查看必须修复的问题和局部修改建议。"}
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
            {selectedChapter ? <SimplifiedReview report={selectedChapter.quality_report?.simplified_review} /> : null}
            {shuangwenEnabled ? (
              <ShuangwenReview
                report={shuangwenReport}
                loading={shuangwenLoading}
                error={shuangwenError}
                onRun={() => void runShuangwenReview()}
              />
            ) : null}
            {chapterLoading && !selectedChapter ? <p className="ws-card__hint">正在加载章节...</p> : null}
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
