export type StructuredErrorFactory = (detail: Record<string, unknown>) => Error | undefined;

export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
}

export function fileProjectPath(projectId: string): string {
  return `${apiBase()}/file-projects/${encodeURIComponent(projectId)}`;
}

export function fileStoryPath(storyId: string): string {
  return `${apiBase()}/file-stories/${encodeURIComponent(storyId)}`;
}

export function isFileProjectId(value: string): boolean {
  return value.startsWith("file:");
}

async function responseError(
  response: Response,
  url: string,
  structuredError?: StructuredErrorFactory,
): Promise<Error> {
  const detail = await response.text().catch(() => "");
  let message = detail ? `${url} failed: ${response.status} ${detail}` : `${url} failed: ${response.status}`;
  if (!detail) return new Error(message);

  let parsed: unknown;
  try {
    parsed = JSON.parse(detail);
  } catch {
    return new Error(message);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return new Error(message);

  const structuredDetail = (parsed as Record<string, unknown>).detail;
  if (structuredDetail && typeof structuredDetail === "object" && !Array.isArray(structuredDetail)) {
    const custom = structuredError?.(structuredDetail as Record<string, unknown>);
    if (custom) return custom;
  } else if (typeof structuredDetail === "string" && structuredDetail.trim()) {
    message = structuredDetail.trim();
  } else if (Array.isArray(structuredDetail)) {
    const issues = structuredDetail
      .map((issue) => {
        if (!issue || typeof issue !== "object" || Array.isArray(issue)) return "";
        const value = (issue as Record<string, unknown>).msg;
        return typeof value === "string" ? value.trim() : "";
      })
      .filter(Boolean);
    if (issues.length) message = issues.join("；");
  }
  return new Error(message);
}

async function requestWithTimeout<T>(
  url: string,
  init: RequestInit,
  readResponse: (response: Response) => Promise<T>,
  timeoutMs: number,
  structuredError?: StructuredErrorFactory,
  allowNotFound = false,
): Promise<T | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    if (allowNotFound && response.status === 404) return null;
    if (!response.ok) throw await responseError(response, url, structuredError);
    return await readResponse(response);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`${url} failed: request timed out (${Math.round(timeoutMs / 1000)}s)`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function fetchJson<T = unknown>(
  url: string,
  init: RequestInit,
  timeoutMs = 30_000,
  structuredError?: StructuredErrorFactory,
): Promise<T> {
  const result = await requestWithTimeout(
    url,
    init,
    async (response) => JSON.parse(await response.text()) as T,
    timeoutMs,
    structuredError,
  );
  return result as T;
}

export async function fetchOptionalJson<T = unknown>(
  url: string,
  init: RequestInit,
  timeoutMs = 30_000,
): Promise<T | null> {
  return await requestWithTimeout(
    url,
    init,
    async (response) => JSON.parse(await response.text()) as T,
    timeoutMs,
    undefined,
    true,
  );
}

export async function fetchVoid(
  url: string,
  init: RequestInit,
  timeoutMs = 30_000,
): Promise<void> {
  await requestWithTimeout(
    url,
    init,
    async () => undefined,
    timeoutMs,
  );
}
