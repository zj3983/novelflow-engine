"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { updateProject, type ImportedWorldBlueprint } from "../../../../lib/api";
import { cleanLines } from "../../../../lib/worldDisplay";

type ChapterBeat = {
  chapter?: number;
  title?: string;
  required_payoff?: string;
  ending_hook?: string;
};

function linesFromText(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function asChapterBeats(value: unknown): ChapterBeat[] {
  return Array.isArray(value)
    ? value
        .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
        .map((item) => ({
          chapter: Number(item.chapter || 0) || undefined,
          title: typeof item.title === "string" ? item.title : "",
          required_payoff: typeof item.required_payoff === "string" ? item.required_payoff : "",
          ending_hook: typeof item.ending_hook === "string" ? item.ending_hook : "",
        }))
    : [];
}

export default function OutlinePage() {
  const { project, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const blueprint = project?.world_blueprint ?? {};
  const openingArc = blueprint.opening_arc ?? {};
  const chapterBeats = useMemo(() => asChapterBeats((openingArc as { chapter_beats?: unknown }).chapter_beats), [openingArc]);
  const forbiddenBreaks = cleanLines(blueprint.forbidden_breaks, 12);
  const progressionRules = cleanLines(blueprint.progression_rules, 12);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [draftArc, setDraftArc] = useState("");
  const [draftFocus, setDraftFocus] = useState("");
  const [draftForbidden, setDraftForbidden] = useState("");
  const [draftBeats, setDraftBeats] = useState<ChapterBeat[]>([]);

  useEffect(() => {
    setDraftArc(String(blueprint.current_arc ?? ""));
    setDraftFocus(project?.current_focus ?? "");
    setDraftForbidden((blueprint.forbidden_breaks ?? []).join("\n"));
    setDraftBeats(chapterBeats);
  }, [blueprint.current_arc, blueprint.forbidden_breaks, chapterBeats, project?.current_focus]);

  function updateDraftBeat(index: number, patch: Partial<ChapterBeat>) {
    setDraftBeats((current) => current.map((beat, beatIndex) => (beatIndex === index ? { ...beat, ...patch } : beat)));
  }

  function addDraftBeat() {
    const nextChapter = Math.max(0, ...draftBeats.map((beat) => Number(beat.chapter || 0))) + 1;
    setDraftBeats((current) => [...current, { chapter: nextChapter, title: "", required_payoff: "", ending_hook: "" }]);
  }

  function removeDraftBeat(index: number) {
    setDraftBeats((current) => current.filter((_, beatIndex) => beatIndex !== index));
  }

  async function saveOutline() {
    if (!project) return;
    setSaving(true);
    setMessage("");
    try {
      const nextBlueprint: ImportedWorldBlueprint = {
        ...blueprint,
        current_arc: draftArc.trim(),
        forbidden_breaks: linesFromText(draftForbidden),
        opening_arc: {
          ...(openingArc as Record<string, unknown>),
          chapter_beats: draftBeats
            .filter((beat) => beat.chapter || beat.title || beat.required_payoff || beat.ending_hook)
            .map((beat) => ({
              chapter: Number(beat.chapter || 0),
              title: beat.title?.trim() ?? "",
              required_payoff: beat.required_payoff?.trim() ?? "",
              ending_hook: beat.ending_hook?.trim() ?? "",
            })),
        } as ImportedWorldBlueprint["opening_arc"],
      };
      await updateProject(projectId, {
        current_focus: draftFocus.trim(),
        seed_outline: draftArc.trim() || project.seed_outline,
        world_blueprint: nextBlueprint,
      });
      setEditing(false);
      setMessage("大纲已保存，下一次推演和写作包会读取这版大纲。");
      refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
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
        subtitle="维护当前主线、下一章目标和章节节拍。"
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : null}

      <section className="ws-card">
        <div className="ws-section-head">
          <div>
            <p className="ws-card__title">主线大纲</p>
            <p className="ws-card__hint">保存后会写回文件项目，下一次剧情推演和写作包会读取这里。</p>
          </div>
          <div className="ws-toolbar">
            {editing ? (
              <>
                <button className="ws-btn ws-btn--sm" type="button" onClick={() => setEditing(false)} disabled={saving}>
                  取消
                </button>
                <button className="ws-btn ws-btn--sm ws-btn--primary" type="button" onClick={() => void saveOutline()} disabled={saving}>
                  {saving ? "保存中..." : "保存大纲"}
                </button>
              </>
            ) : (
              <button className="ws-btn ws-btn--sm" type="button" onClick={() => setEditing(true)}>
                编辑大纲
              </button>
            )}
          </div>
        </div>
        {message ? <p className="ws-card__hint">{message}</p> : null}

        {editing ? (
          <div className="ws-character-section-grid">
            <label className="ws-character-mini">
              <strong>当前主线</strong>
              <textarea className="ws-input" value={draftArc} onChange={(event) => setDraftArc(event.target.value)} rows={4} />
            </label>
            <label className="ws-character-mini">
              <strong>下一章目标</strong>
              <textarea className="ws-input" value={draftFocus} onChange={(event) => setDraftFocus(event.target.value)} rows={4} />
            </label>
            <label className="ws-character-mini">
              <strong>禁写项</strong>
              <textarea className="ws-input" value={draftForbidden} onChange={(event) => setDraftForbidden(event.target.value)} rows={5} />
            </label>
            <section className="ws-character-mini">
              <strong>章节节拍</strong>
              <div className="ws-rule-list">
                {draftBeats.map((beat, index) => (
                  <article className="ws-rule-item" key={`${beat.chapter}-${index}`}>
                    <div className="ws-panel-grid">
                      <label>
                        <dt>章</dt>
                        <input
                          className="ws-input"
                          type="number"
                          value={beat.chapter ?? ""}
                          onChange={(event) => updateDraftBeat(index, { chapter: Number(event.target.value || 0) })}
                        />
                      </label>
                      <label>
                        <dt>标题</dt>
                        <input className="ws-input" value={beat.title ?? ""} onChange={(event) => updateDraftBeat(index, { title: event.target.value })} />
                      </label>
                    </div>
                    <label>
                      <dt>必须兑现</dt>
                      <input
                        className="ws-input"
                        value={beat.required_payoff ?? ""}
                        onChange={(event) => updateDraftBeat(index, { required_payoff: event.target.value })}
                      />
                    </label>
                    <label>
                      <dt>章末钩子</dt>
                      <input className="ws-input" value={beat.ending_hook ?? ""} onChange={(event) => updateDraftBeat(index, { ending_hook: event.target.value })} />
                    </label>
                    <button className="ws-btn ws-btn--sm" type="button" onClick={() => removeDraftBeat(index)}>
                      删除
                    </button>
                  </article>
                ))}
              </div>
              <button className="ws-btn ws-btn--sm" type="button" onClick={addDraftBeat}>
                新增章节节拍
              </button>
            </section>
          </div>
        ) : (
          <>
            <div className="ws-character-section-grid">
              <section className="ws-character-mini">
                <strong>当前主线</strong>
                <p>{blueprint.current_arc || "暂无当前主线。"}</p>
              </section>
              <section className="ws-character-mini">
                <strong>下一章目标</strong>
                <p>{project?.current_focus || "暂无下一章目标。"}</p>
              </section>
            </div>
            {chapterBeats.length > 0 ? (
              <div className="ws-rule-list">
                {chapterBeats.map((beat, index) => (
                  <article className="ws-rule-item" key={`${beat.chapter}-${index}`}>
                    <div>
                      <strong>
                        第 {beat.chapter ?? "?"} 章 {beat.title || ""}
                      </strong>
                      <span>{beat.required_payoff || "暂无必须兑现"}</span>
                    </div>
                    <p>{beat.ending_hook || "暂无章末钩子。"}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p className="ws-card__hint">暂无章节节拍。</p>
            )}
            {progressionRules.length ? (
              <div className="ws-character-block">
                <strong>推进规则</strong>
                <ul>
                  {progressionRules.map((rule, index) => (
                    <li key={`${rule}-${index}`}>{rule}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {forbiddenBreaks.length ? (
              <div className="ws-character-block">
                <strong>禁写项</strong>
                <ul>
                  {forbiddenBreaks.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
