export type ReviewAnnotationIssue = { message: string; suggestion: string; quotes: string[]; source?: string };
export type ReviewAnchor = { start: number; end: number; kind: "simile" | "quote"; messages: string[]; issues: ReviewAnnotationIssue[] };
export type ReviewAnnotations = { anchors: ReviewAnchor[]; global: string[]; unlocated: string[] };

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

// Keep these markers aligned with agents/pipeline.py::_SIMILE_MARKERS.
const SIMILE_PATTERN = /仿佛|如同|犹如|宛如|就像|像是/g;

function quotesFrom(value: unknown): string[] {
  if (typeof value === "string") return value.trim() ? [value] : [];
  if (Array.isArray(value)) return value.flatMap(quotesFrom);
  const item = record(value);
  return [item.quote, item.text, item.excerpt].flatMap(quote => typeof quote === "string" && quote.trim() ? [quote] : []);
}

function collectFindings(quality: unknown): Array<Record<string, unknown>> {
  const report = record(quality);
  const findings: Array<Record<string, unknown>> = [];
  const byCode = new Map<string, Record<string, unknown>>();
  const byMessage = new Map<string, Record<string, unknown>>();
  function addSource(source: unknown, plans: unknown[] = [], canonical = false) {
    if (!Array.isArray(source)) return;
    for (const [index, value] of source.entries()) {
      const finding = typeof value === "string" ? { code: value, message: value } : record(value);
      const code = String(finding.code ?? "");
      const message = String(finding.message ?? finding.reason ?? finding.issue ?? code);
      if (!message || ["writing_review", "primary_conflict", "secondary_conflict", "event_beat"].includes(message)) continue;
      if (typeof value === "string" && /^[a-z_]+(?:\.[a-z_]+)*$/.test(value) && !["style.simile_stacking", "body_too_short", "body_too_long"].includes(value) && !value.startsWith("chapter.length_")) continue;
      const existing = (code ? byCode.get(code) : undefined) ?? byMessage.get(message);
      const incomingQuotes = [finding.evidence, finding.quote, finding.excerpt, finding.quotes].flatMap(quotesFrom);
      const target = existing ?? { ...finding, message, quotes: [] };
      if (existing && target.message === target.code && message !== code) target.message = message;
      target.quotes = [...new Set([...quotesFrom(target.quotes), ...incomingQuotes])];
      const plan = typeof plans[index] === "string" ? plans[index] as string : "";
      const suggestion = String(finding.suggestion || plan || "").trim();
      const priority = canonical ? 3 : plan ? 2 : 1;
      if (suggestion && priority >= Number(target.suggestionPriority ?? 0)) {
        target.suggestion = suggestion;
        target.suggestionPriority = priority;
      }
      if (finding.scope === "global") target.scope = "global";
      if (!existing) findings.push(target);
      if (code) byCode.set(code, target);
      byMessage.set(message, target);
    }
  }
  const visited = new Set<unknown>();
  function visit(envelope: unknown) {
    if (!envelope || visited.has(envelope)) return;
    visited.add(envelope);
    const source = record(envelope);
    for (const key of ["findings", "blocking", "issues", "warnings", "hard_issues", "soft_issues", "annotations"]) {
      addSource(source[key], key === "issues" && Array.isArray(source.revision_plan) ? source.revision_plan : [], source.schema_version === "review-result/v2");
    }
    for (const [key, nested] of Object.entries(source)) {
      if (key === "length_review") continue; // Numbers mirror the named chapter.length_* finding.
      if (key === "complete_writing_review" && record(report.review_result).schema_version === "review-result/v2") continue;
      if (key === "quality_report" || key.endsWith("_review") || key === "review_result") visit(nested);
    }
    for (const raw of Object.values(record(record(source.diagnostics).raw_reports))) visit(raw);
  }
  visit(report.review_result);
  visit(report.writing_review);
  visit(report.simplified_review);
  visit(report);
  return findings;
}

