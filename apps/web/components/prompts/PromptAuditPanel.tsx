import type { PromptAuditIssue, PromptAuditResult } from "../../lib/api";

type PromptAuditPanelProps = {
  result: PromptAuditResult;
  stale?: boolean;
  deepLoading?: boolean;
  deepError?: string;
  onDeepAudit?: () => void;
};

function IssueList({ issues, emptyText }: { issues: PromptAuditIssue[]; emptyText: string }) {
  if (!issues.length) {
    return <p className="ws-card__hint">{emptyText}</p>;
  }

  return (
    <div className="ws-prompt-audit__issues">
      {issues.map((issue) => (
        <article className="ws-prompt-audit__issue" key={`${issue.code}-${issue.location}-${issue.title}`}>
          <div className="ws-prompt-audit__issue-head">
            <strong>{issue.title}</strong>
            <span>预计可减少 {issue.estimated_reduction_characters} 字符</span>
          </div>
          <p>{issue.evidence}</p>
          <dl>
            <div><dt>位置</dt><dd>{issue.location}</dd></div>
            <div><dt>建议</dt><dd>{issue.suggestion}</dd></div>
          </dl>
        </article>
      ))}
    </div>
  );
}

export function PromptAuditPanel({
  result,
  stale = false,
  deepLoading = false,
  deepError,
  onDeepAudit,
}: PromptAuditPanelProps) {
  const { summary } = result;

  return (
    <section className="ws-prompt-audit" aria-labelledby="prompt-audit-title">
      <div className="ws-section-head">
        <div>
          <h2 id="prompt-audit-title" className="ws-card__title">提示词检查</h2>
          {result.runtime ? (
            <p className="ws-card__hint">
              {result.runtime.provider} / {result.runtime.model} · {result.runtime.elapsed_seconds} 秒 · 输入 {result.runtime.prompt_characters} 字符
            </p>
          ) : null}
        </div>
        {onDeepAudit ? (
          <button className="ws-btn" type="button" disabled={deepLoading} onClick={onDeepAudit}>
            {deepLoading ? "检查中..." : "AI 深度检查"}
          </button>
        ) : null}
      </div>

      {deepLoading ? <p className="ws-card__hint" role="status">AI 深度检查中...</p> : null}
      {stale ? <p className="ws-inline-warning" role="status">内容已变化，请重新检查。</p> : null}
      {deepError ? <p className="ws-inline-error" role="alert">{deepError}</p> : null}

      <div className="ws-prompt-audit__summary" aria-label="检查统计">
        <span><strong>{summary.characters}</strong> 总字符</span>
        <span><strong>{summary.lines}</strong> 有效行</span>
        <span>
          <strong>{summary.estimated_redundant_characters}</strong> 预计重复/可减少字符 · {summary.estimated_reduction_percent}%
        </span>
      </div>

      <section className="ws-prompt-audit__group" aria-labelledby="prompt-audit-must-fix">
        <h3 id="prompt-audit-must-fix">必须修</h3>
        <IssueList issues={result.must_fix} emptyText="没有必须修的问题。" />
      </section>

      <section className="ws-prompt-audit__group" aria-labelledby="prompt-audit-suggestions">
        <h3 id="prompt-audit-suggestions">建议精简</h3>
        <IssueList issues={result.suggestions} emptyText="没有需要精简的建议。" />
      </section>

      <section className="ws-prompt-audit__group" aria-labelledby="prompt-audit-passed">
        <h3 id="prompt-audit-passed">正常</h3>
        {result.passed_checks.length ? (
          <ul className="ws-prompt-audit__passed">
            {result.passed_checks.map((check) => <li key={check}>{check}</li>)}
          </ul>
        ) : <p className="ws-card__hint">暂无通过项。</p>}
      </section>
    </section>
  );
}
