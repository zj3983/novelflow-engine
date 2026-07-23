import type { SimplifiedReview as SimplifiedReviewData } from "../../lib/api";

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
  const statusLabel = report.status === "blocked"
    ? "存在硬伤"
    : report.status === "needs_revision"
      ? "需要修改"
      : "通过";
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
        {categories.map((category) => `${category.label} ${category.count}`).join(" · ")}
      </p>
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
        <p className="ws-card__hint">当前章节没有需要处理的问题。</p>
      )}
      {report.total_issues > report.issues.length ? (
        <p className="ws-card__hint">其余 {report.total_issues - report.issues.length} 条保留在内部明细中，改稿先处理上面的问题。</p>
      ) : null}
    </section>
  );
}
