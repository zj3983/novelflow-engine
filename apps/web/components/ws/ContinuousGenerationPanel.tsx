"use client";

import type { ContinuousCount } from "./useContinuousGeneration";
import type { ContinuousGenerationJobResponse } from "../../lib/api";
import { GenerationConsistencyPanel } from "./GenerationConsistencyPanel";
import { userFacingErrorMessage } from "../../lib/user-facing-error";

type Props = {
  action: "start" | "stop" | "continue" | "cancel" | "replan" | null;
  active: boolean;
  busy: boolean;
  count: ContinuousCount;
  error: string;
  job: ContinuousGenerationJobResponse | null;
  nextChapterNeedsOutline: boolean;
  workflowError: string;
  workflowLoading: boolean;
  onCountChange: (count: ContinuousCount) => void;
  onStart: () => void;
  onStop: () => void;
  onConsistencyReplan: () => void;
  onConsistencyContinue: () => void;
  onConsistencyReturn: () => void;
};

const STATUS_LABELS: Record<ContinuousGenerationJobResponse["status"], string> = {
  queued: "排队中",
  running: "生成中",
  stopping: "停止中",
  completed: "已完成",
  stopped: "已停止",
  failed: "失败",
  awaiting_consistency_override: "等待确认",
  replanning: "重新规划中",
  awaiting_replanned_confirmation: "等待确认新计划",
};

function automaticRecoveryMessage(job: ContinuousGenerationJobResponse | null): string {
  if (!job) return "";
  const status = job.auto_consistency_replan_status || "";
  const chapter = job.auto_consistency_replan_chapter || job.current_chapter;
  if (job.status === "replanning" || status === "running") {
    return `第 ${chapter} 章发现一致性问题，正在自动重新规划…`;
  }
  if (status === "replanned_clear") return "重新规划通过，继续生成";
  if (status === "replanned_with_warnings") {
    return "重新规划后仍有一致性提示，已暂停，请处理";
  }
  if (status === "still_blocking") return "重新规划后仍有一致性问题，已暂停";
  if (status === "failed") return "自动重新规划失败，已暂停，原计划仍保留";
  return "";
}

export function ContinuousGenerationPanel({
  action,
  active,
  busy,
  count,
  error,
  job,
  nextChapterNeedsOutline,
  workflowError,
  workflowLoading,
  onCountChange,
  onStart,
  onStop,
  onConsistencyReplan,
  onConsistencyContinue,
  onConsistencyReturn,
}: Props) {
  const awaitingConsistency = job?.status === "awaiting_consistency_override"
    || job?.status === "awaiting_replanned_confirmation";
  const startDisabled = busy || active || Boolean(action) || workflowLoading || Boolean(workflowError);
  const status = job ? STATUS_LABELS[job.status] : "未运行";
  const progress = job
    ? `${status} · 已完成 ${job.completed_count}/${job.requested_count} 章`
    : "选择数量后开始，任务会按顺序生成并保存每一章。";

  return (
    <section className="ws-card" aria-label="连续生产">
      <div className="ws-section-head">
        <div>
          <p className="ws-card__title">连续生产</p>
          <p className="ws-card__hint">按当前卷细纲连续生成，任务状态会在刷新页面后恢复。</p>
        </div>
        <span className="ws-badge">{status}</span>
      </div>
      <div className="ws-action-row ws-action-row--flush">
        <label className="ws-toolbar__meta" htmlFor="continuous-generation-count">
          生成章数
        </label>
        <select
          id="continuous-generation-count"
          aria-label="连续生成章数"
          className="ws-input"
          value={count}
          disabled={busy || active || Boolean(action)}
          onChange={(event) => onCountChange(Number(event.target.value) as ContinuousCount)}
        >
          {[2, 5, 10, 20].map((option) => (
            <option key={option} value={option}>{option} 章</option>
          ))}
        </select>
        {awaitingConsistency ? (
          <span className="ws-card__hint">本章已暂停，先处理生成前一致性提示。</span>
        ) : active ? (
          <button className="ws-btn ws-btn--sm" type="button" disabled={Boolean(action)} onClick={onStop}>
            {action === "stop" ? "停止中..." : "停止连续生产"}
          </button>
        ) : (
          <button className="ws-btn ws-btn--sm ws-btn--primary" type="button" disabled={startDisabled} onClick={onStart}>
            {action === "start" ? "启动中..." : nextChapterNeedsOutline ? "先补齐细纲" : "开始连续生产"}
          </button>
        )}
      </div>
      <p className="ws-card__hint">{progress}</p>
      {job ? <p className="ws-card__hint">计划生成 {job.requested_count} 章，从第 {job.start_chapter} 章开始。</p> : null}
      {job?.progress ? <p className="ws-card__hint">{job.progress}</p> : null}
      {automaticRecoveryMessage(job) ? (
        <p className="ws-card__hint" data-testid="continuous-generation-auto-recovery">
          {automaticRecoveryMessage(job)}
        </p>
      ) : null}
      {job?.completed_chapters.length ? (
        <p className="ws-card__hint">已完成章节：{job.completed_chapters.join("、")}</p>
      ) : null}
      {job?.status === "stopped" && job.stop_reason ? (
        <p className="ws-card__hint">停止原因：{userFacingErrorMessage(job.stop_reason)}</p>
      ) : null}
      {job?.status === "failed" && job.error ? (
        <p className="ws-error">连续生产失败：{userFacingErrorMessage(job.error)}</p>
      ) : null}
      {error ? <p className="ws-error">连续生产请求失败：{userFacingErrorMessage(error)}</p> : null}
      {workflowError ? <p className="ws-error">细纲状态读取失败：{userFacingErrorMessage(workflowError)}</p> : null}
      {workflowLoading ? <p className="ws-card__hint">正在检查下一章所在卷和章节细纲。</p> : null}
      {awaitingConsistency && job.consistency_gate ? (
        <GenerationConsistencyPanel
          gate={job.consistency_gate}
          busy={Boolean(action)}
          replanBusy={action === "replan"}
          originalPlan={job.original_plan}
          revisedPlan={job.revised_plan}
          replanStatus={job.replan_status}
          replanAttempts={job.replan_attempts}
          replanResult={job.replan_result}
          onReplan={onConsistencyReplan}
          onContinue={onConsistencyContinue}
          onReturn={onConsistencyReturn}
        />
      ) : null}
    </section>
  );
}
