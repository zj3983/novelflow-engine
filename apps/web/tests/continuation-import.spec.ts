import { expect, test, type Page, type Route } from "@playwright/test";

const chapters = [
  { chapter_id: "chapter-1", number: 1, title: "雨夜入城", body: "沈砚在雨夜进入临川城。", source_name: "novel.txt", source_start: 0, source_end: 12, fingerprint: "fp-1" },
  { chapter_id: "chapter-2", number: 2, title: "旧友来信", body: "旧友来信，提到城北的失踪案。", source_name: "novel.txt", source_start: 13, source_end: 30, fingerprint: "fp-2" },
];
const continuationApi = /^http:\/\/127\.0\.0\.1:8000\/continuation-imports(?:\/.*)?$/;

const scanResult = {
  source_path: "D:\\novels\\novel.txt",
  source_kind: "file",
  encoding: "utf-8",
  chapters,
  total_chars: 28,
  warnings: [],
  duplicate_groups: [],
  numbering_gaps: [],
  can_analyze: true,
};

const analysis = {
  story_overview: "沈砚进入临川调查旧案。",
  characters: [{ name: "沈砚", role: "主角", summary: "谨慎的调查者", confidence: "inferred", evidence: [{ chapter_id: "chapter-1", excerpt_start: 0, excerpt_end: 2, quote: "沈砚" }], states: [], relationships: [] }],
  world: [{ claim: "临川城正值雨季", confidence: "confirmed", evidence: [{ chapter_id: "chapter-1", excerpt_start: 3, excerpt_end: 5, quote: "雨夜" }] }],
  power_system: [{ claim: "线索需要逐层验证", confidence: "inferred", evidence: [] }],
  timeline: [{ text: "沈砚入城", sequence: "第一章", confidence: "confirmed", evidence: [] }],
  open_hooks: [{ text: "城北失踪案", status: "open", confidence: "confirmed", evidence: [] }],
  style_profile: { narrative_voice: "克制", point_of_view: "第三人称限知", tense: "过去时", pacing: "紧凑", dialogue_style: "简短", prose_features: ["环境推进"], confidence: "inferred", evidence: [] },
  continuation_start: { chapter_id: "chapter-2", situation: "来信带来新线索", guidance: "前往城北", constraints: [] },
  evidence_index: {},
  needs_confirmation: [],
};

function session(status: "parsed" | "analyzing" | "ready" | "failed", revision: number, overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "continuation-import-session/v1",
    session_id: "ci-ui-test",
    revision,
    status,
    source_path: scanResult.source_path,
    source_fingerprint: "source-fp",
    encoding: "utf-8",
    chapters,
    analysis: status === "ready" ? analysis : {},
    analysis_progress: {},
    error: "",
    created_at: "2026-07-27T00:00:00Z",
    updated_at: "2026-07-27T00:00:00Z",
    ...overrides,
  };
}

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: { "access-control-allow-origin": "*" },
    body: JSON.stringify(body),
  });
}

async function routeNovelTypes(page: Page) {
  await page.route("**/novel-types", (route) => fulfill(route, [
    { id: "generic_webnovel", name: "通用网文", description: "通用规则", keywords: [], core_promises: [], ledger_fields: [], rulebook: {}, quality_checks: [], trope_templates: [], builtin: true },
  ]));
}

async function openContinuation(page: Page) {
  await routeNovelTypes(page);
  await page.goto("/projects/new");
  await page.getByRole("tab", { name: "续写已有小说" }).click();
}

async function importChapters(page: Page) {
  await page.getByLabel("小说文件或目录路径").fill(scanResult.source_path);
  await page.getByRole("button", { name: "扫描来源" }).click();
  await expect(page.getByText("识别到 2 章")).toBeVisible();
  await page.getByRole("button", { name: "进入章节校对" }).click();
  await expect(page.getByRole("heading", { name: "校对章节" })).toBeVisible();
}

test("new project page exposes the existing novel continuation workflow", async ({ page }) => {
  await page.route(continuationApi, (route) => fulfill(route, { current_path: "", directories: [], files: [] }));
  await openContinuation(page);
  await expect(page.getByRole("heading", { name: "选择小说来源" })).toBeVisible();
  await expect(page.getByLabel("小说文件或目录路径")).toBeVisible();
});

