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
  VolumeDesignResponse,
  VolumeDetailGenerationResponse,
  VolumeWorkflowResponse,
} from "./api";

const OUTLINE_GENERATION_TIMEOUT_MS = 420_000;
const VOLUME_DETAIL_TIMEOUT_MS = 1_800_000;

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
