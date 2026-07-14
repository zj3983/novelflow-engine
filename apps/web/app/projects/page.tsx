"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../components/ws/PageHeader";
import { listProjects, type ProjectStatus, type ProjectSummary } from "../../lib/api";

const LAST_PROJECT_STORAGE_KEY = "novel-autogrowth.last-project-id";

const STATUS_META: Record<string, { label: string; badge: string }> = {
  draft: { label: "草稿", badge: "ws-badge" },
  outlining: { label: "大纲中", badge: "ws-badge" },
  writing: { label: "写作中", badge: "ws-badge ws-badge--success" },
  reviewing: { label: "审核中", badge: "ws-badge ws-badge--warn" },
  simulating: { label: "推演中", badge: "ws-badge ws-badge--success" },
  paused: { label: "已暂停", badge: "ws-badge ws-badge--warn" },
  completed: { label: "已完成", badge: "ws-badge" },
};

const SOURCE_LABEL: Record<NonNullable<ProjectSummary["storage_source"]>, string> = {
  sqlite: "数据库",
  file: "文件夹",
};

function projectHref(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}`;
}

function statusMeta(status: ProjectStatus | undefined): { label: string; badge: string } {
  const key = String(status || "draft");
  return STATUS_META[key] ?? { label: key, badge: "ws-badge ws-badge--warn" };
}

export default function ProjectsListPage() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastProjectId, setLastProjectId] = useState<string | null>(null);

  useEffect(() => {
    try {
      setLastProjectId(window.localStorage.getItem(LAST_PROJECT_STORAGE_KEY));
    } catch {
      setLastProjectId(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((items) => {
        if (!cancelled) setProjects(items);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const lastProject = useMemo(() => {
    if (!projects || !lastProjectId) return null;
    return projects.find((project) => project.project_id === lastProjectId) ?? null;
  }, [projects, lastProjectId]);

  return (
    <div className="ws-page">
      <PageHeader
        title="我的作品"
        subtitle="选择作品进入工作台。"
        actions={
          <div className="ws-action-row ws-action-row--flush">
            {lastProject ? (
              <Link href={projectHref(lastProject.project_id)} className="ws-btn">
                继续上次作品
              </Link>
            ) : null}
            <Link href="/projects/new" className="ws-btn ws-btn--primary">
              新建小说
            </Link>
          </div>
        }
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : projects === null ? (
        <p className="ws-page__subtitle">加载中...</p>
      ) : projects.length === 0 ? (
        <div className="ws-empty">
          <p className="ws-empty__title">还没有作品</p>
          <p className="ws-empty__hint">作品创建后会出现在这里。</p>
          <Link href="/projects/new" className="ws-btn">
            新建小说
          </Link>
        </div>
      ) : (
        <table className="ws-table">
          <thead>
            <tr>
              <th>小说名</th>
              <th>状态</th>
              <th>当前章</th>
              <th>来源</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {projects.map((project) => {
              const status = statusMeta(project.status);
              const sourceLabel = project.storage_source ? SOURCE_LABEL[project.storage_source] : "数据库";
              return (
                <tr key={project.project_id}>
                  <td>
                    <Link href={projectHref(project.project_id)} className="ws-table__strong">
                      {project.title}
                    </Link>
                  </td>
                  <td>
                    <span className={status.badge}>{status.label}</span>
                  </td>
                  <td>第 {project.current_chapter} 章</td>
                  <td style={{ color: "var(--ws-ink-muted)", fontSize: 12.5 }}>{sourceLabel}</td>
                  <td style={{ textAlign: "right" }}>
                    <Link href={`${projectHref(project.project_id)}/write`} className="ws-btn ws-btn--sm">
                      继续写
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
