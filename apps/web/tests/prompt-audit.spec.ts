import { expect, test, type Page } from "@playwright/test";

import { deepAuditPrompt, type DeepPromptAuditResult } from "../lib/api";

const PROJECT_ID = "file:prompt-audit-fixture";
const PROJECT_PATH = `/projects/${encodeURIComponent(PROJECT_ID)}/prompts`;
const REQUIRED_VARIABLES = ["output_section", "chapter_direction"];

const templatesResponse = {
  schema_version: "project-prompt-templates/v1",
  project_id: PROJECT_ID,
  templates: [
    {
      key: "writer",
      title: "整章正文写作",
      stage: "writing",
      content: "原模板\n{{output_section}}\n{{chapter_direction}}",
      required_variables: REQUIRED_VARIABLES,
      version: "sha256:template",
      source: "global_default",
    },
    {
      key: "reviewer",
      title: "章节审稿",
      stage: "review",
      content: "检查章节质量\n{{output_section}}",
      required_variables: ["output_section"],
      version: "sha256:reviewer",
      source: "global_default",
    },
  ],
};

const auditResult = {
  schema_version: "prompt-audit/v1",
  mode: "template",
  content_sha256: "7e4cd2c5d54be3e8a8c4b18d45ae67cb2f54c3c895d76d53e1256a3078334d5d",
  summary: {
    characters: 72,
    lines: 5,
    estimated_redundant_characters: 16,
    estimated_reduction_percent: 22.2,
    sections: [
      { title: "正文要求", characters: 48, percent: 66.7 },
      { title: "变量", characters: 24, percent: 33.3 },
    ],
  },
  must_fix: [],
  suggestions: [
    {
      code: "duplicate_instruction",
      title: "重复指令",
      evidence: "请保持节奏紧凑。出现两次。",
      location: "第 1-2 行",
      suggestion: "合并为一条节奏要求。",
      estimated_reduction_characters: 16,
    },
  ],
  passed_checks: ["必需变量齐全", "未发现互相冲突的指令"],
};

const deepAuditResult = {
  ...auditResult,
  suggestions: [
    ...auditResult.suggestions,
    {
      code: "semantic_focus",
      title: "语义焦点可更明确",
      evidence: "正文目标与章节方向分散在不同位置。",
      location: "全文",
      suggestion: "将正文目标与章节方向合并为一个清晰的任务段。",
      estimated_reduction_characters: 8,
    },
  ],
  runtime: {
    provider: "openai",
    model: "gpt-5-mini",
    elapsed_seconds: 1.25,
    prompt_characters: 321,
  },
};

type AuditMockOptions = {
  auditStatus?: number;
  auditStarted?: () => void;
  waitForAudit?: Promise<void>;
  deepStatus?: number;
  deepStarted?: () => void;
  waitForDeep?: Promise<void>;
};

async function mockPromptAuditPage(page: Page, options: AuditMockOptions = {}) {
  const {
    auditStatus = 200,
    auditStarted,
    waitForAudit,
    deepStatus = 200,
    deepStarted,
    waitForDeep,
  } = options;
  const auditBodies: unknown[] = [];
  const deepAuditBodies: unknown[] = [];
  const templatePutMethods: string[] = [];

  await page.route("**/prompt-audit/deep", async (route) => {
    deepAuditBodies.push(route.request().postDataJSON());
    deepStarted?.();
    await waitForDeep;
    await route.fulfill({
      status: deepStatus,
      contentType: "application/json",
      body: deepStatus === 200
        ? JSON.stringify(deepAuditResult)
        : JSON.stringify({ detail: "AI 服务暂时不可用" }),
    });
  });

  await page.route("**/prompt-audit", async (route) => {
    auditBodies.push(route.request().postDataJSON());
    auditStarted?.();
    await waitForAudit;
    await route.fulfill({
      status: auditStatus,
      contentType: "application/json",
      body: auditStatus === 200 ? JSON.stringify(auditResult) : JSON.stringify({ detail: "服务暂不可用" }),
    });
  });

  await page.route("**/file-projects/**", async (route) => {
    const request = route.request();
    const pathname = decodeURIComponent(new URL(request.url()).pathname);
    if (pathname.endsWith("/prompt-templates")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(templatesResponse) });
      return;
    }
    if (pathname.includes("/prompt-templates/") && request.method() === "PUT") {
      templatePutMethods.push(request.method());
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        project_id: PROJECT_ID,
        title: "提示词检查测试",
        active_story_id: "",
        status: "draft",
        pipeline_stage: "idea_pending",
        branches: [],
        storage_source: "file",
      }),
    });
  });

  return { auditBodies, deepAuditBodies, templatePutMethods };
}

