"use client";

import { useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { updateProject, type ImportedWorldBlueprint, type ProjectStatus } from "../../../../lib/api";
import { DEFAULT_NOVEL_TYPE_ID, NOVEL_TYPE_OPTIONS, novelTypeLabel } from "../../../../lib/novelTypes";

const SOURCE_LABEL = {
  sqlite: "数据库",
  file: "文件夹",
} as const;

const STATUS_LABEL = {
  draft: "草稿",
  outlining: "大纲中",
  writing: "写作中",
  reviewing: "审核中",
  simulating: "推演中",
  paused: "已暂停",
  completed: "已完成",
} as const;

function statusLabel(status: ProjectStatus | undefined): string {
  const key = String(status || "draft");
  return key in STATUS_LABEL ? STATUS_LABEL[key as keyof typeof STATUS_LABEL] : key;
}

export default function ProjectSettingsPage() {
  const { project, story, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const source = project?.storage_source ? SOURCE_LABEL[project.storage_source] : "数据库";
  const currentTypeId = project?.world_blueprint?.genre_plugin_ids?.[0] || DEFAULT_NOVEL_TYPE_ID;
  const currentType = NOVEL_TYPE_OPTIONS.find((item) => item.id === currentTypeId) ?? NOVEL_TYPE_OPTIONS[0];
  const [savingType, setSavingType] = useState(false);
  const [typeMessage, setTypeMessage] = useState("");

  async function saveNovelType(nextTypeId: string) {
    if (!project) return;
    setSavingType(true);
    setTypeMessage("");
    try {
      const nextBlueprint: ImportedWorldBlueprint = {
        ...(project.world_blueprint ?? {}),
        genre_plugin_ids: nextTypeId === DEFAULT_NOVEL_TYPE_ID ? [DEFAULT_NOVEL_TYPE_ID] : [nextTypeId],
      };
      await updateProject(projectId, { world_blueprint: nextBlueprint });
      setTypeMessage(`小说类型已保存为：${novelTypeLabel(nextTypeId)}。下一次推演和写作包会读取这个类型。`);
      refresh();
    } catch (err) {
      setTypeMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingType(false);
    }
  }

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
        <>
          <section className="ws-card">
            <div className="ws-section-head">
              <div>
                <p className="ws-card__title">小说类型</p>
                <p className="ws-card__hint">类型决定会加载哪套题材规则。网游的背包、铜币、掉落、任务规则只应该来自“网游升级”。</p>
              </div>
              <span className="ws-toolbar__meta">{currentType.label}</span>
            </div>
            <label className="ws-character-mini">
              <strong>当前类型</strong>
              <select className="ws-input" value={currentTypeId} disabled={!project || savingType} onChange={(event) => void saveNovelType(event.target.value)}>
                {NOVEL_TYPE_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="ws-card__hint">{currentType.description}</p>
            {typeMessage ? <p className="ws-card__hint">{typeMessage}</p> : null}
          </section>

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
              <strong>{statusLabel(project?.status)}</strong>
            </div>
            <div>
              <span>路径</span>
              <strong>{project?.source_path || "未设置"}</strong>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
