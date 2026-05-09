"use client";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";

const SOURCE_LABEL = {
  sqlite: "数据库",
  file: "文件夹",
} as const;

const STATUS_LABEL = {
  draft: "草稿",
  simulating: "推演中",
  paused: "已暂停",
  completed: "已完成",
} as const;

export default function ProjectSettingsPage() {
  const { project, story, error, encodedProjectId } = useProjectWorkspace();
  const source = project?.storage_source ? SOURCE_LABEL[project.storage_source] : "数据库";

  return (
    <div className="ws-page ws-page--narrow">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="项目设置"
        subtitle="查看当前项目的基础信息和运行状态。"
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : (
        <div className="ws-detail-list">
          <div>
            <span>标题</span>
            <strong>{project?.title || "未载入"}</strong>
          </div>
          <div>
            <span>作品来源</span>
            <strong>{source}</strong>
          </div>
          <div>
            <span>当前章节</span>
            <strong>第 {story?.current_chapter ?? 0} 章</strong>
          </div>
          <div>
            <span>状态</span>
            <strong>{project ? STATUS_LABEL[project.status] : "草稿"}</strong>
          </div>
          <div>
            <span>路径</span>
            <strong>{project?.source_path || "未设置"}</strong>
          </div>
        </div>
      )}
    </div>
  );
}
