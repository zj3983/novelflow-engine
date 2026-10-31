"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ChapterIndexEntry, RollingOutlineChapter } from "../../lib/api";
import { saveSceneOutline } from "../../lib/project-outline-api";
import { userFacingErrorMessage } from "../../lib/user-facing-error";

export function SceneOutlineEditor({ chapter, written, projectId, onSaved }: {
  chapter: RollingOutlineChapter; written?: ChapterIndexEntry; projectId: string;
  onSaved: (chapter: RollingOutlineChapter) => void;
}) {
  const [draft, setDraft] = useState(chapter);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => { if (!editing) setDraft(chapter); }, [chapter, editing]);
  function patch(values: Partial<RollingOutlineChapter>) { setDraft({ ...draft, ...values }); setMessage(""); }
  async function save() {
    setBusy(true); setError("");
    try {
      const saved = await saveSceneOutline(projectId, { ...draft, cast: draft.cast.map(c => ({ ...c, name: c.name.trim() })).filter(c => c.name), foreshadowing: draft.foreshadowing.map(t => t.trim()).filter(Boolean) });
      setDraft(saved); onSaved(saved); setEditing(false);
      setMessage("场景细纲已保存，写作将读取这一版；已有正文需另行修订。");
    } catch (caught) { setError(userFacingErrorMessage(caught)); }
    finally { setBusy(false); }
  }
  return <article className="ws-outline-item" aria-label={`第${chapter.chapter_number}章场景细纲`}>
    <div className="ws-outline-item__head">
      <strong>第 {chapter.chapter_number} 章 · {chapter.title}</strong>
      <button type="button" className="ws-btn ws-btn--sm" disabled={busy} onClick={() => { setEditing(!editing); setDraft(chapter); setError(""); }}>
        {editing ? "取消编辑" : "编辑场景细纲"}
      </button>
    </div>
    {written ? <div className="ws-card__hint" role="note">
      <p>已有正文《{written.chapter_title}》；{written.chapter_title !== chapter.title ? "与当前规划标题不同，需核对内容。" : "标题相同不代表正文已按这版细纲修订，请核对场景。"}</p>
      <details><summary>对照现有正文摘要</summary><p>{written.summary || "暂无摘要，请阅读正文核对。"}</p></details>
      <Link href={`/projects/${encodeURIComponent(projectId)}/write?chapter=${chapter.chapter_number}`}>查看或修订第{chapter.chapter_number}章正文</Link>
    </div> : <p className="ws-card__hint">待写正文{chapter.source === "manual" ? " · 已人工编辑" : ""}</p>}
    {editing ? <fieldset disabled={busy} style={{ border: 0, padding: 0, minWidth: 0 }}>
      <div className="ws-outline-grid">
        {([["title", "暂定标题"], ["chapter_goal", "本章目标"], ["core_conflict", "核心冲突"], ["gain", "获得"], ["cost", "代价"], ["hook", "章末落点"], ["state_delta", "状态变化"]] as const).map(([field, label]) => <label className="ws-outline-field" key={field}><span>{label}</span><textarea className="ws-input" rows={3} value={draft[field]} onChange={e => patch({ [field]: e.target.value })} /></label>)}
        <label className="ws-outline-field"><span>出场人物（每行一人）</span><textarea className="ws-input" rows={3} value={draft.cast.map(c => c.name).join("\n")} onChange={e => patch({ cast: e.target.value.split("\n").map(name => ({ ...draft.cast.find(c => c.name === name), name })) })} /></label>
        <label className="ws-outline-field"><span>伏笔（每行一条）</span><textarea className="ws-input" rows={3} value={draft.foreshadowing.join("\n")} onChange={e => patch({ foreshadowing: e.target.value.split("\n") })} /></label>
      </div>
      <h3>逐场景推进</h3>
      {draft.scenes.map((scene, index) => <div className="ws-outline-grid" key={index}>
        <strong>场景 {index + 1}</strong>
        {([["location", "地点"], ["action", "动作"], ["result", "结果"]] as const).map(([field, label]) => <label className="ws-outline-field" key={field}><span>场景{index + 1}{label}</span><textarea className="ws-input" rows={3} value={scene[field]} onChange={e => patch({ scenes: draft.scenes.map((s, i) => i === index ? { ...s, [field]: e.target.value } : s) })} /></label>)}
        <button className="ws-btn ws-btn--sm" type="button" disabled={draft.scenes.length <= 2} onClick={() => patch({ scenes: draft.scenes.filter((_, i) => i !== index) })}>删除场景{index + 1}</button>
      </div>)}
      <div className="ws-toolbar">
        <button className="ws-btn" type="button" disabled={draft.scenes.length >= 4} onClick={() => patch({ scenes: [...draft.scenes, { location: "", action: "", result: "" }] })}>增加场景</button>
        <button className="ws-btn ws-btn--primary" type="button" onClick={() => void save()}>{busy ? "保存中…" : "保存本章细纲"}</button>
      </div>
      <p className="ws-card__hint">保留2—4个完整场景。此处单独保存，已有正文会保留。</p>
    </fieldset> : <div className="ws-outline-grid">
      <div className="ws-outline-field"><span>本章目标</span><p>{chapter.chapter_goal}</p></div>
      <div className="ws-outline-field"><span>核心冲突</span><p>{chapter.core_conflict}</p></div>
      <div className="ws-outline-field"><span>出场人物</span><p>{chapter.cast.map(c => c.name).join("、")}</p></div>
      <div className="ws-outline-field"><span>本章得失</span><p>获得：{chapter.gain}<br />代价：{chapter.cost}</p></div>
      <div className="ws-outline-field ws-outline-field--wide"><span>场景推进</span><ol>{chapter.scenes.map((scene, i) => <li key={i}>{scene.location}：{scene.action}，结果是{scene.result}。</li>)}</ol></div>
      <div className="ws-outline-field"><span>伏笔</span><p>{chapter.foreshadowing.join("；") || "无"}</p></div>
      <div className="ws-outline-field"><span>章末落点</span><p>{chapter.hook || "无下一章钩子"}</p></div>
      <div className="ws-outline-field ws-outline-field--wide"><span>状态变化</span><p>{chapter.state_delta}</p></div>
    </div>}
    {error ? <p role="alert" className="ws-outline-error">{error}</p> : null}
    {message ? <p role="status" className="ws-outline-message">{message}</p> : null}
  </article>;
}
