"use client";

import { useEffect, useState } from "react";

import {
  fetchProjectPromptCall,
  fetchProjectPromptCalls,
  type PromptCallDetail,
  type PromptCallSummary,
} from "../../lib/api";

function callStatus(status: string): string {
  if (status === "succeeded") return "成功";
  if (status === "failed") return "失败";
  if (status === "started") return "调用中";
  return status;
}

export function PromptCallsView({ projectId, chapterNumber }: { projectId: string; chapterNumber: number }) {
  const [calls, setCalls] = useState<PromptCallSummary[]>([]);
  const [selected, setSelected] = useState<PromptCallDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSelected(null);
    setError("");
    fetchProjectPromptCalls(projectId, chapterNumber)
      .then((response) => {
        if (!cancelled) setCalls(response.calls);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [chapterNumber, projectId]);

  async function openCall(call: PromptCallSummary) {
    setDetailLoading(call.call_id);
    setError("");
    try {
      setSelected(await fetchProjectPromptCall(projectId, call.call_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setDetailLoading("");
    }
  }

  if (loading) return <p className="ws-card__hint" role="status">正在读取真实模型调用...</p>;

  return (
    <div className="ws-call-workbench">
      <section className="ws-call-list" aria-label="模型调用记录">
        <div className="ws-section-head">
          <div>
            <h2 className="ws-card__title">第 {chapterNumber} 章实际调用</h2>
            <p className="ws-card__hint">每次重试单独记录，失败调用也会保留。</p>
          </div>
        </div>
        {calls.length ? calls.map((call) => (
          <button
            key={call.call_id}
            type="button"
            className={selected?.call_id === call.call_id ? "ws-call-item is-active" : "ws-call-item"}
            aria-label={`查看调用 ${call.call_id}`}
            onClick={() => void openCall(call)}
          >
            <strong>第 {call.attempt} 次 · {call.stage}</strong>
            <small>
              {callStatus(call.status)} · {call.provider || "未知服务"} / {call.model || "未知模型"}
              {call.temperature != null ? ` · 温度 ${call.temperature}` : ""}
            </small>
            <small>{call.prompt_chars ?? 0} 字符{call.error ? ` · ${call.error}` : ""}</small>
          </button>
        )) : <p className="ws-card__hint">本章还没有真实调用记录。</p>}
      </section>

      <section className="ws-call-detail" aria-label="调用详情">
        {detailLoading ? <p className="ws-card__hint" role="status">调用详情加载中...</p> : null}
        {selected ? (
          <>
            <div className="ws-section-head">
              <div>
                <h2 className="ws-card__title">{selected.stage} · 第 {selected.attempt} 次</h2>
                <p className="ws-card__hint">
                  {selected.agent || "未标注 Agent"} · {selected.template_source || "未标注模板来源"}
                </p>
              </div>
            </div>
            {selected.system_prompt ? (
              <details className="ws-prompt-source-body">
                <summary>系统提示词</summary>
                <pre className="ws-prompt-text">{selected.system_prompt}</pre>
              </details>
            ) : null}
            <h3 className="ws-card__title">发给模型的完整提示词</h3>
            <pre className="ws-prompt-text">{selected.user_prompt}</pre>
            <p className="ws-card__hint">读取模块：{selected.module_keys?.join("、") || "未记录"}</p>
          </>
        ) : (
          <p className="ws-card__hint">选择一条调用，查看当时真正发送给模型的完整内容。</p>
        )}
        {error ? <p className="ws-inline-error" role="alert">调用记录加载失败：{error}</p> : null}
      </section>
    </div>
  );
}