test("deepAuditPrompt 仅序列化本地检查结果的白名单字段", async () => {
  const originalFetch = globalThis.fetch;
  let capturedBody: { local_result: Record<string, unknown> } | undefined;
  const localWithRuntime = {
    ...auditResult,
    runtime: deepAuditResult.runtime,
    unexpected_field: "must not be sent",
  } as DeepPromptAuditResult & { unexpected_field: string };

  try {
    globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      capturedBody = JSON.parse(String(init?.body)) as { local_result: Record<string, unknown> };
      return new Response(JSON.stringify(deepAuditResult), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    await deepAuditPrompt({ mode: "template", content: "test content" }, localWithRuntime);

    expect(capturedBody).toBeDefined();
    expect(capturedBody?.local_result.runtime).toBeUndefined();
    expect(capturedBody?.local_result.unexpected_field).toBeUndefined();
    expect(capturedBody?.local_result).toEqual({
      schema_version: auditResult.schema_version,
      mode: auditResult.mode,
      content_sha256: auditResult.content_sha256,
      summary: auditResult.summary,
      must_fix: auditResult.must_fix,
      suggestions: auditResult.suggestions,
      passed_checks: auditResult.passed_checks,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("检查当前未保存的模板并显示紧凑诊断", async ({ page }) => {
  const api = await mockPromptAuditPage(page);
  const editedContent = "请保持节奏紧凑。\n请保持节奏紧凑。\n{{output_section}}\n{{chapter_direction}}";

  await page.goto(PROJECT_PATH);
  expect(api.deepAuditBodies).toHaveLength(0);
  await page.getByLabel("原始模板").fill(editedContent);
  await page.getByRole("button", { name: "检查提示词" }).click();

  await expect.poll(() => api.auditBodies).toEqual([{
    mode: "template",
    content: editedContent,
    template_key: "writer",
    required_variables: REQUIRED_VARIABLES,
  }]);
  expect(api.templatePutMethods).toHaveLength(0);
  await expect(page.getByRole("heading", { name: "提示词检查" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "建议精简" })).toBeVisible();
  await expect(page.getByText("重复指令", { exact: true })).toBeVisible();
  await expect(page.getByText(/72.*字符/)).toBeVisible();
  await expect(page.getByText(/5.*有效行/)).toBeVisible();
  await expect(page.getByText(/16.*22\.2%/)).toBeVisible();
  await expect(page.getByText("分析报告", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "AI 深度检查" })).toBeEnabled();
  expect(api.deepAuditBodies).toHaveLength(0);
});

test("AI 深度检查仅在显式点击后调用并显示语义建议与运行信息", async ({ page }) => {
  const api = await mockPromptAuditPage(page);
  const originalContent = templatesResponse.templates[0].content;

  await page.goto(PROJECT_PATH);
  expect(api.deepAuditBodies).toHaveLength(0);
  await page.getByRole("button", { name: "检查提示词" }).click();
  await expect(page.getByRole("button", { name: "AI 深度检查" })).toBeEnabled();
  expect(api.deepAuditBodies).toHaveLength(0);

  await page.getByRole("button", { name: "AI 深度检查" }).click();

  await expect.poll(() => api.deepAuditBodies).toHaveLength(1);
  expect(api.deepAuditBodies[0]).toEqual({
    mode: "template",
    content: originalContent,
    template_key: "writer",
    required_variables: REQUIRED_VARIABLES,
    local_result: auditResult,
  });
  expect((api.deepAuditBodies[0] as { local_result: Record<string, unknown> }).local_result).not.toHaveProperty("runtime");
  await expect(page.getByText("语义焦点可更明确", { exact: true })).toBeVisible();
  await expect(page.getByText(/openai \/ gpt-5-mini.*1\.25.*321/)).toBeVisible();
});

test("内容过期时禁用深度检查，重新本地检查后恢复", async ({ page }) => {
  const api = await mockPromptAuditPage(page);
  const editedContent = "重新检查后的内容\n{{output_section}}\n{{chapter_direction}}";

  await page.goto(PROJECT_PATH);
  await page.getByRole("button", { name: "检查提示词" }).click();
  const deepButton = page.getByRole("button", { name: "AI 深度检查" });
  await expect(deepButton).toBeEnabled();

  await page.getByLabel("原始模板").fill(editedContent);
  await expect(deepButton).toBeDisabled();
  await expect(page.getByText("内容已变化，请重新检查。", { exact: true })).toBeVisible();
  await deepButton.click({ force: true });
  expect(api.deepAuditBodies).toHaveLength(0);

  await page.getByRole("button", { name: "检查提示词" }).click();
  await expect(deepButton).toBeEnabled();
  expect(api.deepAuditBodies).toHaveLength(0);
});

test("深度检查失败保留本地结果与未保存内容", async ({ page }) => {
  const api = await mockPromptAuditPage(page, { deepStatus: 503 });
  const editedContent = "深度检查失败也要保留\n{{output_section}}\n{{chapter_direction}}";

  await page.goto(PROJECT_PATH);
  await page.getByLabel("原始模板").fill(editedContent);
  await page.getByRole("button", { name: "检查提示词" }).click();
  await page.getByRole("button", { name: "AI 深度检查" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "深度检查失败：AI 服务暂时不可用" })).toBeVisible();
  await expect(page.getByText("重复指令", { exact: true })).toBeVisible();
  await expect(page.getByLabel("原始模板")).toHaveValue(editedContent);
  await expect(page.getByRole("button", { name: "保存为项目覆盖" })).toBeEnabled();
  expect(api.deepAuditBodies).toHaveLength(1);
});

test("深度检查期间编辑内容会忽略旧响应并结束 loading", async ({ page }) => {
  let releaseDeep!: () => void;
  let markDeepStarted!: () => void;
  const deepGate = new Promise<void>((resolve) => { releaseDeep = resolve; });
  const deepStarted = new Promise<void>((resolve) => { markDeepStarted = resolve; });
  await mockPromptAuditPage(page, { deepStarted: markDeepStarted, waitForDeep: deepGate });

  await page.goto(PROJECT_PATH);
  await page.getByRole("button", { name: "检查提示词" }).click();
  await page.getByRole("button", { name: "AI 深度检查" }).click();
  await deepStarted;
  await expect(page.getByText("AI 深度检查中，请稍候...", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "AI 深度检查中..." })).toBeDisabled();

  await page.getByLabel("原始模板").fill("请求期间编辑\n{{output_section}}\n{{chapter_direction}}");
  await expect(page.getByText("AI 深度检查中，请稍候...", { exact: true })).toHaveCount(0);
  const deepResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit/deep"));
  releaseDeep();
  await deepResponse;
  await expect(page.getByText("语义焦点可更明确", { exact: true })).toHaveCount(0);
  await expect(page.getByText("重复指令", { exact: true })).toBeVisible();
});

test("本地重新检查成功会忽略在途深度检查并重置深度状态", async ({ page }) => {
  let releaseDeep!: () => void;
  let markDeepStarted!: () => void;
  const deepGate = new Promise<void>((resolve) => { releaseDeep = resolve; });
  const deepStarted = new Promise<void>((resolve) => { markDeepStarted = resolve; });
  const api = await mockPromptAuditPage(page, { deepStarted: markDeepStarted, waitForDeep: deepGate });

  await page.goto(PROJECT_PATH);
  await page.getByRole("button", { name: "检查提示词" }).click();
  await page.getByRole("button", { name: "AI 深度检查" }).click();
  await deepStarted;
  await page.getByRole("button", { name: "检查提示词" }).click();
  await expect.poll(() => api.auditBodies).toHaveLength(2);
  await expect(page.getByRole("button", { name: "AI 深度检查" })).toBeEnabled();

  const deepResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit/deep"));
  releaseDeep();
  await deepResponse;
  await expect(page.getByText("语义焦点可更明确", { exact: true })).toHaveCount(0);
  await expect(page.getByText("重复指令", { exact: true })).toBeVisible();
});

test("深度检查期间切换模板会忽略旧响应并结束 loading", async ({ page }) => {
  let releaseDeep!: () => void;
  let markDeepStarted!: () => void;
  const deepGate = new Promise<void>((resolve) => { releaseDeep = resolve; });
  const deepStarted = new Promise<void>((resolve) => { markDeepStarted = resolve; });
  await mockPromptAuditPage(page, { deepStarted: markDeepStarted, waitForDeep: deepGate });

  await page.goto(PROJECT_PATH);
  await page.getByRole("button", { name: "检查提示词" }).click();
  await page.getByRole("button", { name: "AI 深度检查" }).click();
  await deepStarted;
  await page.getByRole("button", { name: /章节审稿/ }).click();

  await expect(page.getByText("AI 深度检查中，请稍候...", { exact: true })).toHaveCount(0);
  const deepResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit/deep"));
  releaseDeep();
  await deepResponse;
  await expect(page.getByText("语义焦点可更明确", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "提示词检查" })).toHaveCount(0);
});

test("检查失败时保留未保存内容且不保存模板", async ({ page }) => {
  const api = await mockPromptAuditPage(page, { auditStatus: 503 });
  const editedContent = "尚未保存的正文\n{{output_section}}\n{{chapter_direction}}";

  await page.goto(PROJECT_PATH);
  await page.getByLabel("原始模板").fill(editedContent);
  await page.getByRole("button", { name: "检查提示词" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "检查失败：" })).toBeVisible();
  await expect(page.getByLabel("原始模板")).toHaveValue(editedContent);
  expect(api.templatePutMethods).toHaveLength(0);
});

test("切换模板后忽略先前模板的延迟检查响应", async ({ page }) => {
  let releaseAudit!: () => void;
  let markAuditStarted!: () => void;
  const auditGate = new Promise<void>((resolve) => { releaseAudit = resolve; });
  const auditStarted = new Promise<void>((resolve) => { markAuditStarted = resolve; });
  await mockPromptAuditPage(page, { auditStarted: markAuditStarted, waitForAudit: auditGate });

  await page.goto(PROJECT_PATH);
  await page.getByRole("button", { name: "检查提示词" }).click();
  await auditStarted;
  await page.getByRole("button", { name: /章节审稿/ }).click();

  await expect(page.getByLabel("原始模板")).toHaveValue("检查章节质量\n{{output_section}}");
  await expect(page.getByRole("button", { name: "检查提示词" })).toBeEnabled();
  const auditResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit"));
  releaseAudit();
  await auditResponse;
  await expect(page.getByRole("heading", { name: "提示词检查" })).toHaveCount(0);
});

test("检查结果显示后继续编辑会保留结果并标记过期", async ({ page }) => {
  await mockPromptAuditPage(page);

  await page.goto(PROJECT_PATH);
  await page.getByRole("button", { name: "检查提示词" }).click();
  await expect(page.getByRole("heading", { name: "提示词检查" })).toBeVisible();
  await page.getByLabel("原始模板").fill("结果后的新内容\n{{output_section}}\n{{chapter_direction}}");

  await expect(page.getByText("重复指令", { exact: true })).toBeVisible();
  await expect(page.getByText("内容已变化，请重新检查。", { exact: true })).toBeVisible();
});

test("检查期间编辑会忽略延迟响应并立即结束检查状态", async ({ page }) => {
  let releaseAudit!: () => void;
  let markAuditStarted!: () => void;
  const auditGate = new Promise<void>((resolve) => { releaseAudit = resolve; });
  const auditStarted = new Promise<void>((resolve) => { markAuditStarted = resolve; });
  await mockPromptAuditPage(page, { auditStarted: markAuditStarted, waitForAudit: auditGate });

  await page.goto(PROJECT_PATH);
  await page.getByRole("button", { name: "检查提示词" }).click();
  await auditStarted;
  await page.getByLabel("原始模板").fill("请求期间的新内容\n{{output_section}}\n{{chapter_direction}}");

  await expect(page.getByRole("button", { name: "检查提示词" })).toBeEnabled();
  const auditResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit"));
  releaseAudit();
  await auditResponse;
  await expect(page.getByRole("heading", { name: "提示词检查" })).toHaveCount(0);
});
