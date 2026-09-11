"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  fetchContinuousGenerationJob,
  fetchCurrentContinuousGeneration,
  cancelContinuousGeneration,
  continueContinuousGeneration,
  startContinuousGeneration,
  stopContinuousGeneration,
  type ContinuousGenerationJobResponse,
  type VolumeWorkflowResponse,
} from "../../lib/api";

export type ContinuousCount = 2 | 5 | 10 | 20;
type ContinuousAction = "start" | "stop" | "continue" | "cancel" | null;

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
  const awaitingConsistency = job?.status === "awaiting_consistency_override";
  const active = job?.status === "queued"
    || job?.status === "running"
    || job?.status === "stopping"
    || awaitingConsistency;

  useEffect(() => {
    let cancelled = false;
    if (!enabled || !projectId) {
      setJob(null);
      return;
    }
    fetchCurrentContinuousGeneration(projectId)
      .then((current) => {
        if (cancelled) return;
        setJob(current);
        if (!current) return;
        const lastChapter = current.completed_chapters.at(-1);
        if (current.status === "completed" && lastChapter) {
          router.replace(`/projects/${encodedProjectId}/write?chapter=${lastChapter}`);
        } else if (current.status === "stopped") {
          openStoppedJobDestination(current);
        }
      })
      .catch(() => {
        if (!cancelled) setJob(null);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, projectId]);

  useEffect(() => {
    if (!enabled || !projectId || !job?.job_id || !active || awaitingConsistency) return;
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
          } else if (current.status === "stopped") {
            openStoppedJobDestination(current);
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
  }, [active, awaitingConsistency, encodedProjectId, enabled, job?.job_id, projectId, refresh, router]);

  function openRequiredOutline() {
    const needsVolume = volumeWorkflowStatus === "volume_missing";
    router.push(
      `/projects/${encodedProjectId}/outline?tab=${needsVolume ? "arcs" : "chapters"}&chapter=${nextChapterNumber}&reason=${needsVolume ? "volume_missing" : "volume_detail_required"}`,
    );
  }

  function openStoppedJobDestination(current: ContinuousGenerationJobResponse) {
    if (current.stop_reason === "next_volume_required") {
      router.replace(
        `/projects/${encodedProjectId}/outline?tab=arcs&chapter=${current.current_chapter}&reason=volume_missing`,
      );
      return;
    }
    if (current.stop_reason === "volume_detail_required") {
      router.replace(
        `/projects/${encodedProjectId}/outline?tab=chapters&chapter=${current.current_chapter}&reason=volume_detail_required`,
      );
      return;
    }
    if (current.stop_reason === "candidate_confirmation_required" && current.current_chapter > 0) {
      router.replace(`/projects/${encodedProjectId}/write?chapter=${current.current_chapter}`);
    }
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
    if (!job?.job_id || !active || awaitingConsistency || action) return;
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

  async function continueGeneration() {
    if (!job?.job_id || !awaitingConsistency || action) return;
    setAction("continue");
    setError("");
    try {
      setJob(await continueContinuousGeneration(projectId, job.job_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setAction(null);
    }
  }

  async function cancel() {
    if (!job?.job_id || !awaitingConsistency || action) return null;
    setAction("cancel");
    setError("");
    try {
      const cancelled = await cancelContinuousGeneration(projectId, job.job_id);
      setJob(cancelled);
      return cancelled;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return null;
    } finally {
      setAction(null);
    }
  }

  async function returnToEdit() {
    const targetChapter = job?.consistency_gate?.target_chapter || nextChapterNumber;
    const cancelled = await cancel();
    if (!cancelled) return;
    router.push(
      `/projects/${encodedProjectId}/outline?tab=chapters&chapter=${targetChapter}&reason=consistency_required`,
    );
  }

  return {
    action,
    active,
    awaitingConsistency,
    count,
    error,
    job,
    continueGeneration,
    cancel,
    returnToEdit,
    setCount,
    start,
    stop,
  };
}
