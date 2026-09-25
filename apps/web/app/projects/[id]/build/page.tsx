"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  BuildWorkbenchRepairError,
  BuildWorkbenchRerunError,
  commitBuildWorkbenchTaskEdit,
  fetchBuildOrchestration,
  fetchBuildWorkbench,
  fetchBuildWorkbenchTask,
  fetchCurrentBuildOrchestration,
  preflightBuildWorkbenchTask,
  repairBuildWorkbenchTask,
  rerunBuildWorkbenchTask,
  startBuildOrchestration,
  updateOpeningBuildGraph,
  extendOpeningVolume,
  extendOpeningNextVolume,
  validateBuildWorkbenchTask,
  type BuildOrchestrationJob,
  type BuildOrchestrationMode,
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

function PreflightPanel({ report }: { report?: Record<string, unknown> | null }) {
  if (!report) return null;
  const estimate = (report.estimates ?? {}) as Record<string, unknown>;
  return (
    <section className={styles.preflight_report} aria-label="模型预检结果">
      <strong>模型预检：{String(report.status ?? "unknown")} · {String(report.reason ?? "")}</strong>
      <p>
        {String(report.provider ?? "provider unknown")} / {String(report.protocol ?? "protocol unknown")} · requested {String(report.requested_model ?? "model unknown")}
        {report.resolved_model ? ` · resolved ${String(report.resolved_model)}` : ""}
      </p>
      <p>
        输入估算：必要 {String(estimate.required_input_tokens ?? "?")} + optional {String(estimate.optional_input_tokens ?? "?")} tokens；
        输出预留 {String(estimate.reserved_output_tokens ?? "?")}，安全余量 {String(estimate.safety_margin_tokens ?? "?")}。
        方法 {String(report.estimate_method ?? "unknown")}（估算值，不是精确 tokenizer 结果）。
      </p>
      <details>
        <summary>能力来源、限额和兼容策略</summary>
        <pre>{JSON.stringify({ capabilities: report.capabilities, limits: report.limits, guards: report.effective_preflight_guards, unknown_capability_policy: report.unknown_capability_policy, unknown_limit_policy: report.unknown_limit_policy, adjustments: report.adjustments, repair_actions: report.repair_actions }, null, 2)}</pre>
      </details>
    </section>
  );
}

function DiagnosticPreflight({ details }: { details?: Record<string, unknown> }) {
  const report = details?.preflight;
  return report && typeof report === "object" && !Array.isArray(report)
    ? <PreflightPanel report={report as Record<string, unknown>} />
    : null;
}

