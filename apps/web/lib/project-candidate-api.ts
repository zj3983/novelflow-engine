import { fetchJson, fileProjectPath, isFileProjectId } from "./api-client";
import type {
  CandidateDraft,
  CandidateListResponse,
  ProjectResponse,
  StoryResponse,
} from "./api";

export async function fetchFileProjectCandidates(
  projectId: string,
  chapterNumber?: number,
): Promise<CandidateListResponse> {
  if (!isFileProjectId(projectId)) throw new Error("candidates_only_support_file_projects");
  const query = Number.isInteger(chapterNumber) ? `?chapter_number=${chapterNumber}` : "";
  return await fetchJson(`${fileProjectPath(projectId)}/candidates${query}`, { method: "GET" });
}

export async function discardFileProjectCandidate(
  projectId: string,
  candidateId: string,
): Promise<{ candidate: CandidateDraft }> {
  if (!isFileProjectId(projectId)) throw new Error("candidates_only_support_file_projects");
  return await fetchJson(
    `${fileProjectPath(projectId)}/candidates/${encodeURIComponent(candidateId)}/discard`,
    { method: "POST" },
  );
}

export async function confirmFileProjectCandidate(
  projectId: string,
  candidateId: string,
  force = false,
): Promise<{ candidate: CandidateDraft; project: ProjectResponse; story: StoryResponse }> {
  if (!isFileProjectId(projectId)) throw new Error("candidates_only_support_file_projects");
  const suffix = force ? "?force=true" : "";
  return await fetchJson(
    `${fileProjectPath(projectId)}/candidates/${encodeURIComponent(candidateId)}/confirm${suffix}`,
    { method: "POST" },
    900_000,
  );
}
