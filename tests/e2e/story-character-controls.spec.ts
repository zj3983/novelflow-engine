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

test("config panel exposes only real writing stage model controls", async ({ page }) => {
  await page.goto("/config");

  await expect(page.getByRole("heading", { name: "写作阶段模型" })).toBeVisible();
  await expect(page.getByLabel("剧情规划模型")).toBeVisible();
  await expect(page.getByLabel("正文写作模型")).toBeVisible();
  await expect(page.getByLabel("记忆回写模型")).toBeVisible();
  await expect(page.getByText("角色代理模型")).toHaveCount(0);
  await expect(page.getByText("全局默认模型")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "统一保存" })).toBeVisible();
});

test("provider stage settings persist across reloads", async ({ page }) => {
  await page.route("http://127.0.0.1:8000/runtime-settings", (route) => route.abort());
  await page.goto("/config");
  await page.locator("#config-global-provider").selectOption("openai");

  await page.locator("#config-global-api-key").fill("sk-test-123");
  await page.locator("#config-global-base-url").fill("https://api.example.com/v1");
  await page.getByLabel("剧情规划模型").fill("planner-model");
  await page.getByLabel("正文写作模型").fill("writer-model");
  await page.getByLabel("记忆回写模型").fill("memory-model");
  await page.getByRole("button", { name: "统一保存" }).click();

  await page.reload();
  await expect(page.locator("#config-global-api-key")).toHaveValue("sk-test-123");
  await expect(page.locator("#config-global-base-url")).toHaveValue("https://api.example.com/v1");
  await expect(page.getByLabel("剧情规划模型")).toHaveValue("planner-model");
  await expect(page.getByLabel("正文写作模型")).toHaveValue("writer-model");
  await expect(page.getByLabel("记忆回写模型")).toHaveValue("memory-model");
});
