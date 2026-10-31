import { fetchJson, fileProjectPath, isFileProjectId } from "./api-client";
import type {
  ForeshadowingEntry,
  ForeshadowingResponse,
  GeneratedOutlinePlanResponse,
  OutlineExtensionReadinessResponse,
  OutlineGenerationCheckpointResponse,
  OutlineGenerationMode,
  OutlineGenerationPhaseId,
  ProjectOutline,
  ProjectOutlineUpdate,
  RollingOutline,
  RollingOutlineChapter,
  VolumeDesignResponse,
  VolumeDetailGenerationResponse,
  VolumeWorkflowResponse,
} from "./api";

const OUTLINE_GENERATION_TIMEOUT_MS = 420_000;
const VOLUME_DETAIL_TIMEOUT_MS = 1_800_000;

export type EndingPlanningJob = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: string;
  error: string;
  result: { base_chapter: number; chapter_range: [number, number]; chapter_count: number } | null;
};

export type EndingAuditItem = {
  id: string; kind: "mainline" | "foreshadowing" | "chapter";
  title: string; context: string; disposition: "pending" | "resolved" | "retained" | "expired";
  chapter: number | null; note: string;
};
export type EndingAudit = { items: EndingAuditItem[]; version: string; current_chapter: number; pending_count: number };
export async function fetchEndingAudit(projectId: string): Promise<EndingAudit> {
  return await fetchJson(`${fileProjectPath(projectId)}/outline/ending-audit`, { method: "GET" });
}
export async function saveEndingAuditItem(projectId: string, item: EndingAuditItem, baseVersion: string): Promise<EndingAudit> {
  return await fetchJson(`${fileProjectPath(projectId)}/outline/ending-audit`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ item, base_version: baseVersion }) });
}

export async function fetchEndingPlan(projectId: string): Promise<{ job: EndingPlanningJob | null }> {
  return await fetchJson(`${fileProjectPath(projectId)}/outline/ending-plan`, { method: "GET" });
}

export async function startEndingPlan(projectId: string, outline: ProjectOutline, guidance = ""): Promise<EndingPlanningJob> {
  const { source: _source, ...payload } = outline;
  return await fetchJson(`${fileProjectPath(projectId)}/outline/ending-plan`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ outline: payload, guidance }),
  });
}

function requireFileProject(projectId: string, message: string): void {
  if (!isFileProjectId(projectId)) throw new Error(message);
}

export async function fetchProjectOutline(projectId: string): Promise<ProjectOutline> {
  requireFileProject(projectId, "three_level_outline_requires_file_project");
  return await fetchJson(`${fileProjectPath(projectId)}/outline`, { method: "GET" });
}

export async function fetchProjectRollingOutline(projectId: string): Promise<RollingOutline> {
  requireFileProject(projectId, "rolling_outline_requires_file_project");
  return await fetchJson(`${fileProjectPath(projectId)}/outline/rolling`, { method: "GET" });
}

export async function saveSceneOutline(projectId: string, chapter: RollingOutlineChapter): Promise<RollingOutlineChapter> {
  const fields = Object.fromEntries(["chapter_number", "title", "chapter_goal", "core_conflict", "cast", "scenes", "gain", "cost", "foreshadowing", "hook", "state_delta"].map(key => [key, chapter[key as keyof RollingOutlineChapter]]));
  const response = await fetchJson<{ chapter: RollingOutlineChapter }>(
    `${fileProjectPath(projectId)}/outline/rolling-chapter/${chapter.chapter_number}`,
    { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...fields, base_version: chapter.edit_version }) },
  );
  return response.chapter;
}

export async function fetchVolumeWorkflow(
  projectId: string,
  targetChapter: number,
): Promise<VolumeWorkflowResponse> {
  requireFileProject(projectId, "volume_workflow_requires_file_project");
  return await fetchJson(
    `${fileProjectPath(projectId)}/outline/volume-workflow?target_chapter=${encodeURIComponent(String(targetChapter))}`,
    { method: "GET" },
  );
}

export async function designNextVolume(projectId: string, guidance = ""): Promise<VolumeDesignResponse> {
  requireFileProject(projectId, "volume_workflow_requires_file_project");
  return await fetchJson(
    `${fileProjectPath(projectId)}/outline/volumes/next`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ guidance }),
    },
    OUTLINE_GENERATION_TIMEOUT_MS,
  );
}

export async function generateVolumeDetail(
  projectId: string,
  volumeId: string,
  guidance = "",
): Promise<VolumeDetailGenerationResponse> {
  requireFileProject(projectId, "volume_workflow_requires_file_project");
  return await fetchJson(
    `${fileProjectPath(projectId)}/outline/volumes/${encodeURIComponent(volumeId)}/detail`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ guidance }),
    },
    VOLUME_DETAIL_TIMEOUT_MS,
  );
}

export async function updateProjectOutline(
  projectId: string,
  payload: ProjectOutlineUpdate,
): Promise<ProjectOutline> {
  requireFileProject(projectId, "three_level_outline_requires_file_project");
  return await fetchJson(`${fileProjectPath(projectId)}/outline`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function fetchProjectForeshadowing(projectId: string): Promise<ForeshadowingResponse> {
  return await fetchJson(`${fileProjectPath(projectId)}/foreshadowing`, { method: "GET" });
}

export async function updateProjectForeshadowing(
  projectId: string,
  items: ForeshadowingEntry[],
  baseVersion: string,
): Promise<ForeshadowingResponse> {
  return await fetchJson(`${fileProjectPath(projectId)}/foreshadowing`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ items, base_version: baseVersion }),
  });
}

export async function generateProjectOutline(
  projectId: string,
  mode: OutlineGenerationMode,
  guidance = "",
  restartFrom?: OutlineGenerationPhaseId,
): Promise<GeneratedOutlinePlanResponse> {
  requireFileProject(projectId, "只有文件项目支持生成大纲");
  return await fetchJson(
    `${fileProjectPath(projectId)}/outline/generate`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode, guidance, ...(restartFrom ? { restart_from: restartFrom } : {}) }),
    },
    OUTLINE_GENERATION_TIMEOUT_MS,
  );
}

export async function fetchOutlineExtensionReadiness(
  projectId: string,
): Promise<OutlineExtensionReadinessResponse> {
  requireFileProject(projectId, "只有文件项目支持后续细纲体检");
  return await fetchJson(
    `${fileProjectPath(projectId)}/outline/extension-readiness`,
    { method: "GET" },
  );
}

export async function fetchOutlineGenerationCheckpoints(
  projectId: string,
): Promise<OutlineGenerationCheckpointResponse> {
  return await fetchJson(
    `${fileProjectPath(projectId)}/outline/generation-checkpoints`,
    { method: "GET" },
  );
}
