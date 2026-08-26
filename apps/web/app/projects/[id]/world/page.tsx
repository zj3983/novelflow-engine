"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { EquipmentCatalog } from "../../../../components/ws/EquipmentCatalog";
import { MonsterBestiary } from "../../../../components/ws/MonsterBestiary";
import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { WorldBackgroundEditor } from "../../../../components/ws/WorldBackgroundEditor";
import { WorldEntitiesEditor } from "../../../../components/ws/WorldEntitiesEditor";
import { WorldRulesEditor } from "../../../../components/ws/WorldRulesEditor";
import {
  fetchCurrentWorldBuildJob,
  fetchWorldBuildJob,
  startWorldBuildJob,
  type WorldBuildArtifact,
  type WorldBuildJobResponse,
} from "../../../../lib/api";
import { isGameWebnovel } from "../../../../lib/worldDisplay";

type ArtifactFieldLabels = Record<string, string>;

const ARTIFACT_FIELD_LABELS: Record<string, ArtifactFieldLabels> = {
  core_rules: {
    premise: "故事前提",
    world_rules: "世界规则",
    constraints: "边界约束",
    power_system: "力量体系",
    power_system_spec: "力量体系规格",
    locations: "关键地点",
    factions: "阵营",
  },
  society_and_livelihood: {
    locations: "地点",
    factions: "阵营",
    economy_rules: "经济规则",
    faction_rules: "阵营关系",
    relationship_graph: "关系网",
    world_systems: "世界制度",
    living_world: "民生运转",
  },
  story_engine: {
    current_arc: "当前剧情",
    progression_rules: "推进规则",
    chapter_formula: "章节结构",
    forbidden_breaks: "禁区",
    opening_arc: "开篇规划",
    volume_plan: "卷目标",
    longform_framework: "长篇框架",
    progression_ledger: "成长账本",
  },
  game_ecology: {
    quest_rules: "任务规则",
    panel_rules: "面板规则",
    npc_system: "NPC 系统",
    quest_network: "任务网络",
    server_runtime: "服务器阶段",
    map_ecology: "地图生态",
  },
};

const ARTIFACT_ORDER: string[] = [
  "core_rules",
  "society_and_livelihood",
  "game_ecology",
  "story_engine",
];

function labelForField(moduleId: string, field: string): string {
  return ARTIFACT_FIELD_LABELS[moduleId]?.[field] ?? field;
}

function describeJobStatus(job: WorldBuildJobResponse): {
  tone: "info" | "warning" | "error" | "success";
  message: string;
} {
  if (job.status === "completed") {
    return { tone: "success", message: "世界观构建完成" };
  }
  if (job.status === "interrupted") {
    return {
      tone: "warning",
      message: "上次补全因服务重启被中断，请重新开始补全。",
    };
  }
  if (job.status === "conflicted") {
    return {
      tone: "warning",
      message: "检测到世界观被手动修改，请保留修改后重新补全，或放弃修改继续。",
    };
  }
  if (job.status === "failed") {
    return {
      tone: "error",
      message: job.error
        ? `补全失败：${job.error}`
        : job.progress || "补全失败，请稍后重试。",
    };
  }
  const moduleLabel = job.active_module_title ? `（${job.active_module_title}）` : "";
  return { tone: "info", message: `${job.progress || "正在构建"}${moduleLabel}` };
}

function sortArtifacts(artifacts: WorldBuildArtifact[]): WorldBuildArtifact[] {
  return [...artifacts].sort(
    (a, b) => ARTIFACT_ORDER.indexOf(a.module_id) - ARTIFACT_ORDER.indexOf(b.module_id),
  );
}

