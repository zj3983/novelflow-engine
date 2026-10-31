"use client";

import Link from "next/link";
import { Check, Copy, Expand, MoreHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { useChapterDetail } from "../../../../components/ws/useChapterDetail";
import { SimplifiedReview } from "../../../../components/ws/SimplifiedReview";
import { AnnotatedChapterBody } from "../../../../components/ws/AnnotatedChapterBody";
import { RollingOutlineCard } from "../../../../components/ws/RollingOutlineCard";
import { ContinuousGenerationPanel } from "../../../../components/ws/ContinuousGenerationPanel";
import { useContinuousGeneration } from "../../../../components/ws/useContinuousGeneration";
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
  startFileProjectReviewRepairJob,
  startFileProjectContextReviewJob,
  startGenerationJob,
  type ChapterIndexEntry,
  type CandidateDraft,
  type CodexWritingPacket,
  type GenerationJobStep,
  type LengthReview,
  type SimplifiedReview as SimplifiedReviewData,
  type VolumeWorkflowResponse,
} from "../../../../lib/api";
import { userFacingErrorMessage } from "../../../../lib/user-facing-error";

const PAGE_SIZE = 80;
const LAST_READ_CHAPTER_STORAGE_PREFIX = "novel-autogrowth.last-read-chapter:";

function lastReadChapterStorageKey(projectId: string): string {
  return `${LAST_READ_CHAPTER_STORAGE_PREFIX}${projectId}`;
}

