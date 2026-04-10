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
  await expect(page.getByText("Story Branch: s-001-branch-ch1", { exact: true })).toBeVisible();
  await expect(page.getByText("Chapters in s-001: 1, 2", { exact: true })).toBeVisible();
  await expect(page.getByText("Chapters in s-001-branch-ch1: 1, 2", { exact: true })).toBeVisible();
  await expect(page.getByText("Latest summary in s-001: Chapter 2 body.", { exact: true })).toBeVisible();
  await expect(page.getByText("Latest thread in s-001: Who will control the truth after chapter 2?", { exact: true })).toBeVisible();
  await expect(page.getByText("Latest foreshadowing in s-001: A hidden letter appears.", { exact: true })).toBeVisible();
  await expect(page.getByText("Latest summary in s-001-branch-ch1: Chapter 2 body.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Jump to s-001 Chapter 1", exact: true }).click();
  await expect(page.getByText("Viewing chapter: 1", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Chapter 1" })).toBeVisible();
  await expect(page.locator(".story-tree__item--active")).toContainText("Story Root: s-001");
  await expect(page.locator(".story-tree__chapter-btn--active")).toHaveText("Jump to s-001 Chapter 1");

  await page.getByRole("button", { name: "Jump to s-001 Chapter 2", exact: true }).click();
  await expect(page.getByText("Viewing chapter: 2", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Chapter 2" })).toBeVisible();
  await expect(page.locator(".story-tree__chapter-btn--active")).toHaveText("Jump to s-001 Chapter 2");

  await page.getByRole("button", { name: "Open Story: s-001-branch-ch1", exact: true }).click();
  await expect(page.locator(".story-tree__item--active")).toContainText("Story Branch: s-001-branch-ch1");
  await page.getByRole("button", { name: "Focus Active Branch", exact: true }).click();
  await expect(page.getByText("Story Root: s-001", { exact: true })).toBeVisible();
  await expect(page.getByText("Story Branch: s-001-branch-ch1", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Show All Branches", exact: true }).click();
  await expect(page.getByText("Story Root: s-001", { exact: true })).toBeVisible();
});

test("branch can be deleted from the story tree", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("A witness keeps editing the same confession.");
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("find the true author");

  await page.getByRole("button", { name: "Generate Next Chapter" }).click();
  await page.getByRole("button", { name: "Branch from Chapter 1" }).click();

  await page.getByRole("button", { name: "Delete Active Story" }).click();
  await expect(page.getByText("Story: s-001", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Story: s-001-branch-ch1", exact: true })).toHaveCount(0);
});
