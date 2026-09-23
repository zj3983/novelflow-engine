"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { fetchBuildWorkbench, type BuildWorkbenchGraph, type BuildWorkbenchTask } from "../../../../lib/api";
import styles from "./build.module.css";

const STATUS_LABELS: Record<string, string> = {
  pending: "未开始",
  blocked: "受阻",
  ready: "待执行",
  running: "进行中",
  validation_failed: "校验失败",
  review_required: "待审核",
  completed: "已完成",
  stale: "已过期",
};

const SOURCE_LABELS: Record<string, string> = {
  llm: "AI 生成",
  ai_repair: "AI 修复",
  human: "人工编辑",
  imported: "导入",
  deterministic: "系统生成",
};

function StatusBadge({ status }: { status: string }) {
  const tone = status === "completed" ? "success"
    : status === "running" || status === "ready" ? "active"
      : status === "validation_failed" || status === "blocked" || status === "stale" ? "danger"
        : status === "review_required" ? "warning" : "neutral";
  return <span className={`${styles.status} ${styles[`status_${tone}`]}`}>{STATUS_LABELS[status] ?? status}</span>;
}

function ValueList({ values }: { values: string[] }) {
  return values.length > 0
    ? <ul className={styles.value_list}>{values.map((value) => <li key={value}><code>{value}</code></li>)}</ul>
    : <p className={styles.empty_value}>无</p>;
}

function TaskDetail({ task, graph, onSelectDependency }: {
  task: BuildWorkbenchTask;
  graph: BuildWorkbenchGraph;
  onSelectDependency: (taskId: string) => void;
}) {
  const taskTitles = useMemo(() => new Map(graph.tasks.map((item) => [item.task_id, item.title])), [graph.tasks]);
  const source = task.artifact_source ? SOURCE_LABELS[task.artifact_source] ?? task.artifact_source : "尚无产物";

  return (
    <section className={`ws-card ${styles.detail}`} aria-labelledby="build-task-detail-title">
      <div className={styles.detail_head}>
        <div>
          <p className="ws-card__title">任务详情</p>
          <h2 id="build-task-detail-title" className={styles.task_title}>{task.title}</h2>
          <code className={styles.task_id}>{task.task_id}</code>
        </div>
        <StatusBadge status={task.status} />
      </div>

      <div className={styles.facts}>
        <div><span>产物版本</span><strong>{task.artifact_revision === null ? "暂无" : `r${task.artifact_revision}`}</strong></div>
        <div><span>产物来源</span><strong>{source}</strong></div>
        <div><span>校验状态</span><strong>{task.validation_status}</strong></div>
      </div>

      <section className={styles.detail_section}>
        <h3>依赖任务</h3>
        {task.dependencies.length > 0 ? (
          <ul className={styles.dependency_list}>
            {task.dependencies.map((dependency) => (
              <li key={dependency}>
                <button type="button" onClick={() => onSelectDependency(dependency)}>
                  {taskTitles.get(dependency) ?? dependency}<code>{dependency}</code>
                </button>
              </li>
            ))}
          </ul>
        ) : <p className={styles.empty_value}>无前置依赖</p>}
      </section>

      <div className={styles.path_grid}>
        <section className={styles.detail_section}>
          <h3>读取（reads）</h3>
          <ValueList values={task.reads} />
        </section>
        <section className={styles.detail_section}>
          <h3>负责产出（owns）</h3>
          <ValueList values={task.owns} />
        </section>
      </div>

      <section className={styles.detail_section}>
        <h3>诊断信息</h3>
        {task.diagnostics.length > 0 ? (
          <ul className={styles.diagnostics}>
            {task.diagnostics.map((diagnostic, index) => (
              <li key={`${diagnostic.code}-${diagnostic.path}-${index}`}>
                <strong>{diagnostic.code}</strong>
                <code>{diagnostic.path || "（未提供路径）"}</code>
                <p>{diagnostic.message}</p>
              </li>
            ))}
          </ul>
        ) : <p className={styles.empty_value}>暂无诊断</p>}
      </section>

      {(task.provider || task.model || task.prompt_call_id) ? (
        <section className={styles.detail_section}>
          <h3>模型来源</h3>
          <dl className={styles.provenance}>
            {task.provider ? <><dt>Provider</dt><dd>{task.provider}</dd></> : null}
            {task.model ? <><dt>Model</dt><dd>{task.model}</dd></> : null}
            {task.prompt_call_id ? <><dt>Prompt call</dt><dd><code>{task.prompt_call_id}</code></dd></> : null}
          </dl>
        </section>
      ) : null}
    </section>
  );
}

