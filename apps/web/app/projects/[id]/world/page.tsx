"use client";

import Link from "next/link";
import { useState } from "react";

import { EquipmentCatalog } from "../../../../components/ws/EquipmentCatalog";
import { MonsterBestiary } from "../../../../components/ws/MonsterBestiary";
import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { WorldBackgroundEditor } from "../../../../components/ws/WorldBackgroundEditor";
import { WorldEntitiesEditor } from "../../../../components/ws/WorldEntitiesEditor";
import { WorldRulesEditor } from "../../../../components/ws/WorldRulesEditor";
import { enrichProjectWorld } from "../../../../lib/api";
import { isGameWebnovel } from "../../../../lib/worldDisplay";

export default function WorldPage() {
  const { project, story, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const blueprint = project?.world_blueprint ?? {};
  const [enriching, setEnriching] = useState(false);
  const [setupMessage, setSetupMessage] = useState("");

  async function enrichWorld() {
    if (enriching) return;
    setEnriching(true);
    setSetupMessage("");
    try {
      await enrichProjectWorld(projectId);
      setSetupMessage("世界观已补全，可以继续检查或直接开始写作。");
      void refresh({ invalidateChapter: false }).catch(() => undefined);
    } catch (enrichError) {
      setSetupMessage(`世界观补全失败：${enrichError instanceof Error ? enrichError.message : String(enrichError)}`);
    } finally {
      setEnriching(false);
    }
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="世界观"
        subtitle={project?.world_summary || "维护世界背景、规则、地点、阵营和题材体系。"}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : null}

      {project ? (
        <>
          {(story?.current_chapter ?? 0) === 0 ? (
            <section className="ws-card" aria-labelledby="opening-world-actions-title">
              <div className="ws-section-head">
                <div>
                  <h2 className="ws-card__title" id="opening-world-actions-title">开书准备</h2>
                  <p className="ws-card__hint">可以让 AI 补全世界规则，也可以手动填写后直接开始第一章。</p>
                </div>
                <div className="ws-toolbar">
                  <button className="ws-btn" type="button" disabled={enriching} onClick={() => void enrichWorld()}>
                    {enriching ? "补全中..." : "AI 补全世界观"}
                  </button>
                  <Link className="ws-btn ws-btn--primary" href={`/projects/${encodedProjectId}/write`}>
                    开始写第一章
                  </Link>
                </div>
              </div>
              {setupMessage ? <p className="ws-inline-message" role="status">{setupMessage}</p> : null}
            </section>
          ) : null}
          <WorldBackgroundEditor
            projectId={projectId}
            worldSummary={project.world_summary}
            blueprint={blueprint}
            onSaved={refresh}
          />
          <WorldRulesEditor projectId={projectId} blueprint={blueprint} onSaved={refresh} />
          <WorldEntitiesEditor projectId={projectId} blueprint={blueprint} onSaved={refresh} />
          {isGameWebnovel(project) ? (
            <>
              <EquipmentCatalog projectId={projectId} blueprint={blueprint} onSaved={refresh} />
              <MonsterBestiary projectId={projectId} blueprint={blueprint} onSaved={refresh} />
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
