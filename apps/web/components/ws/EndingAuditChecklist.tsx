"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchEndingAudit, saveEndingAuditItem, type EndingAudit, type EndingAuditItem } from "../../lib/project-outline-api";
import { userFacingErrorMessage } from "../../lib/user-facing-error";

const LABELS = { pending: "待核对", resolved: "已兑现", retained: "明确保留", expired: "作废" };
const KINDS = { mainline: "主线", foreshadowing: "伏笔", chapter: "章纲与正文" };

export function EndingAuditChecklist({ projectId, refreshKey }: { projectId: string; refreshKey: number }) {
  const [audit, setAudit] = useState<EndingAudit | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<EndingAuditItem | null>(null);
  const [filter, setFilter] = useState("pending");
  const [page, setPage] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setAudit(null); setError(""); setEditing(null);
    fetchEndingAudit(projectId).then(value => { if (!cancelled) setAudit(value); }).catch(caught => { if (!cancelled) setError(userFacingErrorMessage(caught)); });
    return () => { cancelled = true; };
  }, [projectId, refreshKey]);
  async function reload() { setBusy(true); setError(""); try { setAudit(await fetchEndingAudit(projectId)); setEditing(null); setPage(0); } catch (caught) { setError(userFacingErrorMessage(caught)); } finally { setBusy(false); } }
  async function save() {
    if (!editing || !audit) return;
    setBusy(true); setError(""); setMessage("");
    try { setAudit(await saveEndingAuditItem(projectId, editing, audit.version)); setEditing(null); setPage(0); setMessage("核对结论已保存。规划或正文变化后，对应项目需要重新核对。"); }
    catch (caught) { setError(userFacingErrorMessage(caught)); }
    finally { setBusy(false); }
  }
  const rows = (audit?.items ?? []).filter(item => filter === "all" || item.disposition === "pending");
  const lastPage = Math.max(0, Math.ceil(rows.length / 20) - 1);
  const visible = rows.slice(Math.min(page, lastPage) * 20, (Math.min(page, lastPage) + 1) * 20);
  return <section className="ws-card" aria-label="完结核对清单">
    <h2>完结核对清单</h2>
    <p className="ws-card__hint">主线、伏笔及章纲与正文逐项核对，记录兑现章节或保留、作废理由。此清单保存复核结论，正文和伏笔账本仍保持原样。</p>
    {audit ? <p>{audit.items.length}项 · {audit.pending_count}项待核对 · {audit.items.length - audit.pending_count}项已记录结论</p> : !error ? <p role="status">正在读取核对清单…</p> : null}
    {error ? <p className="ws-outline-error" role="alert">{error}</p> : null}
    {message ? <p className="ws-outline-message" role="status">{message}</p> : null}
    <details><summary>展开主线与伏笔核对</summary>
      <div className="ws-toolbar"><label>显示 <select className="ws-input" value={filter} onChange={e => { setFilter(e.target.value); setPage(0); }}><option value="pending">待核对</option><option value="all">全部</option></select></label><button className="ws-btn ws-btn--sm" type="button" disabled={busy} onClick={() => void reload()}>刷新核对清单</button></div>
      {visible.map(item => <article className="ws-outline-item" key={item.id}>
        <div className="ws-outline-item__head"><strong>{KINDS[item.kind]} · {item.title}</strong><span>{LABELS[item.disposition]}</span></div>
        <p className="ws-card__hint">{item.context}</p>
        {item.note ? <p>核对说明：{item.note}</p> : null}
        {item.chapter ? <Link href={`/projects/${encodeURIComponent(projectId)}/write?chapter=${item.chapter}`}>查看第{item.chapter}章依据</Link> : null}
        {editing?.id === item.id ? <fieldset disabled={busy} style={{ border: 0, padding: 0 }}>
          <div className="ws-outline-grid">
            <label className="ws-outline-field"><span>核对结论</span><select className="ws-input" value={editing.disposition} onChange={e => setEditing({ ...editing, disposition: e.target.value as EndingAuditItem["disposition"] })}>{Object.entries(LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label className="ws-outline-field"><span>依据章节</span><input className="ws-input" type="number" min={1} max={audit?.current_chapter} value={editing.chapter ?? ""} onChange={e => setEditing({ ...editing, chapter: e.target.value ? Number(e.target.value) : null })} /></label>
            <label className="ws-outline-field ws-outline-field--wide"><span>兑现情况或保留、作废理由</span><textarea className="ws-input" rows={3} maxLength={2000} value={editing.note} onChange={e => setEditing({ ...editing, note: e.target.value })} /></label>
          </div><p className="ws-card__hint">已兑现须填写依据章节和说明；保留、作废须写明理由。</p>
          <div className="ws-toolbar"><button className="ws-btn ws-btn--primary" type="button" onClick={() => void save()}>{busy ? "保存中…" : "保存核对结论"}</button><button className="ws-btn" type="button" onClick={() => setEditing(null)}>取消</button></div>
        </fieldset> : <button className="ws-btn ws-btn--sm" type="button" disabled={busy} onClick={() => setEditing({ ...item })}>记录核对结论</button>}
      </article>)}
      {!rows.length && audit ? <p className="ws-card__hint">{audit.items.length ? "当前筛选下没有待核对项。请复核已记录的章节依据与说明。" : "暂无核对项。"}</p> : null}
      <div className="ws-toolbar"><button className="ws-btn" type="button" disabled={page === 0} onClick={() => { setPage(page - 1); setEditing(null); }}>上一页</button><span>{Math.min(page, lastPage) + 1} / {lastPage + 1}</span><button className="ws-btn" type="button" disabled={page >= lastPage} onClick={() => { setPage(page + 1); setEditing(null); }}>下一页</button></div>
    </details>
  </section>;
}
