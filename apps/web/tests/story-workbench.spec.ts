import { expect, test } from "@playwright/test";

test("workbench shell renders the four-panel layout", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Outline")).toBeVisible();
  await expect(page.getByText("Chapter Draft")).toBeVisible();
  await expect(page.getByText("Character State")).toBeVisible();
  await expect(page.getByText("Controls")).toBeVisible();
});