export function buildReviewAnnotations(body: string, quality: unknown): ReviewAnnotations {
  const findings = collectFindings(quality);
  const result: ReviewAnnotations = { anchors: [], global: [], unlocated: [] };
  let similesLocated = false;
  for (const finding of findings) {
    const code = String(finding.code ?? "");
    const message = String(finding.message ?? code);
    const issue = { message, suggestion: String(finding.suggestion ?? ""), source: String(finding.source ?? "") };
    if (finding.scope === "global" || code.startsWith("chapter.length_") || code === "body_too_long" || code === "body_too_short" || /字数|正文.*字.*(?:超过|低于)|章节.*字.*(?:偏多|偏少)/.test(message)) {
      result.global.push(message);
      continue;
    }
    if (code === "style.simile_stacking" || /显式比喻|比喻过密/.test(message)) {
      if (!similesLocated) {
        for (const match of body.matchAll(new RegExp(SIMILE_PATTERN))) {
          result.anchors.push({ start: match.index!, end: match.index! + match[0].length, kind: "simile", messages: [message], issues: [{ ...issue, quotes: [match[0]] }] });
        }
        similesLocated = true;
        if (!result.anchors.length) result.unlocated.push(message);
      }
      continue;
    }
    const explicitEvidence = quotesFrom(finding.quotes);
    // Legacy style reviewers embed exact examples in their message. Match
    // those examples literally; never infer an offset for general advice.
    const evidence = explicitEvidence.length ? explicitEvidence : [...message.matchAll(/“([^”]{4,})”/g)].map(match => match[1]);
    let matched = false;
    for (const quote of new Set(evidence)) {
      for (let start = body.indexOf(quote); start >= 0; start = body.indexOf(quote, start + quote.length)) {
        result.anchors.push({ start, end: start + quote.length, kind: "quote", messages: [message], issues: [{ ...issue, quotes: [quote] }] });
        matched = true;
      }
    }
    if (!matched || (explicitEvidence.length > 0 && explicitEvidence.some(quote => !body.includes(quote)))) result.unlocated.push(message);
  }
  // Render overlapping evidence once, without duplicating any prose.
  result.anchors.sort((a, b) => a.start - b.start || b.end - a.end);
  const merged: ReviewAnchor[] = [];
  for (const anchor of result.anchors) {
    const previous = merged.at(-1);
    if (previous && anchor.start < previous.end) {
      previous.end = Math.max(previous.end, anchor.end);
      previous.messages = [...new Set([...previous.messages, ...anchor.messages])];
      for (const issue of anchor.issues) {
        const existing = previous.issues.find(item => item.message === issue.message);
        if (existing) existing.quotes = [...new Set([...existing.quotes, ...issue.quotes])];
        else previous.issues.push({ ...issue, quotes: [...issue.quotes] });
      }
    } else {
      merged.push({ ...anchor, issues: anchor.issues.map(issue => ({ ...issue, quotes: [...issue.quotes] })) });
    }
  }
  return { anchors: merged, global: [...new Set(result.global)], unlocated: [...new Set(result.unlocated)] };
}

export function explainReviewAnchor(body: string, anchor: ReviewAnchor) {
  const quote = body.slice(anchor.start, anchor.end);
  const issues = anchor.issues.map(issue => {
    const message = issue.message;
    const issueQuote = issue.quotes.join("、") || quote;
    let label = "审稿问题";
    let problem = message;
    let suggestion = issue.suggestion || "核对这段原文及上下文，再决定是否局部修改；审稿没有提供更具体的建议。";
    if (issue.source === "contextual_prose") {
      const separator = message.indexOf("：");
      return { label: separator > 0 ? message.slice(0, separator) : "上下文表达问题", problem: separator > 0 ? message.slice(separator + 1) : message, suggestion, original: message };
    }
    if (/清单式|电报码|台词像提纲|对话不自然/.test(message)) {
      label = "对白像操作清单";
      problem = "这段话连续罗列步骤或状态。审稿认为它像在念规程，缺少人物当场说话的语气与回应。";
      suggestion = issue.suggestion || "按说话人的身份和当时情绪组织对白，保留必要信息；如果原文是在填写记录或报数，应结合用途复核。";
    } else if (/后台硬词|抽象审稿词/.test(message)) {
      label = "用词偏说明式（需复核）";
      problem = `“${issueQuote}”被文风规则列为偏说明式用词，这是文风提醒，不能据此认定这个词用错。`;
      suggestion = "先判断它是否为这段情节必需的专业术语。专业语境下可以保留；只有多余、难懂的解释才换成具体说法。";
    } else if (/AI高频套话/.test(message)) {
      label = "套话命中（需复核）";
      const repeatedQuote = issue.quotes[0] || quote;
      const count = body.split(repeatedQuote).length - 1;
      problem = `“${repeatedQuote}”在本章出现${count}次，被审稿规则列为套话。需检查这一处是否重复或多余，单独使用并不等于写得有问题。`;
      suggestion = issue.suggestion || "能直接接下一个动作时可删去这个词；如果它确实交代了必要的时间或转折，可以保留。";
    } else if (/机械切段|解释腔|模型在拆规则|报告腔/.test(message)) {
      label = "解释腔提示";
      problem = `审稿命中了“${issueQuote}”，认为这一带的表达偏说明式。请核对是否在重复解释已经展示过的规则或结果。`;
      suggestion = issue.suggestion || "删去重复解说，让动作或对白呈现结果；必要的技术说明可以保留。";
    } else if (anchor.kind === "simile") {
      label = "比喻密度偏高";
      problem = "这处比喻计入了全章比喻密度。审稿提示全章使用过密，并不表示这一个比喻必然有错。";
      suggestion = issue.suggestion || "检查与附近比喻是否重复；多余的改成直接动作或感受，保留准确、有作用的比喻。";
    } else if (/不是X/.test(message)) {
      label = "对称解释句重复";
      problem = "这处使用了“不是……而是……”一类对称解释句，同章重复使用容易显得在替读者下定义。";
    }
    return { label, problem, suggestion, original: message };
  });
  return { quote, issues };
}
