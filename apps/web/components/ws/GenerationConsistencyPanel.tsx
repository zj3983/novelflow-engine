"use client";

import type { GenerationConsistencyGate } from "../../lib/api";

function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "未知";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function severityIcon(severity: string): string {
  return severity === "error" ? "🔴" : severity === "info" ? "🔵" : "🟡";
}

type Props = {
  gate: GenerationConsistencyGate;
  busy?: boolean;
  replanBusy?: boolean;
  originalPlan?: Record<string, unknown> | null;
  revisedPlan?: Record<string, unknown> | null;
  replanStatus?: string;
  replanAttempts?: number;
  replanResult?: Record<string, unknown> | null;
  onReplan?: () => void;
  onContinue: () => void;
  onReturn: () => void;
};

function planSummary(plan: Record<string, unknown> | null | undefined): string[] {
  if (!plan) return [];
  const intent = plan.chapter_intent;
  const intentRecord = intent && typeof intent === "object" && !Array.isArray(intent)
    ? intent as Record<string, unknown>
    : null;
  const title = String(plan.chapter_title || intentRecord?.chapter_title || "").trim();
  const goal = String(plan.chapter_goal || intentRecord?.chapter_goal || "").trim();
  const moves = ["character_moves", "action_briefs", "scene_beats", "scene_cards"]
    .map((key) => Array.isArray(plan[key]) ? plan[key].length : 0)
    .find((count) => count > 0);
  return [
    title ? `标题：${title}` : "",
    goal ? `目标：${goal}` : "",
    moves ? `结构化节拍：${moves} 项` : "",
  ].filter(Boolean);
}

function replanStatusLabel(status: string | undefined): string {
  if (status === "replanned_clear") return "新计划通过一致性检查";
  if (status === "replanned_with_warnings") return "新计划通过，仍有提示";
  if (status === "still_blocking") return "新计划仍有阻断问题";
  if (status === "failed") return "重新规划失败，原计划已保留";
  return "";
}

export function GenerationConsistencyPanel({
  gate,
  busy = false,
  replanBusy = false,
  originalPlan,
  revisedPlan,
  replanStatus = "",
  replanAttempts = 0,
  replanResult,
  onReplan,
  onContinue,
  onReturn,
}: Props) {
  const originalSummary = planSummary(originalPlan);
  const revisedSummary = planSummary(revisedPlan);
  const resultLabel = replanStatusLabel(
    replanStatus || (typeof replanResult?.status === "string" ? replanResult.status : ""),
  );
  const replanAvailable = Boolean(onReplan) && replanAttempts < 1;
  return (
    <section className="ws-card ws-generation-consistency" aria-label="生成前一致性检查" data-testid="generation-consistency-panel">
      <div className="ws-section-head">
        <div>
          <p className="ws-card__title">生成前检查发现 {gate.warnings.length} 个问题</p>
          <p className="ws-card__hint">
            第 {gate.target_chapter} 章 · 检查边界为第 {gate.checked_at_boundary} 章结束；写手尚未启动。
          </p>
        </div>
        <span className="ws-badge">{gate.status === "blocking" ? "需要确认" : "待确认"}</span>
      </div>
      <div className="ws-generation-consistency__warnings">
        {gate.warnings.map((warning, index) => (
          <article className="ws-generation-consistency__warning" data-testid="generation-consistency-warning" key={`${warning.code}-${warning.character_name}-${index}`}>
            <strong>{severityIcon(warning.severity)} {warning.character_name} · {warning.code}</strong>
            <p>{warning.message}</p>
            {warning.observed !== undefined || warning.expected !== undefined ? (
              <p className="ws-card__hint">
                历史记录：{displayValue(warning.observed)}；计划值：{displayValue(warning.expected)}
              </p>
            ) : null}
            {warning.suggestion ? <p className="ws-card__hint">建议：{warning.suggestion}</p> : null}
          </article>
        ))}
      </div>
      {(resultLabel || originalSummary.length > 0 || revisedSummary.length > 0) ? (
        <section className="ws-generation-consistency__replan" aria-label="一致性重新规划结果" data-testid="generation-consistency-replan-result">
          {resultLabel ? <p className="ws-card__hint">{resultLabel}</p> : null}
          {originalSummary.length > 0 ? (
            <div>
              <strong>原计划问题</strong>
              <ul>
                {originalSummary.map((item) => <li key={`original-${item}`}>{item}</li>)}
              </ul>
            </div>
          ) : null}
          {revisedSummary.length > 0 ? (
            <div>
              <strong>新计划摘要</strong>
              <ul>
                {revisedSummary.map((item) => <li key={`revised-${item}`}>{item}</li>)}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}
      <div className="ws-action-row ws-action-row--flush">
        <button className="ws-btn ws-btn--sm" type="button" disabled={busy} onClick={onReturn} data-testid="generation-consistency-return">
          {busy ? "处理中..." : "返回修改"}
        </button>
        {onReplan ? (
          <button className="ws-btn ws-btn--sm" type="button" disabled={busy || !replanAvailable} onClick={onReplan} data-testid="generation-consistency-replan">
            {replanBusy ? "正在根据一致性问题重新规划本章…" : replanAvailable ? "重新规划" : "本任务已重新规划"}
          </button>
        ) : null}
        <button className="ws-btn ws-btn--sm ws-btn--primary" type="button" disabled={busy} onClick={onContinue} data-testid="generation-consistency-continue">
          {busy ? "处理中..." : revisedPlan ? "使用新计划继续" : "仍然生成"}
        </button>
      </div>
    </section>
  );
}
