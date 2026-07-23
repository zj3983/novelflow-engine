import { expect, test } from "@playwright/test";

const runtimeConfiguration = {
  provider: "codexcli",
  providers: {
    codexcli: {
      api_key: "",
      base_url: "",
      codex_command: "codex",
      planner: "gpt-5.6-sol",
      writer: "gpt-5.6-sol",
      memory: "gpt-5.6-terra",
    },
    openai: {
      api_key: "sk-test",
      base_url: "https://api.example.test/v1",
      codex_command: "",
      planner: "openai-planner",
      writer: "openai-writer",
      memory: "openai-memory",
    },
  },
  temperature: 0.7,
  new_character_policy: "Director review",
};

test("/config displays the CLI version and the three real writing stages", async ({ page }) => {
  let saved = structuredClone(runtimeConfiguration);
  let testedPayload: Record<string, unknown> | null = null;

  await page.route("**/runtime-settings/reveal-api-key", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "cache-control": "no-store" },
      body: JSON.stringify({ api_key: "sk-test" }),
    });
  });
  await page.route("**/runtime-settings", async (route) => {
    if (route.request().method() === "PUT") {
      saved = route.request().postDataJSON();
    }
    const response = structuredClone(saved);
    if (response.providers.openai.api_key) response.providers.openai.api_key = "********";
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) });
  });
  await page.route("**/runtime-settings/cli-info", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        available: true,
        command: "codex",
        version: "codex-cli 0.144.5",
        latest_version: "0.144.5",
        update_status: "current",
        models: ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"],
      }),
    });
  });
  await page.route("**/runtime-settings/test", async (route) => {
    testedPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        provider: "openai",
        stage: "writer",
        model: "openai-writer-next",
        message: "provider=openai, stage=writer, model=openai-writer-next: OpenAI 连接正常",
      }),
    });
  });

  await page.goto("/config");

  await expect(page.getByText("codex-cli 0.144.5", { exact: true })).toBeVisible();
  await expect(page.getByText("已是最新版本", { exact: true })).toBeVisible();
  await expect(page.getByLabel("剧情规划模型")).toHaveValue("gpt-5.6-sol");
  await expect(page.getByLabel("正文写作模型")).toHaveValue("gpt-5.6-sol");
  await expect(page.getByLabel("记忆回写模型")).toHaveValue("gpt-5.6-terra");
  await expect(page.getByLabel("剧情规划模型").locator("option")).toHaveCount(4);
  await expect(page.getByLabel("剧情规划模型").getByRole("option", { name: "gpt-5.4" })).toHaveCount(0);
  await expect(page.getByText("全局默认模型")).toHaveCount(0);
  await expect(page.getByText("角色代理模型")).toHaveCount(0);

  await page.getByLabel("模型提供方").selectOption("openai");
  await expect(page.getByLabel("全局 API 密钥")).toHaveValue("");
  await expect(page.getByText("密钥已保存", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "显示 API 密钥" }).click();
  await expect(page.getByLabel("全局 API 密钥")).toHaveValue("sk-test");
  await page.getByRole("button", { name: "隐藏 API 密钥" }).click();
  await expect(page.getByLabel("全局 API 密钥")).toHaveValue("");
  await expect(page.getByLabel("正文写作模型")).toHaveValue("openai-writer");
  await page.getByLabel("正文写作模型").fill("openai-writer-next");
  await page.getByRole("button", { name: "测试正文写作" }).click();

  await expect.poll(() => testedPayload).not.toBeNull();
  expect(testedPayload).toMatchObject({
    stage: "writer",
    runtime_settings: {
      provider: "openai",
      providers: { openai: { writer: "openai-writer-next" } },
    },
  });
  await expect(page.getByText(/OpenAI 连接正常/)).toBeVisible();

  await page.getByRole("button", { name: "统一保存" }).click();
  expect(saved.provider).toBe("openai");
  expect(saved.providers.openai.writer).toBe("openai-writer-next");
});

test("/config reports backend save failures instead of keeping a browser-only copy", async ({ page }) => {
  await page.route("**/runtime-settings", async (route) => {
    if (route.request().method() === "PUT") {
      await route.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"save failed"}' });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(runtimeConfiguration) });
  });
  await page.route("**/runtime-settings/cli-info", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ available: false, command: "codex", version: "", latest_version: "", update_status: "unknown", models: [] }),
    });
  });

  await page.goto("/config");
  await page.getByRole("button", { name: "统一保存" }).click();

  await expect(page.getByText("失败", { exact: true })).toBeVisible();
  await expect(page.getByText(/save failed/)).toBeVisible();
});
