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

test("workbench displays lifecycle metadata for a character", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Outline Input").fill("An archivist enters the story under a false name.");
  await page.getByLabel("Character Name 1").fill("Old Archivist");
  await page.getByLabel("Character Goal 1").fill("hide the witness");
  await page.getByRole("button", { name: "Generate Next Chapter" }).click();

  await expect(page.getByText("Lifecycle: active")).toBeVisible();
});

test("agent settings panel exposes model and mode controls", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("button", { name: "Agent Settings" })).toBeVisible();

  await page.getByLabel("Agent Mode").selectOption("LLM-assisted");
  await page.getByLabel("Character Model").fill("gpt-5.4");
  await page.getByLabel("Director Model").fill("gpt-5.4");
  await page.getByLabel("Writer Model").fill("gpt-5.4-mini");
  await page.getByLabel("Temperature").fill("0.85");
  await page.getByLabel("New Character Policy").selectOption("Director review");

  await expect(page.getByText("Mode: LLM-assisted", { exact: true })).toBeVisible();
  await expect(page.getByText("Character model: gpt-5.4", { exact: true })).toBeVisible();
  await expect(page.getByText("New character policy: Director review", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Runtime mode: LLM-assisted with deterministic fallback", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("DirectorAgent: LLM-assisted", { exact: true })).toBeVisible();
});

test("agent settings persist into story generation payload", async ({ page }) => {
  // Force the workbench onto the deterministic frontend mock path so we can
  // verify settings persistence even when the API server is not running.
  await page.route("http://127.0.0.1:8000/**", (route) => route.abort());
  await page.goto("/");

  await page.getByLabel("Agent Mode").selectOption("LLM-assisted");
  await page.getByLabel("Character Model").fill("gpt-5.4-mini");
  await page.getByLabel("Director Model").fill("gpt-5.4");
  await page.getByLabel("Writer Model").fill("gpt-5.4");
  await page.getByLabel("Temperature").fill("0.85");
  await page
    .getByLabel("New Character Policy")
    .selectOption("Auto-approve named candidates");

  await page.getByRole("button", { name: "Generate Next Chapter" }).click();

  await page.getByText("Bundle", { exact: true }).click();
  const bundleDebug = page.locator(
    'section[aria-label="Chapter Draft Panel"] details pre',
  );
  await expect(bundleDebug).toContainText('"agent_settings"');
  await expect(bundleDebug).toContainText('"mode": "LLM-assisted"');
  await expect(bundleDebug).toContainText(
    '"new_character_policy": "Auto-approve named candidates"',
  );
});
