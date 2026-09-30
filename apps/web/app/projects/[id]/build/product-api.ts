export type ProductStatus = {
  label: string;
  tone: "neutral" | "success" | "warning" | "danger";
  message: string;
  impact?: string;
};
export type ProductAction = { token: string; label: string; enabled: boolean; reason?: string; href?: string };
export type ProductField = { key: string; label: string; value: string; type: "text" | "textarea" | "number"; required?: boolean };
export type ProductForm = { title: string; description?: string; fields: ProductField[]; actions: ProductAction[] };
export type ProductIssue = { message: string; suggestion?: string; tone: "warning" | "danger" };
export type ProductCommon = {
  title: string;
  subtitle: string;
  status: ProductStatus;
  actions: ProductAction[];
  forms?: ProductForm[];
  notices?: string[];
  refresh_after_ms?: number;
};
export type BuildProduct = ProductCommon & {
  progress: { completed: number; total: number; label: string };
  parts: Array<{ selection: string; title: string; status: ProductStatus }>;
  selected?: {
    selection: string;
    title: string;
    description?: string;
    paragraphs: string[];
    issues: ProductIssue[];
    actions: ProductAction[];
    form?: ProductForm;
  };
};
export type WriteProduct = ProductCommon & {
  steps: Array<{ label: string; current: boolean }>;
  chapters: Array<{ number: number; title: string; summary: string }>;
  chapter?: { number: number; title: string; body: string; summary?: string; notes?: string[] };
  candidate?: { number: number; title: string; body: string; review: ProductStatus; issues: ProductIssue[]; actions: ProductAction[]; form?: ProductForm };
};
export type ProductActionResult = { message?: string; redirect?: string };

export class ProductRequestError extends Error {
  constructor(message: string, public impact?: string) { super(message); }
}

function productUrl(projectId: string, screen: string): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
  return `${base}/file-projects/${encodeURIComponent(projectId)}/product/${screen}`;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(url, { cache: "no-store", ...init }); }
  catch { throw new ProductRequestError("暂时无法连接，请稍后重试。", "当前内容不会因此被修改。"); }
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    throw new ProductRequestError(
      typeof detail?.message === "string" ? detail.message : "这次操作未能完成，请刷新后重试。",
      typeof detail?.impact === "string" ? detail.impact : undefined,
    );
  }
  if (!payload) throw new ProductRequestError("暂时无法读取内容，请刷新后重试。");
  return payload as T;
}
export function getBuildProduct(projectId: string, selection?: string) {
  return request<BuildProduct>(productUrl(projectId, `build${selection ? `?selection=${encodeURIComponent(selection)}` : ""}`));
}
export function getWriteProduct(projectId: string, chapter?: number) {
  return request<WriteProduct>(productUrl(projectId, `write${chapter ? `?chapter=${chapter}` : ""}`));
}
export function performProductAction(projectId: string, token: string, values?: Record<string, string>) {
  return request<ProductActionResult>(productUrl(projectId, "actions"), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, ...(values ? { values } : {}) }),
  });
}
