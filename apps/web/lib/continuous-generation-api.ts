import { fetchJson, fetchOptionalJson, fileProjectPath, isFileProjectId } from "./api-client";
import type { ContinuousGenerationJobResponse } from "./api";

const CONTINUOUS_GENERATION_TIMEOUT_MS = 90_000;

export async function startContinuousGeneration(
  projectId: string,
  count: 2 | 5 | 10 | 20,
): Promise<ContinuousGenerationJobResponse> {
  if (!isFileProjectId(projectId)) throw new Error("continuous_generation_only_supports_file_projects");
  return await fetchJson(
    `${fileProjectPath(projectId)}/continuous-generation-jobs`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ count }),
    },
    CONTINUOUS_GENERATION_TIMEOUT_MS,
  );
}

export async function fetchCurrentContinuousGeneration(
  projectId: string,
): Promise<ContinuousGenerationJobResponse | null> {
  if (!isFileProjectId(projectId)) return null;
  try {
    return await fetchOptionalJson(
      `${fileProjectPath(projectId)}/continuous-generation-jobs/current`,
      { method: "GET" },
      CONTINUOUS_GENERATION_TIMEOUT_MS,
    );
  } catch {
    return null;
  }
}

export async function fetchContinuousGenerationJob(
  projectId: string,
  jobId: string,
): Promise<ContinuousGenerationJobResponse> {
  if (!isFileProjectId(projectId)) throw new Error("continuous_generation_only_supports_file_projects");
  return await fetchJson(
    `${fileProjectPath(projectId)}/continuous-generation-jobs/${encodeURIComponent(jobId)}`,
    { method: "GET" },
    CONTINUOUS_GENERATION_TIMEOUT_MS,
  );
}

export async function stopContinuousGeneration(
  projectId: string,
  jobId: string,
): Promise<ContinuousGenerationJobResponse> {
  if (!isFileProjectId(projectId)) throw new Error("continuous_generation_only_supports_file_projects");
  return await fetchJson(
    `${fileProjectPath(projectId)}/continuous-generation-jobs/${encodeURIComponent(jobId)}/stop`,
    { method: "POST" },
    CONTINUOUS_GENERATION_TIMEOUT_MS,
  );
}

export async function continueContinuousGeneration(
  projectId: string,
  jobId: string,
): Promise<ContinuousGenerationJobResponse> {
  if (!isFileProjectId(projectId)) throw new Error("continuous_generation_only_supports_file_projects");
  return await fetchJson(
    `${fileProjectPath(projectId)}/continuous-generation-jobs/${encodeURIComponent(jobId)}/continue`,
    { method: "POST" },
    CONTINUOUS_GENERATION_TIMEOUT_MS,
  );
}

export async function replanContinuousGeneration(
  projectId: string,
  jobId: string,
): Promise<ContinuousGenerationJobResponse> {
  if (!isFileProjectId(projectId)) throw new Error("continuous_generation_only_supports_file_projects");
  return await fetchJson(
    `${fileProjectPath(projectId)}/continuous-generation-jobs/${encodeURIComponent(jobId)}/replan-consistency`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ request_replan: true }),
    },
    900000,
  );
}

export async function cancelContinuousGeneration(
  projectId: string,
  jobId: string,
): Promise<ContinuousGenerationJobResponse> {
  if (!isFileProjectId(projectId)) throw new Error("continuous_generation_only_supports_file_projects");
  return await fetchJson(
    `${fileProjectPath(projectId)}/continuous-generation-jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
    CONTINUOUS_GENERATION_TIMEOUT_MS,
  );
}