export default function BuildWorkbenchPage() {
  const { project, projectId, encodedProjectId } = useProjectWorkspace();
  const [graph, setGraph] = useState<BuildWorkbenchGraph | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchBuildWorkbench(projectId)
      .then((result) => {
        if (!active) return;
        setGraph(result);
        setSelectedTaskId((current) => result.tasks.some((task) => task.task_id === current)
          ? current : result.tasks[0]?.task_id ?? null);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [projectId]);

  const selectedTask = graph?.tasks.find((task) => task.task_id === selectedTaskId) ?? null;
  const completedCount = graph?.tasks.filter((task) => task.status === "completed").length ?? 0;

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[{ label: "作品", href: "/projects" }, { label: project?.title ?? "项目", href: `/projects/${encodedProjectId}` }]}
        title="开书构建"
        subtitle="查看正式 Build Graph 的任务状态、依赖、产物版本与校验诊断。此页面只读取项目状态。"
      />

      {loading ? <section className="ws-card" role="status">正在读取 Build Graph…</section> : null}
      {error ? <section className={`ws-card ${styles.error}`} role="alert">读取失败：{error}</section> : null}

      {!loading && !error && graph && !graph.initialized ? (
        <section className="ws-card" aria-live="polite">
          <h2 className={styles.empty_title}>尚无正式 Build Graph 状态</h2>
          <p className="ws-card__hint">当前项目阶段：{graph.pipeline_stage || "未知"}。任务状态只会在后端创建正式 graph state 后显示。</p>
        </section>
      ) : null}

      {!loading && !error && graph?.initialized ? (
        <>
          <section className={`ws-card ${styles.graph_summary}`} aria-label="构建总览">
            <div><span>Pipeline stage</span><strong>{graph.pipeline_stage || "未知"}</strong></div>
            <div><span>Graph revision</span><strong>{graph.graph_revision === null ? "—" : graph.graph_revision}</strong></div>
            <div><span>任务进度</span><strong>{completedCount} / {graph.tasks.length} 已完成</strong></div>
          </section>

          {graph.tasks.length > 0 ? (
            <div className={styles.columns}>
              <section className={`ws-card ${styles.task_panel}`} aria-labelledby="build-task-list-title">
                <div className={styles.panel_heading}>
                  <div><p className="ws-card__title">Build Graph</p><h2 id="build-task-list-title">任务列表</h2></div>
                  <span>{graph.tasks.length} 项</span>
                </div>
                <ol className={styles.task_list}>
                  {graph.tasks.map((task) => (
                    <li key={task.task_id}>
                      <button
                        type="button"
                        className={`${styles.task_button}${selectedTaskId === task.task_id ? ` ${styles.task_selected}` : ""}${task.status !== "completed" ? ` ${styles.task_attention}` : ""}`}
                        onClick={() => setSelectedTaskId(task.task_id)}
                        aria-current={selectedTaskId === task.task_id ? "true" : undefined}
                      >
                        <span className={styles.task_button_title}>{task.title}</span>
                        <code>{task.task_id}</code>
                        <span className={styles.task_meta}>
                          <StatusBadge status={task.status} />
                          <span>r{task.artifact_revision ?? "—"} · {task.artifact_source ? SOURCE_LABELS[task.artifact_source] ?? task.artifact_source : "无产物"}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ol>
              </section>

              {selectedTask ? <TaskDetail task={selectedTask} graph={graph} onSelectDependency={setSelectedTaskId} /> : null}
            </div>
          ) : <section className="ws-card"><p className="ws-card__hint">当前 graph 没有任务。</p></section>}
        </>
      ) : null}
    </div>
  );
}
