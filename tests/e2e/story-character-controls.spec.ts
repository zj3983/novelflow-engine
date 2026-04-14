import { expect, test } from "../../apps/web/node_modules/@playwright/test";

test("character editor sends frozen protagonist into generation flow", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A court scholar traces a ledger through the archive.");
  await page.getByLabel("Character Name 1").fill("Pei An");
  await page.getByLabel("Character Goal 1").fill("protect the ledger");
  await page.getByLabel("Freeze Character").check();

  await page.getByRole("button", { name: "生成下一章" }).click();

  await expect(page.getByText("主角：Pei An")).toBeVisible();
  await expect(page.getByText("冻结：是")).toBeVisible();
});

test("relationship editor carries trust and tension into generated state", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "添加角色" }).click();
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("expose the forgery");
  await page.getByLabel("Character Name 2").fill("Su Wan");
  await page.getByLabel("Character Goal 2").fill("protect the family name");
  await page.getByLabel("Relationship Target 1").fill("Su Wan");
  await page.getByLabel("Relationship Bond 1").fill("uneasy alliance");
  await page.getByLabel("Trust Level 1").fill("0.4");
  await page.getByLabel("Tension Level 1").fill("0.9");

  await page.getByRole("button", { name: "生成下一章" }).click();

  await expect(page.getByText("关系：Su Wan（uneasy alliance）")).toBeVisible();
  await expect(page.getByText("信任/紧张：0.3 / 1")).toBeVisible();
  await expect(page.getByRole("article")).toContainText("needles the alliance");
});

test("workbench displays lifecycle metadata for a character", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("An archivist enters the story under a false name.");
  await page.getByLabel("Character Name 1").fill("Old Archivist");
  await page.getByLabel("Character Goal 1").fill("hide the witness");
  await page.getByRole("button", { name: "生成下一章" }).click();

  await expect(page.getByText("生命周期：active")).toBeVisible();
});

test("agent settings panel exposes model and mode controls", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("button", { name: "代理设置" })).toBeVisible();

  await page.getByLabel("Agent Mode").selectOption("LLM-assisted");
  await page.getByLabel("Character Model").fill("gpt-5.4");
  await page.getByLabel("Director Model").fill("gpt-5.4");
  await page.getByLabel("Writer Model").fill("gpt-5.4-mini");
  await page.getByLabel("Memory Model").fill("gpt-5.4");
  await page.getByLabel("Temperature").fill("0.85");
  await page.getByLabel("New Character Policy").selectOption("Director review");

  await expect(page.getByText("模式：LLM 协助模式", { exact: true })).toBeVisible();
  await expect(page.getByText("角色模型：gpt-5.4", { exact: true })).toBeVisible();
  await expect(page.getByText("新角色策略：导演审核", { exact: true })).toBeVisible();
  await expect(page.getByText("记忆模型：gpt-5.4", { exact: true })).toBeVisible();
  await expect(
    page.getByText("运行模式：LLM 协助模式，失败时自动回退到规则路径", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("导演代理：LLM 协助模式", { exact: true })).toBeVisible();
});

test("api configuration panel saves global credentials", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("API 配置", { exact: true })).toBeVisible();
  const originalApiKey = await page.getByLabel("OpenAI API Key").inputValue();
  const originalBaseUrl = await page.getByLabel("OpenAI Base URL").inputValue();
  await page.getByLabel("OpenAI API Key").fill("sk-test-123");
  await page.getByLabel("OpenAI Base URL").fill("https://api.example.com/v1");
  await page.getByRole("button", { name: "保存 API 配置" }).click();

  await expect(page.getByText("API 配置已保存", { exact: true })).toBeVisible();
  await page.reload();

  await expect(page.getByLabel("OpenAI API Key")).toHaveValue("sk-test-123");
  await expect(page.getByLabel("OpenAI Base URL")).toHaveValue("https://api.example.com/v1");

  await page.getByLabel("OpenAI API Key").fill(originalApiKey);
  await page.getByLabel("OpenAI Base URL").fill(originalBaseUrl);
  await page.getByRole("button", { name: "保存 API 配置" }).click();
});

test("api configuration panel supports agent-specific overrides", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("角色代理 API Key").fill("sk-character-123");
  await page.getByLabel("角色代理 Base URL").fill("https://character.example.com/v1");
  await page.getByLabel("导演代理 API Key").fill("sk-director-123");
  await page.getByLabel("导演代理 Base URL").fill("https://director.example.com/v1");
  await page.getByRole("button", { name: "保存 API 配置" }).click();

  await expect(page.getByText("API 配置已保存", { exact: true })).toBeVisible();
  await page.reload();

  await expect(page.getByLabel("角色代理 API Key")).toHaveValue("sk-character-123");
  await expect(page.getByLabel("角色代理 Base URL")).toHaveValue(
    "https://character.example.com/v1",
  );
  await expect(page.getByLabel("导演代理 API Key")).toHaveValue("sk-director-123");
  await expect(page.getByLabel("导演代理 Base URL")).toHaveValue(
    "https://director.example.com/v1",
  );
});

test("api configuration panel can test an agent connection", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("角色代理 API Key").fill("sk-character-123");
  await page.getByLabel("角色代理 Base URL").fill("https://character.example.com/v1");
  await page.getByRole("button", { name: "角色代理 测试连接" }).click();

  await expect(page.getByText("角色代理 连接正常", { exact: true })).toBeVisible();
});

test("api configuration panel saves a global default model", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("全局默认模型").fill("gpt-global");
  await page.getByRole("button", { name: "保存 API 配置" }).click();

  await page.reload();
  await expect(page.getByLabel("全局默认模型")).toHaveValue("gpt-global");
});

test("agent settings persist into story generation payload", async ({ page }) => {
  // Force the workbench onto the deterministic frontend mock path so we can
  // verify settings persistence even when the API server is not running.
  await page.route("http://127.0.0.1:8000/**", (route) => route.abort());
  await page.goto("/");

  await page.getByLabel("Agent Mode").selectOption("LLM-assisted");
  await page.getByLabel("Character Model").fill("gpt-5.4-mini");
  await page.getByLabel("Director Model").fill("gpt-5.4");
  await page.getByLabel("Writer Model").fill("gpt-5.4");
  await page.getByLabel("Memory Model").fill("gpt-5.4");
  await page.getByLabel("Temperature").fill("0.85");
  await page
    .getByLabel("New Character Policy")
    .selectOption("Auto-approve named candidates");

  await page.getByRole("button", { name: "生成下一章" }).click();

  await page.getByText("详细数据", { exact: true }).click();
  const bundleDebug = page.locator(
    'section[aria-label="Chapter Draft Panel"] details pre',
  );
  await expect(bundleDebug).toContainText('"agent_settings"');
  await expect(bundleDebug).toContainText('"mode": "LLM-assisted"');
  await expect(bundleDebug).toContainText('"memory_model": "gpt-5.4"');
  await expect(bundleDebug).toContainText(
    '"new_character_policy": "Auto-approve named candidates"',
  );
  await expect(page.locator(".agent-runtime")).toContainText("角色代理：回退");
  await expect(page.locator(".agent-runtime")).toContainText("记忆代理：回退，第 1 章");
});
