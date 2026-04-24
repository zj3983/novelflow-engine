import { expect, test } from "@playwright/test";

test("/config shows a dedicated configuration center", async ({ page }) => {
  await page.goto("/config", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "配置中心" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "全局默认配置" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "角色代理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "导演代理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "写作代理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "记忆代理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "运行策略" })).toBeVisible();
  await expect(page.getByRole("button", { name: "测试连接", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "统一保存", exact: true })).toBeVisible();
});
