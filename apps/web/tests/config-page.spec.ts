import { expect, test, type Page } from "@playwright/test";

const providerCatalog = {
    providers: [
    ["openai", "OpenAI", "openai_compatible", "https://api.openai.com/v1", ["gpt-5"], true, false],
    ["deepseek", "DeepSeek", "openai_compatible", "https://api.deepseek.com/v1", ["deepseek-chat"], true, false],
    ["kimi", "Kimi", "openai_compatible", "https://api.moonshot.cn/v1", ["kimi-k2.5"], true, false],
    ["qwen", "通义千问", "openai_compatible", "https://dashscope.aliyuncs.com/compatible-mode/v1", ["qwen3-max"], true, false],
    ["glm", "智谱 GLM", "openai_compatible", "https://open.bigmodel.cn/api/paas/v4", ["glm-4.5"], true, false],
    ["doubao", "豆包", "openai_compatible", "https://ark.cn-beijing.volces.com/api/v3", ["doubao-seed-1-6"], true, false],
    ["minimax", "MiniMax", "openai_compatible", "https://api.minimaxi.com/v1", ["MiniMax-M2.7"], true, false],
    ["siliconflow", "硅基流动", "openai_compatible", "https://api.siliconflow.cn/v1", ["Qwen/Qwen3"], true, false],
    ["openrouter", "OpenRouter", "openai_compatible", "https://openrouter.ai/api/v1", ["openai/gpt-5"], true, false],
    ["xai", "xAI", "openai_compatible", "https://api.x.ai/v1", ["grok-4"], true, false],
    ["anthropic", "Anthropic", "anthropic", "https://api.anthropic.com", ["claude-sonnet-4"], true, false],
    ["gemini", "Google Gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta", ["gemini-2.5-pro"], true, false],
    ["ollama", "Ollama", "openai_compatible", "http://localhost:11434/v1", ["qwen3:8b"], false, true],
    ["codexcli", "Codex CLI", "codex_cli", "", ["gpt-5-codex"], false, false],
    ["antigravity", "Antigravity CLI", "antigravity_cli", "", ["gemini-3.6-flash-high"], false, false],
    ["custom_openai", "自定义 OpenAI 兼容接口", "openai_compatible", "", [], true, true],
  ].map(([provider_id, name, protocol, default_base_url, models, requires_api_key, base_url_editable]) => ({
    provider_id, name, default_base_url, planner_models: models, writer_models: models,
    requires_api_key, base_url_editable, uses_local_command: String(protocol).endsWith("_cli"), default_command: protocol === "codex_cli" ? "codex" : protocol === "antigravity_cli" ? "agy" : "", account_label: "待检测",
  })),
};

const accounts = Object.fromEntries(providerCatalog.providers.map((provider) => [provider.provider_id, {
  api_key: provider.requires_api_key ? "" : "",
  base_url: provider.default_base_url,
  custom_models: [],
  codex_command: provider.provider_id === "codexcli" ? "codex" : provider.provider_id === "antigravity" ? "agy" : "",
}]));

const runtimeConfiguration = {
  accounts: {
    ...accounts,
    deepseek: { ...accounts.deepseek, api_key: "********", custom_models: ["deepseek-novel"] },
  },
  stages: {
    planner: { provider_id: "codexcli", model: "gpt-5-codex" },
    writer: { provider_id: "deepseek", model: "retired-but-stored-model" },
  },
  image: { enabled: false, api_key: "", base_url: "", model: "" },
};

const untested = { status: "untested", heading: "尚未检测", message: "请先测试模型。", tone: "neutral", can_continue: false, actions: [{ id: "test", label: "测试模型" }] };
const ready = { status: "ready", heading: "模型可用", message: "连接正常，可以继续创作。", tone: "success", can_continue: true, actions: [{ id: "test", label: "重新检测" }] };

async function routeConfig(page: Page, onPut?: (payload: any) => void) {
  await page.route("**/runtime-settings/product/providers", (route) => route.fulfill({ json: providerCatalog }));
  await page.route("**/runtime-settings/product", async (route) => {
    if (route.request().method() === "PUT") onPut?.(route.request().postDataJSON());
    await route.fulfill({ json: runtimeConfiguration });
  });
  await page.route("**/runtime-settings/product/model-status", (route) => route.fulfill({ json: untested }));
  await page.route("**/runtime-settings/product/discover-models", (route) => route.fulfill({ json: {
    message: "请选择需要使用的模型，再测试连接。",
    models: [
      { name: "deepseek-chat", selectable: true, can_test: true, message: "请先测试模型" },
      { name: "text-embedding-3-large", selectable: false, can_test: false, message: "此模型不适合文本写作" },
      { name: "vendor-new-chat", selectable: true, can_test: true, message: "请先测试模型" },
    ],
  } }));
}

