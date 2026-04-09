import { expect, test } from "@playwright/test";

test("workbench shell renders the four-panel layout", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Outline", { exact: true })).toBeVisible();
  await expect(page.getByText("Chapter Draft", { exact: true })).toBeVisible();
  await expect(page.getByText("Character State", { exact: true })).toBeVisible();
  await expect(page.getByText("Controls", { exact: true })).toBeVisible();
});
