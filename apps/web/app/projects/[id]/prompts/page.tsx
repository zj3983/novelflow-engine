"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { fetchProjectPromptPreview, type PromptPreviewEntry, type PromptPreviewResponse } from "../../../../lib/api";

function promptSearchText(prompt: PromptPreviewEntry): string {
  return [prompt.title, prompt.agent, prompt.stage, prompt.source, prompt.description, prompt.content, ...(prompt.module_keys ?? [])]
    .join(" ")
    .toLowerCase();
}

function formatChars(chars: number): string {
  if (chars >= 10000) return `${(chars / 10000).toFixed(1)}万字`;
  return `${chars} 字`;
}

function allPromptText(prompts: PromptPreviewEntry[]): string {
  return prompts
    .map((prompt) =>
      [
        `# ${prompt.title}`,
        `agent: ${prompt.agent}`,
        `stage: ${prompt.stage}`,
        `source: ${prompt.source}`,
        prompt.module_keys?.length ? `modules: ${prompt.module_keys.join(", ")}` : "",
        "",
        promptDisplayText(prompt.content),
      ]
        .filter(Boolean)
        .join("\n"),
    )
    .join("\n\n---\n\n");
}

function splitPromptContent(content: string): { instructions: string; sourceBody: string } {
  const marker = "\n原正文：\n";
  const index = content.indexOf(marker);
  if (index < 0) {
    return { instructions: content, sourceBody: "" };
  }
  return {
    instructions: content.slice(0, index).trimEnd(),
    sourceBody: content.slice(index + marker.length).trimStart(),
  };
}

function promptDisplayText(content: string): string {
  const split = splitPromptContent(content);
  if (!split.sourceBody) return content;
  return `${split.instructions}\n\n原正文：\n[原正文已隐藏，${formatChars(split.sourceBody.length)}]`;
}

function FoldedPromptText({ content }: { content: string }) {
  const compactLimit = 3000;
  const foldThreshold = 6000;
  if (content.length <= foldThreshold) {
    return <pre className="ws-prompt-text">{content}</pre>;
  }
  return (
    <>
      <pre className="ws-prompt-text">
        {content.slice(0, compactLimit)}
        {"\n\n……后续内容较长，已收起。"}
      </pre>
      <details className="ws-prompt-source-body">
        <summary>展开完整内容 · {formatChars(content.length)}</summary>
        <pre className="ws-prompt-text ws-prompt-text--source">{content}</pre>
      </details>
    </>
  );
}

function PromptContent({ prompt }: { prompt: PromptPreviewEntry }) {
  const split = splitPromptContent(prompt.content);
  return (
    <>
      <FoldedPromptText content={split.instructions} />
      {split.sourceBody ? (
        <div className="ws-prompt-source-body">
          <p className="ws-prompt-hidden-source">原正文已隐藏 · {formatChars(split.sourceBody.length)}</p>
        </div>
      ) : null}
    </>
  );
}

function PromptCard({
  prompt,
  defaultOpen,
  copiedKey,
  onCopy,
}: {
  prompt: PromptPreviewEntry;
  defaultOpen?: boolean;
  copiedKey: string | null;
  onCopy: (key: string, text: string) => void;
}) {
  return (
    <details className="ws-card ws-prompt-card" open={defaultOpen}>
      <summary className="ws-prompt-card__summary">
        <span>
          <strong>{prompt.title}</strong>
          <small>
            {prompt.agent} · {prompt.stage} · {formatChars(prompt.chars)}
          </small>
        </span>
        <button
          className="ws-btn ws-btn--sm"
          type="button"
          onClick={(event) => {
            event.preventDefault();
            onCopy(prompt.key, promptDisplayText(prompt.content));
          }}
        >
          {copiedKey === prompt.key ? "已复制" : "复制"}
        </button>
      </summary>
      {prompt.description ? <p className="ws-card__hint">{prompt.description}</p> : null}
      <p className="ws-prompt-card__meta">source: {prompt.source}</p>
      {prompt.module_keys?.length ? (
        <p className="ws-prompt-card__meta">uses: {prompt.module_keys.join(" / ")}</p>
      ) : null}
      <PromptContent prompt={prompt} />
    </details>
  );
}