test("ordinary config receives product responses and only explicitly tests the current model", async ({ page }) => {
  await routeConfig(page);
  const requests: string[] = [];
  const refreshes: any[] = [];
  page.on("request", (request) => { if (request.url().includes("runtime-settings")) requests.push(request.url()); });
  await page.route("**/runtime-settings/product/test-model", async (route) => {
    refreshes.push(route.request().postDataJSON());
    await route.fulfill({ json: ready });
  });
  await page.goto("/config");
  const panel = page.getByRole("region", { name: "正文写作使用状态", exact: true });
  await expect(panel.getByText("尚未检测")).toBeVisible();
  expect(refreshes).toHaveLength(0);
  await page.getByLabel("正文写作模型").selectOption("deepseek-novel");
  await panel.getByRole("button", { name: "测试模型", exact: true }).click();
  await expect(panel.getByText("模型可用")).toBeVisible();
  expect(refreshes[0].settings.stages.writer.model).toBe("deepseek-novel");
  expect(requests.every((url) => url.includes("/runtime-settings/product"))).toBe(true);
  await expect(page.locator("textarea")).toHaveCount(0);
  await expect(page.getByRole("table")).toHaveCount(0);
  for (const forbidden of ["provenance", "verified_at", "expires_at", "best_effort", "Temperature", "Thinking", "JSON 模式", "上下文窗口", "流式读取", "单次调用超时", "高级设置"]) {
    await expect(page.locator(".config-shell")).not.toContainText(forbidden);
  }
  await page.screenshot({ path: "test-results/config-model-usability.png", fullPage: true });
});

test("editing a model discards a late test result", async ({ page }) => {
  await routeConfig(page);
  let release: () => void = () => {};
  const pending = new Promise<void>((resolve) => { release = resolve; });
  let requested = false;
  await page.route("**/runtime-settings/product/test-model", async (route) => {
    requested = true;
    await pending;
    await route.fulfill({ json: ready });
  });
  await page.goto("/config");
  const panel = page.getByRole("region", { name: "正文写作使用状态", exact: true });
  await expect(panel.getByText("尚未检测")).toBeVisible();
  await panel.getByRole("button").click();
  await expect.poll(() => requested).toBe(true);
  await page.getByLabel("正文写作模型").selectOption("deepseek-novel");
  await expect(panel.getByText("尚未检测")).toBeVisible();
  release();
  await expect(panel.getByRole("heading")).toContainText("deepseek-novel");
  await expect(panel.getByText("模型可用")).toHaveCount(0);
});

test("repair actions and explanations come from the backend", async ({ page }) => {
  await routeConfig(page);
  const blocked = { status: "blocked", heading: "请先处理连接问题", message: "当前模型暂时无法写作，请检查密钥。", tone: "warning", can_continue: false,
    actions: [{ id: "edit_connection", label: "去检查密钥" }, { id: "choose_model", label: "改用其他模型" }, { id: "test", label: "处理后重新检测" }] };
  await page.route("**/runtime-settings/product/model-status", (route) => route.fulfill({ json: blocked }));
  await page.goto("/config");
  const panel = page.getByRole("region", { name: "正文写作使用状态", exact: true });
  await expect(panel.getByText(blocked.message)).toBeVisible();
  await panel.getByRole("button", { name: "改用其他模型" }).click();
  await expect(page.getByLabel("正文写作模型")).toBeFocused();
  await panel.getByRole("button", { name: "去检查密钥" }).click();
  await expect(page.getByLabel("DeepSeek API 密钥", { exact: true })).toBeFocused();
});

test("/config uses provider accounts and exactly two stage bindings", async ({ page }) => {
  let saved: any = null;
  await routeConfig(page, (payload) => { saved = payload; });
  await page.goto("/config");

  await expect(page.getByRole("navigation", { name: "供应商列表" }).getByRole("button")).toHaveCount(16);
  await expect(page.getByLabel("剧情规划供应商")).toHaveValue("codexcli");
  await expect(page.getByLabel("正文写作供应商")).toHaveValue("deepseek");
  await expect(page.getByLabel("正文写作模型")).toHaveValue("retired-but-stored-model");
  await expect(page.getByText("规划故事与撰写正文可以选择不同模型。")).toBeVisible();
  await expect(page.getByText(/记忆模型/)).toHaveCount(0);

  await page.getByLabel("正文写作模型").selectOption("deepseek-novel");
  await page.getByRole("button", { name: "统一保存" }).click();
  await expect.poll(() => saved).not.toBeNull();
  expect(saved.stages.writer).toEqual({ provider_id: "deepseek", model: "deepseek-novel" });
  expect(saved.providers).toBeUndefined();
  expect(saved.provider).toBeUndefined();
});

test("Antigravity CLI has an independent command field", async ({ page }) => {
  await routeConfig(page);
  await page.goto("/config");

  await page.getByRole("button", { name: /Antigravity CLI/ }).click();
  await expect(page.getByLabel("Antigravity CLI 命令")).toHaveValue("agy");
  await expect(page.getByRole("region", { name: "供应商账号" }).getByLabel(/API 密钥/)).toHaveCount(0);
});

