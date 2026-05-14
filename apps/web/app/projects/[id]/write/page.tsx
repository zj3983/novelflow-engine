"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { fetchGenerationJob, startFileProjectRegenerationJob, type ChapterBundle } from "../../../../lib/api";

const PAGE_SIZE = 80;

function chapterCharCount(body: string | undefined): number {
  if (!body) return 0;
  return body.replace(/\s+/g, "").length;
}

function chapterSearchText(bundle: ChapterBundle): string {
  return [
    String(bundle.chapter_number),
    bundle.chapter_title || "",
    bundle.chapter_summary?.summary || "",
    bundle.next_outline || "",
  ]
    .join(" ")
    .toLowerCase();
}

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

export default function WritePage() {
  const searchParams = useSearchParams();
  const { project, story, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [regenerating, setRegenerating] = useState(false);
  const [regenerateStatus, setRegenerateStatus] = useState<string | null>(null);
  const [regenerateError, setRegenerateError] = useState<string | null>(null);

  useEffect(() => {
    setPage(1);
  }, [query]);

  const history = story?.history ?? [];
  const requestedChapter = Number(searchParams?.get("chapter") || story?.current_chapter || 0);
  const chapter = useMemo(() => {
    return history.find((bundle) => bundle.chapter_number === requestedChapter) ?? history.at(-1) ?? null;
  }, [history, requestedChapter]);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredBundles = useMemo(() => {
    const sorted = [...history].reverse();
    if (!normalizedQuery) return sorted;
    return sorted.filter((bundle) => chapterSearchText(bundle).includes(normalizedQuery));
  }, [history, normalizedQuery]);
  const totalPages = Math.max(1, Math.ceil(filteredBundles.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visibleBundles = filteredBundles.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const canRegenerate = Boolean(chapter && project?.storage_source === "file");
  const aiFlavorReview = chapter?.quality_report?.ai_flavor_review;
  const aiFlavorMetrics = aiFlavorReview?.metrics;
  const aiFlavorScore = aiFlavorReview?.scores?.ai_flavor;
  const aiFlavorIssues = aiFlavorReview?.issues ?? [];
  const aiFlavorCuts = aiFlavorReview?.cuts ?? [];

  async function handleRegenerateChapter() {
    if (!chapter || !canRegenerate) return;
    setRegenerating(true);
    setRegenerateStatus("排队中");
    setRegenerateError(null);
    try {
      const job = await startFileProjectRegenerationJob(projectId, chapter.chapter_number);
      let currentJob = job;
      setRegenerateStatus(currentJob.progress || currentJob.status);
      while (currentJob.status === "queued" || currentJob.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        currentJob = await fetchGenerationJob(projectId, currentJob.job_id);
        setRegenerateStatus(currentJob.progress || currentJob.status);
      }
      if (currentJob.status === "failed") {
        throw new Error(currentJob.error || "regenerate_failed");
      }
      refresh();
    } catch (err) {
      setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      setRegenerating(false);
      setRegenerateStatus(null);
    }
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title={chapter ? `章节：第 ${chapter.chapter_number} 章` : "章节"}
        subtitle={chapter?.chapter_title || project?.current_focus || "目录和正文放在同一页。"}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : chapter ? (
        <div className="ws-editor-layout ws-editor-layout--chapters">
          <aside className="ws-sidepanel ws-chapter-index" aria-label="章节目录">
            <section className="ws-card">
              <div className="ws-section-head">
                <p className="ws-card__title">目录</p>
                <span className="ws-toolbar__meta">{history.length} 章</span>
              </div>
              <label className="ws-search ws-search--compact">
                <span>搜索</span>
                <input
                  className="ws-input"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="标题、章节号、摘要"
                />
              </label>
              <div className="ws-chapter-list">
                {visibleBundles.map((bundle) => {
                  const active = bundle.chapter_number === chapter.chapter_number;
                  return (
                    <Link
                      key={bundle.chapter_number}
                      href={`/projects/${encodedProjectId}/write?chapter=${bundle.chapter_number}`}
                      className={`ws-chapter-list__item${active ? " ws-chapter-list__item--active" : ""}`}
                      aria-current={active ? "page" : undefined}
                    >
                      <span>第 {bundle.chapter_number} 章</span>
                      <strong>{bundle.chapter_title || "未命名"}</strong>
                      <small>{chapterCharCount(bundle.body)} 字</small>
                    </Link>
                  );
                })}
              </div>
              {totalPages > 1 ? (
                <div className="ws-pagination" aria-label="章节分页">
                  <button
                    className="ws-btn ws-btn--sm"
                    type="button"
                    disabled={safePage <= 1}
                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                  >
                    上一页
                  </button>
                  <span>
                    {safePage} / {totalPages}
                  </span>
                  <button
                    className="ws-btn ws-btn--sm"
                    type="button"
                    disabled={safePage >= totalPages}
                    onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                  >
                    下一页
                  </button>
                </div>
              ) : null}
            </section>
          </aside>

          <article className="ws-reader">
            <header className="ws-reader__head">
              <div>
                <p className="ws-card__title">正文</p>
                <h2>{chapter.chapter_title || "未命名章节"}</h2>
              </div>
              <div className="ws-toolbar">
                <button
                  className="ws-btn ws-btn--sm"
                  type="button"
                  disabled={!canRegenerate || regenerating}
                  onClick={() => void handleRegenerateChapter()}
                >
                  {regenerating ? "重新推演中..." : "重新推演本章"}
                </button>
                <span className="ws-badge">{chapterCharCount(chapter.body)} 字</span>
              </div>
            </header>
            {regenerating && regenerateStatus ? <p className="ws-card__hint">重推进度：{regenerateStatus}</p> : null}
            {regenerateError ? <p className="ws-error">重新推演失败：{regenerateError}</p> : null}
            <div className="ws-reader__body">
              {chapter.body.split(/\n{2,}/).map((paragraph, index) => (
                <p key={index}>{paragraph}</p>
              ))}
            </div>
            <section className="ws-reader__notes">
              <div>
                <p className="ws-card__title">章节摘要</p>
                <p className="ws-card__hint">{chapter.chapter_summary?.summary || "暂无摘要。"}</p>
              </div>
              <div>
                <p className="ws-card__title">下一章焦点</p>
                <p className="ws-card__hint">{chapter.next_outline || "暂无下一章焦点。"}</p>
              </div>
              <div>
                <p className="ws-card__title">AI味检测</p>
                {aiFlavorReview ? (
                  <>
                    <p className="ws-card__hint">
                      评分 {formatAiScore(aiFlavorScore)}；公式句 {formatAiMetric(aiFlavorMetrics, "formula_count")}；抽象词{" "}
                      {formatAiMetric(aiFlavorMetrics, "abstract_count")}；具体度 {formatConcreteDensity(aiFlavorMetrics)}
                    </p>
                    {aiFlavorIssues[0] ? <p className="ws-card__hint">{aiFlavorIssues[0]}</p> : null}
                    {!aiFlavorIssues[0] && aiFlavorCuts[0]?.target_text ? (
                      <p className="ws-card__hint">留意：{aiFlavorCuts[0].target_text}</p>
                    ) : null}
                  </>
                ) : (
                  <p className="ws-card__hint">暂无AI味报告。</p>
                )}
              </div>
            </section>
          </article>
        </div>
      ) : (
        <div className="ws-empty">
          <p className="ws-empty__title">还没有可阅读章节</p>
          <p className="ws-empty__hint">生成第一章后会在这里显示目录和正文。</p>
        </div>
      )}
    </div>
  );
}