function TaskDetail({ task, graph, projectId, onSelectDependency, onSaved, onDraftChange, orchestrationBusy }: {
  task: BuildWorkbenchTask;
  graph: BuildWorkbenchGraph;
  projectId: string;
  onSelectDependency: (taskId: string) => void;
  onSaved: () => Promise<void>;
  onDraftChange: (open: boolean) => void;
  orchestrationBusy: boolean;
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
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightReport, setPreflightReport] = useState<Record<string, unknown> | null>(null);
  const [preflightError, setPreflightError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setDetail(null);
    setEditorOpen(false);
    onDraftChange(false);
    setValidation(null);
    setEditError(null);
    setRerunError(null);
    setRerunDiagnostics([]);
    setPreflightReport(null);
    setPreflightError(null);
    fetchBuildWorkbenchTask(projectId, task.task_id)
      .then((result) => {
        if (!active) return;
        setDetail(result);
        setDraft(JSON.stringify(result.artifact?.payload ?? {}, null, 2));
      })
      .catch((reason: unknown) => { if (active) setEditError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { active = false; };
  }, [projectId, task.task_id, task.artifact_revision, onDraftChange]);

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
      onDraftChange(false);
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

  const previewModelRequest = async (operation: "rerun" | "repair") => {
    if (!detail?.artifact) return;
    if (editorOpen) {
      setPreflightError("当前有未保存的 JSON 草稿。请先保存或取消草稿，再预检正式 artifact 对应的请求。");
      return;
    }
    setPreflightBusy(true);
    setPreflightError(null);
    try {
      const result = await preflightBuildWorkbenchTask(
        projectId,
        task.task_id,
        detail.artifact.revision,
        operation,
      );
      setPreflightReport(result.preflight_report);
    } catch (reason) {
      setPreflightReport(null);
      setPreflightError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setPreflightBusy(false);
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
      <PreflightPanel report={preflightReport ?? detail?.preflight_report ?? task.preflight_report} />

      {detail?.editable && !editorOpen ? <button type="button" className={styles.edit_button} onClick={() => {
        setDraft(JSON.stringify(detail.artifact?.payload ?? {}, null, 2));
        setValidation(null);
        setEditError(null);
        setEditorOpen(true);
        onDraftChange(true);
      }} disabled={orchestrationBusy}>人工编辑</button> : null}
      {detail?.editable ? <div className={styles.preflight_actions}>
        <button type="button" className={styles.edit_button} disabled={preflightBusy || repairBusy || rerunBusy || busy || orchestrationBusy} onClick={() => void previewModelRequest("repair")}>
          {preflightBusy ? "正在预检…" : "预检 AI 修复"}
        </button>
        <button type="button" className={styles.edit_button} disabled={preflightBusy || repairBusy || rerunBusy || busy || orchestrationBusy} onClick={() => void previewModelRequest("rerun")}>
          {preflightBusy ? "正在预检…" : "预检完整重跑"}
        </button>
      </div> : null}
      {preflightError ? <p className={styles.edit_error} role="alert">模型预检失败：{preflightError}</p> : null}
      {detail?.editable ? <p className={styles.empty_value}>预检只在本地解析配置和输入，不调用 provider；开始执行时会重新读取配置并重新计算。</p> : null}
      {detail?.editable ? <button type="button" className={styles.edit_button} disabled={repairBusy || rerunBusy || busy || orchestrationBusy} onClick={() => void repairArtifact()}>
        {repairBusy ? "AI 修复中…" : "AI 修复"}
      </button> : null}
      {detail?.editable ? <button type="button" className={styles.edit_button} disabled={repairBusy || rerunBusy || busy || orchestrationBusy} onClick={() => void rerunArtifact()}>
        {rerunBusy ? "完整重跑中…" : "完整重跑"}
      </button> : null}
      {detail?.editable ? <p className={styles.empty_value}>完整重生成此任务；成功后下游会标记为过期，不会自动重跑。</p> : null}
      {repairError ? <div className={styles.validation_fail} role="alert">
        <strong>{repairError}</strong>
        {repairDiagnostics.length ? <ul className={styles.diagnostics}>{repairDiagnostics.map((diagnostic, index) => (
          <li key={`${diagnostic.code}-${diagnostic.path}-${index}`}><strong>{diagnostic.code}</strong><code>{diagnostic.path || "（未提供路径）"}</code><p>{diagnostic.message}</p><DiagnosticPreflight details={diagnostic.details} /></li>
        ))}</ul> : null}
      </div> : null}
      {rerunError ? <div className={styles.validation_fail} role="alert">
        <strong>{rerunError}</strong>
        {rerunDiagnostics.length ? <ul className={styles.diagnostics}>{rerunDiagnostics.map((diagnostic, index) => (
          <li key={`${diagnostic.code}-${diagnostic.path}-${index}`}><strong>{diagnostic.code}</strong><code>{diagnostic.path || "（未提供路径）"}</code><p>{diagnostic.message}</p><DiagnosticPreflight details={diagnostic.details} /></li>
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
            <button type="button" disabled={busy} onClick={() => { setEditorOpen(false); onDraftChange(false); setValidation(null); setEditError(null); }}>取消</button>
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
                <DiagnosticPreflight details={diagnostic.details} />
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
  const [orchestration, setOrchestration] = useState<BuildOrchestrationJob | null>(null);
  const [orchestrationError, setOrchestrationError] = useState<string | null>(null);
  const [draftOpen, setDraftOpen] = useState(false);
  const [openingBusy, setOpeningBusy] = useState(false);

  const updateOpening = async (extendVolume = false) => {
    if (!graph || draftOpen || openingBusy) return;
    setOpeningBusy(true);
    setOrchestrationError(null);
    try {
      const result = extendVolume
        ? await extendOpeningVolume(projectId, graph.graph_revision)
        : await updateOpeningBuildGraph(projectId, graph.graph_revision, !!graph.opening_graph);
      setGraph(result);
      setSelectedTaskId(result.tasks[0]?.task_id ?? null);
      setDetailReload((current) => current + 1);
    } catch (reason) {
      setOrchestrationError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setOpeningBusy(false);
    }
  };

  const extendNextVolume = async () => {
    if (!graph || draftOpen || openingBusy) return;
    setOpeningBusy(true);
    setOrchestrationError(null);
    try {
      const result = await extendOpeningNextVolume(projectId, graph.graph_revision);
      setGraph(result);
      setSelectedTaskId(result.tasks.find((task) => task.status === "ready")?.task_id ?? selectedTaskId);
      setDetailReload((current) => current + 1);
    } catch (reason) {
      setOrchestrationError(reason instanceof Error ? reason.message : String(reason));
    } finally { setOpeningBusy(false); }
  };

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

  useEffect(() => {
    let active = true;
    fetchCurrentBuildOrchestration(projectId)
      .then((job) => { if (active) setOrchestration((current) =>
        current?.status === "queued" || current?.status === "running" ? current : job,
      ); })
      .catch((reason: unknown) => { if (active) setOrchestrationError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { active = false; };
  }, [projectId]);

  const orchestrationBusy = orchestration?.status === "queued" || orchestration?.status === "running";
  useEffect(() => {
    if (!orchestrationBusy || !orchestration) return;
    let active = true;
    let pending = false;
    const poll = async () => {
      if (pending) return;
      pending = true;
      try {
        const [job, latestGraph] = await Promise.all([
          fetchBuildOrchestration(projectId, orchestration.job_id), fetchBuildWorkbench(projectId),
        ]);
        if (!active) return;
        setOrchestration(job);
        setGraph(latestGraph);
        setDetailReload((current) => current + 1);
      } catch (reason) {
        if (active) setOrchestrationError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        pending = false;
      }
    };
    const timer = window.setInterval(() => { void poll(); }, 1000);
    void poll();
    return () => { active = false; window.clearInterval(timer); };
  }, [projectId, orchestration?.job_id, orchestrationBusy]);

  const runOrchestration = async (mode: BuildOrchestrationMode) => {
    if (draftOpen) {
      setOrchestrationError("当前有未保存的 JSON 草稿。请先保存或取消草稿，再继续构建。");
      return;
    }
    setOrchestrationError(null);
    try {
      setOrchestration(await startBuildOrchestration(projectId, mode));
    } catch (reason) {
      setOrchestrationError(reason instanceof Error ? reason.message : String(reason));
    }
  };

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

      {!loading && !error && graph ? <section className="ws-card" aria-label="完整开局构建">
        <h2 className={styles.empty_title}>{graph.opening_graph ? "完整开局图已启用" : "构建故事到章节的完整开局"}</h2>
        <p className="ws-card__hint">故事核心 → 角色与世界 → 关系 → 全书与分卷规划 → 事件链 → 前 3 章细纲与执行契约。</p>
        <p className="ws-card__hint">{graph.opening_graph ? "在其他页面修改作者输入后，先同步输入，再继续构建。同步会使依赖任务过期。" : "适用于尚未写正文的项目。启用会保留旧产物历史，并将已有世界任务标为待重建。"}</p>
        <button type="button" disabled={openingBusy || orchestrationBusy || draftOpen || graph.opening_execution_started} onClick={() => void updateOpening()}>
          {openingBusy ? "处理中…" : graph.opening_graph ? "同步作者输入" : "启用完整开局图"}
        </button>
        {graph.opening_graph ? <>
          <p className="ws-card__hint">细纲窗口：前 {graph.opening_chapter_count ?? 3} 章。正文逐章人工确认；下一卷需在卷末显式扩展并构建完整细纲。</p>
          <button type="button" disabled={openingBusy || orchestrationBusy || draftOpen || graph.opening_execution_started || graph.tasks.some((task) => task.status !== "completed")} onClick={() => void updateOpening(true)}>补齐首卷细纲任务</button>
          {graph.opening_next_volume_available ? <button type="button" disabled={openingBusy || orchestrationBusy || draftOpen} onClick={() => void extendNextVolume()}>扩展下一卷细纲任务</button> : null}
          {graph.opening_planning_pending ? <p role="status">下一卷规划扩展中。完成并发布全部细纲之前，正文候选入口保持关闭。</p> : null}
          {graph.opening_plan_versions?.length ? <p>规划版本：{graph.opening_plan_versions.map((item) => `v${item.version}（第 ${item.start_chapter}–${item.end_chapter} 章）`).join("、")}</p> : null}
          <a href={`/projects/${encodedProjectId}/write`}>前往正文候选与审查</a>
          {graph.opening_execution_started && !graph.opening_planning_pending ? <p>已确认正文与已消费规划保持锁定；可在卷末显式扩展未来细纲。</p> : null}
        </> : null}
        {orchestrationError && !graph.initialized ? <p role="alert">{orchestrationError}</p> : null}
      </section> : null}

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
            <div><span>物化状态</span><strong>{graph.materialization_status === "in_use" ? "已用于正文，规划已锁定" : graph.materialization_status === "outdated" ? "旧物化结果已过期" : graph.materialization_status === "current" ? "当前" : "未物化"}</strong></div>
          </section>

          <section className={`ws-card ${styles.orchestration}`} aria-label="构建操作">
            <div className={styles.orchestration_actions}>
              <button type="button" disabled={orchestrationBusy || openingBusy || (graph.opening_execution_started && !graph.opening_planning_pending)} onClick={() => void runOrchestration("continue")}>继续构建</button>
              <button type="button" disabled={orchestrationBusy || openingBusy || (graph.opening_execution_started && !graph.opening_planning_pending) || !graph.tasks.some((task) => task.status === "stale")} onClick={() => void runOrchestration("rebuild_stale")}>重建过期项</button>
              <button type="button" disabled={orchestrationBusy || openingBusy || (graph.opening_execution_started && !graph.opening_planning_pending)} onClick={() => void runOrchestration("next")}>运行下一任务</button>
            </div>
            {orchestrationError ? <p role="alert" className={styles.edit_error}>{orchestrationError}</p> : null}
            {orchestration ? <div className={styles.orchestration_progress} aria-live="polite">
              <strong>{orchestration.status === "completed" ? "本次构建已结束" : orchestration.status === "running" || orchestration.status === "queued" ? "正在构建" : "构建已停止"}</strong>
              {orchestration.current_task_id ? <p>当前任务：{orchestration.current_task_title || orchestration.current_task_id}</p> : null}
              <p>已完成任务：{orchestration.completed_task_ids.length ? orchestration.completed_task_ids.map((id) => graph.tasks.find((task) => task.task_id === id)?.title || id).join("、") : "暂无"}</p>
              {orchestration.failure_task_id ? <p>失败任务：{graph.tasks.find((task) => task.task_id === orchestration.failure_task_id)?.title || orchestration.failure_task_id} · {orchestration.error_code}</p> : null}
              {orchestration.next_task_id && orchestration.status === "completed" ? <p>下一任务：{graph.tasks.find((task) => task.task_id === orchestration.next_task_id)?.title || orchestration.next_task_id}</p> : null}
              {orchestration.materialized ? <p>{graph.opening_graph ? `全部任务已就绪，世界、角色和前 ${graph.opening_chapter_count ?? 3} 章细纲已发布。` : "全部任务已就绪，世界设定已重新物化。"}</p> : null}
              {orchestration.diagnostics?.length ? <ul className={styles.diagnostics}>{orchestration.diagnostics.map((diagnostic, index) => (
                <li key={`${diagnostic.code}-${diagnostic.path}-${index}`}><strong>{diagnostic.code}</strong><code>{diagnostic.path || "（未提供路径）"}</code><p>{diagnostic.message}</p></li>
              ))}</ul> : null}
            </div> : null}
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
                        onClick={() => { if (!draftOpen) setSelectedTaskId(task.task_id); else setOrchestrationError("请先保存或取消当前 JSON 草稿。"); }}
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

              {selectedTask ? <TaskDetail key={`${selectedTask.task_id}-${detailReload}`} task={selectedTask} graph={graph} projectId={projectId} onSelectDependency={(id) => { if (!draftOpen) setSelectedTaskId(id); }} onSaved={reloadGraph} onDraftChange={setDraftOpen} orchestrationBusy={orchestrationBusy} /> : null}
            </div>
          ) : <section className="ws-card"><p className="ws-card__hint">当前 graph 没有任务。</p></section>}
        </>
      ) : null}
    </div>
  );
}