export default function PromptsPage() {
  const searchParams = useSearchParams();
  const { project, story, error, encodedProjectId, projectId } = useProjectWorkspace();
  const [preview, setPreview] = useState<PromptPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const history = story?.history ?? [];
  const requestedChapter = Number(searchParams?.get("chapter") || story?.current_chapter || history.at(-1)?.chapter_number || 1);
  const selectedChapter = useMemo(() => {
    return history.find((bundle) => bundle.chapter_number === requestedChapter) ?? history.at(-1) ?? null;
  }, [history, requestedChapter]);
  const targetChapter = selectedChapter?.chapter_number ?? requestedChapter;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    fetchProjectPromptPreview(projectId, targetChapter)
      .then((data) => {
        if (!cancelled) setPreview(data);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, targetChapter]);

  const normalizedQuery = query.trim().toLowerCase();
  const prompts = preview?.prompts ?? [];
  const modules = preview?.modules ?? [];
  const moduleCatalog = preview?.module_catalog ?? [];
  const visiblePrompts = normalizedQuery ? prompts.filter((prompt) => promptSearchText(prompt).includes(normalizedQuery)) : prompts;
  const visibleModules = normalizedQuery ? modules.filter((module) => promptSearchText(module).includes(normalizedQuery)) : modules;
  const totalChars = prompts.reduce((sum, prompt) => sum + prompt.chars, 0);
  const moduleChars = modules.reduce((sum, module) => sum + module.chars, 0);

  async function copyText(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      window.setTimeout(() => setCopiedKey(null), 1200);
    } catch {
      setCopiedKey(null);
    }
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title={preview ? `提示词：第 ${preview.chapter_number} 章` : "提示词"}
        subtitle={preview?.chapter_title || selectedChapter?.chapter_title || "按模块查看当前章节生成链路里的上下文和提示词。"}
        actions={
          prompts.length || modules.length ? (
            <button className="ws-btn" type="button" onClick={() => copyText("all", allPromptText([...modules, ...prompts]))}>
              {copiedKey === "all" ? "已复制" : "复制全部"}
            </button>
          ) : null
        }
      />

      {error || loadError ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error || loadError}</p>
        </div>
      ) : (
        <div className="ws-prompt-layout">
          <aside className="ws-sidepanel ws-chapter-index" aria-label="章节目录">
            <section className="ws-card">
              <div className="ws-section-head">
                <p className="ws-card__title">章节</p>
                <span className="ws-toolbar__meta">{history.length || 0} 章</span>
              </div>
              <div className="ws-chapter-list">
                {history.length ? (
                  [...history].reverse().map((bundle) => {
                    const active = bundle.chapter_number === targetChapter;
                    return (
                      <Link
                        key={bundle.chapter_number}
                        href={`/projects/${encodedProjectId}/prompts?chapter=${bundle.chapter_number}`}
                        className={`ws-chapter-list__item${active ? " ws-chapter-list__item--active" : ""}`}
                      >
                        <span>第 {bundle.chapter_number} 章</span>
                        <strong>{bundle.chapter_title || "未命名"}</strong>
                      </Link>
                    );
                  })
                ) : (
                  <p className="ws-card__hint">暂无章节，显示下一章可复现提示词。</p>
                )}
              </div>
            </section>
          </aside>

          <section className="ws-prompt-main">
            <div className="ws-card">
              <div className="ws-section-head">
                <div>
                  <p className="ws-card__title">模块化输入</p>
                  <p className="ws-card__hint">
                    {loading
                      ? "加载中..."
                      : `${modules.length} 个模块 · ${formatChars(moduleChars)}；${prompts.length} 段 prompt · ${formatChars(totalChars)} · ${
                          preview?.source || "等待加载"
                        }`}
                  </p>
                </div>
              </div>
              <label className="ws-search ws-search--compact">
                <span>筛选</span>
                <input
                  className="ws-input"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="搜模块、agent、阶段、来源或正文"
                />
              </label>
            </div>

            {visibleModules.length ? (
              <section className="ws-prompt-section">
                <div className="ws-section-head">
                  <p className="ws-card__title">上下文模块</p>
                  <span className="ws-toolbar__meta">用到时单独提取</span>
                </div>
                {visibleModules.map((module, index) => (
                  <PromptCard
                    key={module.key}
                    prompt={module}
                    defaultOpen={index < 2}
                    copiedKey={copiedKey}
                    onCopy={copyText}
                  />
                ))}
              </section>
            ) : null}

            {moduleCatalog.length ? (
              <section className="ws-prompt-section">
                <div className="ws-section-head">
                  <p className="ws-card__title">模块职责</p>
                  <span className="ws-toolbar__meta">按阶段装配</span>
                </div>
                <div className="ws-module-catalog">
                  {moduleCatalog.map((module) => (
                    <div className="ws-module-catalog__item" key={module.key}>
                      <strong>{module.title}</strong>
                      <small>{module.key} · {module.stage} · {module.owner} · {module.replaceable ? "可被 Skill 替换" : "系统负责"}</small>
                      <p>{module.description}</p>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            {visiblePrompts.length ? (
              <section className="ws-prompt-section">
                <div className="ws-section-head">
                  <p className="ws-card__title">实际 Prompt</p>
                  <span className="ws-toolbar__meta">每段标明引用模块</span>
                </div>
                {visiblePrompts.map((prompt, index) => (
                  <PromptCard
                    key={prompt.key}
                    prompt={prompt}
                    defaultOpen={index < 2}
                    copiedKey={copiedKey}
                    onCopy={copyText}
                  />
                ))}
              </section>
            ) : (
              <div className="ws-empty">
                <p className="ws-empty__title">{loading ? "提示词加载中" : "没有匹配的模块或提示词"}</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
