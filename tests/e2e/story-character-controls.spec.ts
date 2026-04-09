import { expect, test } from "../../apps/web/node_modules/@playwright/test";

test("character editor sends frozen protagonist into generation flow", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A court scholar traces a ledger through the archive.");
  await page.getByLabel("Character Name 1").fill("Pei An");
  await page.getByLabel("Character Goal 1").fill("protect the ledger");
  await page.getByLabel("Freeze Character").check();

  await page.getByRole("button", { name: "Generate Next Chapter" }).click();

  await expect(page.getByText("Lead: Pei An")).toBeVisible();
  await expect(page.getByText("Frozen: Yes")).toBeVisible();
});

test("relationship editor carries trust and tension into generated state", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Add Character" }).click();
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("expose the forgery");
  await page.getByLabel("Character Name 2").fill("Su Wan");
  await page.getByLabel("Character Goal 2").fill("protect the family name");
  await page.getByLabel("Relationship Target 1").fill("Su Wan");
  await page.getByLabel("Relationship Bond 1").fill("uneasy alliance");
  await page.getByLabel("Trust Level 1").fill("0.4");
  await page.getByLabel("Tension Level 1").fill("0.9");

  await page.getByRole("button", { name: "Generate Next Chapter" }).click();

  await expect(page.getByText("Relationship: Su Wan (uneasy alliance)")).toBeVisible();
  await expect(page.getByText("Trust/Tension: 0.3 / 1")).toBeVisible();
  await expect(page.getByRole("article")).toContainText("needles the alliance");
});