export default function WorldPage() {
  const { project, story, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const blueprint = project?.world_blueprint ?? {};
  const [enriching, setEnriching] = useState(false);
  const [setupMessage, setSetupMessage] = useState("");
  const [worldBuildJob, setWorldBuildJob] = useState<WorldBuildJobResponse | null>(null);
  const worldBuildArtifacts: WorldBuildArtifact[] = Array.isArray(
    blueprint.world_build_artifacts,
  )
    ? (blueprint.world_build_artifacts as WorldBuildArtifact[])
    : [];

  useEffect(() => {
    let cancelled = false;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function restore() {
      controller = new AbortController();
      try {
        const current = await fetchCurrentWorldBuildJob(projectId);
        if (cancelled || !current) {
          return;
        }
        if (current.status === "queued" || current.status === "running") {
          await watchWorldBuildJob(current, controller.signal);
        } else {
          setWorldBuildJob(current);
        }
      } catch (restoreError) {
        if (cancelled) return;
        if (restoreError instanceof Error && restoreError.name === "AbortError") {
          return;
        }
        setSetupMessage(
          `恢复补全状态失败：${restoreError instanceof Error ? restoreError.message : String(restoreError)}`,
        );
      }
    }

    void restore();
    return () => {
      cancelled = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function watchWorldBuildJob(
    initialJob: WorldBuildJobResponse,
    signal?: AbortSignal,
  ): Promise<WorldBuildJobResponse> {
    let job = initialJob;
    setWorldBuildJob(job);
    while (job.status === "queued" || job.status === "running") {
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(resolve, 900);
        if (signal) {
          const onAbort = () => {
            clearTimeout(timeout);
            reject(new DOMException("aborted", "AbortError"));
          };
          if (signal.aborted) {
            onAbort();
            return;
          }
          signal.addEventListener("abort", onAbort, { once: true });
        }
      });
      if (signal?.aborted) {
        throw new DOMException("aborted", "AbortError");
      }
      job = await fetchWorldBuildJob(projectId, job.job_id);
      if (signal?.aborted) {
        throw new DOMException("aborted", "AbortError");
      }
      setWorldBuildJob(job);
    }
    return job;
  }

  async function enrichWorld() {
    if (enriching) return;
    setEnriching(true);
    setSetupMessage("");
    try {
      const started = await startWorldBuildJob(projectId);
      const job = await watchWorldBuildJob(started);
      if (job.status === "completed") {
        setSetupMessage("世界观已补全，可以继续检查或直接开始写作。");
        await refresh({ invalidateChapter: false });
      } else if (job.status === "interrupted") {
        setSetupMessage(job.progress || "服务已重启，请重新开始补全。");
      } else if (job.status === "conflicted") {
        setSetupMessage(
          job.progress || "世界观已被手动修改，请重新开始补全。",
        );
      } else {
        setSetupMessage(describeJobStatus(job).message);
      }
    } catch (enrichError) {
      if (enrichError instanceof DOMException && enrichError.name === "AbortError") {
        return;
      }
      setSetupMessage(
        `世界观补全失败：${enrichError instanceof Error ? enrichError.message : String(enrichError)}`,
      );
    } finally {
      setEnriching(false);
    }
  }

  const orderedArtifacts = sortArtifacts(worldBuildArtifacts);
  const jobStatus = worldBuildJob ? describeJobStatus(worldBuildJob) : null;
  const isJobActive =
    worldBuildJob?.status === "queued" || worldBuildJob?.status === "running";
  const canRetry =
    worldBuildJob?.status === "failed" ||
    worldBuildJob?.status === "interrupted" ||
    worldBuildJob?.status === "conflicted";
  const isOpening = (story?.current_chapter ?? 0) === 0;

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
          {isOpening ? (
            <section className="ws-card" aria-labelledby="opening-world-actions-title">
              <div className="ws-section-head">
                <div>
                  <h2 className="ws-card__title" id="opening-world-actions-title">开书准备</h2>
                  <p className="ws-card__hint">可以让 AI 补全世界规则，也可以手动填写后直接开始第一章。</p>
                </div>
                <div className="ws-toolbar">
                  <button
                    className="ws-btn"
                    type="button"
                    disabled={enriching || isJobActive}
                    onClick={() => void enrichWorld()}
                  >
                    {isJobActive
                      ? "补全中..."
                      : worldBuildJob?.status === "interrupted"
                        ? "重新开始补全"
                        : worldBuildJob?.status === "conflicted"
                          ? "保留手动修改，重新补全"
                          : worldBuildJob?.status === "failed"
                            ? "重试补全"
                            : "AI 补全世界观"}
                  </button>
                  {canRetry ? (
                    <button
                      className="ws-btn ws-btn--ghost"
                      type="button"
                      disabled={enriching || isJobActive}
                      onClick={() => void enrichWorld()}
                    >
                      再次尝试
                    </button>
                  ) : null}
                  <Link className="ws-btn ws-btn--primary" href={`/projects/${encodedProjectId}/write`}>
                    开始写第一章
                  </Link>
                </div>
              </div>
              {setupMessage ? <p className="ws-inline-message" role="status">{setupMessage}</p> : null}
              {jobStatus ? (
                <p
                  className={
                    jobStatus.tone === "error"
                      ? "ws-error-text"
                      : jobStatus.tone === "warning"
                        ? "ws-warning-text"
                        : "ws-inline-message"
                  }
                  role="status"
                >
                  {jobStatus.message}
                </p>
              ) : null}
            </section>
          ) : null}
          {orderedArtifacts.length > 0 ? (
            <section className="ws-card" aria-labelledby="world-build-progress-title">
              <div className="ws-section-head">
                <div>
                  <h2 className="ws-card__title" id="world-build-progress-title">世界观构建记录</h2>
                  <p className="ws-card__hint">每个模块只负责自己的设定范围，写作时按章节需要提取相关内容。</p>
                </div>
              </div>
              <div className="ws-list">
                {orderedArtifacts.map((artifact) => (
                  <details className="ws-list__row" key={artifact.module_id}>
                    <summary>
                      <strong>{artifact.title}</strong>
                      <span className="ws-card__hint">
                        已完成 · {artifact.fields.map((field) => labelForField(artifact.module_id, field)).join("、")}
                      </span>
                    </summary>
                    <div className="ws-card__hint" style={{ marginTop: 10 }}>
                      包含：{artifact.fields.map((field) => labelForField(artifact.module_id, field)).join("、")}
                    </div>
                    <details className="ws-list__row__nested" style={{ marginTop: 8 }}>
                      <summary>查看原始输出</summary>
                      <pre className="ws-code-block" style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
                        {JSON.stringify(artifact.output, null, 2)}
                      </pre>
                    </details>
                  </details>
                ))}
              </div>
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
