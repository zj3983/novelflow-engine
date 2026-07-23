"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { WritingFlowPanel } from "../../../../components/ws/WritingFlow";
import { fetchCurrentGenerationJob, type GenerationJobResponse } from "../../../../lib/api";

export default function GenerationLogPage() {
  const { project, error, encodedProjectId, projectId } = useProjectWorkspace();
  const [job, setJob] = useState<GenerationJobResponse | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      const current = await fetchCurrentGenerationJob(projectId);
      if (cancelled) return;
      setJob(current);
      setLoaded(true);
      if (current && (current.status === "queued" || current.status === "running")) {
        timer = window.setTimeout(() => void poll(), 2000);
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [projectId]);

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
      {job?.status === "failed" && job.error ? <p className="ws-error">任务失败：{job.error}</p> : null}
      {loaded && !job ? (
        <section className="ws-card">
          <p className="ws-card__hint">还没有生成记录。从章节页发起一次生成后，这里会显示完整写作流程。</p>
        </section>
      ) : null}
      {steps.length > 0 ? <WritingFlowPanel steps={steps} status={job?.progress} /> : null}
    </div>
  );
}
