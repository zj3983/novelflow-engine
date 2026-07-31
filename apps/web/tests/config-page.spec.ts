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
  image: {
    enabled: true,
    api_key: "********",
    base_url: "https://images.example.test/v1",
    model: "cover-art-v1",
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
  await expect(page.getByRole("region", { name: "模型执行方式" }).getByText("密钥已保存", { exact: true })).toBeVisible();
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

test("/config keeps cover-image configuration independent from text providers", async ({ page }) => {
  let saved = structuredClone(runtimeConfiguration);
  let revealPayload: Record<string, unknown> | null = null;

  await page.route("**/runtime-settings/reveal-api-key", async (route) => {
    revealPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ api_key: "image-secret" }),
    });
  });
  await page.route("**/runtime-settings", async (route) => {
    if (route.request().method() === "PUT") saved = route.request().postDataJSON();
    const response = structuredClone(saved);
    if (response.providers.openai.api_key) response.providers.openai.api_key = "********";
    if (response.image.api_key) response.image.api_key = "********";
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) });
  });
  await page.route("**/runtime-settings/cli-info", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ available: false, command: "codex", version: "", latest_version: "", update_status: "unknown", models: [] }),
    });
  });

  await page.goto("/config");

  const globalCard = page.getByRole("region", { name: "模型执行方式" });
  const imageCard = page.getByRole("region", { name: "封面图片模型" });
  const strategyCard = page.getByRole("region", { name: "写作阶段模型" });
  await expect(imageCard).toBeVisible();
  await expect(globalCard).toBeVisible();
  await expect(strategyCard).toBeVisible();
  const cardLabels = await page.getByRole("region").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("aria-label")));
  expect(cardLabels.indexOf("模型执行方式")).toBeLessThan(cardLabels.indexOf("封面图片模型"));
  expect(cardLabels.indexOf("封面图片模型")).toBeLessThan(cardLabels.indexOf("写作阶段模型"));
  await expect(imageCard.getByText("独立于正文模型配置", { exact: false })).toBeVisible();
  await expect(page.getByLabel("启用封面图片模型")).toBeChecked();
  await expect(page.getByLabel("封面图片 API 密钥", { exact: true })).toHaveValue("");
  await expect(imageCard.getByText("密钥已保存", { exact: true })).toBeVisible();

  await page.getByLabel("封面图片 API 地址").fill("http://127.0.0.1:8188/v1");
  await page.getByLabel("封面图片模型名称").fill("cover-art-v2");
  await page.getByLabel("启用封面图片模型").uncheck();
  await page.getByRole("button", { name: "统一保存" }).click();

  expect(saved.image).toEqual({
    enabled: false,
    api_key: "********",
    base_url: "http://127.0.0.1:8188/v1",
    model: "cover-art-v2",
  });
  expect(saved.provider).toBe(runtimeConfiguration.provider);
  expect(saved.providers).toEqual({
    ...runtimeConfiguration.providers,
    openai: { ...runtimeConfiguration.providers.openai, api_key: "********" },
  });

  await page.getByLabel("启用封面图片模型").check();
  await page.getByRole("button", { name: "显示封面图片 API 密钥" }).click();
  await expect.poll(() => revealPayload).toEqual({ provider: "image" });
  await expect(page.getByLabel("封面图片 API 密钥", { exact: true })).toHaveValue("image-secret");
  await page.getByRole("button", { name: "隐藏封面图片 API 密钥" }).click();
  await expect(page.getByLabel("封面图片 API 密钥", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "统一保存" }).click();
  expect(saved.image.api_key).toBe("********");
});

test("/config normalizes missing legacy image settings and validates enabled cover image settings", async ({ page }) => {
  let putCount = 0;
  await page.route("**/runtime-settings", async (route) => {
    if (route.request().method() === "PUT") putCount += 1;
    const { image: _image, ...legacy } = runtimeConfiguration;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(legacy) });
  });
  await page.route("**/runtime-settings/cli-info", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ available: false, command: "codex", version: "", latest_version: "", update_status: "unknown", models: [] }) });
  });

  await page.goto("/config");
  await expect(page.getByLabel("启用封面图片模型")).not.toBeChecked();
  await expect(page.getByLabel("封面图片 API 地址")).toHaveValue("");
  await expect(page.getByLabel("封面图片模型名称")).toHaveValue("");
  await page.getByLabel("启用封面图片模型").check();
  await page.getByRole("button", { name: "统一保存" }).click();
  await expect(page.getByText("封面图片 API 地址不能为空")).toBeVisible();
  await expect(page.getByText("封面图片模型名称不能为空")).toBeVisible();
  await expect(page.getByText("封面图片 API 密钥不能为空")).toBeVisible();
  expect(putCount).toBe(0);
});

test("/config scopes cover-key reveal failures to the image card and allows retry", async ({ page }) => {
  let revealAttempts = 0;
  await page.route("**/runtime-settings/reveal-api-key", async (route) => {
    revealAttempts += 1;
    if (revealAttempts === 1) {
      await route.fulfill({ status: 500, contentType: "application/json", body: "image reveal failed" });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ api_key: "recovered-image-key" }) });
  });
  await page.route("**/runtime-settings", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(runtimeConfiguration) });
  });
  await page.route("**/runtime-settings/cli-info", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ available: false, command: "codex", version: "", latest_version: "", update_status: "unknown", models: [] }) });
  });

  await page.goto("/config");
  const imageCard = page.getByRole("region", { name: "封面图片模型" });
  await imageCard.getByRole("button", { name: "显示封面图片 API 密钥" }).click();
  await expect(imageCard.getByText(/image reveal failed/)).toBeVisible();
  await expect(page.getByRole("region", { name: "模型执行方式" }).getByText(/image reveal failed/)).toHaveCount(0);
  await imageCard.getByRole("button", { name: "显示封面图片 API 密钥" }).click();
  await expect(imageCard.getByLabel("封面图片 API 密钥", { exact: true })).toHaveValue("recovered-image-key");
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
