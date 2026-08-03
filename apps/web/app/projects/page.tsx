"use client";

import Link from "next/link";
import { Archive, RotateCcw, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../components/ws/PageHeader";
import {
  archiveProject,
  listProjects,
  permanentlyDeleteProject,
  restoreProject,
  trashProject,
  type ProjectLifecycle,
  type ProjectStatus,
  type ProjectSummary,
} from "../../lib/api";

const LAST_PROJECT_STORAGE_KEY = "novel-autogrowth.last-project-id";

const STATUS_META: Record<string, { label: string; badge: string }> = {
  draft: { label: "草稿", badge: "ws-badge" },
  outlining: { label: "大纲中", badge: "ws-badge" },
  writing: { label: "写作中", badge: "ws-badge ws-badge--success" },
  reviewing: { label: "审核中", badge: "ws-badge ws-badge--warn" },
  simulating: { label: "生成中", badge: "ws-badge ws-badge--success" },
  paused: { label: "已暂停", badge: "ws-badge ws-badge--warn" },
  completed: { label: "已完结", badge: "ws-badge" },
};

const VIEWS: Array<{ value: ProjectLifecycle; label: string }> = [
  { value: "active", label: "创作中" },
  { value: "archived", label: "已归档" },
  { value: "trashed", label: "回收站" },
];

const SOURCE_LABEL: Record<NonNullable<ProjectSummary["storage_source"]>, string> = {
  sqlite: "数据库",
  file: "文件项目",
};

type Confirmation = { kind: "trash" | "delete"; project: ProjectSummary } | null;

function projectHref(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}`;
}

function statusMeta(status: ProjectStatus | undefined): { label: string; badge: string } {
  const key = String(status || "draft");
  return STATUS_META[key] ?? { label: key, badge: "ws-badge ws-badge--warn" };
}

export default function ProjectsListPage() {
  const [view, setView] = useState<ProjectLifecycle>("active");
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastProjectId, setLastProjectId] = useState<string | null>(null);
  const [busyProjectId, setBusyProjectId] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [titleConfirmation, setTitleConfirmation] = useState("");

  useEffect(() => {
    try {
      setLastProjectId(window.localStorage.getItem(LAST_PROJECT_STORAGE_KEY));
    } catch {
      setLastProjectId(null);
    }
  }, []);

  const loadProjects = useCallback(async (lifecycle: ProjectLifecycle) => {
    setProjects(null);
    setError(null);
    try {
      setProjects(await listProjects(lifecycle));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setProjects([]);
    }
  }, []);

  useEffect(() => {
    void loadProjects(view);
  }, [loadProjects, view]);

  const lastProject = useMemo(() => {
    if (view !== "active" || !projects || !lastProjectId) return null;
    return projects.find((project) => project.project_id === lastProjectId) ?? null;
  }, [lastProjectId, projects, view]);

  function clearRememberedProject(projectId: string) {
    if (lastProjectId !== projectId) return;
    try {
      window.localStorage.removeItem(LAST_PROJECT_STORAGE_KEY);
    } catch {
      // The list still updates when storage is unavailable.
    }
    setLastProjectId(null);
  }

  async function runAction(project: ProjectSummary, action: "archive" | "restore") {
    setBusyProjectId(project.project_id);
    setError(null);
    try {
      if (action === "archive") {
        await archiveProject(project.project_id);
        clearRememberedProject(project.project_id);
      } else {
        await restoreProject(project.project_id);
      }
      await loadProjects(view);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyProjectId(null);
    }
  }

  async function confirmLifecycleAction() {
    if (!confirmation) return;
    const { kind, project } = confirmation;
    setBusyProjectId(project.project_id);
    setError(null);
    try {
      if (kind === "trash") {
        await trashProject(project.project_id);
        clearRememberedProject(project.project_id);
      } else {
        await permanentlyDeleteProject(project.project_id, project.title);
      }
      setConfirmation(null);
      setTitleConfirmation("");
      await loadProjects(view);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyProjectId(null);
    }
  }

  const emptyLabel = view === "active" ? "还没有正在创作的小说" : view === "archived" ? "还没有归档小说" : "回收站是空的";

  return (
    <div className="ws-page">
      <PageHeader
        title="我的作品"
        subtitle="管理正在创作、已归档和已删除的小说。"
        actions={
          <div className="ws-action-row ws-action-row--flush">
            {lastProject ? <Link href={projectHref(lastProject.project_id)} className="ws-btn">继续上次作品</Link> : null}
            <Link href="/projects/new" className="ws-btn ws-btn--primary">新建小说</Link>
          </div>
        }
      />

      <div className="ws-segmented-control ws-project-lifecycle-tabs" aria-label="作品分类">
        {VIEWS.map((item) => (
          <button key={item.value} type="button" aria-pressed={view === item.value} onClick={() => setView(item.value)}>
            {item.label}
          </button>
        ))}
      </div>

      {error ? <div className="ws-project-list-error" role="alert">{error}</div> : null}

      {projects === null ? (
        <p className="ws-page__subtitle">加载中...</p>
      ) : projects.length === 0 ? (
        <div className="ws-empty">
          <p className="ws-empty__title">{emptyLabel}</p>
          {view === "active" ? <Link href="/projects/new" className="ws-btn">新建小说</Link> : null}
        </div>
      ) : (
        <div className="ws-table-wrap">
          <table className="ws-table">
            <thead><tr><th>小说名</th><th>状态</th><th>当前章节</th><th>来源</th><th aria-label="操作" /></tr></thead>
            <tbody>
              {projects.map((project) => {
                const status = statusMeta(project.status);
                const disabled = busyProjectId === project.project_id;
                return (
                  <tr key={project.project_id}>
                    <td>{view === "trashed" ? <span className="ws-table__strong">{project.title}</span> : <Link href={projectHref(project.project_id)} className="ws-table__strong">{project.title}</Link>}</td>
                    <td><span className={status.badge}>{status.label}</span></td>
                    <td>第 {project.current_chapter} 章</td>
                    <td className="ws-project-source">{project.storage_source ? SOURCE_LABEL[project.storage_source] : "数据库"}</td>
                    <td>
                      <div className="ws-project-row-actions">
                        {view === "active" ? <button type="button" title="归档" aria-label={`归档《${project.title}》`} disabled={disabled} onClick={() => void runAction(project, "archive")}><Archive size={17} /></button> : null}
                        {view !== "trashed" ? <button type="button" title="移入回收站" aria-label={`将《${project.title}》移入回收站`} disabled={disabled} onClick={() => setConfirmation({ kind: "trash", project })}><Trash2 size={17} /></button> : null}
                        {view !== "active" ? <button type="button" title="恢复" aria-label={`恢复《${project.title}》`} disabled={disabled} onClick={() => void runAction(project, "restore")}><RotateCcw size={17} /></button> : null}
                        {view === "trashed" ? <button type="button" className="is-danger" title="彻底删除" aria-label={`彻底删除《${project.title}》`} disabled={disabled} onClick={() => { setTitleConfirmation(""); setConfirmation({ kind: "delete", project }); }}><Trash2 size={17} /></button> : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {confirmation ? (
        <div className="ws-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyProjectId) setConfirmation(null); }}>
          <section className="ws-dialog" role="dialog" aria-modal="true" aria-label={confirmation.kind === "delete" ? "彻底删除小说" : "移入回收站"}>
            <button type="button" className="ws-dialog__close" aria-label="关闭" disabled={Boolean(busyProjectId)} onClick={() => setConfirmation(null)}><X size={18} /></button>
            <h2>{confirmation.kind === "delete" ? "彻底删除小说" : "移入回收站"}</h2>
            {confirmation.kind === "delete" ? (
              <>
                <p>《{confirmation.project.title}》的正文、设定和记录都会被删除，无法恢复。</p>
                <label className="ws-project-delete-confirm"><span>输入完整书名</span><input autoFocus value={titleConfirmation} onChange={(event) => setTitleConfirmation(event.target.value)} /></label>
              </>
            ) : <p>《{confirmation.project.title}》会移入回收站，之后仍然可以恢复。</p>}
            <div className="ws-dialog__actions">
              <button type="button" className="ws-btn" disabled={Boolean(busyProjectId)} onClick={() => setConfirmation(null)}>取消</button>
              <button type="button" className={confirmation.kind === "delete" ? "ws-btn ws-btn--danger" : "ws-btn ws-btn--primary"} disabled={Boolean(busyProjectId) || (confirmation.kind === "delete" && titleConfirmation !== confirmation.project.title)} onClick={() => void confirmLifecycleAction()}>{confirmation.kind === "delete" ? "彻底删除" : "移入回收站"}</button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
