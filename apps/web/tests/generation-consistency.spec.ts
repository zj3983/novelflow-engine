import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "file:consistency-gate-ui";
const STORY_ID = "file:consistency-gate-ui-story";
const ENCODED_PROJECT_ID = encodeURIComponent(PROJECT_ID);
const ENCODED_STORY_ID = encodeURIComponent(STORY_ID);

function fulfill(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

const consistencyGate = {
  schema_version: "generation-consistency-gate/v1",
  target_chapter: 2,
  status: "blocking",
  warnings: [
    {
      code: "SKILL_NOT_YET_ACQUIRED",
      severity: "error",
      character_name: "林照",
      target_chapter: 2,
      message: "技能尚未获得",
      expected: "未来技能",
      observed: { acquired_chapter: 5 },
      evidence: {},
      source: "progression_ledger",
      suggestion: "返回修改本章计划，或明确确认仍然生成。",
    },
  ],
  checked_characters: ["林照"],
  checked_at_boundary: 1,
  override_applied: false,
};

function generationJob(status: "awaiting_consistency_override" | "completed") {
  return {
    job_id: "gj-consistency-ui",
    story_id: PROJECT_ID,
    status,
    progress: status === "completed" ? "生成完成" : "等待作者确认",
    chapter_number: status === "completed" ? 2 : null,
    error: "",
    steps: [],
    operation: "generate",
    target_chapter: 2,
    consistency_gate: status === "completed" ? null : consistencyGate,
    consistency_override: status === "completed",
    created_at: "2026-09-11T00:00:00Z",
    updated_at: "2026-09-11T00:00:00Z",
  };
}

async function mockConsistencyWorkspace(page: Page) {
  let writerStartCalls = 0;
  let continueCalls = 0;
  let cancelCalls = 0;

  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}`, (route) => fulfill(route, {
    project_id: PROJECT_ID,
    title: "一致性检查测试项目",
    source_path: "D:/fiction/consistency-gate-ui",
    seed_outline: "林照追查一条旧线索。",
    world_summary: "一个需要保持角色状态连续性的故事。",
    current_focus: "先处理生成前提示。",
    author_constraints: [],
    world_blueprint: {},
    character_profiles: [],
    relationship_graph: [],
    status: "simulating",
    pipeline_stage: "simulating",
    active_story_id: STORY_ID,
    branches: [{ story_id: STORY_ID, current_chapter: 1, parent_story_id: null, branched_from_chapter: null }],
    storage_source: "file",
    publishing_assets: { schema_version: "publishing-assets/v1", synopsis: null, cover: null },
  }));

  await page.route(`**/file-stories/${ENCODED_STORY_ID}/overview`, (route) => fulfill(route, {
    story_id: STORY_ID,
    outline: "林照追查一条旧线索。",
    genre: "都市",
    style: "白描",
    current_chapter: 1,
    agent_settings: { mode: "LLM-assisted", temperature: 0.7 },
    agent_runtime: { recent_events: [] },
    author_constraints: [],
    world_facts: [],
    characters: [],
    parent_story_id: null,
    branched_from_chapter: null,
    history: [],
    chapter_count: 1,
    total_body_chars: 20,
    chapters: [{
      chapter_number: 1,
      chapter_title: "第一章 旧线索",
      body_chars: 20,
      summary: "林照发现旧线索。",
      next_focus: "追查线索来源",
      has_quality_report: false,
      has_simulation: true,
    }],
    storage_source: "file",
  }));

  await page.route(`**/file-stories/${ENCODED_STORY_ID}/chapters/1`, (route) => fulfill(route, {
    chapter_number: 1,
    chapter_title: "第一章 旧线索",
    body: "林照在旧档案里发现一条线索。",
  }));

  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/writing-packet**`, (route) => fulfill(route, {
    schema_version: "file-writing-packet/v1",
    chapter_number: 2,
    rolling_fill: null,
    next_chapter_outline: null,
    next_chapter_outline_source: null,
  }));

  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/outline/volume-workflow**`, (route) => fulfill(route, {
    schema_version: "volume-workflow/v1",
    target_chapter: 2,
    status: "detail_complete",
    detail_status: "detail_complete",
    next_action: "generate_prose",
    volume_id: "volume-1",
    volume_range: [1, 60],
  }));

  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/candidates**`, (route) => fulfill(route, {
    schema_version: "candidate-list/v1",
    items: [],
  }));

  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/continuous-generation-jobs/current`, (route) => fulfill(route, null, 404));
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/generation-jobs/current`, (route) => fulfill(route, generationJob("awaiting_consistency_override")));
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/generation-jobs`, (route) => {
    writerStartCalls += 1;
    return fulfill(route, { detail: "unexpected_generation_start" }, 500);
  });
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/generation-jobs/gj-consistency-ui/continue`, async (route) => {
    expect(route.request().method()).toBe("POST");
    continueCalls += 1;
    return fulfill(route, generationJob("completed"));
  });
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/generation-jobs/gj-consistency-ui/cancel`, async (route) => {
    expect(route.request().method()).toBe("POST");
    cancelCalls += 1;
    return fulfill(route, {
      ...generationJob("awaiting_consistency_override"),
      status: "cancelled",
      progress: "已返回修改，未启动写手",
      consistency_gate: consistencyGate,
      consistency_override: false,
    });
  });

  return {
    get writerStartCalls() { return writerStartCalls; },
    get continueCalls() { return continueCalls; },
    get cancelCalls() { return cancelCalls; },
  };
}

test("写作页展示生成前一致性提示，并只在确认后继续任务", async ({ page }) => {
  const calls = await mockConsistencyWorkspace(page);

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/write?chapter=1`, { waitUntil: "networkidle" });

  const panel = page.getByTestId("generation-consistency-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("生成前检查发现 1 个问题");
  await expect(panel).toContainText("🔴 林照 · SKILL_NOT_YET_ACQUIRED");
  await expect(panel).toContainText("技能尚未获得");
  expect(calls.writerStartCalls).toBe(0);

  await panel.getByTestId("generation-consistency-continue").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${ENCODED_PROJECT_ID}/write\\?chapter=2$`));
  expect(calls.continueCalls).toBe(1);
  expect(calls.writerStartCalls).toBe(0);
});

test("写作页的返回修改会取消暂停任务并回到章节细纲", async ({ page }) => {
  const calls = await mockConsistencyWorkspace(page);

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/write?chapter=1`, { waitUntil: "networkidle" });
  await page.getByTestId("generation-consistency-return").click();

  await expect(page).toHaveURL(new RegExp(`/projects/${ENCODED_PROJECT_ID}/outline\\?tab=chapters&chapter=2&reason=consistency_required$`));
  expect(calls.cancelCalls).toBe(1);
  expect(calls.writerStartCalls).toBe(0);
});
