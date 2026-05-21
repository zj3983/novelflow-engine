"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  type BookDissectionReport,
  dissectFileProjectChapter,
  dissectReferenceText,
} from "../../../../lib/api";

type DissectionMode = "reference" | "project";

const SECTION_ORDER = [
  "章节作用",
  "爽点来源",
  "主角进展",
  "冲突推进",
  "对话功能",
  "节奏拆解",
  "结尾钩子",
  "可学习写法",
  "不能照抄",
  "主要问题",
  "不爽原因",
  "设定冲突",
  "对话问题",
  "说明感问题",
  "下一版改法",
  "可写入提示词",
];

function orderedSectionKeys(report: BookDissectionReport): string[] {
  const known = SECTION_ORDER.filter((key) => report.sections[key]?.length);
  const extra = Object.keys(report.sections).filter((key) => !SECTION_ORDER.includes(key));
  return [...known, ...extra];
}

function ReportPanel({ report }: { report: BookDissectionReport | null }) {
  if (!report) {
    return (
      <div className="ws-empty">
        <p className="ws-empty__title">还没有拆书报告</p>
        <p className="ws-empty__hint">粘贴参考章节，或选择本书章节后开始体检。报告只读，不会自动写入作者约束。</p>
      </div>
    );
  }

  const keys = orderedSectionKeys(report);

  return (
    <div className="ws-stat-row">
      {report.summary ? (
        <section className="ws-card" style={{ gridColumn: "1 / -1" }}>
          <p className="ws-card__title">摘要</p>
          <p className="ws-card__hint">{report.summary}</p>
        </section>
      ) : null}
      {keys.map((key) => (
        <section className="ws-card" key={key} style={{ gridColumn: "1 / -1" }}>
          <p className="ws-card__title">{key}</p>
          <ul className="ws-plain-list">
            {report.sections[key].map((item, index) => (
              <li key={`${key}-${index}`}>{item}</li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

export default function DissectionPage() {
  const { project, story, error, encodedProjectId } = useProjectWorkspace();
  const [mode, setMode] = useState<DissectionMode>("reference");
  const [referenceText, setReferenceText] = useState("");
  const [genre, setGenre] = useState("网游");
  const [focus, setFocus] = useState("爽点和对话");
  const [chapterNumber, setChapterNumber] = useState<number | undefined>();
  const [report, setReport] = useState<BookDissectionReport | null>(null);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const chapters = useMemo(() => story?.history ?? [], [story?.history]);

  useEffect(() => {
    if (chapterNumber !== undefined || chapters.length === 0) return;
    setChapterNumber(story?.current_chapter || chapters.at(-1)?.chapter_number);
  }, [chapterNumber, chapters, story?.current_chapter]);

  async function runDissection() {
    setRunning(true);
    setMessage(null);
    try {
      const nextReport =
        mode === "reference"
          ? await dissectReferenceText({ text: referenceText, genre, focus })
          : await dissectFileProjectChapter(project?.project_id || "", chapterNumber);
      setReport(nextReport);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "拆书失败，请稍后重试。");
    } finally {
      setRunning(false);
    }
  }

  const canRunReference = referenceText.trim().length > 0;
  const canRunProject = Boolean(project?.project_id && chapterNumber);

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="拆书"
        subtitle="拆参考章节的写法，也体检本书章节的问题。报告只读，不会自动写入作者约束。"
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : (
        <div className="ws-editor-layout">
          <section className="ws-card">
            <div className="ws-section-head">
              <div>
                <p className="ws-card__title">分析模式</p>
                <p className="ws-card__hint">结果用于阅读和判断，不会自动改正文，也不会自动写入作者约束。</p>
              </div>
            </div>

            <div className="ws-action-row" role="tablist" aria-label="拆书模式">
              <button
                className={`ws-btn ws-btn--sm${mode === "reference" ? " ws-btn--primary" : ""}`}
                type="button"
                role="tab"
                aria-selected={mode === "reference"}
                onClick={() => setMode("reference")}
              >
                参考书拆解
              </button>
              <button
                className={`ws-btn ws-btn--sm${mode === "project" ? " ws-btn--primary" : ""}`}
                type="button"
                role="tab"
                aria-selected={mode === "project"}
                onClick={() => setMode("project")}
              >
                本书体检
              </button>
            </div>

            {mode === "reference" ? (
              <div className="ws-form-grid">
                <label className="ws-search">
                  <span>题材</span>
                  <input className="ws-input" value={genre} onChange={(event) => setGenre(event.target.value)} />
                </label>
                <label className="ws-search">
                  <span>关注点</span>
                  <input className="ws-input" value={focus} onChange={(event) => setFocus(event.target.value)} />
                </label>
                <label className="ws-search ws-form-grid__wide">
                  <span>参考文本</span>
                  <textarea
                    className="ws-input ws-textarea"
                    rows={16}
                    value={referenceText}
                    onChange={(event) => setReferenceText(event.target.value)}
                    placeholder="粘贴要拆解的参考章节或片段。"
                  />
                </label>
              </div>
            ) : (
              <div className="ws-form-grid">
                <label className="ws-search ws-form-grid__wide">
                  <span>章节</span>
                  <select
                    className="ws-input"
                    value={chapterNumber ?? ""}
                    onChange={(event) => setChapterNumber(Number(event.target.value) || undefined)}
                    disabled={chapters.length === 0}
                  >
                    {chapters.length === 0 ? <option value="">暂无章节</option> : null}
                    {chapters.map((chapter) => (
                      <option key={chapter.chapter_number} value={chapter.chapter_number}>
                        第 {chapter.chapter_number} 章{chapter.chapter_title ? `：${chapter.chapter_title}` : ""}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}

            <div className="ws-action-row">
              <button
                className="ws-btn ws-btn--primary"
                type="button"
                onClick={() => void runDissection()}
                disabled={running || (mode === "reference" ? !canRunReference : !canRunProject)}
              >
                {running ? "分析中..." : "开始分析"}
              </button>
              {message ? <span className="ws-toolbar__meta">{message}</span> : null}
            </div>
          </section>

          <aside className="ws-sidepanel">
            <section className="ws-card">
              <p className="ws-card__title">只读说明</p>
              <p className="ws-card__hint">
                参考书拆解只提炼结构和写法；本书体检只指出问题和可选提示。所有报告都不会自动写入作者约束。
              </p>
            </section>
          </aside>

          <section style={{ gridColumn: "1 / -1" }} aria-live="polite">
            <ReportPanel report={report} />
          </section>
        </div>
      )}
    </div>
  );
}
