import { expect, test, type Page } from "@playwright/test";

import { deepAuditPrompt, type DeepPromptAuditResult } from "../lib/api";

const PROJECT_ID = "file:prompt-audit-fixture";
const PROJECT_PATH = `/projects/${encodeURIComponent(PROJECT_ID)}/prompts`;
const REQUIRED_VARIABLES = ["output_section", "chapter_direction"];
const FIRST_CALL_PROMPT = "真实调用一的完整提示词";
const SECOND_CALL_PROMPT = "真实调用二的完整提示词";
const SYSTEM_ONLY_SECRET = "SYSTEM_ONLY_AUDIT_SECRET";
const SECOND_SYSTEM_ONLY_SECRET = "SECOND_SYSTEM_ONLY_AUDIT_SECRET";
const OUTPUT_ONLY_SECRET = "OUTPUT_ONLY_AUDIT_SECRET";

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

const promptCallsResponse = {
  schema_version: "prompt-call-list/v1",
  project_id: PROJECT_ID,
  chapter_number: 1,
  calls: [
    { call_id: "pc-audit", chapter_number: 1, stage: "正文写作", agent: "writer", attempt: 1, status: "succeeded", provider: "openai", model: "gpt-5-mini", prompt_chars: FIRST_CALL_PROMPT.length },
    { call_id: "pc-second", chapter_number: 1, stage: "章节审稿", agent: "reviewer", attempt: 2, status: "succeeded", provider: "openai", model: "gpt-5-mini", prompt_chars: SECOND_CALL_PROMPT.length },
  ],
};

const promptCallDetails = {
  "pc-audit": {
    ...promptCallsResponse.calls[0],
    user_prompt: FIRST_CALL_PROMPT,
    system_prompt: SYSTEM_ONLY_SECRET,
    output_summary: OUTPUT_ONLY_SECRET,
    module_keys: ["character_context"],
    template_source: "global_default",
  },
  "pc-second": {
    ...promptCallsResponse.calls[1],
    user_prompt: SECOND_CALL_PROMPT,
    system_prompt: SECOND_SYSTEM_ONLY_SECRET,
    output_summary: "第二条调用的模型输出",
    module_keys: ["chapter_context"],
    template_source: "project_override",
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
    const body = route.request().postDataJSON() as { mode?: string };
    deepAuditBodies.push(body);
    deepStarted?.();
    await waitForDeep;
    await route.fulfill({
      status: deepStatus,
      contentType: "application/json",
      body: deepStatus === 200
        ? JSON.stringify({ ...deepAuditResult, mode: body.mode ?? deepAuditResult.mode })
        : JSON.stringify({ detail: "AI 服务暂时不可用" }),
    });
  });

  await page.route("**/prompt-audit", async (route) => {
    const body = route.request().postDataJSON() as { mode?: string };
    auditBodies.push(body);
    auditStarted?.();
    await waitForAudit;
    await route.fulfill({
      status: auditStatus,
      contentType: "application/json",
      body: auditStatus === 200
        ? JSON.stringify({ ...auditResult, mode: body.mode ?? auditResult.mode })
        : JSON.stringify({ detail: "服务暂不可用" }),
    });
  });

  await page.route("**/file-projects/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = decodeURIComponent(url.pathname);
    const requestedProjectId = pathname.match(/\/file-projects\/([^/]+)/)?.[1] ?? PROJECT_ID;
    if (pathname.endsWith("/prompt-templates")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(templatesResponse) });
      return;
    }
    if (pathname.endsWith("/prompt-calls")) {
      const chapterNumber = Number(url.searchParams.get("chapter_number") ?? 1);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...promptCallsResponse,
          project_id: requestedProjectId,
          chapter_number: chapterNumber,
          calls: promptCallsResponse.calls.map((call) => ({ ...call, chapter_number: chapterNumber })),
        }),
      });
      return;
    }
    const callId = pathname.match(/\/prompt-calls\/(pc-audit|pc-second)$/)?.[1] as keyof typeof promptCallDetails | undefined;
    if (callId) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(promptCallDetails[callId]) });
      return;
    }
    if (pathname.includes("/prompt-templates/") && request.method() === "PUT") {
      templatePutMethods.push(request.method());
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        project_id: requestedProjectId,
        title: `${requestedProjectId} 提示词检查测试`,
        active_story_id: requestedProjectId,
        status: "draft",
        pipeline_stage: "idea_pending",
        branches: [],
        storage_source: "file",
      }),
    });
  });

  await page.route("**/file-stories/**", async (route) => {
    const storyId = decodeURIComponent(new URL(route.request().url()).pathname).match(/\/file-stories\/([^/]+)/)?.[1] ?? PROJECT_ID;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        story_id: storyId,
        outline: "提示词审计测试大纲",
        genre: "测试",
        style: "网文",
        current_chapter: 2,
        agent_settings: {
          mode: "LLM-assisted",
          global_model: "gpt-5-mini",
          character_model: "gpt-5-mini",
          director_model: "gpt-5-mini",
          writer_model: "gpt-5-mini",
          memory_model: "gpt-5-mini",
          temperature: 0.7,
          new_character_policy: "Director review",
        },
        characters: [],
        world_facts: [],
        author_constraints: [],
        agent_runtime: { recent_events: [] },
        parent_story_id: null,
        branched_from_chapter: null,
        history: [
          { chapter_number: 1, chapter_title: "第一章", body: "第一章正文" },
          { chapter_number: 2, chapter_title: "第二章", body: "第二章正文" },
        ],
      }),
    });
  });

  return { auditBodies, deepAuditBodies, templatePutMethods };
}

