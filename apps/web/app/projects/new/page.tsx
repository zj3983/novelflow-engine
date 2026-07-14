"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";

import { PageHeader } from "../../../components/ws/PageHeader";
import { createFileProject } from "../../../lib/api";
import { DEFAULT_NOVEL_TYPE_ID, NOVEL_TYPE_OPTIONS } from "../../../lib/novelTypes";

type CreationMode = "inspiration" | "blank";

export default function NewProjectPage() {
  const router = useRouter();
  const [mode, setMode] = useState<CreationMode>("inspiration");
  const [title, setTitle] = useState("");
  const [novelTypeId, setNovelTypeId] = useState(DEFAULT_NOVEL_TYPE_ID);
  const [idea, setIdea] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const canSubmit = useMemo(() => {
    if (!novelTypeId) return false;
    return mode === "blank" ? Boolean(title.trim()) : Boolean(idea.trim());
  }, [idea, mode, novelTypeId, title]);

  function selectMode(nextMode: CreationMode) {
    setMode(nextMode);
    setError("");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || submitting) return;

    setSubmitting(true);
    setError("");
    try {
      const response = await createFileProject({
        mode,
        title: title.trim(),
        novel_type_id: novelTypeId,
        idea: mode === "inspiration" ? idea.trim() : "",
      });
      router.push(response.next_path);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(`创建失败：${message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="ws-page ws-page--narrow">
      <PageHeader
        crumbs={[{ label: "作品", href: "/projects" }, { label: "新建小说" }]}
        title="新建小说"
        subtitle="选择一个起点，建立新的写作项目。"
      />

      <section className="ws-project-create" aria-label="新建小说表单">
        <div className="ws-project-create__tabs" role="tablist" aria-label="创建方式">
          <button
            id="creation-mode-inspiration"
            type="button"
            role="tab"
            aria-selected={mode === "inspiration"}
            aria-controls="creation-form"
            className={`ws-project-create__tab${mode === "inspiration" ? " is-active" : ""}`}
            onClick={() => selectMode("inspiration")}
          >
            从灵感开书
          </button>
          <button
            id="creation-mode-blank"
            type="button"
            role="tab"
            aria-selected={mode === "blank"}
            aria-controls="creation-form"
            className={`ws-project-create__tab${mode === "blank" ? " is-active" : ""}`}
            onClick={() => selectMode("blank")}
          >
            建立空白小说
          </button>
        </div>

        <form
          id="creation-form"
          className="ws-project-create__form"
          role="tabpanel"
          aria-labelledby={`creation-mode-${mode}`}
          onSubmit={handleSubmit}
        >
          <label className="ws-project-create__field">
            <span>小说类型</span>
            <select value={novelTypeId} onChange={(event) => setNovelTypeId(event.target.value)} required>
              {NOVEL_TYPE_OPTIONS.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="ws-project-create__field">
            <span>
              小说名 <small>{mode === "blank" ? "必填" : "选填"}</small>
            </span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={120}
              required={mode === "blank"}
              autoComplete="off"
            />
          </label>

          {mode === "inspiration" ? (
            <label className="ws-project-create__field ws-project-create__field--wide">
              <span>
                灵感 <small>必填</small>
              </span>
              <textarea
                value={idea}
                onChange={(event) => setIdea(event.target.value)}
                maxLength={1000}
                required
                rows={6}
              />
              <small className="ws-project-create__count">{idea.length} / 1000</small>
            </label>
          ) : null}

          {error ? (
            <p className="ws-project-create__error" role="alert">
              {error}
            </p>
          ) : null}

          <div className="ws-project-create__actions">
            <button className="ws-btn ws-btn--primary" type="submit" disabled={!canSubmit || submitting}>
              {submitting ? "创建中..." : "创建小说"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
