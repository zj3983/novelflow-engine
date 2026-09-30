import { expect, type Page, type Route } from "@playwright/test";
import type { BuildProduct, ProductAction, ProductStatus, WriteProduct } from "../../app/projects/[id]/build/product-api";
export const projectId = "file:author-product-fixture";
export const encodedId = encodeURIComponent(projectId);
export const projectPath = `/projects/${encodedId}`;
export const prefix = `/file-projects/${encodedId}/product/`;
export const opaque = (n: number) => n.toString(16).padStart(64, "a");
export const status = (label = "准备中", message = "完成故事准备后，即可开始创作。", tone: ProductStatus["tone"] = "neutral"): ProductStatus => ({ label, message, tone });
export const action = (label: string, n: number, enabled = true): ProductAction => ({ label, token: opaque(n), enabled });
export function buildView(): BuildProduct { return {
  title: "准备故事", subtitle: "从故事想法走向章节。", status: status(),
  progress: { completed: 1, total: 2, label: "已完成 1 项，共 2 项" },
  parts: [{ selection: opaque(10), title: "世界设定", status: status("需要修改", "上游设定已修改，需要重新生成这一部分。", "warning") }],
  selected: { selection: opaque(10), title: "世界设定", paragraphs: ["城镇的集市每逢雨天关闭。"], issues: [], actions: [action("让 AI 修复", 11), action("重新生成这一部分", 12)],
    form: { title: "我来修改", fields: [{ key: opaque(13), label: "世界规则", type: "textarea", value: "每逢雨天关闭集市。" }], actions: [action("检查修改", 14), action("保存修改", 15)] } },
  actions: [action("继续准备故事", 1)],
}; }
export function writeView(number = 1): WriteProduct { return {
  title: `章节：第 ${number} 章`, subtitle: "灰狼坡", status: status("已确认", "可以继续生成下一章候选。", "success"),
  steps: [{ label: "生成候选", current: false }, { label: "审查", current: false }, { label: "人工确认", current: false }, { label: "继续写作", current: true }],
  chapters: [1, 2].map((n) => ({ number: n, title: `第${n}章标题`, summary: `第${n}章摘要` })),
  chapter: { number, title: `第${number}章标题`, body: `第 ${number} 章正文，只属于当前选择。`, summary: "林照找到一枚旧铜牌。" },
  actions: [action("生成下一章", 20), action("扩写本章", 21), action("重新生成本章", 22)],
}; }
export function candidate(number = 1, blocked = false): NonNullable<WriteProduct["candidate"]> { return {
  number, title: "雨夜遗嘱", body: `第 ${number} 章候选正文。\n\n律师仔细核对遗嘱。`,
  review: blocked ? status("需要修改", "遗嘱日期与已确认时间线冲突。", "danger") : status("待确认", "请阅读正文并人工确认。"),
  issues: blocked ? [{ message: "遗嘱日期与已确认时间线冲突。", suggestion: "修正时间后再提交。", tone: "danger" }] : [],
  actions: [action("丢弃候选稿", 30), action("确认提交", 31)],
}; }
export async function fulfill(route: Route, body: unknown, code = 200) { await route.fulfill({ status: code, contentType: "application/json", body: JSON.stringify(body) }); }
export async function productRoutes(page: Page, handlers: { build?: (selection: string | null) => BuildProduct | Promise<BuildProduct>; write?: (chapter: number | undefined) => WriteProduct | Promise<WriteProduct>; post?: (body: { token: string; values?: Record<string, string> }, route: Route) => Promise<void> }) {
  const requests: Array<{ path: string; body?: unknown }> = [];
  const forbidden: string[] = [];
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith(prefix)) { forbidden.push(url.pathname); await route.abort(); return; }
    requests.push({ path: url.pathname + url.search, body: route.request().method() === "POST" ? route.request().postDataJSON() : undefined });
    if (url.pathname.endsWith("/actions") && handlers.post) { await handlers.post(route.request().postDataJSON(), route); return; }
    if (url.pathname.endsWith("/build") && handlers.build) { await fulfill(route, await handlers.build(url.searchParams.get("selection"))); return; }
    if (url.pathname.endsWith("/write") && handlers.write) { await fulfill(route, await handlers.write(Number(url.searchParams.get("chapter")) || undefined)); return; }
    await fulfill(route, { detail: { message: "这项内容暂时不可用。" } }, 404);
  });
  return { requests, forbidden };
}
export async function expectAuthorBoundary(page: Page, forbidden: string[]) {
  expect(forbidden).toEqual([]);
  await expect(page.locator("main")).not.toContainText(/Build Graph|artifact|revision|diagnostics|preflight|Canon|validation_failed|review_required|stale|raw JSON|原始详情|任务契约|模型状态/i);
}
