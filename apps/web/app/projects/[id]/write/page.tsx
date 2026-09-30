"use client";
import Link from "next/link";
import { Check, Copy } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { getWriteProduct } from "../build/product-api";
import { ProductActions, ProductEditor, ProductIssues } from "../build/ProductControls";
import { useProductScreen } from "../build/useProductScreen";
import { WorkflowNotice } from "../build/WorkflowNotice";
import styles from "./write.module.css";

const PAGE_SIZE = 80;
async function copyText(text: string) {
  try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return; } } catch { /* Use the browser's copy command when available. */ }
  const area = document.createElement("textarea");
  area.value = text; area.style.position = "fixed"; area.style.opacity = "0";
  document.body.appendChild(area); area.select();
  const copied = document.execCommand("copy"); area.remove();
  if (!copied) throw new Error();
}

export default function WritePage() {
  const { projectId, encodedProjectId } = useProjectWorkspace();
  const search = useSearchParams();
  const requested = Number(search?.get("chapter")) || undefined;
  const load = useCallback(() => getWriteProduct(projectId, requested), [projectId, requested]);
  const { view, loading, unavailable, busy, dirty, setDirty, error, message, reload, onAction } = useProductScreen(projectId, load);
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 760px)");
    const update = () => setNarrow(media.matches);
    update(); media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const directory = useRef<HTMLDivElement>(null);
  const filtered = useMemo(() => [...(view?.chapters ?? [])].reverse().filter((item) => `${item.number} ${item.title} ${item.summary}`.toLowerCase().includes(query.trim().toLowerCase())), [view?.chapters, query]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pages);
  const visible = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const currentNumber = view?.candidate?.number ?? view?.chapter?.number;
  useEffect(() => { setPage(1); }, [query]);
  useEffect(() => { setCopied(false); setCopyError(false); }, [view?.chapter?.number]);
  useEffect(() => {
    const container = directory.current;
    const item = container?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!container || !item) return;
    const box = container.getBoundingClientRect();
    const target = item.getBoundingClientRect();
    if (target.top < box.top) container.scrollTop += target.top - box.top;
    else if (target.bottom > box.bottom) container.scrollTop += target.bottom - box.bottom;
  }, [currentNumber, safePage]);
  async function copyChapter() {
    if (!view?.chapter) return;
    try { await copyText(`第 ${view.chapter.number} 章 ${view.chapter.title}\n\n${view.chapter.body}`); setCopied(true); setCopyError(false); }
    catch { setCopyError(true); }
  }
  return <div className="ws-page">
    <PageHeader crumbs={[{ label: "作品", href: "/projects" }, { label: "当前作品", href: `/projects/${encodedProjectId}` }]} title={view?.title ?? "章节创作"} subtitle={view?.subtitle ?? "生成候选，审查后人工确认，再继续写作。"} />
    {loading ? <p role="status">正在读取章节…</p> : null}
    {error ? <section className="ws-card" role="alert"><p>{error.message}</p>{error.impact ? <p>{error.impact}</p> : null}<button className="ws-btn" onClick={() => void reload()}>重新读取</button></section> : null}
    {message ? <p role="status">{message}</p> : null}
    {view ? <>
      <WorkflowNotice status={view.status} title="正文写作路径">
        <ol className={styles.steps} aria-label="写作步骤">{view.steps.map((step, index) => <li key={index} aria-current={step.current ? "step" : undefined}>{step.label}</li>)}</ol>
        <ProductActions actions={view.actions} busy={busy || loading || unavailable || dirty} onAction={onAction} />
      </WorkflowNotice>
      {view.notices?.map((notice, index) => <p key={index} className="ws-card__hint">{notice}</p>)}
      {view.forms?.map((form) => <ProductEditor key={form.title} form={form} busy={busy || loading || unavailable} onAction={onAction} onDirty={(value) => setDirty(value, form.title)} />)}
      {dirty ? <p role="status">正在编辑，请先保存或取消，再继续操作。</p> : null}
      <div className="ws-editor-layout ws-editor-layout--chapters">
        <aside className="ws-sidepanel ws-chapter-index" aria-label="章节目录">
          <section className="ws-card"><div className="ws-section-head"><h2 className="ws-card__title">目录</h2><span>{view.chapters.length} 章</span></div>
            <label className="ws-search ws-search--compact"><span>搜索</span><input className="ws-input" placeholder="标题、章节号、摘要" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            <div ref={directory} className={`ws-chapter-list ${styles.directory}`}>{visible.map((item) => <Link key={item.number} className={`ws-chapter-list__item${currentNumber === item.number ? " ws-chapter-list__item--active" : ""}`} href={`/projects/${encodedProjectId}/write?chapter=${item.number}${narrow ? "#chapter-reader" : ""}`} scroll={narrow} aria-current={currentNumber === item.number ? "page" : undefined} onClick={(event) => { if (busy || dirty) event.preventDefault(); }}><strong>第 {item.number} 章 · {item.title}</strong><span>{item.summary}</span></Link>)}</div>
            {pages > 1 ? <div className="ws-toolbar"><button className="ws-btn ws-btn--sm" disabled={safePage <= 1} onClick={() => setPage(safePage - 1)}>上一页</button><span>{safePage} / {pages}</span><button className="ws-btn ws-btn--sm" disabled={safePage >= pages} onClick={() => setPage(safePage + 1)}>下一页</button></div> : null}
          </section>
        </aside>
        <article id="chapter-reader" className="ws-reader">
          {view.candidate ? <section className={`ws-card ${styles.candidate}`} aria-label="候选稿">
            <header><p className="ws-card__title">候选稿，尚未提交</p><h2>第 {view.candidate.number} 章 · {view.candidate.title}</h2></header>
            <WorkflowNotice status={view.candidate.review} title="候选稿审查结果"><ProductIssues issues={view.candidate.issues} /></WorkflowNotice>
            <p className="ws-card__hint">请先阅读正文与审查建议。只有人工确认后，候选才会成为正式章节。</p>
            <ProductActions actions={view.candidate.actions} busy={busy || loading || unavailable || dirty} onAction={onAction} />
            {view.candidate.form ? <ProductEditor key={view.candidate.number} form={view.candidate.form} busy={busy || loading || unavailable} onAction={onAction} onDirty={setDirty} /> : null}
            <article className="ws-reader__body" aria-label="候选稿完整正文">{view.candidate.body.split(/\n{2,}/).map((paragraph, index) => <p key={index}>{paragraph}</p>)}</article>
          </section> : null}
          {view.chapter ? <>
            <header className="ws-reader__head"><div><p className="ws-card__title">正文</p><h2>{view.chapter.title}</h2></div><button className="ws-btn ws-btn--sm" title="复制章节标题和正文" onClick={() => void copyChapter()}>{copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}{copied ? "已复制" : "复制章节"}</button></header>
            {copyError ? <p role="alert">复制失败，请允许浏览器访问剪贴板后重试。</p> : null}
            <div className="ws-reader__body">{view.chapter.body.split(/\n{2,}/).map((paragraph, index) => <p key={index}>{paragraph}</p>)}</div>
            {view.chapter.summary ? <section className="ws-reader__notes"><h3>章节摘要</h3><p>{view.chapter.summary}</p></section> : null}
            {view.chapter.notes?.map((note, index) => <p className="ws-card__hint" key={index}>{note}</p>)}
          </> : null}

        </article>
      </div>
    </> : null}
  </div>;
}
