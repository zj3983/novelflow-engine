"use client";

import Link from "next/link";
import { Check, Copy } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { useChapterDetail } from "../../../../components/ws/useChapterDetail";
import { SimplifiedReview } from "../../../../components/ws/SimplifiedReview";
import { resolveChapterDirectionId } from "../../../../lib/chapterDirections";
import {
  downstreamRewriteNotice,
  confirmFileProjectCandidate,
  discardFileProjectCandidate,
  fetchFileProjectCandidates,
  fetchGenerationJob,
  fetchProjectWritingPacket,
  startFileProjectRegenerationJob,
  startGenerationJob,
  type ChapterIndexEntry,
  type ChapterDirectionOption,
  type CandidateDraft,
  type CodexWritingPacket,
  type GenerationJobStep,
} from "../../../../lib/api";

const PAGE_SIZE = 80;

function WritingProgressRow({ status, href }: { status: string; href: string }) {
  return (
    <section className="ws-writing-progress" aria-label="工作进度">
      <strong>工作进度</strong>
      <span className="ws-writing-progress__status" title={status}>{status}</span>
      <Link href={href}>查看完整日志</Link>
    </section>
  );
}

function CandidatePanel({
  candidate,
  action,
  onConfirm,
  onDiscard,
}: {
  candidate: CandidateDraft;
  action: "confirm" | "discard" | null;
  onConfirm: () => void;
  onDiscard: () => void;
}) {
  return (
    <section className="ws-card" aria-label="候选稿">
      <div className="ws-section-head">
        <div>
          <p className="ws-card__title">候选稿，尚未提交</p>
          <p className="ws-card__hint">
            第 {candidate.chapter_number} 章 · {chapterCharCount(candidate.body)} 字 · 快照 {candidate.context_snapshot_id || "未记录"}
          </p>
        </div>
        <div className="ws-toolbar">
          <button className="ws-btn ws-btn--sm" type="button" disabled={Boolean(action)} onClick={onDiscard}>
            {action === "discard" ? "丢弃中..." : "丢弃候选稿"}
          </button>
          <button className="ws-btn ws-btn--sm ws-btn--primary" type="button" disabled={Boolean(action)} onClick={onConfirm}>
            {action === "confirm" ? "提交中..." : "确认提交"}
          </button>
        </div>
      </div>
      <article className="ws-reader__body" style={{ maxHeight: 360, overflow: "auto" }}>
        {candidate.body.split(/\n{2,}/).slice(0, 12).map((paragraph, index) => (
          <p key={index}>{paragraph}</p>
        ))}
      </article>
    </section>
  );
}

type CopyStatus = "idle" | "copied" | "failed";

function chapterCopyText(chapterNumber: number, chapterTitle: string | undefined, body: string): string {
  const heading = [`第 ${chapterNumber} 章`, chapterTitle?.trim()].filter(Boolean).join(" ");
  return `${heading}\n\n${body.trim()}`;
}

async function writeTextToClipboard(text: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
  } catch {
    // Some browsers expose Clipboard API but reject it outside a secure context.
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("copy_failed");
}

function chapterCharCount(body: string | undefined): number {
  if (!body) return 0;
  return body.replace(/\s+/g, "").length;
}

function chapterSearchText(bundle: ChapterIndexEntry): string {
  return [
    String(bundle.chapter_number),
    bundle.chapter_title || "",
    bundle.summary || "",
    bundle.next_focus || "",
  ]
    .join(" ")
    .toLowerCase();
}