function readLastReadChapter(projectId: string): number | null {
  if (typeof window === "undefined") return null;
  try {
    const chapterNumber = Number(window.localStorage.getItem(lastReadChapterStorageKey(projectId)));
    return Number.isInteger(chapterNumber) && chapterNumber > 0 ? chapterNumber : null;
  } catch {
    return null;
  }
}

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
  previousVersion,
  onRepair,
  onContextReview,
  repairDisabled,
}: {
  candidate: CandidateDraft;
  action: "confirm" | "force-confirm" | "discard" | null;
  onConfirm: () => void;
  onForceConfirm: () => void;
  onDiscard: () => void;
  previousVersion?: { title?: string; body: string };
  onRepair?: () => void;
  onContextReview?: () => void;
  repairDisabled?: boolean;
}) {
  const hasQualityWarnings = candidate.quality_report?.ok === false;
  const lengthReview = candidate.quality_report?.length_review as LengthReview | undefined;
  const lengthBlocked = lengthReview?.acceptance_pass === false;
  const repair = candidate.quality_report?.review_repair as { edits?: Array<{ before: string; after: string; reason: string }> } | undefined;
  const candidateReview = candidate.quality_report?.simplified_review as SimplifiedReviewData | undefined;
  const hasReviewAdvice = (candidateReview?.total_issues ?? 0) > 0;
  const issueCount = candidateReview?.total_issues ?? (Array.isArray(candidate.quality_report?.issues)
    ? candidate.quality_report.issues.length
    : 0);
  return (
    <section className="ws-candidate" aria-label="候选稿">
      <header className="ws-candidate__head">
        <div>
          <p className="ws-candidate__eyebrow">第 {candidate.chapter_number} 章 · 候选稿</p>
          <h2>{candidate.chapter_title || `第 ${candidate.chapter_number} 章`}</h2>
          <p>{chapterCharCount(candidate.body)} 字</p>
        </div>
      </header>
      {onContextReview ? <button className="ws-btn ws-btn--sm" type="button" disabled={repairDisabled || Boolean(action)} onClick={onContextReview}>上下文审稿</button> : null}
      {hasQualityWarnings || lengthBlocked || hasReviewAdvice ? (
        <div className="ws-review-strip ws-review-strip--warning" role="status">
          <span className="ws-review-strip__mark" aria-hidden="true">!</span>
          <div>
            <strong>{lengthBlocked ? "字数未达标，修订后才能提交" : issueCount > 0 ? `${issueCount} 条内容提醒` : "有内容需要复核"}</strong>
            <p>{lengthBlocked
              ? `当前${chapterCharCount(candidate.body)}字，目标${lengthReview?.min_chars ?? 4200}—${lengthReview?.max_chars ?? 4500}字，硬性范围${lengthReview?.hard_min_chars ?? 3800}—${lengthReview?.hard_max_chars ?? 4500}字。候选稿已保留，不会写入正式章节。`
              : "建议读完候选稿后，再决定提交或丢弃。"}</p>
            {onRepair ? <button className="ws-btn ws-btn--sm" type="button" disabled={repairDisabled || Boolean(action)} onClick={onRepair}>按审查精修</button> : null}
          </div>
        </div>
      ) : null}
      {candidateReview ? <details className="ws-previous-version"><summary>查看候选稿审查</summary><SimplifiedReview report={candidateReview} compact /></details> : null}
      {repair?.edits?.length ? <details className="ws-previous-version">
        <summary>查看逐处修改（{repair.edits.length}处）</summary>
        {repair.edits.map((edit, index) => <div key={index}>
          <p><strong>原句：</strong>{edit.before}</p>
          <p><strong>改句：</strong>{edit.after}</p>
          <p className="ws-card__hint">{edit.reason}</p>
        </div>)}
      </details> : null}
      <AnnotatedChapterBody body={candidate.body} qualityReport={candidate.quality_report} className="ws-reader__body ws-candidate__body" />
      {previousVersion ? (
        <details className="ws-previous-version">
          <summary>查看当前已提交版本</summary>
          <h3>{previousVersion.title || `第 ${candidate.chapter_number} 章`}</h3>
          <article className="ws-reader__body">
            {previousVersion.body.split(/\n{2,}/).map((paragraph, index) => (
              <p key={index}>{paragraph}</p>
            ))}
          </article>
        </details>
      ) : null}
      <footer className="ws-candidate__actions">
        <p>{previousVersion ? "提交后会用候选稿替换当前版本。" : "确认后，候选稿会成为本章正文。"}</p>
        <div className="ws-toolbar">
          <button className="ws-btn ws-btn--sm" type="button" disabled={Boolean(action)} onClick={onDiscard}>
            {action === "discard" ? "丢弃中..." : "丢弃候选稿"}
          </button>
          {hasQualityWarnings && !lengthBlocked ? (
            <button className="ws-btn ws-btn--sm" type="button" disabled={Boolean(action)} onClick={onForceConfirm}>
              {action === "force-confirm" ? "提交中..." : "仍然采用"}
            </button>
          ) : null}
          <button className="ws-btn ws-btn--primary" type="button" disabled={Boolean(action) || lengthBlocked} onClick={onConfirm}>
            {action === "confirm" ? "提交中..." : "确认提交"}
          </button>
        </div>
      </footer>
    </section>
  );
}

