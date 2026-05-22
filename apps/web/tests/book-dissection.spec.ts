import { expect, test, type Page } from "@playwright/test";

const PROJECT_ID = "file:dissection-smoke";
const STORY_ID = "file:dissection-story";

function cn(codes: number[]): string {
  return String.fromCodePoint(...codes);
}

const ANALYZE = cn([0x5f00, 0x59cb, 0x5206, 0x6790]);
const PROJECT_MODE = cn([0x672c, 0x4e66, 0x4f53, 0x68c0]);
const PROGRESS_LINE = cn([
  0x672c, 0x7ae0, 0x8fdb, 0x5c55, 0x5df2, 0x7ecf, 0x843d, 0x5230, 0x5177, 0x4f53, 0x8d26, 0x672c,
  0xff1a, 0x7ecf, 0x9a8c, 0x33, 0x30, 0x2f, 0x31, 0x30, 0x30, 0xff0c, 0x751f, 0x547d, 0x34,
  0x32, 0x2f, 0x31, 0x30, 0x30, 0xff0c, 0x6cd5, 0x529b, 0x30, 0x2f, 0x36, 0x30, 0x3002,
]);
const CONFLICT_LINE = cn([
  0x6e05, 0x9053, 0x592b, 0x59d4, 0x6258, 0x8fd8, 0x5dee, 0x32, 0x4efd, 0xff0c, 0x4e0b,
  0x4e00, 0x7ae0, 0x76ee, 0x6807, 0x6e05, 0x695a, 0x3002,
]);
const NEXT_LINE = cn([
  0x4e0b, 0x4e00, 0x7ae0, 0x5148, 0x8865, 0x9f50, 0x32, 0x4efd, 0x6750, 0x6599, 0xff0c,
  0x518d, 0x5904, 0x7406, 0x59d4, 0x6258, 0x3002,
]);
const NO_HIT = cn([0x6682, 0x672a, 0x547d, 0x4e2d]);
const NO_HARD_ERROR = cn([0x672a, 0x53d1, 0x73b0, 0x786c, 0x6027, 0x9519, 0x8bef]);

async function proxyDissectionRoutes(page: Page) {
  await page.route("**/file-projects/file%3Adissection-smoke", async (route) => {
    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
      body: JSON.stringify({
        project_id: PROJECT_ID,
        title: "Dissection Smoke",
        source_path: "D:/fiction/dissection-smoke",
        seed_outline: "A market clue opens the story.",
        world_summary: "A game world with visible costs.",
        current_focus: "Make the reference structure inspectable.",
        author_constraints: [],
        world_blueprint: {},
        character_profiles: [],
        relationship_graph: [],
        status: "simulating",
        pipeline_stage: "simulating",
        active_story_id: STORY_ID,
        branches: [{ story_id: STORY_ID, current_chapter: 1, parent_story_id: null, branched_from_chapter: null }],
      }),
    });
  });

  await page.route("**/file-stories/file%3Adissection-story", async (route) => {
    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
      body: JSON.stringify({
        story_id: STORY_ID,
        outline: "A player tests a market clue.",
        genre: "game fantasy",
        style: "webnovel",
        current_chapter: 1,
        agent_settings: {
          mode: "LLM-assisted",
          global_model: "qwen3.6-plus",
          character_model: "qwen3.6-plus",
          director_model: "qwen3.6-plus",
          writer_model: "qwen3.6-plus",
          memory_model: "qwen3.6-plus",
          temperature: 0.7,
          new_character_policy: "Director review",
        },
        agent_runtime: {
          character_agent: { mode: "LLM-assisted", source: "idle", fallback_reason: "", last_run_chapter: 0 },
          director_agent: { mode: "LLM-assisted", source: "idle", fallback_reason: "", last_run_chapter: 0 },
          writer_agent: { mode: "LLM-assisted", source: "idle", fallback_reason: "", last_run_chapter: 0 },
          memory_agent: { mode: "LLM-assisted", source: "idle", fallback_reason: "", last_run_chapter: 0 },
          outline_agent: { mode: "LLM-assisted", source: "idle", fallback_reason: "", last_run_chapter: 0 },
          recent_events: [],
        },
        author_constraints: [],
        world_facts: [],
        parent_story_id: null,
        branched_from_chapter: null,
        characters: [],
        history: [
          {
            chapter_number: 1,
            chapter_title: "Opening Trade",
            body: "The player breaks one trade into smaller orders.",
          },
        ],
      }),
    });
  });

  await page.route("**/book-dissection/reference", async (route) => {
    expect(route.request().method()).toBe("POST");
    const payload = route.request().postDataJSON() as { text?: string; genre?: string; focus?: string };
    expect(payload.text).toContain("market stall");

    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
      body: JSON.stringify({
        schema_version: "book-dissection/v1",
        mode: "reference",
        summary: "Reference chapter uses pressure, choice, and consequence.",
        sections: {
          pacing: ["Opening pressure lands before explanation."],
          method: ["Let the price change show the rule."],
        },
      }),
    });
  });

  await page.route("**/file-projects/file%3Adissection-smoke/book-dissection/chapter", async (route) => {
    expect(route.request().method()).toBe("POST");
    const payload = route.request().postDataJSON() as { chapter_number?: number };
    expect(payload.chapter_number).toBe(1);

    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
      body: JSON.stringify({
        schema_version: "book-dissection/v1",
        mode: "project",
        chapter_number: 1,
        chapter_title: "Opening Trade",
        sections: {
          role: ["Opening function is visible."],
          progress: [PROGRESS_LINE],
          conflict: [CONFLICT_LINE],
          issues: [],
          setting: [],
          next: [NEXT_LINE],
        },
      }),
    });
  });
}

test("dissection page can submit a reference text and render the report", async ({ page }) => {
  await proxyDissectionRoutes(page);

  await page.goto(`/projects/${encodeURIComponent(PROJECT_ID)}/dissection`, { waitUntil: "networkidle" });

  await page.locator("textarea.ws-textarea").fill("The market stall price changes after the first anonymous order.");
  await expect(page.getByRole("button", { name: ANALYZE })).toBeEnabled();
  await page.getByRole("button", { name: ANALYZE }).click();

  await expect(page.getByText("Reference chapter uses pressure, choice, and consequence.")).toBeVisible();
  await expect(page.getByText("Opening pressure lands before explanation.")).toBeVisible();
  await expect(page.getByText("Let the price change show the rule.")).toBeVisible();
});

test("dissection page can inspect a project chapter without empty filler", async ({ page }) => {
  await proxyDissectionRoutes(page);

  await page.goto(`/projects/${encodeURIComponent(PROJECT_ID)}/dissection`, { waitUntil: "networkidle" });

  await page.getByRole("tab", { name: PROJECT_MODE }).click();
  await expect(page.getByRole("button", { name: ANALYZE })).toBeEnabled();
  await page.getByRole("button", { name: ANALYZE }).click();

  await expect(page.getByText(PROGRESS_LINE)).toBeVisible();
  await expect(page.getByText(CONFLICT_LINE)).toBeVisible();
  await expect(page.getByText(NO_HIT)).toHaveCount(0);
  await expect(page.getByText(NO_HARD_ERROR)).toHaveCount(0);
});
