"use client";

import Link from "next/link";
import { Check, Copy, Expand } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { useChapterDetail } from "../../../../components/ws/useChapterDetail";
import { SimplifiedReview } from "../../../../components/ws/SimplifiedReview";
import { RollingOutlineCard } from "../../../../components/ws/RollingOutlineCard";
import {
  downstreamRewriteNotice,
  confirmFileProjectCandidate,
  discardFileProjectCandidate,
  fetchFileProjectCandidates,
  fetchGenerationJob,
  fetchProjectWritingPacket,
  fetchVolumeWorkflow,
  startFileProjectRegenerationJob,
  startFileProjectExpansionJob,
  startGenerationJob,
  type ChapterIndexEntry,
  type CandidateDraft,
  type CodexWritingPacket,
  type GenerationJobStep,
  type VolumeWorkflowResponse,
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
  onForceConfirm,
  onDiscard,
}: {
  candidate: CandidateDraft;
  action: "confirm" | "force-confirm" | "discard" | null;
  onConfirm: () => void;
  onForceConfirm: () => void;
  onDiscard: () => void;
}) {
  const hasQualityWarnings = candidate.quality_report?.ok === false;
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
          {hasQualityWarnings ? (
            <button className="ws-btn ws-btn--sm" type="button" disabled={Boolean(action)} onClick={onForceConfirm}>
              {action === "force-confirm" ? "采用中..." : "仍然采用"}
            </button>
          ) : null}
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
  const [expanding, setExpanding] = useState(false);
  const [generatingNext, setGeneratingNext] = useState(false);
  const [regenerateStatus, setRegenerateStatus] = useState<string | null>(null);
  const [generationSteps, setGenerationSteps] = useState<GenerationJobStep[]>([]);
  const [regenerateError, setRegenerateError] = useState<string | null>(null);
  const [temporaryGuidance, setTemporaryGuidance] = useState("");
  const [nextWritingPacket, setNextWritingPacket] = useState<CodexWritingPacket | null>(null);
  const [volumeWorkflow, setVolumeWorkflow] = useState<VolumeWorkflowResponse | null>(null);
  const [volumeWorkflowLoading, setVolumeWorkflowLoading] = useState(true);
  const [volumeWorkflowError, setVolumeWorkflowError] = useState("");
  const [copyStatus, setCopyStatus] = useState<CopyStatus>("idle");
  const [pendingCandidate, setPendingCandidate] = useState<CandidateDraft | null>(null);
  const [nextPendingCandidate, setNextPendingCandidate] = useState<CandidateDraft | null>(null);
  const [candidateAction, setCandidateAction] = useState<"confirm" | "force-confirm" | "discard" | null>(null);
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
      setVolumeWorkflow(null);
      setVolumeWorkflowLoading(false);
      setVolumeWorkflowError("");
      return;
    }
    setVolumeWorkflowLoading(true);
    setVolumeWorkflowError("");
    fetchVolumeWorkflow(projectId, nextChapterNumber)
      .then((response) => {
        if (!cancelled) {
          setVolumeWorkflow(response);
          setVolumeWorkflowError("");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setVolumeWorkflow(null);
          setVolumeWorkflowError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setVolumeWorkflowLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isFileProject, nextChapterNumber, projectId, refreshVersion]);

  useEffect(() => {
    let cancelled = false;
    if (!isFileProject || !projectId) {
      setNextWritingPacket(null);
      return;
    }
    fetchProjectWritingPacket(projectId, nextChapterNumber)
      .then((packet) => {
        if (cancelled) return;
        // Round 8 Task 5: the legacy chapter-direction picker was
        // removed; the rolling outline (and its status) is now the
        // source of truth for what the next chapter looks like. The
        // packet still carries ``chapter_direction_options`` for
        // backward compatibility, but its options list is always empty.
        setNextWritingPacket(packet);
      })
      .catch(() => {
        if (cancelled) return;
        setNextWritingPacket(null);
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
    fetchFileProjectCandidates(projectId, requestedChapter)
      .then((response) => {
        if (cancelled) return;
        const pending = response.items
          .filter((item) => item.status === "pending");
        const latest = pending
          .filter((item) => item.chapter_number === requestedChapter)
          .sort((left, right) => left.created_at.localeCompare(right.created_at))
          .at(-1) ?? null;
        setPendingCandidate(latest);
      })
      .catch(() => {
        if (!cancelled) setPendingCandidate(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isFileProject, projectId, requestedChapter, refreshVersion]);

  useEffect(() => {
    let cancelled = false;
    if (!isFileProject || !projectId || nextChapterNumber === requestedChapter) {
      setNextPendingCandidate(null);
      return;
    }
    fetchFileProjectCandidates(projectId, nextChapterNumber)
      .then((response) => {
        if (cancelled) return;
        const latest = response.items
          .filter((item) => item.status === "pending" && item.chapter_number === nextChapterNumber)
          .sort((left, right) => left.created_at.localeCompare(right.created_at))
          .at(-1) ?? null;
        setNextPendingCandidate(latest);
      })
      .catch(() => {
        if (!cancelled) setNextPendingCandidate(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isFileProject, nextChapterNumber, projectId, requestedChapter, refreshVersion]);

  const nextChapterOutline = nextWritingPacket?.next_chapter_outline ?? null;
  const nextChapterOutlineSource = nextWritingPacket?.next_chapter_outline_source ?? null;
  const rollingFill = nextWritingPacket?.rolling_fill ?? null;
  const nextChapterNeedsOutline = isFileProject
    && (volumeWorkflowLoading || Boolean(volumeWorkflowError) || volumeWorkflow?.status !== "detail_complete");
  const nextChapterActionLabel = volumeWorkflow?.status === "volume_missing"
    ? "先设计下一卷"
    : volumeWorkflow?.status === "volume_plan_ready"
      ? "先生成本卷细纲"
      : volumeWorkflow?.status === "detail_partial"
        ? "继续生成本卷细纲"
        : "生成下一章";
  const writingReview = chapter?.quality_report?.writing_review;
  const downstreamNotice = downstreamRewriteNotice(chapter?.quality_report);
  const lengthReview = chapter?.quality_report?.length_review ?? writingReview?.length_review;
  const bodyChars = lengthReview?.body_chars ?? chapterCharCount(chapter?.body);
  const minChars = lengthReview?.min_chars ?? 3800;
  const maxChars = lengthReview?.max_chars ?? 5500;
  const lengthPassed = lengthReview?.pass ?? bodyChars >= minChars;
  const lengthIssues = lengthReview?.issues ?? [];
  const writingLessons = story?.writing_lessons ?? [];

  async function loadPendingCandidate(chapterNumber: number): Promise<CandidateDraft | null> {
    if (!isFileProject) return null;
    const response = await fetchFileProjectCandidates(projectId, chapterNumber);
    const pending = response.items
      .filter((item) => item.status === "pending")
      .sort((left, right) => left.created_at.localeCompare(right.created_at))
      .at(-1) ?? null;
    if (chapterNumber === requestedChapter) {
      setPendingCandidate(pending);
    } else if (chapterNumber === nextChapterNumber) {
      setNextPendingCandidate(pending);
    }
    return pending;
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

  async function handleExpandChapter() {
    if (!chapter || !isFileProject || expanding) return;
    const operationToken = ++operationTokenRef.current;
    const operationIsActive = () => mountedRef.current && operationTokenRef.current === operationToken;
    setExpanding(true);
    setRegenerateStatus("扩写已排队");
    setRegenerateError(null);
    try {
      const job = await startFileProjectExpansionJob(projectId, chapter.chapter_number);
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
        throw new Error(currentJob.error || "chapter_expansion_failed");
      }
      if (!operationIsActive()) return;
      await loadPendingCandidate(chapter.chapter_number);
    } catch (err) {
      if (operationIsActive()) setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      if (operationIsActive()) {
        setExpanding(false);
        setRegenerateStatus(null);
      }
    }
  }

  async function handleGenerateNextChapter() {
    if (!generationTargetId || !canGenerateNext) return;
    if (nextChapterNeedsOutline) {
      const reason = volumeWorkflow?.status === "volume_missing"
        ? "volume_missing"
        : "volume_detail_required";
      const tab = volumeWorkflow?.status === "volume_missing" ? "arcs" : "chapters";
      router.push(`/projects/${encodedProjectId}/outline?tab=${tab}&chapter=${nextChapterNumber}&reason=${reason}`);
      return;
    }
    const operationToken = ++operationTokenRef.current;
    const operationIsActive = () => mountedRef.current && operationTokenRef.current === operationToken;
    setGeneratingNext(true);
    setRegenerateStatus("排队中");
    setRegenerateError(null);
    try {
      const job = await startGenerationJob(generationTargetId);
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
      await refresh({ invalidateChapter: false });
      setNextPendingCandidate(null);
      router.push(`/projects/${encodedProjectId}/write?chapter=${generatedChapterNumber}`);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      if (
        operationIsActive()
        && (
          detail.includes("chapter_outline_required")
          || detail.includes("next_volume_required")
          || detail.includes("volume_detail_required")
          || detail.includes("volume_detail_incomplete")
        )
      ) {
        const needsVolume = detail.includes("next_volume_required");
        router.push(
          `/projects/${encodedProjectId}/outline?tab=${needsVolume ? "arcs" : "chapters"}&chapter=${nextChapterNumber}&reason=${needsVolume ? "volume_missing" : "volume_detail_required"}`,
        );
      } else if (operationIsActive()) {
        setRegenerateError(detail);
      }
    } finally {
      if (operationIsActive()) {
        setGeneratingNext(false);
        setRegenerateStatus(null);
      }
    }
  }

  async function handleConfirmCandidate(force = false) {
    if (!pendingCandidate || !isFileProject || candidateAction) return;
    setCandidateAction(force ? "force-confirm" : "confirm");
    setRegenerateError(null);
    try {
      await confirmFileProjectCandidate(projectId, pendingCandidate.candidate_id, force);
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
        title={chapter
          ? `章节：第 ${chapter.chapter_number} 章`
          : pendingCandidate
            ? `候选稿：第 ${pendingCandidate.chapter_number} 章`
            : "章节"}
        subtitle={chapter?.chapter_title || pendingCandidate?.chapter_title || project?.current_focus || "目录和正文放在同一页。"}
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
            {!chapter && pendingCandidate ? (
              <>
                <header className="ws-reader__head">
                  <div>
                    <p className="ws-card__title">全新章节候选稿</p>
                    <h2>{pendingCandidate.chapter_title || `第 ${pendingCandidate.chapter_number} 章`}</h2>
                  </div>
                  <span className="ws-badge">尚未提交</span>
                </header>
                <CandidatePanel
                  candidate={pendingCandidate}
                  action={candidateAction}
                  onDiscard={() => void handleDiscardCandidate()}
                  onConfirm={() => void handleConfirmCandidate()}
                  onForceConfirm={() => void handleConfirmCandidate(true)}
                />
              </>
            ) : chapterError ? (
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
                  disabled={!canGenerateNext || expanding || regenerating || generatingNext || nextChapterNeedsOutline}
                  onClick={() => void handleGenerateNextChapter()}
                >
                  {generatingNext ? "生成中..." : "生成下一章"}
                </button>
                <button
                  className="ws-btn ws-btn--sm"
                  type="button"
                  disabled={expanding || regenerating || generatingNext}
                  onClick={() => void handleExpandChapter()}
                >
                  <Expand size={15} aria-hidden="true" />
                  {expanding ? "扩写中..." : "扩写本章"}
                </button>
                <button
                  className="ws-btn ws-btn--sm"
                  type="button"
                  disabled={!canRegenerate || expanding || regenerating || generatingNext}
                  onClick={() => void handleRegenerateChapter()}
                >
                  {regenerating ? "重新生成中..." : "重新生成本章"}
                </button>
                <span className="ws-badge">{chapterCharCount(chapter.body)} 字</span>
              </div>
            </header>
            {copyStatus === "failed" ? <p className="ws-error" role="alert">复制失败，请允许浏览器访问剪贴板后重试。</p> : null}

            {(expanding || regenerating || generatingNext || generationSteps.length > 0) ? (
              <WritingProgressRow
                status={regenerateStatus || generationSteps[generationSteps.length - 1]?.message || "准备中"}
                href={`/projects/${encodedProjectId}/log`}
              />
            ) : null}

            {regenerateError ? <p className="ws-error">任务失败：{regenerateError}</p> : null}
            {nextPendingCandidate ? (
              <section className="ws-card" aria-label="下一章候选稿已保留">
                <div className="ws-section-head">
                  <div>
                    <p className="ws-card__title">下一章候选稿已保留</p>
                    <p className="ws-card__hint">
                      第 {nextPendingCandidate.chapter_number} 章候选稿已经生成并保留，不会覆盖当前章节。
                    </p>
                  </div>
                  <Link
                    className="ws-btn ws-btn--sm ws-btn--primary"
                    href={`/projects/${encodedProjectId}/write?chapter=${nextPendingCandidate.chapter_number}`}
                  >
                    查看第 {nextPendingCandidate.chapter_number} 章候选稿
                  </Link>
                </div>
              </section>
            ) : null}
            {pendingCandidate ? (
              <CandidatePanel
                candidate={pendingCandidate}
                action={candidateAction}
                onDiscard={() => void handleDiscardCandidate()}
                onConfirm={() => void handleConfirmCandidate()}
                onForceConfirm={() => void handleConfirmCandidate(true)}
              />
            ) : null}
            {nextWritingPacket && rollingFill ? (
              <RollingOutlineCard
                chapterNumber={nextChapterNumber}
                status={rollingFill.status}
                source={nextChapterOutlineSource}
                outline={nextChapterOutline}
                error={rollingFill.error ?? ""}
                filledChapterNumbers={rollingFill.filled_chapter_numbers ?? []}
                outlineHref={`/projects/${encodedProjectId}/outline?tab=chapters&chapter=${nextChapterNumber}`}
              />
            ) : null}
            {isFileProject && (volumeWorkflowLoading || volumeWorkflowError || (volumeWorkflow && volumeWorkflow.status !== "detail_complete")) ? (
              <section className="ws-card" aria-label="下一章准备状态">
                <p className="ws-card__title">第 {nextChapterNumber} 章还不能生成</p>
                <p className="ws-card__hint">
                  {volumeWorkflowLoading
                    ? "正在检查下一章所在卷和章节细纲。"
                    : volumeWorkflowError
                      ? `卷纲状态读取失败：${volumeWorkflowError}`
                      : volumeWorkflow?.status === "volume_missing"
                    ? "上一卷已经结束，请先设计下一卷。新卷确定后，再生成这一整卷的章节细纲。"
                    : volumeWorkflow?.status === "detail_partial"
                      ? `本卷细纲只完成了一部分，请先补完第 ${volumeWorkflow.volume_range?.[0]}-${volumeWorkflow.volume_range?.[1]} 章。`
                      : `本卷已经设计好，请先生成第 ${volumeWorkflow?.volume_range?.[0]}-${volumeWorkflow?.volume_range?.[1]} 章的完整细纲。`}
                </p>
                {!volumeWorkflowLoading && !volumeWorkflowError && volumeWorkflow ? (
                  <Link
                    className="ws-btn ws-btn--sm ws-btn--primary"
                    href={`/projects/${encodedProjectId}/outline?tab=${volumeWorkflow.status === "volume_missing" ? "arcs" : "chapters"}&chapter=${nextChapterNumber}&reason=${volumeWorkflow.status === "volume_missing" ? "volume_missing" : "volume_detail_required"}`}
                  >
                    {nextChapterActionLabel}
                  </Link>
                ) : null}
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
            disabled={!canGenerateNext || generatingNext || nextChapterNeedsOutline}
            onClick={() => void handleGenerateNextChapter()}
          >
            {generatingNext ? "生成中..." : "生成第一章"}
          </button>
          {isFileProject && (volumeWorkflowLoading || volumeWorkflowError || (volumeWorkflow && volumeWorkflow.status !== "detail_complete")) ? (
            <section className="ws-card" aria-label="第一章准备状态">
              <p className="ws-card__hint">
                {volumeWorkflowLoading
                  ? "正在检查第一卷细纲。"
                  : volumeWorkflowError
                    ? `卷纲状态读取失败：${volumeWorkflowError}`
                    : "请先在大纲页完成第一卷设计和整卷章节细纲。"}
              </p>
              {!volumeWorkflowLoading && !volumeWorkflowError && volumeWorkflow ? (
                <Link
                  className="ws-btn ws-btn--sm ws-btn--primary"
                  href={`/projects/${encodedProjectId}/outline?tab=${volumeWorkflow.status === "volume_missing" ? "arcs" : "chapters"}&chapter=${nextChapterNumber}`}
                >
                  {nextChapterActionLabel}
                </Link>
              ) : null}
            </section>
          ) : null}
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
              onForceConfirm={() => void handleConfirmCandidate(true)}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}
