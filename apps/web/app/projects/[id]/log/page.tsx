"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { WritingFlowPanel } from "../../../../components/ws/WritingFlow";
import {
  fetchGenerationJob,
  fetchGenerationJobHistory,
  type GenerationJobResponse,
  type GenerationJobSummary,
} from "../../../../lib/api";

function jobStatusLabel(status: GenerationJobSummary["status"]): string {
  if (status === "completed") return "完成";
  if (status === "failed") return "失败";
  if (status === "running") return "生成中";
  return "排队中";
}

function jobTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "时间未知" : parsed.toLocaleString("zh-CN", { hour12: false });
}

export default function GenerationLogPage() {
  const { project, error, encodedProjectId, projectId } = useProjectWorkspace();
  const [job, setJob] = useState<GenerationJobResponse | null>(null);
  const [history, setHistory] = useState<GenerationJobSummary[]>([]);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [loadError, setLoadError] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoaded(false);
    setLoadError("");
    setJob(null);
    setHistory([]);
    setSelectedJobId("");
    async function loadHistory() {
      try {
        const response = await fetchGenerationJobHistory(projectId);
        if (cancelled) return;
        setHistory(response.items);
        setSelectedJobId(response.items[0]?.job_id || "");
      } catch (reason) {
        if (cancelled) return;
        setLoadError(reason instanceof Error ? reason.message : "生成记录加载失败");
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }
    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!selectedJobId) return;
    let cancelled = false;
    let timer: number | undefined;
    async function pollSelected() {
      try {
        const selected = await fetchGenerationJob(projectId, selectedJobId);
        if (cancelled) return;
        setJob(selected);
        setLoadError("");
        setHistory((items) => items.map((item) => item.job_id === selected.job_id
          ? { ...item, status: selected.status, progress: selected.progress, error: selected.error, updated_at: selected.updated_at }
          : item));
        if (selected.status === "queued" || selected.status === "running") {
          timer = window.setTimeout(() => void pollSelected(), 2000);
        }
      } catch (reason) {
        if (!cancelled) setLoadError(reason instanceof Error ? reason.message : "生成记录加载失败");
      }
    }
    void pollSelected();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [projectId, selectedJobId]);

  const steps = Array.isArray(job?.steps) ? job.steps : [];
  const running = job?.status === "queued" || job?.status === "running";

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "项目", href: `/projects/${encodedProjectId}` },
        ]}
        title="生成日志"
        subtitle={running ? "生成进行中，页面每 2 秒自动刷新。" : "最近一次生成任务的完整写作流程。"}
      />
      {error ? <p className="ws-error">{error}</p> : null}
      {loadError ? <p className="ws-error">生成记录加载失败：{loadError}</p> : null}
      {job?.status === "failed" && job.error ? <p className="ws-error">任务失败：{job.error}</p> : null}
      {history.length > 0 ? (
        <section className="ws-card">
          <h2 className="ws-card__title">历史任务</h2>
          <div className="ws-chapter-list ws-generation-history" aria-label="生成任务历史">
            {history.map((item) => (
              <button
                type="button"
                key={item.job_id}
                className={`ws-chapter-list__item${item.job_id === selectedJobId ? " ws-chapter-list__item--active" : ""}`}
                onClick={() => setSelectedJobId(item.job_id)}
              >
                <strong>第 {item.chapter_number ?? "?"} 章 · {jobStatusLabel(item.status)}</strong>
                <span>{item.progress || "暂无进度"}</span>
                <small>{jobTime(item.updated_at)}</small>
              </button>
            ))}
          </div>
        </section>
      ) : null}
      {loaded && history.length === 0 ? (
        <section className="ws-card">
          <p className="ws-card__hint">还没有生成记录。从章节页发起一次生成后，这里会显示完整写作流程。</p>
        </section>
      ) : null}
      {steps.length > 0 ? <WritingFlowPanel steps={steps} status={job?.progress} /> : null}
    </div>
  );
}
