import { expect, test } from "../../apps/web/node_modules/@playwright/test";

test("multi-character cast appears in generated state and rollback clears the draft", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("Two investigators circle the same ledger from opposite sides of the court.");
  await page.getByRole("button", { name: "Add Character" }).click();
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("expose the forgery");
  await page.getByLabel("Character Name 2").fill("Su Wan");
  await page.getByLabel("Character Goal 2").fill("protect the family name");

  await page.getByRole("button", { name: "Generate Next Chapter" }).click();

  await expect(page.getByText("Cast: Lin Yue, Su Wan")).toBeVisible();
  await expect(page.getByText("Lead: Lin Yue")).toBeVisible();

  await page.getByRole("button", { name: "Rollback Chapter" }).click();

  await expect(page.getByText("No chapter generated yet.")).toBeVisible();
});