test("continuation source step does not overflow a mobile viewport", async ({ page }) => {
  await page.route(continuationApi, (route) => fulfill(route, { current_path: "", directories: [], files: [] }));
  await page.setViewportSize({ width: 375, height: 667 });
  await openContinuation(page);
  const dimensions = await page.locator(".ws-continuation").evaluate((element) => ({
    left: element.getBoundingClientRect().left,
    right: element.getBoundingClientRect().right,
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.left).toBeGreaterThanOrEqual(0);
  expect(dimensions.right).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.viewport);
});

test("happy path confirms analysis, sends settings, and follows next_path", async ({ page }) => {
  let getCount = 0;
  let createPayload: any = null;
  await page.route(continuationApi, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname.endsWith("/list-sources")) return fulfill(route, { current_path: "", directories: [], files: [] });
    if (url.pathname.endsWith("/scan")) return fulfill(route, scanResult);
    if (url.pathname === "/continuation-imports" && method === "POST") return fulfill(route, session("parsed", 1), 201);
    if (url.pathname.endsWith("/chapters")) return fulfill(route, session("parsed", 2));
    if (url.pathname.endsWith("/analyze")) return fulfill(route, { session_id: "ci-ui-test", status: "analyzing" }, 202);
    if (url.pathname.endsWith("/analysis") && method === "GET") return fulfill(route, analysis);
    if (url.pathname.endsWith("/analysis") && method === "PUT") return fulfill(route, session("ready", 4));
    if (url.pathname.endsWith("/create-project")) {
      createPayload = route.request().postDataJSON();
      return fulfill(route, { project_id: "p-continued", title: "旧书新章", source_path: "D:/exports/p-continued", current_chapter: 2, storage_source: "file", next_path: "/projects/file%3Ap-continued/outline" }, 201);
    }
    if (url.pathname.endsWith("/ci-ui-test") && method === "GET") {
      getCount += 1;
      return fulfill(route, getCount === 1 ? session("analyzing", 2) : session("ready", 3));
    }
    return route.abort();
  });

  await openContinuation(page);
  await importChapters(page);
  await page.getByRole("button", { name: "保存并分析" }).click();
  await expect(page.getByRole("heading", { name: "确认分析结果" })).toBeVisible();
  await expect(page.getByText("沈砚进入临川调查旧案。")).toBeVisible();
  await page.getByRole("tab", { name: "人物" }).click();
  await page.getByLabel("沈砚人物摘要").fill("谨慎而敏锐的调查者");
  await page.getByRole("button", { name: "确认分析结果" }).click();
  await page.getByLabel("后续方向").fill("先查城北，再揭开旧友隐瞒的身份。");
  await page.getByLabel("每章目标字数").fill("5200");
  await page.getByRole("button", { name: "适度改编" }).click();
  await page.getByRole("button", { name: "创建续写项目" }).click();

  await expect(page).toHaveURL(/file%3Ap-continued\/outline$/);
  expect(createPayload.expected_revision).toBe(4);
  expect(createPayload.settings).toMatchObject({ fidelity: "adaptive", target_chars: 5200, direction: "先查城北，再揭开旧友隐瞒的身份。", novel_type_id: "generic_webnovel" });
});

test("unknown encoding offers a forced encoding retry", async ({ page }) => {
  const scanPayloads: any[] = [];
  await page.route(continuationApi, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/list-sources")) return fulfill(route, { current_path: "", directories: [], files: [] });
    if (url.pathname.endsWith("/scan")) {
      const payload = route.request().postDataJSON();
      scanPayloads.push(payload);
      if (!payload.forced_encoding) return fulfill(route, { detail: "source_encoding_unknown" }, 422);
      return fulfill(route, { ...scanResult, encoding: payload.forced_encoding });
    }
    return route.abort();
  });
  await openContinuation(page);
  await page.getByLabel("小说文件或目录路径").fill(scanResult.source_path);
  await page.getByRole("button", { name: "扫描来源" }).click();
  await expect(page.getByText("无法判断文本编码")).toBeVisible();
  await page.getByLabel("文本编码").selectOption("gb18030");
  await page.getByRole("button", { name: "扫描来源" }).click();
  await expect(page.getByText("GB18030", { exact: false })).toBeVisible();
  expect(scanPayloads[1].forced_encoding).toBe("gb18030");
});

