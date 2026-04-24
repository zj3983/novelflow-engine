import { expect, test } from "../../apps/web/node_modules/@playwright/test";

test("character editor sends frozen protagonist into generation flow", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A court scholar traces a ledger through the archive.");
  await page.getByLabel("Character Name 1").fill("Pei An");
  await page.getByLabel("Character Goal 1").fill("protect the ledger");
  await page.getByLabel("Freeze Character").check();

  await page.getByRole("banner").getByRole("button", { name: "开始生成第一章" }).click();

  await expect(page.getByLabel("章节主区域")).toContainText("第 1 章");
  await expect(page.getByRole("complementary", { name: "创作侧栏" })).toContainText("Pei An");
});

test("generation is disabled when the outline is empty", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("");

  await expect(page.getByRole("banner").getByRole("button", { name: "开始生成第一章" })).toBeDisabled();
});

test("generation is disabled when there is no valid character", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Character Name 1").fill("");
  await page.getByLabel("Character Goal 1").fill("");

  await expect(page.getByRole("banner").getByRole("button", { name: "开始生成第一章" })).toBeDisabled();
});

test("relationship editor carries trust and tension into generated state", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("Two investigators circle the same ledger from opposite sides of the court.");
  await page.getByRole("button", { name: "添加角色" }).click();
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("expose the forgery");
  await page.getByLabel("Character Name 2").fill("Su Wan");
  await page.getByLabel("Character Goal 2").fill("protect the family name");
  await page.getByLabel("Relationship Target 1").fill("Su Wan");
  await page.getByLabel("Relationship Bond 1").fill("uneasy alliance");
  await page.getByLabel("Trust Level 1").fill("0.4");
  await page.getByLabel("Tension Level 1").fill("0.9");

  await page.getByRole("banner").getByRole("button", { name: "开始生成第一章" }).click();

  await expect(page.getByLabel("章节主区域")).toContainText("第 1 章");
  await expect(page.getByRole("complementary", { name: "创作侧栏" })).toContainText("Lin Yue");
  await expect(page.getByRole("complementary", { name: "创作侧栏" })).toContainText("Su Wan");
});

test("workbench displays lifecycle metadata for a character", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("An archivist enters the story under a false name.");
  await page.getByLabel("Character Name 1").fill("Old Archivist");
  await page.getByLabel("Character Goal 1").fill("hide the witness");
  await page.getByLabel("Freeze Character").check();
  await page.getByRole("banner").getByRole("button", { name: "开始生成第一章" }).click();

  await expect(page.getByLabel("章节主区域")).toContainText("第 1 章");
  await expect(page.getByRole("complementary", { name: "创作侧栏" })).toContainText("Old Archivist");
  await expect(page.getByRole("complementary", { name: "创作侧栏" }).getByText("冻结")).toBeVisible();
});

test("config panel exposes model controls", async ({ page }) => {
  await page.goto("/config");

  await expect(page.getByRole("heading", { name: "配置中心" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "运行策略" })).toBeVisible();
  await expect(page.getByText("当前仅支持 LLM 协助模式")).toBeVisible();
  await expect(page.locator("#config-global-model")).toBeVisible();
  await expect(page.locator("#config-character-model")).toBeVisible();
  await expect(page.getByRole("button", { name: "统一保存" })).toBeVisible();
});

test("api configuration panel saves global credentials", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/runtime-settings", (route) => route.abort());
  await page.goto("/config");

  const originalApiKey = await page.locator("#config-global-api-key").inputValue();
  const originalBaseUrl = await page.locator("#config-global-base-url").inputValue();
  await page.locator("#config-global-api-key").fill("sk-test-123");
  await page.locator("#config-global-base-url").fill("https://api.example.com/v1");
  await page.getByRole("button", { name: "统一保存" }).click();

  await page.reload();
  await expect(page.locator("#config-global-api-key")).toHaveValue("sk-test-123");
  await expect(page.locator("#config-global-base-url")).toHaveValue("https://api.example.com/v1");

  await page.locator("#config-global-api-key").fill(originalApiKey);
  await page.locator("#config-global-base-url").fill(originalBaseUrl);
  await page.getByRole("button", { name: "统一保存" }).click();
});

test("api configuration panel supports agent-specific overrides", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/runtime-settings", (route) => route.abort());
  await page.goto("/config");

  await page.locator("#config-角色代理-api-key").fill("sk-character-123");
  await page.locator("#config-角色代理-base-url").fill("https://character.example.com/v1");
  await page.locator("#config-导演代理-api-key").fill("sk-director-123");
  await page.locator("#config-导演代理-base-url").fill("https://director.example.com/v1");
  await page.getByRole("button", { name: "统一保存" }).click();

  await page.reload();
  await expect(page.locator("#config-角色代理-api-key")).toHaveValue("sk-character-123");
  await expect(page.locator("#config-角色代理-base-url")).toHaveValue("https://character.example.com/v1");
  await expect(page.locator("#config-导演代理-api-key")).toHaveValue("sk-director-123");
  await expect(page.locator("#config-导演代理-base-url")).toHaveValue("https://director.example.com/v1");
});

test("api configuration panel can test an agent connection", async ({ page }) => {
  let called = false;
  await page.route("**/runtime-settings/test", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "content-type",
        },
        body: "",
      });
      return;
    }
    called = true;
    await route.fulfill({
      status: 200,
      headers: {
        "content-type": "application/json",
        "access-control-allow-origin": "*",
      },
      body: JSON.stringify({
        ok: true,
        agent_name: "character",
        message: "连接成功",
      }),
    });
  });
  await page.goto("/config");

  await page.locator("#config-角色代理-api-key").fill("sk-character-123");
  await page.locator("#config-角色代理-base-url").fill("https://character.example.com/v1");
  await page.getByRole("button", { name: "测试角色代理连接" }).click();

  await expect.poll(() => called).toBeTruthy();
  const characterCard = page.getByRole("article", { name: "角色代理" });
  await expect(characterCard.locator(".config-status")).toContainText("测试中");
});

test("api configuration panel saves a global default model", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/runtime-settings", (route) => route.abort());
  await page.route("http://127.0.0.1:8000/runtime-strategy", (route) => route.abort());
  await page.goto("/config");

  await page.locator("#config-global-model").fill("gpt-global");
  await page.getByRole("button", { name: "统一保存" }).click();

  await page.reload();
  await expect(page.locator("#config-global-model")).toHaveValue("gpt-global");
});

test("config settings persist across reloads", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/runtime-settings", (route) => route.abort());
  await page.goto("/config");

  await page.locator("#config-global-model").fill("gpt-5.4");
  await page.locator("#config-character-model").fill("gpt-5.4-mini");
  await page.locator("#config-director-model").fill("gpt-5.4");
  await page.locator("#config-writer-model").fill("gpt-5.4");
  await page.locator("#config-memory-model").fill("gpt-5.4");
  await page.getByRole("button", { name: "统一保存" }).click();

  await page.reload();
  await expect(page.locator("#config-global-model")).toHaveValue("gpt-5.4");
  await expect(page.locator("#config-character-model")).toHaveValue("gpt-5.4-mini");
});
