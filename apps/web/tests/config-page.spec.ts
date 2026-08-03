import { expect, test, type Page } from "@playwright/test";

const providerCatalog = {
  schema_version: "provider-catalog/v1",
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
    ["custom_openai", "自定义 OpenAI 兼容接口", "openai_compatible", "", [], true, true],
  ].map(([provider_id, name, protocol, default_base_url, models, requires_api_key, base_url_editable]) => ({
    provider_id, name, protocol, default_base_url, planner_models: models, writer_models: models,
    requires_api_key, base_url_editable, help_text: `${name} 配置说明`,
  })),
};

const accounts = Object.fromEntries(providerCatalog.providers.map((provider) => [provider.provider_id, {
  api_key: provider.requires_api_key ? "" : "",
  base_url: provider.default_base_url,
  custom_models: [],
  codex_command: provider.provider_id === "codexcli" ? "codex" : "",
}]));

const runtimeConfiguration = {
  schema_version: "runtime-config/v2",
  accounts: {
    ...accounts,
    deepseek: { ...accounts.deepseek, api_key: "********", custom_models: ["deepseek-novel"] },
  },
  stages: {
    planner: { provider_id: "codexcli", model: "gpt-5-codex" },
    writer: { provider_id: "deepseek", model: "retired-but-stored-model" },
  },
  image: { enabled: false, api_key: "", base_url: "", model: "" },
  temperature: 0.7,
  new_character_policy: "Director review",
};

async function routeConfig(page: Page, onPut?: (payload: any) => void) {
  await page.route("**/runtime-settings/providers", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(providerCatalog) }));
  await page.route("**/runtime-settings", async (route) => {
    if (route.request().method() === "PUT") onPut?.(route.request().postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(runtimeConfiguration) });
  });
}

test("/config uses provider accounts and exactly two stage bindings", async ({ page }) => {
  let saved: any = null;
  await routeConfig(page, (payload) => { saved = payload; });
  await page.goto("/config");

  await expect(page.getByRole("navigation", { name: "供应商列表" }).getByRole("button")).toHaveCount(15);
  await expect(page.getByLabel("剧情规划供应商")).toHaveValue("codexcli");
  await expect(page.getByLabel("正文写作供应商")).toHaveValue("deepseek");
  await expect(page.getByLabel("正文写作模型")).toHaveValue("retired-but-stored-model");
  await expect(page.getByText(/状态提取跟随剧情规划/)).toBeVisible();
  await expect(page.getByText(/记忆模型/)).toHaveCount(0);

  await page.getByLabel("正文写作模型").selectOption("deepseek-novel");
  await page.getByRole("button", { name: "统一保存" }).click();
  await expect.poll(() => saved).not.toBeNull();
  expect(saved.schema_version).toBe("runtime-config/v2");
  expect(saved.stages.writer).toEqual({ provider_id: "deepseek", model: "deepseek-novel" });
  expect(saved.providers).toBeUndefined();
  expect(saved.provider).toBeUndefined();
});

test("each provider keeps its own key, endpoint, models and connection test", async ({ page }) => {
  let revealPayload: any = null;
  let testPayload: any = null;
  await routeConfig(page);
  await page.route("**/runtime-settings/reveal-api-key", async (route) => {
    revealPayload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "application/json", headers: { "cache-control": "no-store" }, body: JSON.stringify({ api_key: "deepseek-secret" }) });
  });
  await page.route("**/runtime-settings/test", async (route) => {
    testPayload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, provider: "deepseek", stage: "writer", model: "retired-but-stored-model", message: "连接成功" }) });
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
  expect(testPayload.runtime_settings.accounts.deepseek).toMatchObject({ api_key: "********", custom_models: ["deepseek-novel"] });
  await expect(page.getByText("连接成功")).toBeVisible();

  await page.getByRole("button", { name: /OpenAI/, exact: false }).first().click();
  await expect(page.getByLabel("OpenAI API 密钥", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("OpenAI 自定义模型")).toHaveValue("");
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
