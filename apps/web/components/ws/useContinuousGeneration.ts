"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  fetchContinuousGenerationJob,
  fetchCurrentContinuousGeneration,
  startContinuousGeneration,
  stopContinuousGeneration,
  type ContinuousGenerationJobResponse,
  type VolumeWorkflowResponse,
} from "../../lib/api";

type ContinuousCount = 2 | 5 | 10 | 20;
type ContinuousAction = "start" | "stop" | null;

type UseContinuousGenerationOptions = {
  enabled: boolean;
  projectId: string;
  encodedProjectId: string;
  nextChapterNumber: number;
  nextChapterNeedsOutline: boolean;
  volumeWorkflowStatus?: VolumeWorkflowResponse["status"];
  busy: boolean;
  refresh: (options?: { invalidateChapter?: boolean }) => Promise<unknown>;
};

export function useContinuousGeneration({
  enabled,
  projectId,
  encodedProjectId,
  nextChapterNumber,
  nextChapterNeedsOutline,
  volumeWorkflowStatus,
  busy,
  refresh,
}: UseContinuousGenerationOptions) {
  const router = useRouter();
  const [count, setCount] = useState<ContinuousCount>(5);
  const [job, setJob] = useState<ContinuousGenerationJobResponse | null>(null);
  const [error, setError] = useState("");
  const [action, setAction] = useState<ContinuousAction>(null);
  const active = job?.status === "queued" || job?.status === "running" || job?.status === "stopping";

  useEffect(() => {
    let cancelled = false;
    if (!enabled || !projectId) {
      setJob(null);
      return;
    }
    fetchCurrentContinuousGeneration(projectId)
      .then((current) => {
        if (!cancelled) setJob(current);
      })
      .catch(() => {
        if (!cancelled) setJob(null);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, projectId]);

  useEffect(() => {
    if (!enabled || !projectId || !job?.job_id || !active) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      fetchContinuousGenerationJob(projectId, job.job_id)
        .then(async (current) => {
          if (cancelled) return;
          setJob(current);
          if (current.status !== "completed" && current.status !== "stopped" && current.status !== "failed") {
            return;
          }
          await refresh({ invalidateChapter: false });
          if (cancelled) return;
          const lastChapter = current.completed_chapters.at(-1);
          if (current.status === "completed" && lastChapter) {
            router.replace(`/projects/${encodedProjectId}/write?chapter=${lastChapter}`);
          }
        })
        .catch((reason) => {
          if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
        });
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [active, encodedProjectId, enabled, job?.job_id, projectId, refresh, router]);

  function openRequiredOutline() {
    const needsVolume = volumeWorkflowStatus === "volume_missing";
    router.push(
      `/projects/${encodedProjectId}/outline?tab=${needsVolume ? "arcs" : "chapters"}&chapter=${nextChapterNumber}&reason=${needsVolume ? "volume_missing" : "volume_detail_required"}`,
    );
  }

  async function start() {
    if (!enabled || busy || active || action) return;
    if (nextChapterNeedsOutline) {
      openRequiredOutline();
      return;
    }
    setAction("start");
    setError("");
    try {
      setJob(await startContinuousGeneration(projectId, count));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setAction(null);
    }
  }

  async function stop() {
    if (!job?.job_id || !active || action) return;
    setAction("stop");
    setError("");
    try {
      setJob(await stopContinuousGeneration(projectId, job.job_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setAction(null);
    }
  }

  return {
    action,
    active,
    count,
    error,
    job,
    setCount,
    start,
    stop,
  };
}
