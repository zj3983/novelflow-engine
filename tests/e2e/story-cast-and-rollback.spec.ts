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

test("chapter history can be viewed and branched from an earlier chapter", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A court archivist must decide which truth survives.");
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("find the hidden ledger");

  await page.getByRole("button", { name: "Generate Next Chapter" }).click();
  await page.getByRole("button", { name: "Generate Next Chapter" }).click();

  await expect(page.getByRole("button", { name: "View Chapter 1" })).toBeVisible();
  await expect(page.getByRole("button", { name: "View Chapter 2" })).toBeVisible();

  await page.getByRole("button", { name: "View Chapter 1" }).click();
  await expect(page.getByRole("heading", { name: "Chapter 1" })).toBeVisible();

  await page.getByRole("button", { name: "Branch from Chapter 1" }).click();
  await expect(page.getByText("Branch story: s-001-branch-ch1", { exact: true })).toBeVisible();
  await expect(page.getByText("Current chapter: 1", { exact: true })).toBeVisible();
  await expect(page.getByText("Parent story: s-001", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Story: s-001", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Generate Next Chapter" }).click();
  await expect(page.getByText("Current chapter: 2", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Open Story: s-001", exact: true }).click();
  await expect(page.getByText("Story: s-001", { exact: true })).toBeVisible();
  await expect(page.getByText("Current chapter: 2", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Story: s-001-branch-ch1", exact: true })).toBeVisible();
});
