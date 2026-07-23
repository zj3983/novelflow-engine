"use client";

import { ConfirmedFactsPanel } from "../../../../components/ws/ConfirmedFactsPanel";
import { MonsterBestiary } from "../../../../components/ws/MonsterBestiary";
import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { WorldBackgroundEditor } from "../../../../components/ws/WorldBackgroundEditor";
import { WorldEntitiesEditor } from "../../../../components/ws/WorldEntitiesEditor";
import { WorldRulesEditor } from "../../../../components/ws/WorldRulesEditor";

export default function WorldPage() {
  const { project, story, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const blueprint = project?.world_blueprint ?? {};

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="世界观"
        subtitle={project?.world_summary || "维护世界背景、规则、地点、阵营、怪物与已确认事实。"}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : null}

      {project ? (
        <>
          <WorldBackgroundEditor
            projectId={projectId}
            worldSummary={project.world_summary}
            blueprint={blueprint}
            onSaved={refresh}
          />
          <WorldRulesEditor projectId={projectId} blueprint={blueprint} onSaved={refresh} />
          <WorldEntitiesEditor projectId={projectId} blueprint={blueprint} onSaved={refresh} />
          <MonsterBestiary projectId={projectId} blueprint={blueprint} onSaved={refresh} />
          <ConfirmedFactsPanel facts={story?.world_facts ?? []} />
        </>
      ) : null}
    </div>
  );
}