function ChapterReviewSummary({ report, judgements = [], onRepair, onContextReview, repairDisabled }: { report?: SimplifiedReviewData; judgements?: Array<{ issue: string; reason: string }>; onRepair?: () => void; onContextReview?: () => void; repairDisabled?: boolean }) {
  if (!report) return null;

  const hasIssues = report.total_issues > 0 || judgements.length > 0 || report.status === "blocked" || report.status === "warning" || report.status === "needs_revision";
  const isBlocked = report.status === "blocked";
  const contextPending = report.diagnostics?.requires_contextual_prose_review === true && report.diagnostics?.contextual_prose_review_executed !== true;
  const summary = judgements.length ? "正文已采用；审查建议及当时的采用理由保留，仍可逐项复核。" : report.issues[0]?.message || (contextPending ? "关键词仅作线索，请运行上下文审稿。" : report.summary) || "当前章节没有需要处理的问题。";
  const label = isBlocked
    ? `${report.total_issues || 1} 条需要处理的问题`
    : hasIssues
      ? `${Math.max(report.total_issues, judgements.length)} 条审查建议${judgements.length ? "（已采用正文）" : "待复核"}`
      : contextPending ? "文风待上下文审稿" : "章节检查已通过";

  return (
    <section className={`ws-review-strip${isBlocked ? " ws-review-strip--blocking" : hasIssues ? " ws-review-strip--warning" : ""}`} aria-label="章节审查">
      <span className="ws-review-strip__mark" aria-hidden="true">{isBlocked ? "!" : hasIssues ? "·" : "✓"}</span>
      <div className="ws-review-strip__copy">
        <strong>{label}</strong>
        <p>{summary}</p>
      </div>
      <div className="ws-toolbar">
      {onContextReview ? <button className="ws-btn ws-btn--sm" type="button" disabled={repairDisabled} onClick={onContextReview}>上下文审稿</button> : null}
      {hasIssues && onRepair ? <button className="ws-btn ws-btn--sm" type="button" disabled={repairDisabled} onClick={onRepair}>按审查精修</button> : null}
      {hasIssues ? (
        <details className="ws-review-strip__details">
          <summary>查看审查</summary>
          <div className="ws-review-strip__expanded">
            {judgements.length ? <div>
              <p className="ws-card__title">审查建议与采用说明</p>
              {judgements.map((item, index) => <div key={index}><p>{item.issue}</p><p className="ws-card__hint">当时采用理由：{item.reason}</p></div>)}
              {report.issues.filter(issue => !judgements.some(item => item.issue === issue.message)).map((issue, index) => <div key={`remaining-${index}`}><p>{issue.message}</p><p className="ws-card__hint">修订建议：{issue.suggestion}</p></div>)}
            </div> : <SimplifiedReview report={report} compact />}
          </div>
        </details>
      ) : null}
      </div>
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

function keepChapterInView(container: HTMLElement, chapterItem: HTMLElement): void {
  const containerBounds = container.getBoundingClientRect();
  const chapterBounds = chapterItem.getBoundingClientRect();

  if (chapterBounds.top < containerBounds.top) {
    container.scrollTop -= containerBounds.top - chapterBounds.top;
  } else if (chapterBounds.bottom > containerBounds.bottom) {
    container.scrollTop += chapterBounds.bottom - containerBounds.bottom;
  }
  if (chapterBounds.left < containerBounds.left) {
    container.scrollLeft -= containerBounds.left - chapterBounds.left;
  } else if (chapterBounds.right > containerBounds.right) {
    container.scrollLeft += chapterBounds.right - containerBounds.right;
  }
}

export default function WritePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { project, story, chapterIndex, error, loading: workspaceLoading, encodedProjectId, projectId, refreshVersion, refresh } = useProjectWorkspace();
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
  const [repairRequest, setRepairRequest] = useState<{ chapterNumber: number; candidateId?: string; issues: string[] } | null>(null);
  const mountedRef = useRef(false);
  const operationTokenRef = useRef(0);
  const chapterListRef = useRef<HTMLDivElement | null>(null);
  const chapterParam = searchParams?.get("chapter");
  const [lastReadChapter, setLastReadChapter] = useState<number | null>(null);
  const [chapterPreferenceReady, setChapterPreferenceReady] = useState(false);

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

  useEffect(() => {
    setChapterPreferenceReady(false);
    if (chapterParam) {
      setLastReadChapter(null);
      setChapterPreferenceReady(true);
      return;
    }
    setLastReadChapter(readLastReadChapter(projectId));
    setChapterPreferenceReady(true);
  }, [chapterParam, projectId]);

  const rememberedChapter = chapterPreferenceReady && lastReadChapter !== null
    && chapterIndex.some((entry) => entry.chapter_number === lastReadChapter)
    ? lastReadChapter
    : null;
  const requestedChapter = Number(chapterParam || rememberedChapter || story?.current_chapter || chapterIndex.at(-1)?.chapter_number || 0);
  const { chapter, loading: chapterLoading, error: chapterError } = useChapterDetail({
    projectId,
    story: story ?? null,
    chapterNumber: requestedChapter,
    refreshVersion,
  });

  useEffect(() => {
    if (!chapterPreferenceReady || !Number.isInteger(requestedChapter) || requestedChapter <= 0) return;
    if (!chapterIndex.some((entry) => entry.chapter_number === requestedChapter)) return;
    try {
      window.localStorage.setItem(lastReadChapterStorageKey(projectId), String(requestedChapter));
    } catch {
      // Ignore storage errors; the URL remains the source of truth for direct links.
    }
  }, [chapterIndex, chapterPreferenceReady, projectId, requestedChapter]);
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
  const activeBundleIndex = filteredBundles.findIndex((bundle) => bundle.chapter_number === requestedChapter);
  const activePage = activeBundleIndex >= 0 ? Math.floor(activeBundleIndex / PAGE_SIZE) + 1 : null;

  useEffect(() => {
    if (activePage === null) return;
    setPage((currentPage) => currentPage === activePage ? currentPage : activePage);
  }, [activePage, filteredBundles, normalizedQuery, requestedChapter]);

  useEffect(() => {
    const container = chapterListRef.current;
    if (!container) return;
    const chapterItem = container.querySelector<HTMLElement>(`[data-chapter-number="${requestedChapter}"]`);
    if (!chapterItem) return;
    keepChapterInView(container, chapterItem);
  }, [filteredBundles, refreshVersion, requestedChapter, safePage]);

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
    if (!isFileProject || !projectId || chapterLoading || chapter?.chapter_number === requestedChapter) {
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
  }, [isFileProject, projectId, requestedChapter, refreshVersion, chapterLoading, chapter?.chapter_number]);

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
  const endingReached = volumeWorkflow?.status === "ending_reached";
  const nextChapterNeedsOutline = isFileProject
    && (volumeWorkflowLoading || Boolean(volumeWorkflowError) || volumeWorkflow?.status !== "detail_complete");
  const continuousGeneration = useContinuousGeneration({
    enabled: isFileProject,
    projectId,
    encodedProjectId,
    nextChapterNumber,
    nextChapterNeedsOutline,
    volumeWorkflowStatus: volumeWorkflow?.status,
    busy: expanding || regenerating || generatingNext,
    refresh,
  });
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
  const bodyChars = chapterCharCount(chapter?.body);
  const minChars = lengthReview?.min_chars ?? 3800;
  const maxChars = lengthReview?.max_chars ?? 4500;
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

  function openReviewRepair() {
    const source = pendingCandidate ?? chapter;
    if (!source || !isFileProject) return;
    const report = source.quality_report?.simplified_review as SimplifiedReviewData | undefined;
    setRepairRequest({
      chapterNumber: source.chapter_number,
      candidateId: pendingCandidate?.candidate_id,
      issues: report?.issues?.map(issue => issue.message) ?? ["按当前审查结果修正存在问题的表达。"],
    });
  }

  async function handleReviewRepair() {
    if (!repairRequest || regenerating || expanding || generatingNext || continuousGeneration.active || candidateAction) return;
    const operationToken = ++operationTokenRef.current;
    const operationIsActive = () => mountedRef.current && operationTokenRef.current === operationToken;
    setRegenerating(true);
    setRegenerateStatus("审查精修已排队");
    setRegenerateError(null);
    try {
      let job = await startFileProjectReviewRepairJob(projectId, repairRequest.chapterNumber, repairRequest.candidateId);
      while (operationIsActive()) {
        setGenerationSteps(job.steps ?? []);
        setRegenerateStatus(job.progress || job.status);
        if (job.status === "failed") throw new Error(job.error || "审查精修失败，原稿未改动。");
        if (job.status === "completed") break;
        await new Promise(resolve => window.setTimeout(resolve, 2000));
        if (!operationIsActive()) return;
        job = await fetchGenerationJob(projectId, job.job_id);
      }
      if (!operationIsActive()) return;
      await loadPendingCandidate(repairRequest.chapterNumber);
      setRepairRequest(null);
    } catch (err) {
      if (operationIsActive()) setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      if (operationIsActive()) {
        setRegenerating(false);
        setRegenerateStatus(null);
      }
    }
  }

  async function handleContextReview() {
    const source = pendingCandidate ?? chapter;
    if (!source || regenerating || expanding || generatingNext || continuousGeneration.active || candidateAction) return;
    const operationToken = ++operationTokenRef.current;
    const operationIsActive = () => mountedRef.current && operationTokenRef.current === operationToken;
    setRegenerating(true);
    setRegenerateStatus("上下文审稿已排队");
    setRegenerateError(null);
    try {
      let job = await startFileProjectContextReviewJob(projectId, source.chapter_number, pendingCandidate?.candidate_id);
      while (operationIsActive()) {
        setGenerationSteps(job.steps ?? []);
        setRegenerateStatus(job.progress || job.status);
        if (job.status === "failed") throw new Error(job.error || "上下文审稿未完成，请重试。");
        if (job.status === "completed") break;
        await new Promise(resolve => window.setTimeout(resolve, 2000));
        if (!operationIsActive()) return;
        job = await fetchGenerationJob(projectId, job.job_id);
      }
      if (!operationIsActive()) return;
      await refresh({ invalidateChapter: true });
      if (pendingCandidate) await loadPendingCandidate(source.chapter_number);
    } catch (err) {
      if (operationIsActive()) setRegenerateError(err instanceof Error ? err.message : String(err));
    } finally {
      if (operationIsActive()) { setRegenerating(false); setRegenerateStatus(null); }
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
    if (!generationTargetId || !canGenerateNext || endingReached) return;
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
      await refresh({ invalidateChapter: generatedChapterNumber === requestedChapter });
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
    <div className="ws-page ws-page--writing">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title={pendingCandidate
          ? `第 ${pendingCandidate.chapter_number} 章 · 候选稿`
          : chapter
            ? `第 ${chapter.chapter_number} 章`
            : "章节"}
        subtitle={pendingCandidate
          ? "检查候选正文，确认后提交。"
          : chapter?.chapter_title || project?.title || project?.current_focus || "目录和正文放在同一页。"}
        actions={chapter || pendingCandidate ? (
          <div className="ws-writing-head-actions">
            <span className={`ws-writing-state${pendingCandidate ? " ws-writing-state--pending" : ""}`}>
              {pendingCandidate ? "待确认" : "已确认正文"}
            </span>
            {pendingCandidate ? (
              <details className="ws-writing-menu ws-writing-debug">
                <summary aria-label="运行详情" title="运行详情">
                  <MoreHorizontal size={19} aria-hidden="true" />
                  <span>运行详情</span>
                </summary>
                <div className="ws-writing-menu__items">
                  <div className="ws-writing-debug__row">
                    <span>上下文快照</span>
                    <code>{pendingCandidate.context_snapshot_id || "未记录"}</code>
                  </div>
                  <div className="ws-writing-debug__row">
                    <span>候选编号</span>
                    <code>{pendingCandidate.candidate_id}</code>
                  </div>
                </div>
              </details>
            ) : null}
          </div>
        ) : undefined}
      />

      {project ? (
        <div className="ws-toolbar" aria-label="本书写法">
          <span className="ws-toolbar__meta">
            后续写作采用：{[
              project.world_blueprint?.writing_style,
              project.world_blueprint?.writing_guidance ? "自定义写法" : "",
              project.world_blueprint?.writing_reference ? "参考片段" : "",
            ].filter(Boolean).join(" · ") || "默认表达"}
          </span>
          <Link href={`/projects/${encodedProjectId}/settings`}>调整写法</Link>
        </div>
      ) : null}

      {repairRequest ? <section className="ws-card" aria-label="审查精修">
        <h2 className="ws-card__title">第 {repairRequest.chapterNumber} 章 · 按审查精修</h2>
        <p>根据当前审查定位问题句，生成局部替换；保留人物、剧情、状态和章末落点。原稿保留，复审后生成候选稿，由你查看逐处对照并确认提交。</p>
        <ul>{repairRequest.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>
        <div className="ws-toolbar">
          <button className="ws-btn ws-btn--primary" type="button" disabled={regenerating || expanding || generatingNext || continuousGeneration.active || Boolean(candidateAction)} onClick={() => void handleReviewRepair()}>{regenerating ? "精修中..." : "生成精修候选稿"}</button>
          <button className="ws-btn ws-btn--sm" type="button" disabled={regenerating} onClick={() => setRepairRequest(null)}>取消</button>
        </div>
        {regenerateStatus ? <p role="status">{regenerateStatus}</p> : null}
        {regenerateError ? <p className="ws-error" role="alert">{userFacingErrorMessage(regenerateError)}</p> : null}
      </section> : null}

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{userFacingErrorMessage(error)}</p>
        </div>
      ) : workspaceLoading ? (
        <div className="ws-empty">
          <p className="ws-empty__title">正在加载章节...</p>
        </div>
      ) : chapterIndex.length > 0 ? (
        <div className="ws-editor-layout ws-editor-layout--chapters">
          <aside className="ws-sidepanel ws-chapter-index" aria-label="章节目录">
            <section className="ws-chapter-index__inner">
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
              <div className="ws-chapter-list" ref={chapterListRef}>
                {visibleBundles.map((bundle) => {
                  const active = bundle.chapter_number === requestedChapter;
                  return (
                    <Link
                      key={bundle.chapter_number}
                      href={`/projects/${encodedProjectId}/write?chapter=${bundle.chapter_number}`}
                      scroll={false}
                      className={`ws-chapter-list__item${active ? " ws-chapter-list__item--active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      data-chapter-number={bundle.chapter_number}
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

          <article className={`ws-reader${pendingCandidate ? " ws-reader--candidate" : ""}`} id="chapter-reader">
            {pendingCandidate ? (
              <CandidatePanel
                candidate={pendingCandidate}
                action={candidateAction}
                onDiscard={() => void handleDiscardCandidate()}
                onConfirm={() => void handleConfirmCandidate()}
                onForceConfirm={() => void handleConfirmCandidate(true)}
                onRepair={openReviewRepair}
                onContextReview={() => void handleContextReview()}
                repairDisabled={expanding || regenerating || generatingNext || continuousGeneration.active}
                previousVersion={chapter ? { title: chapter.chapter_title, body: chapter.body } : undefined}
              />
            ) : !chapter && requestedChapter === nextChapterNumber ? (
              <div className="ws-empty">
                <p className="ws-empty__title">第 {nextChapterNumber} 章待写</p>
                <p className="ws-empty__hint">{nextChapterOutline?.title || "按已保存的章节细纲继续写作。"}</p>
                <button
                  className="ws-btn ws-btn--primary"
                  type="button"
                  disabled={!canGenerateNext || generatingNext || volumeWorkflowLoading || Boolean(volumeWorkflowError) || endingReached || continuousGeneration.active}
                  onClick={() => void handleGenerateNextChapter()}
                >
                  {generatingNext ? "生成中..." : nextChapterNeedsOutline ? nextChapterActionLabel : `生成第${nextChapterNumber}章`}
                </button>
                {(generatingNext || generationSteps.length > 0) ? (
                  <WritingProgressRow
                    status={regenerateStatus || generationSteps[generationSteps.length - 1]?.message || "准备中"}
                    href={`/projects/${encodedProjectId}/log`}
                  />
                ) : null}
                {regenerateError ? <p className="ws-error">任务失败：{userFacingErrorMessage(regenerateError)}</p> : null}
                {volumeWorkflowError ? <p className="ws-error">细纲状态读取失败，请稍后重试。</p> : null}
              </div>
            ) : chapterError ? (
              <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
                <p style={{ color: "var(--ws-danger)", margin: 0 }}>章节加载失败：{userFacingErrorMessage(chapterError)}</p>
              </div>
            ) : chapter ? (
              <>
            <header className="ws-reader__head">
              <span className="ws-reader__section-label">正文</span>
              <div className="ws-toolbar">
                <button
                  className="ws-btn ws-btn--sm ws-btn--primary"
                  type="button"
                  disabled={!canGenerateNext || expanding || regenerating || generatingNext || nextChapterNeedsOutline || continuousGeneration.active}
                  onClick={() => void handleGenerateNextChapter()}
                >
                  {endingReached ? "已到完结章" : generatingNext ? "生成中..." : "生成下一章"}
                </button>
                <button
                  className="ws-btn ws-btn--sm"
                  type="button"
                  disabled={expanding || regenerating || generatingNext || continuousGeneration.active}
                  onClick={() => void handleExpandChapter()}
                >
                  <Expand size={15} aria-hidden="true" />
                  {expanding ? "扩写中..." : "扩写本章"}
                </button>
                <button
                  className="ws-btn ws-btn--sm"
                  type="button"
                  disabled={!canRegenerate || expanding || regenerating || generatingNext || continuousGeneration.active}
                  onClick={() => void handleRegenerateChapter()}
                >
                  {regenerating ? "重新生成中..." : "重新生成本章"}
                </button>
                <button
                  className="ws-writing-icon-button"
                  type="button"
                  aria-label={copyStatus === "copied" ? "已复制" : "复制章节"}
                  title={copyStatus === "copied" ? "已复制" : "复制章节标题和正文"}
                  onClick={() => void handleCopyChapter()}
                >
                  {copyStatus === "copied" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                </button>
                <details className="ws-writing-menu">
                  <summary aria-label="更多操作" title="更多操作">
                    <MoreHorizontal size={19} aria-hidden="true" />
                    <span>更多操作</span>
                  </summary>
                  <div className="ws-writing-menu__items">
                    <Link className="ws-writing-menu__item" href={`/projects/${encodedProjectId}/log`}>运行详情</Link>
                  </div>
                </details>
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

            {regenerateError ? <p className="ws-error">任务失败：{userFacingErrorMessage(regenerateError)}</p> : null}
            {nextPendingCandidate ? (
              <section className="ws-next-candidate" aria-label="下一章候选稿已保留">
                <span>第 {nextPendingCandidate.chapter_number} 章候选稿已准备好</span>
                <Link href={`/projects/${encodedProjectId}/write?chapter=${nextPendingCandidate.chapter_number}`}>
                  前往审阅
                </Link>
              </section>
            ) : null}
            {isFileProject && (volumeWorkflowLoading || volumeWorkflowError || (volumeWorkflow && volumeWorkflow.status !== "detail_complete")) ? (
              <section className="ws-next-step" aria-label="下一章准备状态">
                <div>
                  <strong>{endingReached ? "已到设定的完结章" : volumeWorkflowLoading ? "正在准备下一章" : "下一章需要先完成细纲"}</strong>
                  <p>
                    {endingReached
                      ? "可以继续修订已有章节，或回到大纲页检查结尾安排。"
                      : volumeWorkflowLoading
                      ? "正在检查下一章的章节安排。"
                      : volumeWorkflowError
                        ? "大纲状态暂时无法读取，请稍后重试或查看运行记录。"
                        : volumeWorkflow?.status === "volume_missing"
                          ? "先设计新一卷，再生成这一卷的章节细纲。"
                          : volumeWorkflow?.status === "detail_partial"
                            ? `请先补完第 ${volumeWorkflow?.volume_range?.[0]}–${volumeWorkflow?.volume_range?.[1]} 章的细纲。`
                            : `请先完成第 ${volumeWorkflow?.volume_range?.[0]}–${volumeWorkflow?.volume_range?.[1]} 章的细纲。`}
                  </p>
                </div>
                {volumeWorkflowError ? (
                  <Link className="ws-btn ws-btn--sm" href={`/projects/${encodedProjectId}/log`}>
                    运行详情
                  </Link>
                ) : endingReached ? (
                  <Link className="ws-btn ws-btn--sm" href={`/projects/${encodedProjectId}/outline?tab=chapters&chapter=${volumeWorkflow?.volume_range?.[1]}`}>
                    查看结尾章纲
                  </Link>
                ) : !volumeWorkflowLoading && volumeWorkflow ? (
                  <Link
                    className="ws-btn ws-btn--sm"
                    href={`/projects/${encodedProjectId}/outline?tab=${volumeWorkflow.status === "volume_missing" ? "arcs" : "chapters"}&chapter=${nextChapterNumber}&reason=${volumeWorkflow.status === "volume_missing" ? "volume_missing" : "volume_detail_required"}`}
                  >
                    {nextChapterActionLabel}
                  </Link>
                ) : null}
              </section>
            ) : null}
            <ChapterReviewSummary report={chapter.quality_report?.simplified_review} judgements={chapter.quality_report?.writing_review?.advisory_judgements} onRepair={isFileProject ? openReviewRepair : undefined} onContextReview={isFileProject ? () => void handleContextReview() : undefined} repairDisabled={chapterLoading || expanding || regenerating || generatingNext || continuousGeneration.active} />
            <AnnotatedChapterBody key={chapter.chapter_number} body={chapter.body} qualityReport={chapter.quality_report} />
            {!endingReached || continuousGeneration.active || temporaryGuidance ? <details className="ws-writing-details ws-writing-details--tools" open={continuousGeneration.active || undefined}>
              <summary>
                <span>{endingReached ? "结尾修订提示" : "下一章与创作工具"}</span>
                <small>{endingReached ? "本次改稿提示" : "细纲、自动续写、本次改稿提示"}</small>
              </summary>
              <div className="ws-writing-details__content">
                {!endingReached && nextWritingPacket && rollingFill ? (
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
                {isFileProject && (!endingReached || continuousGeneration.active) ? (
                  <ContinuousGenerationPanel
                    action={continuousGeneration.action}
                    active={continuousGeneration.active}
                    busy={expanding || regenerating || generatingNext}
                    count={continuousGeneration.count}
                    error={continuousGeneration.error}
                    job={continuousGeneration.job}
                    nextChapterNeedsOutline={nextChapterNeedsOutline}
                    workflowError={volumeWorkflowError}
                    workflowLoading={volumeWorkflowLoading}
                    onCountChange={continuousGeneration.setCount}
                    onStart={() => void continuousGeneration.start()}
                    onStop={() => void continuousGeneration.stop()}
                  />
                ) : null}
                {isFileProject ? (
                  <label className="ws-project-create__field">
                    <span>本次重写要求</span>
                    <textarea
                      className="ws-input"
                      rows={5}
                      maxLength={1000}
                      value={temporaryGuidance}
                      disabled={expanding || regenerating || generatingNext || continuousGeneration.active}
                      onChange={(event) => setTemporaryGuidance(event.target.value)}
                    />
                    <small>填写需要修正的衔接或表达问题，再点“重新生成本章”。只影响这次重写。</small>
                  </label>
                ) : null}
                {temporaryGuidance ? (
                  <section className="ws-card">
                    <div className="ws-section-head">
                      <div>
                        <p className="ws-card__title">本次重写提示</p>
                        <p className="ws-card__hint">只影响这次重新生成，不会写入作者约束。</p>
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
              </div>
            </details> : null}
            <details className="ws-writing-details">
              <summary>
                <span>章节信息</span>
                <small>摘要、下一章焦点、字数与连续性</small>
              </summary>
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
              </section>
            </details>
              </>
            ) : chapterLoading ? (
              <div className="ws-empty"><p className="ws-empty__title">正在加载章节...</p></div>
            ) : (
              <div className="ws-empty"><p className="ws-empty__title">没有找到该章节</p></div>
            )}
          </article>
        </div>
      ) : pendingCandidate ? (
        <article className="ws-reader ws-reader--candidate" id="chapter-reader">
          <CandidatePanel
            candidate={pendingCandidate}
            action={candidateAction}
            onDiscard={() => void handleDiscardCandidate()}
            onConfirm={() => void handleConfirmCandidate()}
            onForceConfirm={() => void handleConfirmCandidate(true)}
            onRepair={openReviewRepair}
            onContextReview={() => void handleContextReview()}
            repairDisabled={expanding || regenerating || generatingNext || continuousGeneration.active}
          />
        </article>
      ) : (
        <div className="ws-empty">
          <p className="ws-empty__title">还没有可阅读章节</p>
          <p className="ws-empty__hint">生成第一章后会在这里显示目录和正文。</p>
          <button
            className="ws-btn ws-btn--primary"
            type="button"
            disabled={!canGenerateNext || generatingNext || nextChapterNeedsOutline || continuousGeneration.active}
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
        </div>
      )}
    </div>
  );
}
