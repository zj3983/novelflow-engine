"use client";

import type { GenerationJobStep } from "../../lib/api";

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
