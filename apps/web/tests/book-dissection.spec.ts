import { expect, test, type Page } from "@playwright/test";

const PROJECT_ID = "file:dissection-smoke";
const STORY_ID = "file:dissection-story";

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
          "节奏拆解": ["Opening pressure lands before explanation."],
          "可学习写法": ["Let the price change show the rule."],
        },
      }),
    });
  });
}

test("dissection page can submit a reference text and render the report", async ({ page }) => {
  await proxyDissectionRoutes(page);

  await page.goto(`/projects/${encodeURIComponent(PROJECT_ID)}/dissection`, { waitUntil: "domcontentloaded" });

  await page.getByPlaceholder(/参考章节|鍙傝€冪珷/).fill("The market stall price changes after the first anonymous order.");
  await page.getByRole("button", { name: /开始分析|寮€濮嬪垎鏋?/ }).click();

  await expect(page.getByText("Reference chapter uses pressure, choice, and consequence.")).toBeVisible();
  await expect(page.getByText("Opening pressure lands before explanation.")).toBeVisible();
  await expect(page.getByText("Let the price change show the rule.")).toBeVisible();
});