async function openRecordedCall(page: Page, callId = "pc-audit") {
  await page.goto(`${PROJECT_PATH}?view=calls&chapter=1`);
  await page.getByRole("button", { name: `查看调用 ${callId}` }).click();
  await expect(page.getByText(promptCallDetails[callId as keyof typeof promptCallDetails].user_prompt, { exact: true })).toBeVisible();
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
  const response = await deepResponse;
  await response.finished();
  await page.waitForTimeout(50);
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
  const response = await deepResponse;
  await response.finished();
  await page.waitForTimeout(50);
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
  const response = await deepResponse;
  await response.finished();
  await page.waitForTimeout(50);
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
  const response = await auditResponse;
  await response.finished();
  await page.waitForTimeout(50);
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
  const response = await auditResponse;
  await response.finished();
  await page.waitForTimeout(50);
  await expect(page.getByRole("heading", { name: "提示词检查" })).toHaveCount(0);
});

test("真实调用仅检查 user_prompt，深度检查只在显式点击后运行", async ({ page }) => {
  const api = await mockPromptAuditPage(page);

  await openRecordedCall(page);
  expect(api.auditBodies).toHaveLength(0);
  expect(api.deepAuditBodies).toHaveLength(0);
  await page.getByRole("button", { name: "检查这次调用" }).click();

  await expect.poll(() => api.auditBodies).toEqual([{
    mode: "final_call",
    content: FIRST_CALL_PROMPT,
  }]);
  expect(JSON.stringify(api.auditBodies[0])).not.toContain(SYSTEM_ONLY_SECRET);
  expect(JSON.stringify(api.auditBodies[0])).not.toContain(OUTPUT_ONLY_SECRET);
  expect(api.deepAuditBodies).toHaveLength(0);
  await expect(page.getByText("重复指令", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "AI 深度检查" })).toBeEnabled();

  await page.getByRole("button", { name: "AI 深度检查" }).click();

  await expect.poll(() => api.deepAuditBodies).toHaveLength(1);
  expect(api.deepAuditBodies[0]).toEqual({
    mode: "final_call",
    content: FIRST_CALL_PROMPT,
    local_result: { ...auditResult, mode: "final_call" },
  });
  expect((api.deepAuditBodies[0] as { local_result: Record<string, unknown> }).local_result).not.toHaveProperty("runtime");
  await expect(page.getByText("语义焦点可更明确", { exact: true })).toBeVisible();
  await expect(page.getByText(/openai \/ gpt-5-mini.*1\.25.*321/)).toBeVisible();
});

test("第二条真实调用的本地与深度检查始终使用自己的 user_prompt", async ({ page }) => {
  const api = await mockPromptAuditPage(page);

  await openRecordedCall(page, "pc-second");
  await page.getByRole("button", { name: "检查这次调用" }).click();
  await page.getByRole("button", { name: "AI 深度检查" }).click();

  await expect.poll(() => api.deepAuditBodies).toHaveLength(1);
  expect(api.auditBodies).toHaveLength(1);
  expect((api.auditBodies[0] as { content?: string }).content).toBe(SECOND_CALL_PROMPT);
  expect((api.deepAuditBodies[0] as { content?: string }).content).toBe(SECOND_CALL_PROMPT);
  for (const payload of [...api.auditBodies, ...api.deepAuditBodies]) {
    const serialized = JSON.stringify(payload);
    expect(serialized).not.toContain(FIRST_CALL_PROMPT);
    expect(serialized).not.toContain(SYSTEM_ONLY_SECRET);
    expect(serialized).not.toContain(SECOND_SYSTEM_ONLY_SECRET);
  }
});

