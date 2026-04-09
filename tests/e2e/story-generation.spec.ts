// This repo keeps JS tooling scoped to `apps/web/`, so we import Playwright from there.
import { expect, test } from "../../apps/web/node_modules/@playwright/test";

test("generate next chapter updates the draft and state panels", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Generate Next Chapter" }).click();
  await expect(page.getByRole("article")).toContainText("Chapter 1 body.");
  await expect(page.getByText("Chapter 1", { exact: true })).toBeVisible();
  await expect(page.getByText("Continuity: OK")).toBeVisible();
  await expect(page.getByText("Next beat")).toBeVisible();
});

test("second chapter reuses previous fact and foreshadowing in prose", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Generate Next Chapter" }).click();
  await page.getByRole("button", { name: "Generate Next Chapter" }).click();

  await expect(page.getByRole("article")).toContainText("Carries forward");
  await expect(page.getByRole("article")).toContainText("A hidden letter appears.");
});
