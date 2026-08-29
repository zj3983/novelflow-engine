import { apiBase, fetchJson, fileProjectPath, isFileProjectId } from "./api-client";
import type {
  DeepPromptAuditResult,
  PromptAuditRequest,
  PromptAuditResult,
  PromptCallDetail,
  PromptCallListResponse,
  PromptContextResponse,
  PromptPreviewResponse,
  PromptTemplateEntry,
  PromptTemplatesResponse,
} from "./api";

export async function fetchProjectPromptPreview(
  projectId: string,
  chapterNumber?: number | null,
): Promise<PromptPreviewResponse> {
  const params = new URLSearchParams();
  if (chapterNumber != null) params.set("chapter_number", String(chapterNumber));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const path = isFileProjectId(projectId)
    ? `${fileProjectPath(projectId)}/prompt-preview${suffix}`
    : `${apiBase()}/projects/${encodeURIComponent(projectId)}/prompt-preview${suffix}`;
  return await fetchJson(path, { method: "GET" }, 120_000);
}

export async function fetchGlobalPromptTemplates(): Promise<PromptTemplatesResponse> {
  return await fetchJson(`${apiBase()}/prompt-templates`, { method: "GET" });
}

export async function auditPrompt(payload: PromptAuditRequest): Promise<PromptAuditResult> {
  return await fetchJson(`${apiBase()}/prompt-audit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deepAuditPrompt(
  payload: PromptAuditRequest,
  localResult: PromptAuditResult,
): Promise<DeepPromptAuditResult> {
  const sanitizedLocalResult: PromptAuditResult = {
    schema_version: localResult.schema_version,
    mode: localResult.mode,
    content_sha256: localResult.content_sha256,
    summary: localResult.summary,
    must_fix: localResult.must_fix,
    suggestions: localResult.suggestions,
    passed_checks: localResult.passed_checks,
  };
  return await fetchJson(
    `${apiBase()}/prompt-audit/deep`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, local_result: sanitizedLocalResult }),
    },
    360_000,
  );
}

export async function saveGlobalPromptTemplate(
  templateKey: string,
  content: string,
): Promise<PromptTemplateEntry> {
  return await fetchJson(`${apiBase()}/prompt-templates/${encodeURIComponent(templateKey)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export async function fetchProjectPromptTemplates(projectId: string): Promise<PromptTemplatesResponse> {
  return await fetchJson(`${fileProjectPath(projectId)}/prompt-templates`, { method: "GET" });
}

export async function saveProjectPromptTemplate(
  projectId: string,
  templateKey: string,
  content: string,
): Promise<PromptTemplateEntry> {
  return await fetchJson(`${fileProjectPath(projectId)}/prompt-templates/${encodeURIComponent(templateKey)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

export async function deleteProjectPromptTemplate(
  projectId: string,
  templateKey: string,
): Promise<PromptTemplateEntry> {
  return await fetchJson(`${fileProjectPath(projectId)}/prompt-templates/${encodeURIComponent(templateKey)}`, {
    method: "DELETE",
  });
}

export async function fetchProjectPromptContext(
  projectId: string,
  chapterNumber?: number | null,
): Promise<PromptContextResponse> {
  const params = new URLSearchParams();
  if (chapterNumber != null) params.set("chapter_number", String(chapterNumber));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return await fetchJson(`${fileProjectPath(projectId)}/prompt-context${suffix}`, { method: "GET" });
}

export async function fetchProjectPromptCalls(
  projectId: string,
  chapterNumber?: number | null,
): Promise<PromptCallListResponse> {
  const params = new URLSearchParams();
  if (chapterNumber != null) params.set("chapter_number", String(chapterNumber));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return await fetchJson(`${fileProjectPath(projectId)}/prompt-calls${suffix}`, { method: "GET" });
}

export async function fetchProjectPromptCall(
  projectId: string,
  callId: string,
): Promise<PromptCallDetail> {
  return await fetchJson(
    `${fileProjectPath(projectId)}/prompt-calls/${encodeURIComponent(callId)}`,
    { method: "GET" },
  );
}