test("真实调用本地检查失败时保留调用详情和完整提示词", async ({ page }) => {
  await mockPromptAuditPage(page, { auditStatus: 503 });

  await openRecordedCall(page);
  await page.getByRole("button", { name: "检查这次调用" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "检查失败：服务暂不可用" })).toBeVisible();
  await expect(page.getByText(FIRST_CALL_PROMPT, { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: /正文写作/ })).toBeVisible();
});

test("真实调用深度检查失败时保留本地诊断", async ({ page }) => {
  const api = await mockPromptAuditPage(page, { deepStatus: 503 });

  await openRecordedCall(page);
  await page.getByRole("button", { name: "检查这次调用" }).click();
  await page.getByRole("button", { name: "AI 深度检查" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "深度检查失败：AI 服务暂时不可用" })).toBeVisible();
  await expect(page.getByText("重复指令", { exact: true })).toBeVisible();
  await expect(page.getByText(FIRST_CALL_PROMPT, { exact: true })).toBeVisible();
  expect(api.deepAuditBodies).toHaveLength(1);
});

test("切换真实调用会清空诊断并忽略旧调用的延迟本地结果", async ({ page }) => {
  let releaseAudit!: () => void;
  let markAuditStarted!: () => void;
  const auditGate = new Promise<void>((resolve) => { releaseAudit = resolve; });
  const auditStarted = new Promise<void>((resolve) => { markAuditStarted = resolve; });
  await mockPromptAuditPage(page, { auditStarted: markAuditStarted, waitForAudit: auditGate });

  await openRecordedCall(page);
  await expect(page.getByRole("button", { name: "查看调用 pc-audit" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "查看调用 pc-second" })).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "检查这次调用" }).click();
  await auditStarted;
  await page.getByRole("button", { name: "查看调用 pc-second" }).click();

  await expect(page.getByText(SECOND_CALL_PROMPT, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "查看调用 pc-audit" })).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("button", { name: "查看调用 pc-second" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "检查这次调用" })).toBeEnabled();
  const auditResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit"));
  releaseAudit();
  const response = await auditResponse;
  await response.finished();
  await page.waitForTimeout(50);
  await expect(page.getByRole("heading", { name: "提示词检查" })).toHaveCount(0);
  await expect(page.getByText(FIRST_CALL_PROMPT, { exact: true })).toHaveCount(0);
});

test("切换真实调用会清空诊断并忽略旧调用的延迟深度结果", async ({ page }) => {
  let releaseDeep!: () => void;
  let markDeepStarted!: () => void;
  const deepGate = new Promise<void>((resolve) => { releaseDeep = resolve; });
  const deepStarted = new Promise<void>((resolve) => { markDeepStarted = resolve; });
  await mockPromptAuditPage(page, { deepStarted: markDeepStarted, waitForDeep: deepGate });

  await openRecordedCall(page);
  await page.getByRole("button", { name: "检查这次调用" }).click();
  await page.getByRole("button", { name: "AI 深度检查" }).click();
  await deepStarted;
  await page.getByRole("button", { name: "查看调用 pc-second" }).click();

  await expect(page.getByText(SECOND_CALL_PROMPT, { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "提示词检查" })).toHaveCount(0);
  const deepResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit/deep"));
  releaseDeep();
  const response = await deepResponse;
  await response.finished();
  await page.waitForTimeout(50);
  await expect(page.getByText("语义焦点可更明确", { exact: true })).toHaveCount(0);
});

