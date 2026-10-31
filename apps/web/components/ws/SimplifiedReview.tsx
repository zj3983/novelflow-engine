import { LoaderCircle, ScanSearch } from "lucide-react";

import type {
  ShuangwenSkillReview,
  SimplifiedReview as SimplifiedReviewData,
} from "../../lib/api";

type Props = {
  report?: SimplifiedReviewData;
  compact?: boolean;
};

const CATEGORY_LABELS: Record<string, string> = {
  hard: "硬伤",
  dialogue: "对话",
  prose: "正文",
  ai_flavor: "AI味",
};

export function SimplifiedReview({ report, compact = false }: Props) {
  if (!report) {
    return (
      <section className={compact ? "" : "ws-card"} data-testid="simplified-review">
        <p className="ws-card__title">审稿</p>
        <p className="ws-card__hint">尚未审稿。</p>
      </section>
    );
  }

  const categories = [report.categories.hard, report.categories.dialogue, report.categories.ai_flavor, report.categories.prose];
  const aiCheckExecuted = report.diagnostics?.ai_flavor_check_executed;
  const contextRequired = report.diagnostics?.requires_contextual_prose_review === true;
  const contextExecuted = report.diagnostics?.contextual_prose_review_executed === true;
  const statusLabel = report.status === "blocked"
    ? "有必须修改的问题"
    : report.status === "warning" || report.status === "needs_revision"
      ? "有修改建议"
      : contextRequired && !contextExecuted ? "文风待审" : "通过";
  return (
    <section className={compact ? "" : "ws-card"} data-testid="simplified-review">
      <div className="ws-section-head">
        <div>
          <p className="ws-card__title">{report.agent_label || "综合审稿"}</p>
          <p className="ws-card__hint">{report.summary}</p>
        </div>
        <span className="ws-badge">{statusLabel}</span>
      </div>
      <p className="ws-card__hint">
        {categories.map((category) => category === report.categories.ai_flavor && contextRequired && !contextExecuted
          ? "AI味 待上下文审稿"
          : category === report.categories.ai_flavor && aiCheckExecuted === false
          ? `${category.label} ${category.count ? `${category.count}（未专项检查）` : "未检查"}`
          : `${category.label} ${category.count}`).join(" · ")}
      </p>
      {contextRequired ? <p className="ws-card__hint">{contextExecuted ? "上下文审稿已完成：结合全文、人物口吻和叙事用途判断。" : "尚未完成上下文审稿；关键词命中仅作线索，不作为正文问题。"}</p> : typeof aiCheckExecuted === "boolean" ? (
        <p className="ws-card__hint">
          {aiCheckExecuted ? "AI味规则检查已执行：检查固定句式、套话和报告腔。" : "AI味专项检查未执行，不能据此判断正文没有问题。"}
        </p>
      ) : null}
      {contextExecuted && typeof report.diagnostics?.contextual_prose_review_summary === "string" ? <p className="ws-card__hint">上下文结论：{report.diagnostics.contextual_prose_review_summary}</p> : null}
      {report.issues.length ? (
        <ul className="ws-plain-list">
          {report.issues.slice(0, 3).map((issue, index) => (
            <li key={`${issue.category}-${issue.message}-${index}`}>
              <strong>{CATEGORY_LABELS[issue.category] || issue.category}：</strong>
              {issue.message}
              <span className="ws-card__hint"> 修改：{issue.suggestion}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="ws-card__hint">{contextRequired && !contextExecuted ? "上下文文风结论待确认。" : "当前审稿未发现需要处理的问题。"}</p>
      )}
      {(report.findings?.length ?? 0) > report.issues.length ? (
        <details>
          <summary>查看其余 {report.findings!.length - report.issues.length} 条审稿问题</summary>
          <ul className="ws-plain-list">{report.findings!.slice(report.issues.length).map((issue, index) => <li key={index}>
            <strong>{CATEGORY_LABELS[issue.category] || issue.category}：</strong>{issue.message}
            <span className="ws-card__hint"> 修改：{issue.suggestion}</span>
          </li>)}</ul>
        </details>
      ) : report.total_issues > report.issues.length ? (
        <p className="ws-card__hint">其余 {report.total_issues - report.issues.length} 条保留在内部明细中，改稿先处理上面的问题。</p>
      ) : null}
    </section>
  );
}

type ShuangwenReviewProps = {
  report?: ShuangwenSkillReview;
  loading?: boolean;
  error?: string;
  onRun: () => void;
};

export function ShuangwenReview({
  report,
  loading = false,
  error = "",
  onRun,
}: ShuangwenReviewProps) {
  const executed = report?.executed === true;
  const findings = executed
    ? Array.from(new Set([...Object.values(report.checks).flat(), ...report.issues]))
    : [];
  const statusLabel = report?.status === "passed" ? "通过" : "有修改建议";

  return (
    <section className="ws-card" data-testid="shuangwen-review">
      <div className="ws-section-head">
        <div>
          <p className="ws-card__title">爽文检查</p>
          {executed ? <p className="ws-card__hint">{report.summary}</p> : null}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {executed ? (
            <span className={`ws-badge${report.status === "passed" ? " ws-badge--success" : " ws-badge--warn"}`}>
              {statusLabel}
            </span>
          ) : null}
          <button
            type="button"
            className="ws-button"
            disabled={loading}
            aria-label={loading ? "正在运行爽文检查" : "运行爽文检查"}
            onClick={onRun}
          >
            {loading ? <LoaderCircle aria-hidden="true" size={16} /> : <ScanSearch aria-hidden="true" size={16} />}
            {loading ? "检查中..." : "运行爽文检查"}
          </button>
        </div>
      </div>
      {!executed ? <p className="ws-card__hint">尚未执行爽文检查</p> : null}
      {executed && findings.length ? (
        <ul className="ws-plain-list">
          {findings.map((finding) => <li key={finding}>{finding}</li>)}
        </ul>
      ) : null}
      {executed && report.status === "passed" && !findings.length ? (
        <p className="ws-card__hint">本次检查未发现需要处理的问题。</p>
      ) : null}
      {error ? <p className="ws-inline-error" role="alert">{error}</p> : null}
    </section>
  );
}
