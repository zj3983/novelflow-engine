"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  fetchProjectOutline,
  generateProjectOutline,
  updateProjectOutline,
  type OutlineGenerationMode,
  type ProjectChapterOutline,
  type ProjectOutline,
  type ProjectOutlineArc,
} from "../../../../lib/api";

type OutlineTab = "overall" | "arcs" | "chapters";

const TABS: Array<{ id: OutlineTab; label: string }> = [
  { id: "overall", label: "总纲" },
  { id: "arcs", label: "阶段大纲" },
  { id: "chapters", label: "章节大纲" },
];

function newArcId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `arc-${Date.now()}`;
}

function newArc(index: number): ProjectOutlineArc {
  const startChapter = index === 0 ? 1 : index * 10 + 1;
  return {
    id: newArcId(),
    title: "",
    start_chapter: startChapter,
    end_chapter: startChapter + 9,
    goal: "",
    obstacle: "",
    payoff: "",
    end_state: "",
    stage_antagonist: "",
    long_term_antagonist_traces: [],
  };
}

function newChapter(chapterNumber: number): ProjectChapterOutline {
  return {
    chapter_number: chapterNumber,
    title: "",
    goal: "",
    obstacle: "",
    action: "",
    turn: "",
    payoff: "",
    ending_hook: "",
    cast: [],
  };
}

function rangesOverlap(left: ProjectOutlineArc, right: ProjectOutlineArc): boolean {
  return left.start_chapter <= right.end_chapter && right.start_chapter <= left.end_chapter;
}

