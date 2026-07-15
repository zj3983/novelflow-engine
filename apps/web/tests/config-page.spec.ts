import { expect, test } from "@playwright/test";

test("/config only shows settings used by the selected provider", async ({ page }) => {
  await page.goto("/config", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("配置已载入。")).toBeVisible();

  await expect(page.getByRole("heading", { name: "全局默认配置" })).toBeVisible();
  await expect(page.getByLabel("Codex CLI 命令")).toBeVisible();
  await expect(page.getByLabel("全局 API 密钥")).toBeHidden();
  await expect(page.getByLabel("全局接口地址")).toBeHidden();
  await expect(page.getByRole("heading", { name: "运行策略" })).toBeHidden();
  await expect(page.getByRole("button", { name: "Agent 覆盖（高级）" })).toBeHidden();
  await expect(page.getByRole("button", { name: "测试连接", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "统一保存", exact: true })).toBeVisible();

  await page.getByLabel("模型来源").selectOption("openai");
  await expect(page.getByLabel("Codex CLI 命令")).toBeHidden();
  await expect(page.getByLabel("全局 API 密钥")).toBeVisible();
  await expect(page.getByLabel("全局接口地址")).toBeVisible();
  await expect(page.getByRole("heading", { name: "运行策略" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Agent 覆盖（高级）" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "角色代理" })).toBeHidden();

  await page.getByRole("button", { name: "Agent 覆盖（高级）" }).click();
  await expect(page.getByRole("heading", { name: "角色代理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "导演代理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "写作代理" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "记忆代理" })).toBeVisible();
});
