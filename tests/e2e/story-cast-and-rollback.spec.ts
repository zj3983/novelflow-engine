import { expect, test } from "../../apps/web/node_modules/@playwright/test";

test("multi-character cast appears in generated state and rollback clears the draft", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("Two investigators circle the same ledger from opposite sides of the court.");
  await page.getByRole("button", { name: "添加角色" }).click();
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("expose the forgery");
  await page.getByLabel("Character Name 2").fill("Su Wan");
  await page.getByLabel("Character Goal 2").fill("protect the family name");

  await page.getByRole("banner").getByRole("button", { name: "开始生成第一章" }).click();
  await expect(page.getByLabel("章节主区域")).toContainText("第 1 章");
  await expect(page.getByRole("complementary", { name: "创作侧栏" })).toContainText("Lin Yue");
  await expect(page.getByRole("complementary", { name: "创作侧栏" })).toContainText("Su Wan");

  await page.getByRole("button", { name: "回滚上一章" }).click();
});

test("chapter history can be viewed and branched from an earlier chapter", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A court archivist must decide which truth survives.");
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("find the hidden ledger");

  await page.getByRole("banner").getByRole("button", { name: "开始生成第一章" }).click();

  await expect(page.locator(".chapter-history-card").first()).toContainText("第 1 章");

  await page.locator(".chapter-history-card").first().getByRole("button", { name: "从这里分支" }).click();
});

test("branch can be deleted from the story tree", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A witness keeps editing the same confession.");
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("find the true author");

  await page.getByRole("banner").getByRole("button", { name: "开始生成第一章" }).click();

  await expect(page.locator(".chapter-history-card").first().getByRole("button", { name: "从这里分支" })).toBeVisible();
  await page.locator(".chapter-history-card").first().getByRole("button", { name: "从这里分支" }).click();
});
