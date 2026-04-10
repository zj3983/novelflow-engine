import { expect, test } from "@playwright/test";

test("workbench shell renders the four-panel layout", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("大纲", { exact: true })).toBeVisible();
  await expect(page.getByText("章节草稿", { exact: true })).toBeVisible();
  await expect(page.getByText("角色状态", { exact: true })).toBeVisible();
  await expect(page.getByText("控制区", { exact: true })).toBeVisible();
});

test("book import sidebar renders a visible import entry", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.getByText("导入书籍目录", { exact: true })).toBeVisible();
  await expect(page.getByLabel("本地目录路径", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "校验目录", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "载入到工作台", exact: true })).toBeVisible();
});
