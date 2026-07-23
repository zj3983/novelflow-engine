"use client";

import { useEffect, useState } from "react";

import { fetchProjectPromptContext, type PromptContextResponse } from "../../lib/api";

export function PromptContextView({ projectId, chapterNumber }: { projectId: string; chapterNumber: number }) {
  const [context, setContext] = useState<PromptContextResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    fetchProjectPromptContext(projectId, chapterNumber)
      .then((response) => {
        if (!cancelled) setContext(response);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [chapterNumber, projectId]);

  if (loading) return <p className="ws-card__hint" role="status">正在读取第 {chapterNumber} 章上下文...</p>;
  if (error) return <p className="ws-inline-error" role="alert">上下文加载失败：{error}</p>;

  const modules = context?.modules ?? [];
  return (
    <section className="ws-prompt-section" aria-label="上下文模块">
      <div className="ws-section-head">
        <div>
          <h2 className="ws-card__title">第 {context?.chapter_number ?? chapterNumber} 章上下文</h2>
          <p className="ws-card__hint">这里只显示生成时可装配的数据，不包含提示词指令。</p>
        </div>
      </div>
      {modules.length ? modules.map((module) => (
        <details className="ws-card ws-prompt-card" key={module.key} open={module.available}>
          <summary className="ws-prompt-card__summary">
            <span>
              <strong>{module.title}</strong>
              <small>{module.stage} · {module.available ? `${module.chars} 字` : "本章未提供"}</small>
            </span>
          </summary>
          {module.available ? (
            <pre className="ws-prompt-text">{module.content}</pre>
          ) : (
            <p className="ws-card__hint">本章没有提供该模块，不会把空内容传给模型。</p>
          )}
        </details>
      )) : <p className="ws-card__hint">本章没有可用的上下文模块。</p>}
    </section>
  );
}