export default function OutlinePage() {
  const { project, story, error: projectError, encodedProjectId, projectId } = useProjectWorkspace();
  const [activeTab, setActiveTab] = useState<OutlineTab>("overall");
  const [draft, setDraft] = useState<ProjectOutline | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState<OutlineGenerationMode | null>(null);
  const [guidance, setGuidance] = useState("");
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError("");
    fetchProjectOutline(projectId)
      .then((outline) => {
        if (!cancelled) setDraft(outline);
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
  }, [projectId]);

  const warnings = useMemo(() => {
    if (!draft) return [];
    const items: string[] = [];
    if (!draft.overall.story.trim()) {
      items.push("请先填写总纲中的核心故事。");
    }
    const hasOverlap = draft.arcs.some((arc, index) => draft.arcs.slice(index + 1).some((other) => rangesOverlap(arc, other)));
    if (hasOverlap) {
      items.push("阶段章节范围有重叠；生成时会采用起始章节最接近当前章的阶段。");
    }
    const lastPlannedChapter = Math.max(0, ...draft.chapters.map((chapter) => chapter.chapter_number));
    const remainingChapters = lastPlannedChapter - (story?.current_chapter ?? 0);
    if (remainingChapters > 0 && remainingChapters <= 2) {
      items.push(`章节计划仅剩 ${remainingChapters} 章，请先补充后续章节。`);
    }
    return items;
  }, [draft, story?.current_chapter]);

  function updateArc(index: number, patch: Partial<ProjectOutlineArc>) {
    setDraft((current) =>
      current
        ? { ...current, arcs: current.arcs.map((arc, arcIndex) => (arcIndex === index ? { ...arc, ...patch } : arc)) }
        : current,
    );
  }

  function updateChapter(index: number, patch: Partial<ProjectChapterOutline>) {
    setDraft((current) =>
      current
        ? {
            ...current,
            chapters: current.chapters.map((chapter, chapterIndex) =>
              chapterIndex === index ? { ...chapter, ...patch } : chapter,
            ),
          }
        : current,
    );
  }

  function addArc() {
    setDraft((current) => (current ? { ...current, arcs: [...current.arcs, newArc(current.arcs.length)] } : current));
  }

  function addChapter() {
    setDraft((current) => {
      if (!current) return current;
      const chapterNumber = Math.max(0, ...current.chapters.map((chapter) => chapter.chapter_number)) + 1;
      return { ...current, chapters: [...current.chapters, newChapter(chapterNumber)] };
    });
  }

  async function saveOutline() {
    if (!draft) return;
    setSaving(true);
    setMessage("");
    try {
      const { source: _source, ...payload } = draft;
      const saved = await updateProjectOutline(projectId, payload);
      setDraft(saved);
      setMessage("大纲已保存，下一次剧情规划会读取这版内容。");
    } catch (err) {
      setMessage(`保存失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }

  async function runGeneration(mode: OutlineGenerationMode) {
    if (!draft) return;
    setGenerating(mode);
    setMessage("");
    try {
      const generated = await generateProjectOutline(projectId, mode, guidance.trim());
      setDraft({ ...generated.outline, source: "saved" });
      setGuidance("");
      setMessage(mode === "extend" ? "后续五章已补充。" : mode === "regenerate" ? "大纲和开篇角色已重新生成。" : "大纲和开篇角色已生成。");
    } catch (err) {
      setMessage(`生成失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setGenerating(null);
    }
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="大纲"
        subtitle="总纲管全书方向，阶段大纲管一段剧情，章节大纲只管当前一章。"
      />

      {projectError || loadError ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{projectError || loadError}</p>
        </div>
      ) : null}

      <section className="ws-outline-workspace" aria-label="三级大纲编辑器">
        <div className="ws-section-head">
          <div>
            <p className="ws-card__title">故事规划</p>
            <p className="ws-card__hint">
              {draft?.source === "legacy" ? "当前是旧大纲预览，保存后转为新版结构。" : "保存后，生成时只提取当前章节需要的大纲。"}
            </p>
          </div>
          <button className="ws-btn ws-btn--primary" type="button" onClick={() => void saveOutline()} disabled={saving || generating !== null || !draft}>
            {saving ? "保存中..." : "保存大纲"}
          </button>
        </div>

        {draft ? (
          <div className="ws-outline-generation">
            <label className="ws-outline-field ws-outline-field--wide">
              <span>本次生成补充要求</span>
              <textarea
                className="ws-input"
                rows={3}
                maxLength={1000}
                placeholder="只在这次生成中使用，不会写入长期设定。"
                value={guidance}
                onChange={(event) => setGuidance(event.target.value)}
              />
            </label>
            <div className="ws-outline-generation__actions">
              {draft.arcs.length === 0 && draft.chapters.length === 0 ? (
                <button className="ws-btn" type="button" disabled={generating !== null || saving} onClick={() => void runGeneration("initial")}>
                  {generating === "initial" ? "生成中..." : "生成大纲"}
                </button>
              ) : (
                <>
                  <button className="ws-btn" type="button" disabled={generating !== null || saving} onClick={() => void runGeneration("regenerate")}>
                    {generating === "regenerate" ? "生成中..." : "重新生成"}
                  </button>
                  <button className="ws-btn" type="button" disabled={generating !== null || saving} onClick={() => void runGeneration("extend")}>
                    {generating === "extend" ? "生成中..." : "补充后续章节"}
                  </button>
                </>
              )}
            </div>
          </div>
        ) : null}

        <div className="ws-outline-tabs" role="tablist" aria-label="大纲层级">
          {TABS.map((tab) => (
            <button
              className={`ws-outline-tab${activeTab === tab.id ? " is-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {message ? <p className="ws-outline-message">{message}</p> : null}
        {warnings.map((warning) => (
          <p className="ws-outline-warning" key={warning}>
            {warning}
          </p>
        ))}

        {loading ? <p className="ws-card__hint">正在读取大纲...</p> : null}

        {draft && activeTab === "overall" ? (
          <div className="ws-outline-grid" role="tabpanel">
            <label className="ws-outline-field ws-outline-field--wide">
              <span>核心故事</span>
              <textarea
                className="ws-input"
                rows={5}
                value={draft.overall.story}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, story: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>主角长期目标</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.protagonist_goal}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, protagonist_goal: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>主线冲突</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.main_conflict}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, main_conflict: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>成长路线</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.growth_path}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, growth_path: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>结局方向</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.ending_direction}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, ending_direction: event.target.value } })}
              />
            </label>
          </div>
        ) : null}

        {draft && activeTab === "arcs" ? (
          <div role="tabpanel">
            <div className="ws-outline-list">
              {draft.arcs.map((arc, index) => (
                <article className="ws-outline-item" key={arc.id}>
                  <div className="ws-outline-item__head">
                    <strong>阶段 {index + 1}</strong>
                    <button
                      className="ws-btn ws-btn--sm"
                      type="button"
                      onClick={() => setDraft({ ...draft, arcs: draft.arcs.filter((_, arcIndex) => arcIndex !== index) })}
                    >
                      删除
                    </button>
                  </div>
                  <div className="ws-outline-grid">
                    <label className="ws-outline-field">
                      <span>阶段名称</span>
                      <input className="ws-input" value={arc.title} onChange={(event) => updateArc(index, { title: event.target.value })} />
                    </label>
                    <label className="ws-outline-field">
                      <span>阶段对手</span>
                      <input className="ws-input" value={arc.stage_antagonist} onChange={(event) => updateArc(index, { stage_antagonist: event.target.value })} />
                    </label>
                    <div className="ws-outline-range">
                      <label className="ws-outline-field">
                        <span>起始章</span>
                        <input
                          className="ws-input"
                          type="number"
                          min={1}
                          value={arc.start_chapter}
                          onChange={(event) => updateArc(index, { start_chapter: Number(event.target.value) })}
                        />
                      </label>
                      <label className="ws-outline-field">
                        <span>结束章</span>
                        <input
                          className="ws-input"
                          type="number"
                          min={1}
                          value={arc.end_chapter}
                          onChange={(event) => updateArc(index, { end_chapter: Number(event.target.value) })}
                        />
                      </label>
                    </div>
                    {([
                      ["goal", "阶段目标"],
                      ["obstacle", "主要阻碍"],
                      ["payoff", "关键兑现"],
                      ["end_state", "结束状态"],
                    ] as const).map(([field, label]) => (
                      <label className="ws-outline-field" key={field}>
                        <span>{label}</span>
                        <textarea className="ws-input" rows={3} value={arc[field]} onChange={(event) => updateArc(index, { [field]: event.target.value })} />
                      </label>
                    ))}
                    <label className="ws-outline-field ws-outline-field--wide">
                      <span>长期对手留下的痕迹</span>
                      <textarea
                        className="ws-input"
                        rows={3}
                        value={arc.long_term_antagonist_traces.join("\n")}
                        onChange={(event) => updateArc(index, { long_term_antagonist_traces: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })}
                      />
                    </label>
                  </div>
                </article>
              ))}
            </div>
            <button className="ws-btn" type="button" onClick={addArc}>
              新增阶段
            </button>
          </div>
        ) : null}

        {draft && activeTab === "chapters" ? (
          <div role="tabpanel">
            <div className="ws-outline-list">
              {draft.chapters.map((chapter, index) => (
                <article className="ws-outline-item" key={`${chapter.chapter_number}-${index}`}>
                  <div className="ws-outline-item__head">
                    <strong>第 {chapter.chapter_number} 章</strong>
                    <button
                      className="ws-btn ws-btn--sm"
                      type="button"
                      onClick={() => setDraft({ ...draft, chapters: draft.chapters.filter((_, chapterIndex) => chapterIndex !== index) })}
                    >
                      删除
                    </button>
                  </div>
                  <div className="ws-outline-grid">
                    <label className="ws-outline-field">
                      <span>章节号</span>
                      <input
                        className="ws-input"
                        type="number"
                        min={1}
                        value={chapter.chapter_number}
                        onChange={(event) => updateChapter(index, { chapter_number: Number(event.target.value) })}
                      />
                    </label>
                    <label className="ws-outline-field">
                      <span>暂定标题</span>
                      <input className="ws-input" value={chapter.title} onChange={(event) => updateChapter(index, { title: event.target.value })} />
                    </label>
                    <label className="ws-outline-field">
                      <span>出场人物</span>
                      <textarea
                        className="ws-input"
                        rows={3}
                        value={chapter.cast.join("\n")}
                        onChange={(event) => updateChapter(index, { cast: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })}
                      />
                    </label>
                    {([
                      ["goal", "本章目标"],
                      ["obstacle", "主要阻碍"],
                      ["action", "主角行动"],
                      ["turn", "关键转折"],
                      ["payoff", "本章兑现"],
                      ["ending_hook", "章末钩子"],
                    ] as const).map(([field, label]) => (
                      <label className="ws-outline-field" key={field}>
                        <span>{label}</span>
                        <textarea
                          className="ws-input"
                          rows={3}
                          value={chapter[field]}
                          onChange={(event) => updateChapter(index, { [field]: event.target.value })}
                        />
                      </label>
                    ))}
                  </div>
                </article>
              ))}
            </div>
            <button className="ws-btn" type="button" onClick={addChapter}>
              新增章节
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}
