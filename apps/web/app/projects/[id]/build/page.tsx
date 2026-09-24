"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  BuildWorkbenchRepairError,
  BuildWorkbenchRerunError,
  commitBuildWorkbenchTaskEdit,
  fetchBuildWorkbench,
  fetchBuildWorkbenchTask,
  repairBuildWorkbenchTask,
  rerunBuildWorkbenchTask,
  validateBuildWorkbenchTask,
  type BuildWorkbenchGraph,
  type BuildWorkbenchTask,
  type BuildWorkbenchTaskDetail,
  type BuildWorkbenchValidation,
} from "../../../../lib/api";
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

function TaskDetail({ task, graph, projectId, onSelectDependency, onSaved }: {
  task: BuildWorkbenchTask;
  graph: BuildWorkbenchGraph;
  projectId: string;
  onSelectDependency: (taskId: string) => void;
  onSaved: () => Promise<void>;
}) {
  const taskTitles = useMemo(() => new Map(graph.tasks.map((item) => [item.task_id, item.title])), [graph.tasks]);
  const source = task.artifact_source ? SOURCE_LABELS[task.artifact_source] ?? task.artifact_source : "尚无产物";
  const [detail, setDetail] = useState<BuildWorkbenchTaskDetail | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [validation, setValidation] = useState<BuildWorkbenchValidation | null>(null);
  const [busy, setBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [repairBusy, setRepairBusy] = useState(false);
  const [repairDiagnostics, setRepairDiagnostics] = useState<BuildWorkbenchTaskDetail["diagnostics"]>([]);
  const [repairError, setRepairError] = useState<string | null>(null);
  const [rerunBusy, setRerunBusy] = useState(false);
  const [rerunDiagnostics, setRerunDiagnostics] = useState<BuildWorkbenchTaskDetail["diagnostics"]>([]);
  const [rerunError, setRerunError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setDetail(null);
    setEditorOpen(false);
    setValidation(null);
    setEditError(null);
    setRerunError(null);
    setRerunDiagnostics([]);
    fetchBuildWorkbenchTask(projectId, task.task_id)
      .then((result) => {
        if (!active) return;
        setDetail(result);
        setDraft(JSON.stringify(result.artifact?.payload ?? {}, null, 2));
      })
      .catch((reason: unknown) => { if (active) setEditError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { active = false; };
  }, [projectId, task.task_id, task.artifact_revision]);

  const validateDraft = async () => {
    setEditError(null);
    let payload: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(draft);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Payload 必须是 JSON object");
      payload = parsed as Record<string, unknown>;
    } catch (reason) {
      setValidation(null);
      setEditError(reason instanceof Error ? reason.message : String(reason));
      return;
    }
    setBusy(true);
    try {
      setValidation(await validateBuildWorkbenchTask(projectId, task.task_id, payload));
    } catch (reason) {
      setValidation(null);
      setEditError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); }
  };

  const saveDraft = async () => {
    if (!validation?.passed || !detail?.artifact) return;
    let payload: Record<string, unknown>;
    try { payload = JSON.parse(draft) as Record<string, unknown>; }
    catch (reason) { setEditError(reason instanceof Error ? reason.message : String(reason)); return; }
    setBusy(true);
    setEditError(null);
    try {
      await commitBuildWorkbenchTaskEdit(projectId, task.task_id, detail.artifact.revision, payload);
      setEditorOpen(false);
      setValidation(null);
      await onSaved();
    } catch (reason) {
      setEditError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); }
  };

  const repairArtifact = async () => {
    if (!detail?.editable || !detail.artifact) return;
    if (editorOpen) {
      setRepairError("当前有未保存的 JSON 草稿。请先保存或取消草稿，再运行 AI 修复。");
      return;
    }
    setRepairBusy(true);
    setRepairDiagnostics([]);
    setRepairError(null);
    try {
      await repairBuildWorkbenchTask(projectId, task.task_id, detail.artifact.revision);
      await onSaved();
    } catch (reason) {
      if (reason instanceof BuildWorkbenchRepairError) {
        setRepairDiagnostics(reason.diagnostics);
        setRepairError(reason.message);
      } else {
        setRepairError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      setRepairBusy(false);
    }
  };

  const rerunArtifact = async () => {
    if (!detail?.editable || !detail.artifact) return;
    if (editorOpen) {
      setRerunError("当前有未保存的 JSON 草稿。请先保存或取消草稿，再完整重跑任务。");
      return;
    }
    setRerunBusy(true);
    setRerunDiagnostics([]);
    setRerunError(null);
    try {
      await rerunBuildWorkbenchTask(projectId, task.task_id, detail.artifact.revision);
      await onSaved();
    } catch (reason) {
      if (reason instanceof BuildWorkbenchRerunError) {
        setRerunDiagnostics(reason.diagnostics);
        setRerunError(reason.message);
      } else {
        setRerunError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      setRerunBusy(false);
    }
  };

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
        <div><span>产物版本</span><strong>{detail?.artifact ? `r${detail.artifact.revision}` : task.artifact_revision === null ? "暂无" : `r${task.artifact_revision}`}</strong></div>
        <div><span>产物来源</span><strong>{detail?.artifact ? SOURCE_LABELS[detail.artifact.source] ?? detail.artifact.source : source}</strong></div>
        <div><span>校验状态</span><strong>{task.validation_status}</strong></div>
      </div>

      {detail?.editable && !editorOpen ? <button type="button" className={styles.edit_button} onClick={() => {
        setDraft(JSON.stringify(detail.artifact?.payload ?? {}, null, 2));
        setValidation(null);
        setEditError(null);
        setEditorOpen(true);
      }}>人工编辑</button> : null}
      {detail?.editable ? <button type="button" className={styles.edit_button} disabled={repairBusy || rerunBusy || busy} onClick={() => void repairArtifact()}>
        {repairBusy ? "AI 修复中…" : "AI 修复"}
      </button> : null}
      {detail?.editable ? <button type="button" className={styles.edit_button} disabled={repairBusy || rerunBusy || busy} onClick={() => void rerunArtifact()}>
        {rerunBusy ? "完整重跑中…" : "完整重跑"}
      </button> : null}
      {detail?.editable ? <p className={styles.empty_value}>完整重生成此任务；成功后下游会标记为过期，不会自动重跑。</p> : null}
      {repairError ? <div className={styles.validation_fail} role="alert">
        <strong>{repairError}</strong>
        {repairDiagnostics.length ? <ul className={styles.diagnostics}>{repairDiagnostics.map((diagnostic, index) => (
          <li key={`${diagnostic.code}-${diagnostic.path}-${index}`}><strong>{diagnostic.code}</strong><code>{diagnostic.path || "（未提供路径）"}</code><p>{diagnostic.message}</p></li>
        ))}</ul> : null}
      </div> : null}
      {rerunError ? <div className={styles.validation_fail} role="alert">
        <strong>{rerunError}</strong>
        {rerunDiagnostics.length ? <ul className={styles.diagnostics}>{rerunDiagnostics.map((diagnostic, index) => (
          <li key={`${diagnostic.code}-${diagnostic.path}-${index}`}><strong>{diagnostic.code}</strong><code>{diagnostic.path || "（未提供路径）"}</code><p>{diagnostic.message}</p></li>
        ))}</ul> : null}
      </div> : null}
      {editorOpen ? (
        <section className={styles.editor} aria-label="人工编辑产物">
          <div className={styles.editor_heading}><strong>人工编辑 JSON</strong><span>当前 revision：r{detail?.artifact?.revision}</span></div>
          <textarea
            aria-label="Artifact JSON draft"
            spellCheck={false}
            value={draft}
            onChange={(event) => { setDraft(event.target.value); setValidation(null); setEditError(null); }}
          />
          <div className={styles.editor_actions}>
            <button type="button" disabled={busy} onClick={() => { setEditorOpen(false); setValidation(null); setEditError(null); }}>取消</button>
            <button type="button" disabled={busy} onClick={() => void validateDraft()}>{busy ? "处理中…" : "校验"}</button>
            <button type="button" disabled={busy || !validation?.passed} onClick={() => void saveDraft()}>保存</button>
          </div>
          {editError ? <p className={styles.edit_error} role="alert">{editError}</p> : null}
          {validation ? <div className={validation.passed ? styles.validation_pass : styles.validation_fail} role="status">
            <strong>{validation.passed ? `校验通过 · ${validation.disposition}` : "校验未通过"}</strong>
            {validation.diagnostics.length ? <ul className={styles.diagnostics}>{validation.diagnostics.map((diagnostic, index) => (
              <li key={`${diagnostic.code}-${diagnostic.path}-${index}`}><strong>{diagnostic.code}</strong><code>{diagnostic.path || "（未提供路径）"}</code><p>{diagnostic.message}</p></li>
            ))}</ul> : null}
          </div> : null}
        </section>
      ) : null}
      {detail?.materialization_status === "outdated" ? <p className={styles.outdated_marker}>旧物化结果已过期；保存不会自动重建世界。</p> : null}

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
  const [detailReload, setDetailReload] = useState(0);

  const reloadGraph = async () => {
    const result = await fetchBuildWorkbench(projectId);
    setGraph(result);
    setDetailReload((current) => current + 1);
  };

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
        subtitle="查看正式 Build Graph 状态与产物；模型任务支持先校验再保存人工修改。"
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
            <div><span>物化状态</span><strong>{graph.materialization_status === "outdated" ? "旧物化结果已过期" : graph.materialization_status === "current" ? "当前" : "未物化"}</strong></div>
          </section>

          {graph.tasks.some((task) => task.status === "stale") ? <section className={`ws-card ${styles.stale_notice}`} role="status">
            <strong>上游修改后，以下任务已过期</strong>
            <ul>{graph.tasks.filter((task) => task.status === "stale").map((task) => <li key={task.task_id}>{task.title} <code>{task.task_id}</code></li>)}</ul>
          </section> : null}

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

              {selectedTask ? <TaskDetail key={`${selectedTask.task_id}-${detailReload}`} task={selectedTask} graph={graph} projectId={projectId} onSelectDependency={setSelectedTaskId} onSaved={reloadGraph} /> : null}
            </div>
          ) : <section className="ws-card"><p className="ws-card__hint">当前 graph 没有任务。</p></section>}
        </>
      ) : null}
    </div>
  );
}
