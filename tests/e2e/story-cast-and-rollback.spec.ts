import { expect, test } from "../../apps/web/node_modules/@playwright/test";

test("multi-character cast appears in generated state and rollback clears the draft", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("Two investigators circle the same ledger from opposite sides of the court.");
  await page.getByRole("button", { name: "添加角色" }).click();
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("expose the forgery");
  await page.getByLabel("Character Name 2").fill("Su Wan");
  await page.getByLabel("Character Goal 2").fill("protect the family name");

  await page.getByRole("button", { name: "生成下一章" }).click();

  await expect(page.getByText("角色表：Lin Yue, Su Wan")).toBeVisible();
  await expect(page.getByText("主角：Lin Yue")).toBeVisible();

  await page.getByRole("button", { name: "回滚章节" }).click();

  await expect(page.getByText("还没有生成章节。")).toBeVisible();
});

test("chapter history can be viewed and branched from an earlier chapter", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A court archivist must decide which truth survives.");
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("find the hidden ledger");

  await page.getByRole("button", { name: "生成下一章" }).click();
  await page.getByRole("button", { name: "生成下一章" }).click();

  await expect(page.getByRole("button", { name: "查看第 1 章" })).toBeVisible();
  await expect(page.getByRole("button", { name: "查看第 2 章" })).toBeVisible();

  await page.getByRole("button", { name: "查看第 1 章" }).click();
  await expect(page.getByRole("heading", { name: "第 1 章" })).toBeVisible();

  await page.getByRole("button", { name: "从第 1 章分叉" }).click();
  await expect(page.getByText("分支故事：s-001-branch-ch1", { exact: true })).toBeVisible();
  await expect(page.getByText("当前章节：1", { exact: true })).toBeVisible();
  await expect(page.getByText("父故事：s-001", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "打开故事：s-001", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "生成下一章" }).click();
  await expect(page.getByText("当前章节：2", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "打开故事：s-001", exact: true }).click();
  await expect(page.getByText("故事：s-001", { exact: true })).toBeVisible();
  await expect(page.getByText("当前章节：2", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "打开故事：s-001-branch-ch1", exact: true })).toBeVisible();
  await expect(page.getByText("分支故事：s-001-branch-ch1", { exact: true })).toBeVisible();
  await expect(page.getByText("章节列表：1, 2").first()).toBeVisible();
  await expect(page.getByText("最新摘要：Chapter 2 body.").first()).toBeVisible();
  await expect(page.getByText("最新未解线索：Who will control the truth after chapter 2?").first()).toBeVisible();
  await expect(page.getByText("最新伏笔：A hidden letter appears.").first()).toBeVisible();
  await expect(page.getByText("章节卡：s-001 第 1 章 - 开局", { exact: true })).toBeVisible();
  await expect(page.getByText("标签：s-001 第 1 章 - 历史节点，分支导航", { exact: true })).toBeVisible();
  await expect(page.getByText("章节卡：s-001 第 2 章 - 压力上升", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "跳转到 s-001 第 1 章", exact: true }).click();
  await expect(page.getByText("正在查看：1", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "第 1 章" })).toBeVisible();
  await expect(page.locator(".story-tree__item--active")).toContainText("主线故事：s-001");
  await expect(page.locator(".story-tree__chapter-btn--active")).toHaveText("跳转到 s-001 第 1 章");

  await page.getByRole("button", { name: "跳转到 s-001 第 2 章", exact: true }).click();
  await expect(page.getByText("正在查看：2", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "第 2 章" })).toBeVisible();
  await expect(page.locator(".story-tree__chapter-btn--active")).toHaveText("跳转到 s-001 第 2 章");

  await page.getByRole("button", { name: "打开故事：s-001-branch-ch1", exact: true }).click();
  await expect(page.locator(".story-tree__item--active")).toContainText("分支故事：s-001-branch-ch1");
  await page.getByRole("button", { name: "聚焦当前分支", exact: true }).click();
  await expect(page.getByText("主线故事：s-001").first()).toBeVisible();
  await expect(page.getByText("分支故事：s-001-branch-ch1").first()).toBeVisible();

  await page.getByRole("button", { name: "显示全部分支", exact: true }).click();
  await expect(page.getByText("主线故事：s-001").first()).toBeVisible();
});

test("branch can be deleted from the story tree", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A witness keeps editing the same confession.");
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("find the true author");

  await page.getByRole("button", { name: "生成下一章" }).click();
  await page.getByRole("button", { name: "从第 1 章分叉" }).click();

  await page.getByRole("button", { name: "删除当前故事" }).click();
  await expect(page.getByText("故事：s-001", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "打开故事：s-001-branch-ch1", exact: true })).toHaveCount(0);
});