export default function WritePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { project, story, chapterIndex, error, encodedProjectId, projectId, refreshVersion, refresh } = useProjectWorkspace();
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
  const [copyStatus, setCopyStatus] = useState<CopyStatus>("idle");
  const [pendingCandidate, setPendingCandidate] = useState<CandidateDraft | null>(null);
  const [candidateAction, setCandidateAction] = useState<"confirm" | "discard" | null>(null);
  const mountedRef = useRef(false);
  const operationTokenRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      operationTokenRef.current += 1;
    };
  }, []);

  useEffect(() => {
    setPage(1);
  }, [query]);

  const requestedChapter = Number(searchParams?.get("chapter") || story?.current_chapter || chapterIndex.at(-1)?.chapter_number || 0);
  const { chapter, loading: chapterLoading, error: chapterError } = useChapterDetail({
    projectId,
    story: story ?? null,
    chapterNumber: requestedChapter,
    refreshVersion,
  });
  const guidanceStorageKey = chapter ? `book-dissection-guidance:${projectId}:${chapter.chapter_number}` : "";

  useEffect(() => {
    setCopyStatus("idle");
  }, [chapter?.chapter_number]);

  useEffect(() => {
    if (copyStatus !== "copied") return;
    const timeout = window.setTimeout(() => setCopyStatus("idle"), 1800);
    return () => window.clearTimeout(timeout);
  }, [copyStatus]);

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
    const sorted = [...chapterIndex].reverse();
    if (!normalizedQuery) return sorted;
    return sorted.filter((bundle) => chapterSearchText(bundle).includes(normalizedQuery));
  }, [chapterIndex, normalizedQuery]);
  const totalPages = Math.max(1, Math.ceil(filteredBundles.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const visibleBundles = filteredBundles.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const isFileProject = projectId.startsWith("file:") || project?.storage_source === "file";
  const canRegenerate = Boolean(
    chapter &&
      isFileProject &&
      !chapterLoading &&
      chapter.chapter_number === requestedChapter,
  );
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
        setSelectedDirectionId((current) =>
          resolveChapterDirectionId(current, options?.options, options?.recommended_id),
        );
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

  useEffect(() => {
    let cancelled = false;
    if (!isFileProject || !projectId) {
      setPendingCandidate(null);
      return;
    }
    const chapterNumbers = Array.from(new Set([requestedChapter, nextChapterNumber].filter((value) => value > 0)));
    Promise.all(chapterNumbers.map((number) => fetchFileProjectCandidates(projectId, number)))
      .then((responses) => {
        if (cancelled) return;
        const pending = responses
          .flatMap((response) => response.items)
          .filter((item) => item.status === "pending")
          .sort((left, right) => left.created_at.localeCompare(right.created_at));
        setPendingCandidate(pending.at(-1) ?? null);
      })
      .catch(() => {
        if (!cancelled) setPendingCandidate(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isFileProject, projectId, requestedChapter, nextChapterNumber, refreshVersion]);

  const directionOptions = nextWritingPacket?.chapter_direction_options?.options ?? [];
  const selectedDirection = directionOptions.find((option) => option.id === selectedDirectionId) ?? directionOptions[0] ?? null;
  const writingReview = chapter?.quality_report?.writing_review;
  const downstreamNotice = downstreamRewriteNotice(chapter?.quality_report);
  const lengthReview = chapter?.quality_report?.length_review ?? writingReview?.length_review;
  const bodyChars = lengthReview?.body_chars ?? chapterCharCount(chapter?.body);
  const minChars = lengthReview?.min_chars ?? 3800;
  const maxChars = lengthReview?.max_chars ?? 5500;
  const lengthPassed = lengthReview?.pass ?? bodyChars >= minChars;
  const lengthIssues = lengthReview?.issues ?? [];
  const writingLessons = story?.writing_lessons ?? [];

  async function loadPendingCandidate(chapterNumber: number): Promise<void> {
    if (!isFileProject) return;
    const response = await fetchFileProjectCandidates(projectId, chapterNumber);
    const pending = response.items
      .filter((item) => item.status === "pending")
      .sort((left, right) => left.created_at.localeCompare(right.created_at))
      .at(-1) ?? null;
    setPendingCandidate(pending);
  }

  async function handleRegenerateChapter() {
    if (!chapter || !canRegenerate || chapterLoading || chapter.chapter_number !== requestedChapter) return;
    const operationToken = ++operationTokenRef.current;
    const operationIsActive = () => mountedRef.current && operationTokenRef.current === operationToken;
    setRegenerating(true);
    setRegenerateStatus("排队中");
    setRegenerateError(null);
    try {
      const job = await startFileProjectRegenerationJob(projectId, chapter.chapter_number, undefined, temporaryGuidance || undefined);
      if (!operationIsActive()) return;
      let currentJob = job;
      setGenerationSteps(Array.isArray(job.steps) ? job.steps : []);
      setRegenerateStatus(currentJob.progress || currentJob.status);
      while (currentJob.status === "queued" || currentJob.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        if (!operationIsActive()) return;
        currentJob = await fetchGenerationJob(projectId, currentJob.job_id);
        if (!operationIsActive()) return;
        setGenerationSteps(Array.isArray(currentJob.steps) ? currentJob.steps : []);
        setRegenerateStatus(currentJob.progress || currentJob.status);
      }
      if (currentJob.status === "failed") {
        throw new Error(currentJob.error || "regenerate_failed");
      }
      if (!operationIsActive()) return;
      clearTemporaryGuidance();
      const completedChapterNumber = Number(currentJob.chapter_number) || chapter.chapter_number;
      await loadPendingCandidate(completedChapterNumber);
    } catch (err) {
      if (operationIsActive()) setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      if (operationIsActive()) {
        setRegenerating(false);
        setRegenerateStatus(null);
      }
    }
  }

  async function handleGenerateNextChapter() {
    if (!generationTargetId || !canGenerateNext) return;
    const operationToken = ++operationTokenRef.current;
    const operationIsActive = () => mountedRef.current && operationTokenRef.current === operationToken;
    setGeneratingNext(true);
    setRegenerateStatus("排队中");
    setRegenerateError(null);
    try {
      const job = await startGenerationJob(generationTargetId, isFileProject ? selectedDirection?.id : undefined);
      if (!operationIsActive()) return;
      let currentJob = job;
      setGenerationSteps(Array.isArray(job.steps) ? job.steps : []);
      setRegenerateStatus(currentJob.progress || currentJob.status);
      while (currentJob.status === "queued" || currentJob.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        if (!operationIsActive()) return;
        currentJob = await fetchGenerationJob(generationTargetId, currentJob.job_id);
        if (!operationIsActive()) return;
        setGenerationSteps(Array.isArray(currentJob.steps) ? currentJob.steps : []);
        setRegenerateStatus(currentJob.progress || currentJob.status);
      }
      if (currentJob.status === "failed") {
        throw new Error(currentJob.error || "generate_next_failed");
      }
      if (!operationIsActive()) return;
      const completedChapterNumber = Number(currentJob.chapter_number);
      const generatedChapterNumber = Number.isInteger(completedChapterNumber) && completedChapterNumber > 0
        ? completedChapterNumber
        : nextChapterNumber;
      await loadPendingCandidate(generatedChapterNumber);
    } catch (err) {
      if (operationIsActive()) setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      if (operationIsActive()) {
        setGeneratingNext(false);
        setRegenerateStatus(null);
      }
    }
  }

  async function handleConfirmCandidate() {
    if (!pendingCandidate || !isFileProject || candidateAction) return;
    setCandidateAction("confirm");
    setRegenerateError(null);
    try {
      await confirmFileProjectCandidate(projectId, pendingCandidate.candidate_id);
      setPendingCandidate(null);
      void refresh().catch(() => undefined);
      router.replace(`/projects/${encodedProjectId}/write?chapter=${pendingCandidate.chapter_number}`);
    } catch (err) {
      setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      setCandidateAction(null);
    }
  }

  async function handleDiscardCandidate() {
    if (!pendingCandidate || !isFileProject || candidateAction) return;
    setCandidateAction("discard");
    setRegenerateError(null);
    try {
      await discardFileProjectCandidate(projectId, pendingCandidate.candidate_id);
      setPendingCandidate(null);
    } catch (err) {
      setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      setCandidateAction(null);
    }
  }

  async function handleCopyChapter() {
    if (!chapter) return;
    try {
      await writeTextToClipboard(chapterCopyText(chapter.chapter_number, chapter.chapter_title, chapter.body));
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
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
      ) : chapterIndex.length > 0 ? (
        <div className="ws-editor-layout ws-editor-layout--chapters">
          <aside className="ws-sidepanel ws-chapter-index" aria-label="章节目录">
            <section className="ws-card">
              <div className="ws-section-head">
                <p className="ws-card__title">目录</p>
                <span className="ws-toolbar__meta">{chapterIndex.length} 章</span>
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
                  const active = bundle.chapter_number === requestedChapter;
                  return (
                    <Link
                      key={bundle.chapter_number}
                      href={`/projects/${encodedProjectId}/write?chapter=${bundle.chapter_number}#chapter-reader`}
                      className={`ws-chapter-list__item${active ? " ws-chapter-list__item--active" : ""}`}
                      aria-current={active ? "page" : undefined}
                    >
                      <span>第 {bundle.chapter_number} 章</span>
                      <strong>{bundle.chapter_title || "未命名"}</strong>
                      <small>{bundle.body_chars} 字</small>
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

          <article className="ws-reader" id="chapter-reader">
            {chapterError ? (
              <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
                <p style={{ color: "var(--ws-danger)", margin: 0 }}>章节加载失败：{chapterError}</p>
              </div>
            ) : chapter ? (
              <>
            <header className="ws-reader__head">
              <div>
                <p className="ws-card__title">正文</p>
                <h2>{chapter.chapter_title || "未命名章节"}</h2>
              </div>
              <div className="ws-toolbar">
                <button
                  className="ws-btn ws-btn--sm"
                  type="button"
                  title="复制章节标题和正文"
                  onClick={() => void handleCopyChapter()}
                >
                  {copyStatus === "copied" ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
                  {copyStatus === "copied" ? "已复制" : "复制章节"}
                </button>
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
            {copyStatus === "failed" ? <p className="ws-error" role="alert">复制失败，请允许浏览器访问剪贴板后重试。</p> : null}

            {(regenerating || generatingNext || generationSteps.length > 0) ? (
              <WritingProgressRow
                status={regenerateStatus || generationSteps[generationSteps.length - 1]?.message || "准备中"}
                href={`/projects/${encodedProjectId}/log`}
              />
            ) : null}

            {regenerateError ? <p className="ws-error">任务失败：{regenerateError}</p> : null}
            {pendingCandidate ? (
              <CandidatePanel
                candidate={pendingCandidate}
                action={candidateAction}
                onDiscard={() => void handleDiscardCandidate()}
                onConfirm={() => void handleConfirmCandidate()}
              />
            ) : null}
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
              {downstreamNotice ? (
                <div>
                  <p className="ws-card__title">章节连续性</p>
                  <p className="ws-card__hint">{downstreamNotice}</p>
                </div>
              ) : null}
              <SimplifiedReview report={chapter.quality_report?.simplified_review} compact />
            </section>
              </>
            ) : chapterLoading ? (
              <div className="ws-empty"><p className="ws-empty__title">正在加载章节...</p></div>
            ) : (
              <div className="ws-empty"><p className="ws-empty__title">没有找到该章节</p></div>
            )}
          </article>
        </div>
      ) : (
        <div className="ws-empty">
          <p className="ws-empty__title">还没有可阅读章节</p>
          <p className="ws-empty__hint">生成第一章后会在这里显示目录和正文。</p>
          <button
            className="ws-btn ws-btn--primary"
            type="button"
            disabled={!canGenerateNext || generatingNext}
            onClick={() => void handleGenerateNextChapter()}
          >
            {generatingNext ? "生成中..." : "生成第一章"}
          </button>
          {(generatingNext || generationSteps.length > 0) ? (
            <WritingProgressRow
              status={regenerateStatus || generationSteps[generationSteps.length - 1]?.message || "准备中"}
              href={`/projects/${encodedProjectId}/log`}
            />
          ) : null}
          {regenerateError ? <p className="ws-error">任务失败：{regenerateError}</p> : null}
          {pendingCandidate ? (
            <CandidatePanel
              candidate={pendingCandidate}
              action={candidateAction}
              onDiscard={() => void handleDiscardCandidate()}
              onConfirm={() => void handleConfirmCandidate()}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}