test("重新本地检查会结束深度 loading 并忽略先前的延迟深度结果", async ({ page }) => {
  let releaseDeep!: () => void;
  let markDeepStarted!: () => void;
  const deepGate = new Promise<void>((resolve) => { releaseDeep = resolve; });
  const deepStarted = new Promise<void>((resolve) => { markDeepStarted = resolve; });
  const api = await mockPromptAuditPage(page, { deepStarted: markDeepStarted, waitForDeep: deepGate });

  await openRecordedCall(page);
  await page.getByRole("button", { name: "检查这次调用" }).click();
  await page.getByRole("button", { name: "AI 深度检查" }).click();
  await deepStarted;
  await expect(page.getByRole("button", { name: "AI 深度检查中..." })).toBeDisabled();

  await page.getByRole("button", { name: "检查这次调用" }).click();
  await expect.poll(() => api.auditBodies).toHaveLength(2);
  await expect(page.getByText("AI 深度检查中，请稍候...", { exact: true })).toHaveCount(0);
  await expect(page.getByText("重复指令", { exact: true })).toBeVisible();

  const deepResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit/deep"));
  releaseDeep();
  const response = await deepResponse;
  await response.finished();
  await page.waitForTimeout(50);
  await expect(page.getByText("语义焦点可更明确", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/openai \/ gpt-5-mini.*1\.25.*321/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "AI 深度检查" })).toBeEnabled();
});

test("章节变化会结束本地 loading 并忽略先前章节的延迟结果", async ({ page }) => {
  let releaseAudit!: () => void;
  let markAuditStarted!: () => void;
  const auditGate = new Promise<void>((resolve) => { releaseAudit = resolve; });
  const auditStarted = new Promise<void>((resolve) => { markAuditStarted = resolve; });
  await mockPromptAuditPage(page, { auditStarted: markAuditStarted, waitForAudit: auditGate });

  await openRecordedCall(page);
  await page.getByRole("button", { name: "检查这次调用" }).click();
  await auditStarted;
  await expect(page.getByRole("button", { name: "检查中..." })).toBeDisabled();
  await page.getByRole("link", { name: /第 2 章/ }).click();

  await expect(page).toHaveURL(/view=calls&chapter=2/);
  await expect(page.getByRole("heading", { name: "第 2 章实际调用" })).toBeVisible();
  await expect(page.getByText("提示词检查中...", { exact: true })).toHaveCount(0);
  const auditResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit"));
  releaseAudit();
  const response = await auditResponse;
  await response.finished();
  await page.waitForTimeout(50);
  await expect(page.getByRole("heading", { name: "提示词检查" })).toHaveCount(0);
});

test("切换工作台视图会使真实调用的延迟深度检查失效", async ({ page }) => {
  let releaseDeep!: () => void;
  let markDeepStarted!: () => void;
  const deepGate = new Promise<void>((resolve) => { releaseDeep = resolve; });
  const deepStarted = new Promise<void>((resolve) => { markDeepStarted = resolve; });
  await mockPromptAuditPage(page, { deepStarted: markDeepStarted, waitForDeep: deepGate });

  await openRecordedCall(page);
  await page.getByRole("button", { name: "检查这次调用" }).click();
  await page.getByRole("button", { name: "AI 深度检查" }).click();
  await deepStarted;
  await page.getByRole("tab", { name: "上下文模块" }).click();
  await expect(page.getByRole("tab", { name: "上下文模块" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("AI 深度检查中，请稍候...", { exact: true })).toHaveCount(0);
  const deepResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit/deep"));
  releaseDeep();
  const response = await deepResponse;
  await response.finished();
  await page.waitForTimeout(50);
  await page.getByRole("tab", { name: "实际调用" }).click();
  await expect(page.getByRole("heading", { name: "提示词检查" })).toHaveCount(0);
  await expect(page.getByText("语义焦点可更明确", { exact: true })).toHaveCount(0);
});

test("切换工作台视图会使真实调用的延迟检查失效", async ({ page }) => {
  let releaseAudit!: () => void;
  let markAuditStarted!: () => void;
  const auditGate = new Promise<void>((resolve) => { releaseAudit = resolve; });
  const auditStarted = new Promise<void>((resolve) => { markAuditStarted = resolve; });
  await mockPromptAuditPage(page, { auditStarted: markAuditStarted, waitForAudit: auditGate });

  await openRecordedCall(page);
  await page.getByRole("button", { name: "检查这次调用" }).click();
  await auditStarted;
  await page.getByRole("tab", { name: "上下文模块" }).click();
  await expect(page.getByRole("tab", { name: "上下文模块" })).toHaveAttribute("aria-selected", "true");
  const auditResponse = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/prompt-audit"));
  releaseAudit();
  const response = await auditResponse;
  await response.finished();
  await page.waitForTimeout(50);
  await page.getByRole("tab", { name: "实际调用" }).click();
  await expect(page.getByRole("heading", { name: "提示词检查" })).toHaveCount(0);
});
