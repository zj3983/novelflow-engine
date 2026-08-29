"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  designNextVolume,
  fetchProjectOutline,
  fetchProjectRollingOutline,
  fetchVolumeWorkflow,
  generateVolumeDetail,
  type ProjectOutline,
  type RollingOutline,
  type RollingOutlineChapter,
  type VolumeWorkflowResponse,
} from "../../lib/api";
import { userFacingErrorMessage } from "../../lib/user-facing-error";

type VolumeOutlineWorkflowProps = {
  projectId: string;
  encodedProjectId: string;
  nextChapter: number;
  reason: string | null;
  outline: ProjectOutline;
  rollingChapters: RollingOutlineChapter[];
  guidance: string;
  onGuidanceConsumed: () => void;
  onMessage: (message: string) => void;
  onTabChange: (tab: "arcs" | "chapters") => void;
  onWorkspaceRefresh: (outline: ProjectOutline, rollingOutline: RollingOutline) => void;
};

const EMPTY_ROLLING_OUTLINE: RollingOutline = {
  schema_version: "rolling-outline/v1",
  chapters: [],
};

export function VolumeOutlineWorkflow({
  projectId,
  encodedProjectId,
  nextChapter,
  reason,
  outline,
  rollingChapters,
  guidance,
  onGuidanceConsumed,
  onMessage,
  onTabChange,
  onWorkspaceRefresh,
}: VolumeOutlineWorkflowProps) {
  const [workflow, setWorkflow] = useState<VolumeWorkflowResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setWorkflow(null);
    setError("");
    fetchVolumeWorkflow(projectId, nextChapter)
      .then((response) => {
        if (!cancelled) setWorkflow(response);
      })
      .catch((caught) => {
        if (!cancelled) setError(userFacingErrorMessage(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [nextChapter, projectId]);

  const volume = workflow?.volume_id
    ? outline.arcs.find((arc) => arc.id === workflow.volume_id) ?? null
    : null;
  const progress = useMemo(() => {
    const range = workflow?.volume_range;
    if (!range) return { completed: 0, total: 0 };
    const [start, end] = range;
    const detailed = new Set<number>();
    for (const chapter of outline.chapters) {
      if (start <= chapter.chapter_number && chapter.chapter_number <= end) {
        detailed.add(chapter.chapter_number);
      }
    }
    for (const chapter of rollingChapters) {
      if (start <= chapter.chapter_number && chapter.chapter_number <= end) {
        detailed.add(chapter.chapter_number);
      }
    }
    return { completed: detailed.size, total: end - start + 1 };
  }, [outline.chapters, rollingChapters, workflow?.volume_range]);

  async function refreshWorkspace() {
    const [latestOutline, latestRollingOutline, latestWorkflow] = await Promise.all([
      fetchProjectOutline(projectId),
      fetchProjectRollingOutline(projectId).catch(() => EMPTY_ROLLING_OUTLINE),
      fetchVolumeWorkflow(projectId, nextChapter),
    ]);
    onWorkspaceRefresh(latestOutline, latestRollingOutline);
    setWorkflow(latestWorkflow);
  }

  async function runAction(action: "design" | "detail") {
    if (action === "detail" && !workflow?.volume_id) return;
    setBusy(true);
    setError("");
    onMessage("");
    try {
      if (action === "design") {
        await designNextVolume(projectId, guidance.trim());
      } else {
        await generateVolumeDetail(projectId, workflow!.volume_id!, guidance.trim());
      }
      await refreshWorkspace();
      onGuidanceConsumed();
      if (action === "design") {
        onMessage("下一卷已经设计完成，请继续生成这一整卷的章节细纲。");
        onTabChange("arcs");
      } else {
        onMessage("本卷章节细纲已经补全，可以开始生成正文。");
        onTabChange("chapters");
      }
    } catch (caught) {
      setError(userFacingErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {workflow ? (
        <section className="ws-outline-generation-progress" aria-label="当前卷写作流程">
          <strong>{volume?.title || (workflow.volume_range ? "当前卷" : "下一卷")}</strong>
          {workflow.volume_range ? (
            <p>
              第 {workflow.volume_range[0]}-{workflow.volume_range[1]} 章，
              章节细纲已完成 {progress.completed}/{progress.total} 章。
            </p>
          ) : (
            <p>上一卷已经写完，需要先设计下一卷，再生成整卷章节细纲。</p>
          )}
          {reason === "volume_missing" ? (
            <p>你刚才要生成第 {nextChapter} 章，但这一章还没有所属的新卷。</p>
          ) : reason === "volume_detail_required" ? (
            <p>你刚才要生成第 {nextChapter} 章，但这一卷的章节细纲还没有全部完成。</p>
          ) : null}
          <div className="ws-outline-generation__actions">
            {workflow.status === "volume_missing" ? (
              <button className="ws-btn ws-btn--primary" type="button" disabled={busy} onClick={() => void runAction("design")}>
                {busy ? "设计中..." : "设计下一卷"}
              </button>
            ) : workflow.status === "volume_plan_ready" || workflow.status === "detail_partial" ? (
              <button
                className="ws-btn ws-btn--primary"
                type="button"
                disabled={busy || !workflow.volume_id}
                onClick={() => void runAction("detail")}
              >
                {busy ? "生成中..." : workflow.status === "detail_partial" ? "继续生成本卷细纲" : "生成本卷完整细纲"}
              </button>
            ) : (
              <Link className="ws-btn ws-btn--primary" href={`/projects/${encodedProjectId}/write?chapter=${nextChapter}`}>
                开始写第 {nextChapter} 章
              </Link>
            )}
          </div>
        </section>
      ) : null}
      {error ? <p className="ws-error">卷纲流程加载失败：{userFacingErrorMessage(error)}</p> : null}
    </>
  );
}
