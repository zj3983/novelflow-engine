"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { buildReviewAnnotations, explainReviewAnchor } from "../../lib/review-annotations";

export function AnnotatedChapterBody({ body, qualityReport, className = "ws-reader__body" }: { body: string; qualityReport?: unknown; className?: string }) {
  const annotations = useMemo(() => buildReviewAnnotations(body, qualityReport), [body, qualityReport]);
  const [visible, setVisible] = useState(true);
  const [active, setActive] = useState(-1);
  const [locationsOpen, setLocationsOpen] = useState(false);
  const marks = useRef<Array<HTMLElement | null>>([]);
  useEffect(() => { setActive(-1); }, [body, qualityReport]);
  useEffect(() => {
    if (!visible || active < 0) return;
    marks.current[active]?.focus({ preventScroll: true });
    marks.current[active]?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [active, visible]);
  const count = annotations.anchors.length;
  const explainedIndex = active >= 0 ? active : 0;
  const explanation = annotations.anchors[explainedIndex] ? explainReviewAnchor(body, annotations.anchors[explainedIndex]) : null;
  function goTo(index: number) {
    const next = (index + count) % count;
    if (visible && active === next) {
      marks.current[next]?.focus({ preventScroll: true });
      marks.current[next]?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
    setVisible(true);
    setActive(next);
  }
  let offset = 0;
  const paragraphs = body.split(/(\n{2,})/).map((text, chunkIndex) => {
    const start = offset;
    offset += text.length;
    if (chunkIndex % 2 || !text) return null;
    const end = start + text.length;
    const fragments = [];
    let cursor = start;
    if (visible) annotations.anchors.forEach((anchor, index) => {
      if (anchor.end <= start || anchor.start >= end) return;
      const left = Math.max(start, anchor.start);
      const right = Math.min(end, anchor.end);
      fragments.push(<Fragment key={`text-${index}`}>{body.slice(cursor, left)}</Fragment>);
      fragments.push(<mark key={`mark-${index}`} className={`ws-review-mark${active === index ? " ws-review-mark--active" : ""}`} data-review-mark={index} data-review-number={index + 1} data-active={active === index} tabIndex={0} role="button" onClick={() => goTo(index)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); goTo(index); } }} title={anchor.messages.join("；")} aria-label={`审稿标注 ${index + 1}：${anchor.messages.join("；")}`} ref={node => { if (anchor.start >= start) marks.current[index] = node; }}>{body.slice(left, right)}</mark>);
      cursor = right;
    });
    fragments.push(<Fragment key="tail">{body.slice(cursor, end)}</Fragment>);
    return <p key={chunkIndex}>{fragments}</p>;
  });
  return <>
    {count || annotations.global.length || annotations.unlocated.length ? <section className="ws-review-annotations" aria-label="正文问题标注">
      <div className="ws-toolbar">
        <strong>正文标注 {count} 处</strong>
        {count ? <>
          <button className="ws-btn ws-btn--sm" type="button" aria-expanded={locationsOpen} onClick={() => setLocationsOpen(value => !value)}>{locationsOpen ? "收起原文清单" : `查看全部${count}处原文`}</button>
          <button className="ws-btn ws-btn--sm" type="button" onClick={() => goTo(0)}>定位问题原文</button>
          <button className="ws-btn ws-btn--sm" type="button" onClick={() => goTo(active < 0 ? count - 1 : active - 1)}>上一处</button>
          <button className="ws-btn ws-btn--sm" type="button" onClick={() => goTo(active < 0 ? 0 : active + 1)}>下一处</button>
          <button className="ws-btn ws-btn--sm" type="button" onClick={() => setVisible(value => !value)}>{visible ? "隐藏标注" : "显示标注"}</button>
        </> : null}
        {count ? <span role="status">{active < 0 ? "点击定位可跳到问题处" : `已定位 ${active + 1}/${count} 处`}</span> : null}
      </div>
      <p className="ws-card__hint">原文问题 {new Set(annotations.anchors.flatMap(anchor => anchor.messages)).size} 项 · 全章问题 {annotations.global.length} 项 · 待定位 {annotations.unlocated.length} 项</p>
      {explanation ? <aside className="ws-review-active-reason" aria-label="标注问题说明" key={explainedIndex}>
        <strong>第 {explainedIndex + 1} 处问题说明</strong>
        <p className="ws-review-issue-quote"><strong>原文：</strong>{explanation.quote}</p>
        {explanation.issues.map((issue, index) => <div className="ws-review-issue" key={index}>
          <p><strong>问题：{issue.label}</strong>。{issue.problem}</p>
          <p><strong>建议：</strong>{issue.suggestion}</p>
          <details><summary>查看原始审稿意见</summary><p className="ws-card__hint">{issue.original}</p></details>
        </div>)}
      </aside> : null}
      {locationsOpen ? <ol className="ws-review-location-list" aria-label="全部标注原文">
        {annotations.anchors.map((anchor, index) => {
          const start = Math.max(0, anchor.start - 24);
          const end = Math.min(body.length, anchor.end + 50);
          return <li key={index}><button type="button" aria-label={`定位第${index + 1}处`} title={body.slice(start, end)} onClick={() => { setLocationsOpen(false); goTo(index); }}>
            <span className="ws-review-location-number">{index + 1}</span>
            <span className="ws-review-location-excerpt">{start > 0 ? "…" : ""}{body.slice(start, anchor.start)}<strong>{body.slice(anchor.start, anchor.end)}</strong>{body.slice(anchor.end, end)}{end < body.length ? "…" : ""}
              <span className="ws-review-location-problem">问题：{explainReviewAnchor(body, anchor).issues.map(issue => issue.label).join("；")}</span>
            </span>
          </button></li>;
        })}
      </ol> : null}
      {count ? <p className="ws-card__hint">点击正文高亮或原文清单，查看这一处的具体问题和修改建议。文风提醒需要结合语境复核。</p> : null}
      {annotations.global.map(message => <p className="ws-card__hint" key={message}>全章问题：{message} 不对应某一句正文。</p>)}
      {annotations.unlocated.map(message => <p className="ws-card__hint" key={message}>待补原文定位：{message} 审稿未提供完整、可匹配的原句。</p>)}
    </section> : null}
    <div className={className} data-testid="annotated-chapter-body">{paragraphs}</div>
  </>;
}
