export function safeDecodeURIComponent(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export function projectHref(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}`;
}
