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
  onContinue: () => void;
  onReturn: () => void;
};

export function GenerationConsistencyPanel({
  gate,
  busy = false,
  onContinue,
  onReturn,
}: Props) {
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
      <div className="ws-action-row ws-action-row--flush">
        <button className="ws-btn ws-btn--sm" type="button" disabled={busy} onClick={onReturn} data-testid="generation-consistency-return">
          {busy ? "处理中..." : "返回修改"}
        </button>
        <button className="ws-btn ws-btn--sm ws-btn--primary" type="button" disabled={busy} onClick={onContinue} data-testid="generation-consistency-continue">
          {busy ? "处理中..." : "仍然生成"}
        </button>
      </div>
    </section>
  );
}