test("chapter review supports rename, reorder, merge, split, and revisioned save", async ({ page }) => {
  let saved: any = null;
  await page.route(continuationApi, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/list-sources")) return fulfill(route, { current_path: "", directories: [], files: [] });
    if (url.pathname.endsWith("/scan")) return fulfill(route, scanResult);
    if (url.pathname === "/continuation-imports") return fulfill(route, session("parsed", 1), 201);
    if (url.pathname.endsWith("/chapters")) { saved = route.request().postDataJSON(); return fulfill(route, { ...session("parsed", 2), chapters: saved.chapters }); }
    return route.abort();
  });
  await openContinuation(page);
  await importChapters(page);
  await page.getByLabel("章节名").fill("雨夜临川");
  await page.getByRole("button", { name: "下移" }).click();
  await page.getByRole("button", { name: "上移" }).click();
  await page.getByRole("button", { name: /旧友来信/ }).click();
  await page.getByRole("button", { name: "合并上一章" }).click();
  const body = page.getByLabel("正文");
  await body.focus();
  await body.evaluate((element: HTMLTextAreaElement) => element.setSelectionRange(4, 4));
  await page.getByRole("button", { name: "按光标拆分" }).click();
  await page.getByRole("button", { name: "保存章节" }).click();
  await expect.poll(() => saved).not.toBeNull();
  expect(saved.expected_revision).toBe(1);
  expect(saved.chapters).toHaveLength(2);
  expect(saved.chapters.map((item: any) => item.number)).toEqual([1, 2]);
  expect(saved.chapters.every((item: any) => item.fingerprint !== "pending")).toBeTruthy();
});

test("analysis failure stops polling and offers retry", async ({ page }) => {
  let gets = 0;
  await page.route(continuationApi, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/list-sources")) return fulfill(route, { current_path: "", directories: [], files: [] });
    if (url.pathname.endsWith("/scan")) return fulfill(route, scanResult);
    if (url.pathname === "/continuation-imports") return fulfill(route, session("parsed", 1), 201);
    if (url.pathname.endsWith("/chapters")) return fulfill(route, session("parsed", 2));
    if (url.pathname.endsWith("/analyze")) return fulfill(route, { session_id: "ci-ui-test", status: "analyzing" }, 202);
    if (url.pathname.endsWith("/ci-ui-test")) { gets += 1; return fulfill(route, gets === 1 ? session("analyzing", 2) : session("failed", 3, { error: "continuation_analysis_invalid_response" })); }
    return route.abort();
  });
  await openContinuation(page);
  await importChapters(page);
  await page.getByRole("button", { name: "保存并分析" }).click();
  await expect(page.getByRole("button", { name: "重新分析" })).toBeVisible();
  const stoppedAt = gets;
  await page.waitForTimeout(1600);
  expect(gets).toBe(stoppedAt);
});

test("analysis that is already failed after startup reports the terminal error", async ({ page }) => {
  await page.route(continuationApi, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/list-sources")) return fulfill(route, { current_path: "", directories: [], files: [] });
    if (url.pathname.endsWith("/scan")) return fulfill(route, scanResult);
    if (url.pathname === "/continuation-imports") return fulfill(route, session("parsed", 1), 201);
    if (url.pathname.endsWith("/chapters")) return fulfill(route, session("parsed", 2));
    if (url.pathname.endsWith("/analyze")) return fulfill(route, { session_id: "ci-ui-test", status: "analyzing" }, 202);
    if (url.pathname.endsWith("/ci-ui-test")) return fulfill(route, session("failed", 3, { error: "continuation_analysis_invalid_response" }));
    return route.abort();
  });
  await openContinuation(page);
  await importChapters(page);
  await page.getByRole("button", { name: "保存并分析" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "分析结果不完整" })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新分析" })).toBeEnabled();
});

test("blocking conflicts require resolution and create errors stay inline", async ({ page }) => {
  const conflicted = { ...analysis, needs_confirmation: [{ claim: "旧友身份不一致", source: "characters", reason: "conflicting_evidence" }] };
  let gets = 0;
  await page.route(continuationApi, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname.endsWith("/list-sources")) return fulfill(route, { current_path: "", directories: [], files: [] });
    if (url.pathname.endsWith("/scan")) return fulfill(route, scanResult);
    if (url.pathname === "/continuation-imports") return fulfill(route, session("parsed", 1), 201);
    if (url.pathname.endsWith("/chapters")) return fulfill(route, session("parsed", 2));
    if (url.pathname.endsWith("/analyze")) return fulfill(route, { session_id: "ci-ui-test", status: "analyzing" }, 202);
    if (url.pathname.endsWith("/analysis") && method === "GET") return fulfill(route, conflicted);
    if (url.pathname.endsWith("/analysis") && method === "PUT") return fulfill(route, session("ready", 4));
    if (url.pathname.endsWith("/create-project")) return fulfill(route, { detail: "source_changed_since_scan" }, 409);
    if (url.pathname.endsWith("/ci-ui-test")) { gets += 1; return fulfill(route, gets === 1 ? session("analyzing", 2) : session("ready", 3, { analysis: conflicted })); }
    return route.abort();
  });
  await openContinuation(page);
  await importChapters(page);
  await page.getByRole("button", { name: "保存并分析" }).click();
  const confirm = page.getByRole("button", { name: "确认分析结果" });
  await expect(confirm).toBeDisabled();
  await page.getByRole("button", { name: "标记已处理" }).click();
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await page.getByRole("button", { name: "创建续写项目" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "原始文件已经变化" })).toBeVisible();
  await expect(page.getByRole("button", { name: "创建续写项目" })).toBeEnabled();
});

