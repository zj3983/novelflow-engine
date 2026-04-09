import { expect, test } from "../../apps/web/node_modules/@playwright/test";

test("character editor sends frozen protagonist into generation flow", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A court scholar traces a ledger through the archive.");
  await page.getByLabel("Character Name").fill("Pei An");
  await page.getByLabel("Character Goal").fill("protect the ledger");
  await page.getByLabel("Freeze Character").check();

  await page.getByRole("button", { name: "Generate Next Chapter" }).click();

  await expect(page.getByText("Lead: Pei An")).toBeVisible();
  await expect(page.getByText("Frozen: Yes")).toBeVisible();
});
