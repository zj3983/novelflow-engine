"use client";

import { useEffect, useRef, useState } from "react";

import {
  auditPrompt,
  deepAuditPrompt,
  fetchProjectPromptCall,
  fetchProjectPromptCalls,
  type DeepPromptAuditResult,
  type PromptAuditResult,
  type PromptCallDetail,
  type PromptCallSummary,
} from "../../lib/api";
import { PromptAuditPanel } from "./PromptAuditPanel";

function callStatus(status: string): string {
  if (status === "succeeded") return "成功";
  if (status === "failed") return "失败";
  if (status === "started") return "调用中";
  return status;
}

import { userFacingErrorMessage } from "../../lib/user-facing-error";

export function PromptCallsView({ projectId, chapterNumber }: { projectId: string; chapterNumber: number }) {
  const [calls, setCalls] = useState<PromptCallSummary[]>([]);
  const [selected, setSelected] = useState<PromptCallDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState("");
  const [error, setError] = useState("");
  const [localAuditResult, setLocalAuditResult] = useState<PromptAuditResult | null>(null);
  const [displayAuditResult, setDisplayAuditResult] = useState<PromptAuditResult | DeepPromptAuditResult | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState("");
  const [deepLoading, setDeepLoading] = useState(false);
  const [deepError, setDeepError] = useState("");
  const detailRequestId = useRef(0);
  const auditRequestId = useRef(0);
  const deepRequestId = useRef(0);

  function clearAuditState() {
    auditRequestId.current += 1;
    deepRequestId.current += 1;
    setLocalAuditResult(null);
    setDisplayAuditResult(null);
    setAuditLoading(false);
    setAuditError("");
    setDeepLoading(false);
    setDeepError("");
  }

  useEffect(() => {
    let cancelled = false;
    detailRequestId.current += 1;
    clearAuditState();
    setLoading(true);
    setCalls([]);
    setSelected(null);
    setDetailLoading("");
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
    return () => {
      cancelled = true;
      detailRequestId.current += 1;
      auditRequestId.current += 1;
      deepRequestId.current += 1;
    };
  }, [chapterNumber, projectId]);

  async function openCall(call: PromptCallSummary) {
    const requestId = detailRequestId.current + 1;
    detailRequestId.current = requestId;
    clearAuditState();
    setSelected(null);
    setDetailLoading(call.call_id);
    setError("");
    try {
      const result = await fetchProjectPromptCall(projectId, call.call_id);
      if (requestId === detailRequestId.current) {
        setSelected(result);
      }
    } catch (reason) {
      if (requestId === detailRequestId.current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (requestId === detailRequestId.current) {
        setDetailLoading("");
      }
    }
  }

  async function runAudit() {
    if (!selected || auditLoading) return;
    const requestContent = selected.user_prompt;
    const requestId = auditRequestId.current + 1;
    auditRequestId.current = requestId;
    deepRequestId.current += 1;
    setAuditLoading(true);
    setAuditError("");
    setDeepLoading(false);
    setDeepError("");
    setLocalAuditResult(null);
    setDisplayAuditResult(null);
    try {
      const result = await auditPrompt({ mode: "final_call", content: requestContent });
      if (requestId === auditRequestId.current) {
        setLocalAuditResult(result);
        setDisplayAuditResult(result);
      }
    } catch (reason) {
      if (requestId === auditRequestId.current) {
        setAuditError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (requestId === auditRequestId.current) {
        setAuditLoading(false);
      }
    }
  }

  async function runDeepAudit() {
    if (!selected || !localAuditResult || deepLoading) return;
    const requestContent = selected.user_prompt;
    const requestLocalResult = localAuditResult;
    const requestId = deepRequestId.current + 1;
    deepRequestId.current = requestId;
    setDeepLoading(true);
    setDeepError("");
    try {
      const result = await deepAuditPrompt(
        { mode: "final_call", content: requestContent },
        requestLocalResult,
      );
      if (requestId === deepRequestId.current) {
        setDisplayAuditResult(result);
      }
    } catch (reason) {
      if (requestId === deepRequestId.current) {
        setDeepError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (requestId === deepRequestId.current) {
        setDeepLoading(false);
      }
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
            aria-pressed={selected?.call_id === call.call_id}
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
            {selected.genre_stage_modules?.length ? (
              <div>
                <p className="ws-card__hint">
                  题材阶段来源：{selected.genre_stage_profile || "未标注"}
                </p>
                <div className="ws-tag-list" aria-label="题材阶段模块">
                  {selected.genre_stage_modules.map((module) => (
                    <span className="ws-tag" key={module}>{module}</span>
                  ))}
                </div>
              </div>
            ) : null}
            {selected.system_prompt ? (
              <details className="ws-prompt-source-body">
                <summary>系统提示词</summary>
                <pre className="ws-prompt-text">{selected.system_prompt}</pre>
              </details>
            ) : null}
            <div className="ws-section-head">
              <h3 className="ws-card__title">发给模型的完整提示词</h3>
              <button className="ws-btn" type="button" disabled={auditLoading} onClick={() => void runAudit()}>
                {auditLoading ? "检查中..." : "检查这次调用"}
              </button>
            </div>
            <pre className="ws-prompt-text">{selected.user_prompt}</pre>
            <p className="ws-card__hint">读取模块：{selected.module_keys?.join("、") || "未记录"}</p>
            {auditLoading ? <p className="ws-card__hint" role="status">提示词检查中...</p> : null}
            {auditError ? <p className="ws-inline-error" role="alert">检查失败：{auditError}</p> : null}
            {displayAuditResult ? (
              <PromptAuditPanel
                result={displayAuditResult}
                stale={false}
                deepLoading={deepLoading}
                deepError={deepError}
                onDeepAudit={localAuditResult ? () => void runDeepAudit() : undefined}
              />
            ) : null}
          </>
        ) : (
          <p className="ws-card__hint">选择一条调用，查看当时真正发送给模型的完整内容。</p>
        )}
        {error ? <p className="ws-inline-error" role="alert">调用记录加载失败：{userFacingErrorMessage(error)}</p> : null}
      </section>
    </div>
  );
}