test("quick continuation from source confirms defaults and follows project route", async ({ page }) => {
  let getCount = 0;
  let quickPayload: unknown = null;
  await page.route(continuationApi, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname.endsWith("/list-sources")) return fulfill(route, { current_path: "", directories: [], files: [] });
    if (url.pathname.endsWith("/scan")) return fulfill(route, scanResult);
    if (url.pathname === "/continuation-imports" && method === "POST") return fulfill(route, session("parsed", 1), 201);
    if (url.pathname.endsWith("/chapters")) return fulfill(route, session("parsed", 2));
    if (url.pathname.endsWith("/analyze")) return fulfill(route, { session_id: "ci-ui-test", status: "analyzing" }, 202);
    if (url.pathname.endsWith("/analysis")) return fulfill(route, analysis);
    if (url.pathname.endsWith("/quick-continue")) {
      quickPayload = route.request().postDataJSON();
      return fulfill(route, {
        session_id: "ci-ui-test",
        project_id: "file:p-quick",
        project_route: "/projects/file%3Ap-quick/write?chapter=3",
        job_id: "fgj-quick",
        job_status: "queued",
      }, 202);
    }
    if (url.pathname.endsWith("/ci-ui-test")) {
      getCount += 1;
      return fulfill(route, getCount === 1 ? session("analyzing", 2) : session("ready", 3));
    }
    return route.abort();
  });

  await page.setViewportSize({ width: 375, height: 667 });
  await openContinuation(page);
  await page.getByLabel("小说文件或目录路径").fill(scanResult.source_path);
  await page.getByRole("button", { name: "扫描来源" }).click();
  await page.getByRole("button", { name: "快速续写" }).click();

  const confirmation = page.getByRole("dialog", { name: "快速续写确认" });
  await expect(confirmation).toContainText("第 2 章之后");
  await expect(confirmation).toContainText("忠实续写");
  await expect(confirmation).toContainText("4,500 字");
  await expect(confirmation).toContainText("前往城北");
  const dimensions = await confirmation.evaluate((element) => ({
    right: element.getBoundingClientRect().right,
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.right).toBeLessThanOrEqual(dimensions.viewport);
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.viewport);
  await confirmation.getByRole("button", { name: "确认并生成下一章" }).click();

  await expect(page).toHaveURL(/file%3Ap-quick\/write\?chapter=3$/);
  expect(quickPayload).toEqual({});
});

test("quick continuation reports analysis blockers without creating a project", async ({ page }) => {
  const blocked = {
    ...analysis,
    needs_confirmation: [{ claim: "旧友身份不一致", source: "characters", reason: "conflicting_evidence" }],
  };
  let quickCalls = 0;
  await page.route(continuationApi, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/list-sources")) return fulfill(route, { current_path: "", directories: [], files: [] });
    if (url.pathname.endsWith("/scan")) return fulfill(route, scanResult);
    if (url.pathname === "/continuation-imports") return fulfill(route, session("parsed", 1), 201);
    if (url.pathname.endsWith("/chapters")) return fulfill(route, session("parsed", 2));
    if (url.pathname.endsWith("/analyze")) return fulfill(route, { session_id: "ci-ui-test", status: "analyzing" }, 202);
    if (url.pathname.endsWith("/analysis")) return fulfill(route, blocked);
    if (url.pathname.endsWith("/quick-continue")) { quickCalls += 1; return fulfill(route, { detail: "analysis_confirmation_required" }, 409); }
    if (url.pathname.endsWith("/ci-ui-test")) return fulfill(route, session("ready", 3, { analysis: blocked }));
    return route.abort();
  });

  await openContinuation(page);
  await page.getByLabel("小说文件或目录路径").fill(scanResult.source_path);
  await page.getByRole("button", { name: "扫描来源" }).click();
  await page.getByRole("button", { name: "快速续写" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "待确认内容" })).toBeVisible();
  expect(quickCalls).toBe(0);
});
