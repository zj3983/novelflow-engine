"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  auditPrompt,
  deleteProjectPromptTemplate,
  fetchProjectPromptTemplates,
  saveGlobalPromptTemplate,
  saveProjectPromptTemplate,
  type PromptTemplateEntry,
  type PromptAuditResult,
} from "../../lib/api";
import { PromptAuditPanel } from "./PromptAuditPanel";

const SOURCE_LABELS: Record<PromptTemplateEntry["source"], string> = {
  global_default: "全局默认",
  global_override: "全局修改",
  project_override: "项目覆盖",
};

export function PromptTemplatesView({ projectId }: { projectId: string }) {
  const [templates, setTemplates] = useState<PromptTemplateEntry[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<"project" | "global" | "restore" | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [auditResult, setAuditResult] = useState<PromptAuditResult | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState("");
  const auditRequestId = useRef(0);

  const selected = useMemo(
    () => templates.find((template) => template.key === selectedKey) ?? templates[0] ?? null,
    [selectedKey, templates],
  );

  async function loadTemplates(preferredKey?: string) {
    auditRequestId.current += 1;
    setAuditResult(null);
    setAuditError("");
    setAuditLoading(false);
    setLoading(true);
    setError("");
    try {
      const response = await fetchProjectPromptTemplates(projectId);
      setTemplates(response.templates);
      const nextKey = preferredKey && response.templates.some((item) => item.key === preferredKey)
        ? preferredKey
        : response.templates[0]?.key ?? "";
      setSelectedKey(nextKey);
      setContent(response.templates.find((item) => item.key === nextKey)?.content ?? "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTemplates();
  }, [projectId]);

  function selectTemplate(template: PromptTemplateEntry) {
    auditRequestId.current += 1;
    setSelectedKey(template.key);
    setContent(template.content);
    setMessage("");
    setError("");
    setAuditResult(null);
    setAuditError("");
    setAuditLoading(false);
  }

  async function runAudit() {
    if (!selected) return;
    const requestId = auditRequestId.current + 1;
    auditRequestId.current = requestId;
    setAuditLoading(true);
    setAuditError("");
    setAuditResult(null);
    try {
      const result = await auditPrompt({
        mode: "template",
        content,
        template_key: selected.key,
        required_variables: selected.required_variables,
      });
      if (requestId === auditRequestId.current) {
        setAuditResult(result);
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

  async function save(scope: "project" | "global") {
    if (!selected) return;
    setSaving(scope);
    setMessage("");
    setError("");
    try {
      if (scope === "project") {
        await saveProjectPromptTemplate(projectId, selected.key, content);
        setMessage("已保存为本项目覆盖");
      } else {
        await saveGlobalPromptTemplate(selected.key, content);
        setMessage("已更新全局模板，未覆盖该模板的项目会使用新内容");
      }
      await loadTemplates(selected.key);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(null);
    }
  }

  async function restoreGlobal() {
    if (!selected) return;
    setSaving("restore");
    setMessage("");
    setError("");
    try {
      await deleteProjectPromptTemplate(projectId, selected.key);
      setMessage("已删除项目覆盖，恢复使用全局模板");
      await loadTemplates(selected.key);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(null);
    }
  }

  if (loading && templates.length === 0) {
    return <p className="ws-card__hint" role="status">提示词模板加载中...</p>;
  }

  if (error && templates.length === 0) {
    return <p className="ws-inline-error" role="alert">模板加载失败：{error}</p>;
  }

  return (
    <div className="ws-template-workbench">
      <aside className="ws-template-list" aria-label="提示词模板列表">
        {templates.map((template) => (
          <button
            key={template.key}
            type="button"
            className={template.key === selected?.key ? "is-active" : ""}
            onClick={() => selectTemplate(template)}
          >
            <strong>{template.title}</strong>
            <small>{template.stage} · {SOURCE_LABELS[template.source]}</small>
          </button>
        ))}
      </aside>

      {selected ? (
        <section className="ws-template-editor" aria-labelledby="prompt-template-title">
          <div className="ws-section-head">
            <div>
              <h2 id="prompt-template-title" className="ws-card__title">{selected.title}</h2>
              <p className="ws-card__hint">
                {selected.key} · {SOURCE_LABELS[selected.source]} · 版本 {selected.version.slice(0, 12)}
              </p>
            </div>
          </div>
          <label className="ws-field">
            <span>原始模板</span>
            <textarea
              className="ws-textarea ws-template-editor__textarea"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              spellCheck={false}
            />
          </label>
          <p className="ws-card__hint">
            必需变量：{selected.required_variables.map((name) => `{{${name}}}`).join("、") || "无"}
          </p>
          <div className="ws-actions">
            <button className="ws-btn ws-btn--primary" type="button" disabled={saving !== null || auditLoading} onClick={() => void save("project")}>
              {saving === "project" ? "保存中..." : "保存为项目覆盖"}
            </button>
            <button className="ws-btn" type="button" disabled={saving !== null || auditLoading} onClick={() => void save("global")}>
              {saving === "global" ? "保存中..." : "更新全局模板"}
            </button>
            {selected.source === "project_override" ? (
              <button className="ws-btn" type="button" disabled={saving !== null || auditLoading} onClick={() => void restoreGlobal()}>
                {saving === "restore" ? "恢复中..." : "恢复全局模板"}
              </button>
            ) : null}
            <button className="ws-btn" type="button" disabled={saving !== null || auditLoading} onClick={() => void runAudit()}>
              {auditLoading ? "检查中..." : "检查提示词"}
            </button>
          </div>
          {message ? <p className="ws-inline-success" role="status">{message}</p> : null}
          {error ? <p className="ws-inline-error" role="alert">保存失败：{error}</p> : null}
          {auditLoading ? <p className="ws-card__hint" role="status">提示词检查中...</p> : null}
          {auditError ? <p className="ws-inline-error" role="alert">检查失败：{auditError}</p> : null}
          {auditResult ? <PromptAuditPanel result={auditResult} stale={false} /> : null}
        </section>
      ) : (
        <p className="ws-card__hint">没有可编辑的提示词模板。</p>
      )}
    </div>
  );
}
