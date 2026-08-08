"use client";

import { useState } from "react";

import {
  fetchWorkflowArtifact,
  type GenerationJobStep,
  type WorkflowArtifactJob,
  type WorkflowArtifactResponse,
  type WorkflowArtifactStage,
} from "../../lib/api";

export type WritingFlowStage = {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "failed";
  seconds: string;
  reads: string[];
  outputs: Record<string, unknown>;
  usedModules: string[];
};

const STAGE_LABELS: Record<string, string> = {
  orchestrator: "编排器",
  director: "章节规划",
  writer: "写手",
  review: "审稿",
  memory: "记忆更新",
  context_loader: "资料读取",
  world_simulation: "剧情准备",
  context_builder: "写作上下文准备",
};

const SOURCE_LABELS: Record<string, string> = {
  "file-project-route": "任务接口层",
  orchestrator: "编排器",
  context_loader: "资料读取器",
  chapter_planning: "章节规划",
  director: "章节规划模块",
  writer: "写作模块",
  reviewer: "审稿模块",
  memory: "记忆模块",
  world_simulation: "剧情准备模块",
  context_builder: "写作上下文准备",
  llm: "模型调用",
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function normalizedStatus(value: GenerationJobStep["status"]): WritingFlowStage["status"] {
  if (value === "done") return "done";
  if (value === "error") return "failed";
  if (value === "queued") return "pending";
  return "running";
}

function artifactText(artifact: GenerationJobStep["artifact"]): string {
  try {
    return JSON.stringify(artifact, null, 2);
  } catch {
    return String(artifact);
  }
}

export function writingFlowPlanningSourceText(outputs: Record<string, unknown>): string {
  if (outputs.planning_source === "outline") return "已有章节细纲";
  if (outputs.planning_source === "model_fallback") return "模型补全";
  return "";
}

export function buildWritingFlow(steps: GenerationJobStep[]): WritingFlowStage[] {
  const flow: WritingFlowStage[] = [];
  const indexes = new Map<string, number>();

  for (const step of steps) {
    if (!isObject(step.artifact) || !isObject(step.artifact.workflow_step)) continue;
    const definition = step.artifact.workflow_step;
    const key = typeof definition.id === "string" ? definition.id.trim() : "";
    const label = typeof definition.label === "string" ? definition.label.trim() : "";
    if (!key || !label) continue;
    const next: WritingFlowStage = {
      key,
      label,
      status: normalizedStatus(step.status),
      seconds: typeof definition.seconds === "string" ? definition.seconds : "",
      reads: stringList(definition.reads),
      outputs: isObject(step.artifact.outputs) ? step.artifact.outputs : {},
      usedModules: stringList(step.artifact.used_modules),
    };
    const existingIndex = indexes.get(key);
    if (existingIndex === undefined) {
      indexes.set(key, flow.length);
      flow.push(next);
    } else {
      const previous = flow[existingIndex];
      flow[existingIndex] = {
        ...previous,
        ...next,
        reads: next.reads.length ? next.reads : previous.reads,
        outputs: Object.keys(next.outputs).length ? next.outputs : previous.outputs,
        usedModules: next.usedModules.length ? next.usedModules : previous.usedModules,
      };
    }
  }

  return flow;
}

export function writingFlowStatusText(stage: WritingFlowStage): string {
  if (stage.status === "pending") return "等待中";
  if (stage.status === "running") return "进行中";
  if (stage.status === "done") return stage.seconds ? `完成 ${stage.seconds}s` : "已完成";
  return "失败";
}

const AGENT_LABELS: Record<string, string> = {
  DirectorAgent: "导演",
  WriterAgent: "写手",
  FactExtractor: "事实提取",
  FocusedConsistencyAgent: "一致性检查",
};

const STAGE_LABELS_ARTIFACT: Record<string, string> = {
  director: "章节规划",
  writer: "正文生成",
  "fact-extractor": "事实提取",
  consistency: "一致性检查",
};

function summarizeReads(reads: WorkflowArtifactStage["reads"]): string {
  if (!Array.isArray(reads) || reads.length === 0) return "无读取记录";
  return reads
    .map((entry) => {
      if (!isObject(entry)) return String(entry);
      const kind = typeof entry.kind === "string" ? entry.kind : "";
      const id = typeof entry.id === "string" ? entry.id : "";
      return kind && id ? `${kind}:${id}` : kind || id || JSON.stringify(entry);
    })
    .filter(Boolean)
    .join("、");
}

function elapsedSeconds(stage: WorkflowArtifactStage): string {
  if (!Number.isFinite(stage.elapsed_ms) || stage.elapsed_ms <= 0) return "—";
  if (stage.elapsed_ms < 1000) return `${stage.elapsed_ms}ms`;
  return `${(stage.elapsed_ms / 1000).toFixed(2)}s`;
}

function summarizeStageRecord(record: WorkflowArtifactStage): string {
  // The summary list is the same string the workbench showed
  // before the audit panel was introduced: a one-line text the
  // operator can scan in the timeline view. The full record is
  // loaded on demand when the operator clicks "查看本步产物".
  if (record.output_summary) return record.output_summary;
  if (record.artifact_path) return record.artifact_path;
  if (record.artifact_sha256) return `sha256=${record.artifact_sha256.slice(0, 12)}`;
  return "无本步产物摘要";
}

export function WorkflowArtifactPanel({
  projectId,
  jobs,
}: {
  projectId: string;
  jobs: WorkflowArtifactJob[];
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [records, setRecords] = useState<Record<string, WorkflowArtifactStage>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  if (jobs.length === 0) {
    return (
      <p className="ws-card__hint">
        新流程尚未生成结构化工件。新章节生成完毕后此处会自动列出本步骤的读取资料、调用模块和本步产物。
      </p>
    );
  }
  const latest = jobs[jobs.length - 1];

  const toggleStage = async (stageId: string) => {
    const key = `${latest.job_id}/${stageId}`;
    if (expanded[key]) {
      setExpanded((current) => ({ ...current, [key]: false }));
      return;
    }
    setExpanded((current) => ({ ...current, [key]: true }));
    if (records[key]) return;
    setLoading((current) => ({ ...current, [key]: true }));
    setErrors((current) => ({ ...current, [key]: "" }));
    try {
      const response: WorkflowArtifactResponse = await fetchWorkflowArtifact(
        projectId,
        latest.job_id,
        stageId,
      );
      setRecords((current) => ({ ...current, [key]: response.stage }));
    } catch (reason) {
      setErrors((current) => ({
        ...current,
        [key]: reason instanceof Error ? reason.message : String(reason),
      }));
    } finally {
      setLoading((current) => ({ ...current, [key]: false }));
    }
  };

  return (
    <div className="ws-workflow-artifacts">
      <p className="ws-card__hint">
        任务 <code>{latest.job_id}</code> 的结构化工件：
      </p>
      <ol className="ws-plain-list">
        {latest.stages.map((stage) => {
          const detailKey = `${latest.job_id}/${stage.stage_id}`;
          const isExpanded = Boolean(expanded[detailKey]);
          const fullRecord = records[detailKey] ?? stage;
          const isLoading = Boolean(loading[detailKey]);
          const detailError = errors[detailKey] ?? "";
          return (
            <li key={detailKey} className="ws-workflow-artifacts__stage">
              <p style={{ margin: 0 }}>
                <strong>
                  {STAGE_LABELS_ARTIFACT[stage.stage_id] ?? stage.stage_id}
                </strong>{" "}
                <span className="ws-badge">
                  {AGENT_LABELS[stage.agent_id] ?? stage.agent_id} · {stage.status} · {elapsedSeconds(stage)}
                </span>
              </p>
              {stage.provider || stage.model ? (
                <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                  模型：{stage.provider || "?"} / {stage.model || "?"}
                </p>
              ) : null}
              {stage.selected_entity_ids.length > 0 ? (
                <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                  涉及实体：{stage.selected_entity_ids.join("、")}
                </p>
              ) : null}
              {stage.selected_module_ids.length > 0 ? (
                <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                  调用模块：{stage.selected_module_ids.join("、")}
                </p>
              ) : null}
              <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                读取资料：{summarizeReads(stage.reads)}
              </p>
              {stage.output_summary || stage.artifact_path ? (
                <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                  本步产物：<code>{summarizeStageRecord(stage)}</code>
                </p>
              ) : null}
              {stage.artifact_path ? (
                <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                  产物路径：<code>{stage.artifact_path}</code>
                </p>
              ) : null}
              {stage.error ? (
                <p className="ws-inline-error" style={{ margin: "4px 0 0" }}>
                  错误：{stage.error}
                </p>
              ) : null}
              <button
                type="button"
                className="ws-button"
                style={{ marginTop: 6 }}
                aria-expanded={isExpanded}
                aria-controls={`${detailKey}-detail`}
                onClick={() => {
                  void toggleStage(stage.stage_id);
                }}
              >
                {isExpanded ? "收起本步详情" : "查看本步详情"}
              </button>
              {isExpanded ? (
                <div
                  id={`${detailKey}-detail`}
                  className="ws-workflow-artifacts__detail"
                  aria-label={`${stage.stage_id} 详情`}
                >
                  {isLoading ? (
                    <p className="ws-card__hint">正在读取本步详情…</p>
                  ) : detailError ? (
                    <p className="ws-inline-error">本步详情加载失败：{detailError}</p>
                  ) : (
                    <>
                      <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                        提示词模板：{fullRecord.prompt_template_id || "?"}@{
                          fullRecord.prompt_template_version || "?"
                        }
                      </p>
                      <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                        本步产物：
                        <code>
                          {fullRecord.output_summary || fullRecord.artifact_path || "—"}
                        </code>
                      </p>
                      {fullRecord.artifact_sha256 ? (
                        <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                          产物哈希：<code>{fullRecord.artifact_sha256}</code>
                        </p>
                      ) : null}
                      {fullRecord.reads.length > 0 ? (
                        <details>
                          <summary className="ws-card__hint">读取资料明细</summary>
                          <pre className="ws-artifact__payload">
                            {JSON.stringify(fullRecord.reads, null, 2)}
                          </pre>
                        </details>
                      ) : null}
                      {fullRecord.started_at || fullRecord.finished_at ? (
                        <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                          起止时间：{fullRecord.started_at || "?"} → {fullRecord.finished_at || "?"}
                        </p>
                      ) : null}
                    </>
                  )}
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function stageLabel(stage: string | undefined): string {
  if (!stage) return "";
  return STAGE_LABELS[stage] ?? stage;
}

function sourceLabel(source: string | undefined): string {
  if (!source) return "";
  return SOURCE_LABELS[source] ?? source;
}

export function WritingFlowPanel({ steps, status }: { steps: GenerationJobStep[]; status?: string | null }) {
  const flow = buildWritingFlow(steps);
  const technicalSteps = steps.filter(
    (step) => !isObject(step.artifact) || !isObject(step.artifact.workflow_step),
  );

  return (
    <section className="ws-card">
      <div className="ws-section-head">
        <p className="ws-card__title">写作流程</p>
        <span className="ws-badge">{status || steps[steps.length - 1]?.message || "准备中"}</span>
      </div>

      {flow.length > 0 ? (
        <ol className="ws-plain-list">
          {flow.map((item) => (
            <li key={item.key}>
              <p style={{ margin: 0 }}>
                <strong>{item.label}</strong>{" "}
                <span className="ws-badge">{writingFlowStatusText(item)}</span>
              </p>
              {item.reads.length > 0 ? (
                <p className="ws-card__hint" style={{ margin: "6px 0 0" }}>
                  读取：{item.reads.join("、")}
                </p>
              ) : null}
              {item.usedModules.length > 0 ? (
                <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                  调用：{item.usedModules.join("、")}
                </p>
              ) : null}
              {writingFlowPlanningSourceText(item.outputs) ? (
                <p className="ws-card__hint" style={{ margin: "4px 0 0" }}>
                  规划来源：{writingFlowPlanningSourceText(item.outputs)}
                </p>
              ) : null}
              {Object.keys(item.outputs).length > 0 ? (
                <details style={{ marginTop: 4 }}>
                  <summary className="ws-card__hint">查看本步产物</summary>
                  <pre className="ws-artifact__payload">{artifactText(item.outputs)}</pre>
                </details>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="ws-card__hint">尚未收到结构化写作步骤。</p>
      )}

      <details>
        <summary className="ws-card__hint">运行日志（模型请求、耗时与错误）</summary>
        {technicalSteps.length > 0 ? (
          <ul className="ws-plain-list">
            {technicalSteps.map((step, index) => (
              <li key={`${step.at || "t"}-${index}-${step.message}`}>
                <p style={{ margin: 0 }}>{step.message}</p>
                <p className="ws-card__hint">
                  {step.stage ? `阶段：${stageLabel(step.stage)}` : ""}
                  {step.source ? ` · 来源：${sourceLabel(step.source)}` : ""}
                </p>
                {step.artifact !== undefined ? (
                  <details>
                    <summary className="ws-card__hint">查看技术数据</summary>
                    <pre className="ws-artifact__payload">{artifactText(step.artifact)}</pre>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="ws-card__hint">暂无技术日志。</p>
        )}
      </details>
    </section>
  );
}