test("each provider keeps its own key, endpoint, models and connection test", async ({ page }) => {
  let revealPayload: any = null;
  let testPayload: any = null;
  await routeConfig(page);
  await page.route("**/runtime-settings/reveal-api-key", async (route) => {
    revealPayload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "cache-control": "no-store" }, body: JSON.stringify({ api_key: "deepseek-secret" }) });
  });
  await page.route("**/runtime-settings/product/test-model", async (route) => {
    testPayload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ready) });
  });

  await page.goto("/config");
  await page.getByRole("button", { name: /DeepSeek/ }).click();
  await expect(page.getByLabel("DeepSeek API 地址")).toHaveValue("https://api.deepseek.com/v1");
  await expect(page.getByLabel("DeepSeek 自定义模型")).toHaveValue("deepseek-novel");
  await page.getByRole("button", { name: "显示 DeepSeek API 密钥" }).click();
  await expect.poll(() => revealPayload).toEqual({ provider_id: "deepseek" });
  await expect(page.getByLabel("DeepSeek API 密钥", { exact: true })).toHaveValue("deepseek-secret");
  await page.getByRole("button", { name: "测试连接" }).click();
  await expect.poll(() => testPayload).not.toBeNull();
  expect(testPayload.stage).toBe("writer");
  expect(testPayload.settings.accounts.deepseek).toMatchObject({ api_key: "********", custom_models: ["deepseek-novel"] });
  await expect(page.getByText(ready.message)).toBeVisible();

  await page.getByRole("button", { name: /OpenAI/, exact: false }).first().click();
  await expect(page.getByLabel("OpenAI API 密钥", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("OpenAI 自定义模型")).toHaveValue("");
});

test("discovered models require explicit selection and block incompatible entries", async ({ page }) => {
  let testedModel = "";
  await routeConfig(page);
  await page.route("**/runtime-settings/product/test-model", async (route) => {
    testedModel = route.request().postDataJSON().settings.stages.writer.model;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ready) });
  });
  await page.goto("/config");
  await page.getByRole("button", { name: /DeepSeek/ }).click();
  await page.getByRole("button", { name: "获取模型列表" }).click();

  await expect(page.getByText("此模型不适合文本写作", { exact: true })).toBeVisible();
  await expect(page.getByLabel("启用模型 deepseek-chat")).not.toBeChecked();
  await expect(page.getByLabel("启用模型 text-embedding-3-large")).toBeDisabled();

  await page.getByLabel("启用模型 deepseek-chat").check();
  await expect(page.getByLabel("DeepSeek 自定义模型")).toHaveValue("deepseek-novel, deepseek-chat");
  await page.getByRole("button", { name: "测试模型 vendor-new-chat" }).click();
  await expect.poll(() => testedModel).toBe("vendor-new-chat");
});

test("save blocks missing keys, invalid endpoints and an empty Codex command", async ({ page }) => {
  let putCount = 0;
  await routeConfig(page, () => { putCount += 1; });
  await page.goto("/config");

  await page.getByLabel("剧情规划供应商").selectOption("openai");
  await page.getByRole("button", { name: "统一保存" }).click();
  await expect(page.getByText("OpenAI API 密钥不能为空")).toBeVisible();

  await page.getByRole("button", { name: /OpenAI/, exact: false }).first().click();
  await page.getByLabel("OpenAI API 密钥", { exact: true }).fill("sk-openai");
  await page.getByLabel("正文写作供应商").selectOption("custom_openai");
  await page.getByRole("button", { name: /自定义 OpenAI/ }).click();
  await page.getByLabel("自定义 OpenAI 兼容接口 API 密钥", { exact: true }).fill("sk-custom");
  await page.getByLabel("自定义 OpenAI 兼容接口 自定义模型").fill("novel-model");
  await page.getByLabel("正文写作供应商").selectOption("custom_openai");
  await page.getByLabel("正文写作模型").selectOption("novel-model");
  await page.getByRole("button", { name: "统一保存" }).click();
  await expect(page.getByText("自定义 OpenAI 兼容接口 API 地址格式不正确")).toBeVisible();

  await page.getByLabel("正文写作供应商").selectOption("codexcli");
  await page.getByRole("button", { name: /Codex CLI/ }).click();
  await page.getByLabel("Codex CLI 命令").fill("");
  await page.getByRole("button", { name: "统一保存" }).click();
  await expect(page.getByText("Codex CLI 命令不能为空")).toBeVisible();
  expect(putCount).toBe(0);
});

test("cover image settings remain independent from text accounts", async ({ page }) => {
  let saved: any = null;
  await routeConfig(page, (payload) => { saved = payload; });
  await page.goto("/config");

  await page.getByLabel("启用封面图片模型").check();
  await page.getByLabel("封面图片 API 地址").fill("http://127.0.0.1:8188/v1");
  await page.getByLabel("封面图片模型名称").fill("cover-v2");
  await page.getByLabel("封面图片 API 密钥", { exact: true }).fill("image-secret");
  await page.getByRole("button", { name: "统一保存" }).click();
  await expect.poll(() => saved).not.toBeNull();
  expect(saved.image).toEqual({ enabled: true, api_key: "image-secret", base_url: "http://127.0.0.1:8188/v1", model: "cover-v2" });
  expect(saved.accounts.deepseek.api_key).toBe("********");
});
