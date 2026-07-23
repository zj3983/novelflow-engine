"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { WritingFlowPanel } from "../../../../components/ws/WritingFlow";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { SimplifiedReview } from "../../../../components/ws/SimplifiedReview";
import {
  fetchGenerationJob,
  fetchProjectWritingPacket,
  startFileProjectRegenerationJob,
  startGenerationJob,
  type ChapterBundle,
  type ChapterDirectionOption,
  type CodexWritingPacket,
  type GenerationJobStep,
} from "../../../../lib/api";

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

export default function WritePage() {
  const searchParams = useSearchParams();
  const { project, story, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [regenerating, setRegenerating] = useState(false);
  const [generatingNext, setGeneratingNext] = useState(false);
  const [regenerateStatus, setRegenerateStatus] = useState<string | null>(null);
  const [generationSteps, setGenerationSteps] = useState<GenerationJobStep[]>([]);
  const [regenerateError, setRegenerateError] = useState<string | null>(null);
  const [temporaryGuidance, setTemporaryGuidance] = useState("");
  const [nextWritingPacket, setNextWritingPacket] = useState<CodexWritingPacket | null>(null);
  const [selectedDirectionId, setSelectedDirectionId] = useState("");

  useEffect(() => {
    setPage(1);
  }, [query]);

  const history = story?.history ?? [];
  const requestedChapter = Number(searchParams?.get("chapter") || story?.current_chapter || 0);
  const chapter = useMemo(() => {
    return history.find((bundle) => bundle.chapter_number === requestedChapter) ?? history.at(-1) ?? null;
  }, [history, requestedChapter]);
  const guidanceStorageKey = chapter ? `book-dissection-guidance:${projectId}:${chapter.chapter_number}` : "";

  useEffect(() => {
    if (!chapter || searchParams?.get("guidance") !== "dissection") {
      setTemporaryGuidance("");
      return;
    }
    try {
      const raw = window.sessionStorage.getItem(guidanceStorageKey);
      const payload = raw ? JSON.parse(raw) : null;
      setTemporaryGuidance(typeof payload?.guidance === "string" ? payload.guidance : "");
    } catch {
      setTemporaryGuidance("");
    }
  }, [chapter, guidanceStorageKey, searchParams]);

  function clearTemporaryGuidance() {
    if (guidanceStorageKey) {
      window.sessionStorage.removeItem(guidanceStorageKey);
    }
    setTemporaryGuidance("");
  }

  const normalizedQuery = query.trim().toLowerCase();
  const filteredBundles = useMemo(() => {
    const sorted = [...history].reverse();
    if (!normalizedQuery) return sorted;
    return sorted.filter((bundle) => chapterSearchText(bundle).includes(normalizedQuery));
  }, [history, normalizedQuery]);
  const totalPages = Math.max(1, Math.ceil(filteredBundles.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visibleBundles = filteredBundles.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const isFileProject = projectId.startsWith("file:") || project?.storage_source === "file";
  const canRegenerate = Boolean(chapter && isFileProject);
  const generationTargetId = isFileProject ? projectId : story?.story_id;
  const canGenerateNext = Boolean(generationTargetId);
  const nextChapterNumber = (story?.current_chapter ?? 0) + 1;

  useEffect(() => {
    let cancelled = false;
    if (!isFileProject || !projectId) {
      setNextWritingPacket(null);
      setSelectedDirectionId("");
      return;
    }
    fetchProjectWritingPacket(projectId, nextChapterNumber)
      .then((packet) => {
        if (cancelled) return;
        const options = packet.chapter_direction_options;
        setNextWritingPacket(packet);
        setSelectedDirectionId((current) => {
          if (current && options?.options.some((item) => item.id === current)) {
            return current;
          }
          return options?.recommended_id || options?.options[0]?.id || "";
        });
      })
      .catch(() => {
        if (cancelled) return;
        setNextWritingPacket(null);
        setSelectedDirectionId("");
      });
    return () => {
      cancelled = true;
    };
  }, [isFileProject, nextChapterNumber, projectId]);

  const directionOptions = nextWritingPacket?.chapter_direction_options?.options ?? [];
  const selectedDirection = directionOptions.find((option) => option.id === selectedDirectionId) ?? directionOptions[0] ?? null;
  const writingReview = chapter?.quality_report?.writing_review;
  const lengthReview = chapter?.quality_report?.length_review ?? writingReview?.length_review;
  const bodyChars = lengthReview?.body_chars ?? chapterCharCount(chapter?.body);
  const minChars = lengthReview?.min_chars ?? 3800;
  const maxChars = lengthReview?.max_chars ?? 5500;
  const lengthPassed = lengthReview?.pass ?? bodyChars >= minChars;
  const lengthIssues = lengthReview?.issues ?? [];
  const writingLessons = story?.writing_lessons ?? [];

  async function handleRegenerateChapter() {
    if (!chapter || !canRegenerate) return;
    setRegenerating(true);
    setRegenerateStatus("排队中");
    setRegenerateError(null);
    try {
      const job = await startFileProjectRegenerationJob(projectId, chapter.chapter_number, undefined, temporaryGuidance || undefined);
      let currentJob = job;
      setGenerationSteps(Array.isArray(job.steps) ? job.steps : []);
      setRegenerateStatus(currentJob.progress || currentJob.status);
      while (currentJob.status === "queued" || currentJob.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        currentJob = await fetchGenerationJob(projectId, currentJob.job_id);
        setGenerationSteps(Array.isArray(currentJob.steps) ? currentJob.steps : []);
        setRegenerateStatus(currentJob.progress || currentJob.status);
      }
      if (currentJob.status === "failed") {
        throw new Error(currentJob.error || "regenerate_failed");
      }
      clearTemporaryGuidance();
      refresh();
    } catch (err) {
      setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      setRegenerating(false);
      setRegenerateStatus(null);
    }
  }

  async function handleGenerateNextChapter() {
    if (!generationTargetId || !canGenerateNext) return;
    setGeneratingNext(true);
    setRegenerateStatus("排队中");
    setRegenerateError(null);
    try {
      const job = await startGenerationJob(generationTargetId, isFileProject ? selectedDirection?.id : undefined);
      let currentJob = job;
      setGenerationSteps(Array.isArray(job.steps) ? job.steps : []);
      setRegenerateStatus(currentJob.progress || currentJob.status);
      while (currentJob.status === "queued" || currentJob.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        currentJob = await fetchGenerationJob(generationTargetId, currentJob.job_id);
        setGenerationSteps(Array.isArray(currentJob.steps) ? currentJob.steps : []);
        setRegenerateStatus(currentJob.progress || currentJob.status);
      }
      if (currentJob.status === "failed") {
        throw new Error(currentJob.error || "generate_next_failed");
      }
      refresh();
    } catch (err) {
      setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      setGeneratingNext(false);
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
                  className="ws-btn ws-btn--sm ws-btn--primary"
                  type="button"
                  disabled={!canGenerateNext || regenerating || generatingNext}
                  onClick={() => void handleGenerateNextChapter()}
                >
                  {generatingNext ? "生成中..." : "生成下一章"}
                </button>
                <button
                  className="ws-btn ws-btn--sm"
                  type="button"
                  disabled={!canRegenerate || regenerating || generatingNext}
                  onClick={() => void handleRegenerateChapter()}
                >
                  {regenerating ? "重新生成中..." : "重新生成本章"}
                </button>
                <span className="ws-badge">{chapterCharCount(chapter.body)} 字</span>
              </div>
            </header>

            {(regenerating || generatingNext || generationSteps.length > 0) ? (
              <section className="ws-card">
                <div className="ws-section-head">
                  <p className="ws-card__title">生成任务</p>
                  <span className="ws-badge">
                    {regenerateStatus || generationSteps[generationSteps.length - 1]?.message || "准备中"}
                  </span>
                </div>
                <WritingFlowPanel steps={generationSteps} />
                <p className="ws-card__hint">
                  <Link href={`/projects/${encodedProjectId}/log`}>查看日志页，获取完整历史记录 →</Link>
                </p>
              </section>
            ) : null}

            {regenerateError ? <p className="ws-error">任务失败：{regenerateError}</p> : null}
            {directionOptions.length > 0 ? (
              <section className="ws-card">
                <div className="ws-section-head">
                  <div>
                    <p className="ws-card__title">下一章方向</p>
                    <p className="ws-card__hint">生成前先选剧情分支，系统会锁定本章目标、哇点和章末钩子。</p>
                  </div>
                  {selectedDirection ? <span className="ws-badge">已选：{selectedDirection.name}</span> : null}
                </div>
                <div className="ws-simple-grid">
                  {directionOptions.map((option: ChapterDirectionOption) => {
                    const active = option.id === selectedDirectionId;
                    return (
                      <button
                        key={option.id}
                        className={`ws-simple-item${active ? " ws-simple-item--active" : ""}`}
                        type="button"
                        onClick={() => setSelectedDirectionId(option.id)}
                        style={{
                          textAlign: "left",
                          cursor: "pointer",
                          borderColor: active ? "var(--ws-accent)" : undefined,
                        }}
                      >
                        <strong>
                          {option.name}
                          {option.recommended ? " · 推荐" : ""}
                        </strong>
                        <span>{option.reader_promise}</span>
                        <small>{option.ending_hook}</small>
                      </button>
                    );
                  })}
                </div>
                {selectedDirection ? <p className="ws-card__hint">本章目标：{selectedDirection.chapter_goal}</p> : null}
              </section>
            ) : null}
            {temporaryGuidance ? (
              <section className="ws-card">
                <div className="ws-section-head">
                  <div>
                    <p className="ws-card__title">本次重写提示</p>
                    <p className="ws-card__hint">来自拆书报告，只影响这次重新生成，不会写入作者约束。</p>
                  </div>
                  <button className="ws-btn ws-btn--sm" type="button" onClick={clearTemporaryGuidance}>
                    清除
                  </button>
                </div>
                <ul className="ws-plain-list">
                  {temporaryGuidance.split("\n").map((line, index) => (
                    <li key={index}>{line}</li>
                  ))}
                </ul>
              </section>
            ) : null}
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
                <p className="ws-card__title">写作学习</p>
                {writingLessons.length ? (
                  <p className="ws-card__hint">{writingLessons.slice(-2).join("；")}</p>
                ) : (
                  <p className="ws-card__hint">暂无项目写作经验。</p>
                )}
              </div>
              <div>
                <p className="ws-card__title">字数检查</p>
                <p className="ws-card__hint">
                  {bodyChars} / {minChars}-{maxChars} 字；{lengthPassed ? "通过" : "未达标"}
                </p>
                {lengthIssues[0] ? <p className="ws-card__hint">{lengthIssues[0]}</p> : null}
              </div>
              <SimplifiedReview report={chapter.quality_report?.simplified_review} compact />
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
