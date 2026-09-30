"use client";
import { useCallback, useState } from "react";
import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { getBuildProduct } from "./product-api";
import { ProductActions, ProductEditor, ProductIssues } from "./ProductControls";
import { useProductScreen } from "./useProductScreen";
import { WorkflowNotice } from "./WorkflowNotice";
import styles from "./build.module.css";

export default function BuildWorkbenchPage() {
  const { projectId, encodedProjectId } = useProjectWorkspace();
  const [selection, setSelection] = useState<string>();
  const load = useCallback(() => getBuildProduct(projectId, selection), [projectId, selection]);
  const { view, loading, unavailable, busy, dirty, setDirty, error, message, reload, onAction } = useProductScreen(projectId, load);
  return <div className="ws-page">
    <PageHeader crumbs={[{ label: "作品", href: "/projects" }, { label: "当前作品", href: `/projects/${encodedProjectId}` }]} title={view?.title ?? "准备故事"} subtitle={view?.subtitle ?? "整理故事设定，准备开始创作。"} />
    {loading ? <p role="status">正在读取创作进度…</p> : null}
    {error ? <section className="ws-card" role="alert"><p>{error.message}</p>{error.impact ? <p>{error.impact}</p> : null}<button className="ws-btn" onClick={() => void reload()}>重新读取</button></section> : null}
    {message ? <p role="status">{message}</p> : null}
    {view ? <>
      <WorkflowNotice status={view.status} title="当前创作阶段">
        <progress className={styles.progress} aria-label="准备进度" value={view.progress.completed} max={Math.max(1, view.progress.total)} />
        <p>{view.progress.label}</p>
        <ProductActions actions={view.actions} busy={busy || loading || unavailable || dirty} onAction={onAction} />
      </WorkflowNotice>
      {view.notices?.map((notice, index) => <p className="ws-card__hint" key={index}>{notice}</p>)}
      {view.forms?.map((form) => <ProductEditor key={form.title} form={form} busy={busy || loading || unavailable} onAction={onAction} onDirty={(value) => setDirty(value, form.title)} />)}
      {dirty ? <p role="status">正在编辑，请先保存或取消，再切换内容。</p> : null}
      <div className={styles.columns}>
        <section className="ws-card" aria-label="故事准备内容"><h2>故事准备</h2><ol className={styles.parts}>
          {view.parts.map((part) => <li key={part.selection}><button type="button" className={styles.part} disabled={busy || loading || unavailable || dirty} aria-current={view.selected?.selection === part.selection ? "true" : undefined} onClick={() => setSelection(part.selection)}><strong>{part.title}</strong><span>{part.status.label}</span><span>{part.status.message}</span></button></li>)}
        </ol></section>
        {view.selected ? <section className="ws-card" aria-label="当前准备内容">
          <h2>{view.selected.title}</h2>
          {view.selected.description ? <p>{view.selected.description}</p> : null}
          {view.selected.paragraphs.map((paragraph, index) => <p className={styles.content} key={index}>{paragraph}</p>)}
          <ProductIssues issues={view.selected.issues} />
          <ProductActions actions={view.selected.actions} busy={busy || loading || unavailable || dirty} onAction={onAction} />
          {view.selected.form ? <ProductEditor key={view.selected.selection} form={view.selected.form} busy={busy || loading || unavailable} onAction={onAction} onDirty={setDirty} /> : null}
        </section> : null}
      </div>
    </> : null}
  </div>;
}
