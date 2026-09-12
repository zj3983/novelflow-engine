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

function generationJob(status: "awaiting_consistency_override" | "awaiting_replanned_confirmation" | "completed") {
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

type ContinuousUiStatus = "replanning" | "running" | "awaiting_replanned_confirmation";

function continuousGenerationJob(status: ContinuousUiStatus) {
  const revisedGate = {
    ...consistencyGate,
    status: "blocking",
    warnings: consistencyGate.warnings,
  };
  return {
    schema_version: "continuous-generation-job/v1",
    job_id: "cgj-consistency-ui",
    project_id: PROJECT_ID,
    story_id: STORY_ID,
    status,
    phase: status === "awaiting_replanned_confirmation" ? status : "generating",
    requested_count: 2,
    completed_count: 0,
    start_chapter: 2,
    current_chapter: 2,
    completed_chapters: [],
    review_warnings: [],
    consistency_gate: status === "awaiting_replanned_confirmation" ? revisedGate : consistencyGate,
    consistency_override: false,
    consistency_override_chapters: [],
    original_plan: { chapter_number: 2, character_moves: [{ name: "林照", skills_used: ["未来技能"] }] },
    revised_plan: status === "awaiting_replanned_confirmation" ? { chapter_number: 2, scene_beats: [{}, {}] } : null,
    original_consistency_gate: consistencyGate,
    revised_consistency_gate: status === "awaiting_replanned_confirmation" ? revisedGate : null,
    replan_status: status === "replanning" ? "running" : status === "running" ? "replanned_clear" : "still_blocking",
    replan_attempts: status === "replanning" ? 1 : 1,
    replan_result: status === "replanning" ? null : { status: status === "running" ? "replanned_clear" : "still_blocking" },
    auto_consistency_replan_chapter: 2,
    auto_consistency_replan_attempted: true,
    auto_consistency_replan_attempts: 1,
    auto_consistency_replan_status: status === "replanning" ? "running" : status === "running" ? "replanned_clear" : "still_blocking",
    consistency_recovery_history: [],
    candidate_id: "",
    stop_requested: false,
    progress: status === "replanning"
      ? "第 2 章发现一致性问题，正在自动重新规划"
      : status === "running"
        ? "第 2 章重新规划通过，继续生成"
        : "自动重新规划后仍有一致性问题，已暂停，等待处理",
    stop_reason: "",
    error: "",
    created_at: "2026-09-11T00:00:00Z",
    updated_at: "2026-09-11T00:00:00Z",
  };
}

async function mockConsistencyWorkspace(
  page: Page,
  options: { continuousStatus?: ContinuousUiStatus } = {},
) {
  let writerStartCalls = 0;
  let continueCalls = 0;
  let cancelCalls = 0;
  let replanCalls = 0;

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

  if (options.continuousStatus) {
    const continuousJob = continuousGenerationJob(options.continuousStatus);
    await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/continuous-generation-jobs/current`, (route) => fulfill(route, continuousJob));
    await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/continuous-generation-jobs/cgj-consistency-ui`, (route) => fulfill(route, continuousJob));
    await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/generation-jobs/current`, (route) => fulfill(route, null, 404));
  } else {
    await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/continuous-generation-jobs/current`, (route) => fulfill(route, null, 404));
    await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/generation-jobs/current`, (route) => fulfill(route, generationJob("awaiting_consistency_override")));
  }
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
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/generation-jobs/gj-consistency-ui/replan-consistency`, async (route) => {
    expect(route.request().method()).toBe("POST");
    replanCalls += 1;
    const revisedGate = {
      ...consistencyGate,
      status: "clear",
      warnings: [],
      override_applied: false,
    };
    return fulfill(route, {
      ...generationJob("awaiting_replanned_confirmation"),
      progress: "新计划已通过生成前一致性检查",
      consistency_gate: revisedGate,
      original_plan: {
        chapter_number: 2,
        chapter_goal: "追查旧线索",
        character_moves: [{ name: "林照", skills_used: ["未来技能"] }],
      },
      revised_plan: {
        chapter_number: 2,
        chapter_title: "旧线索",
        chapter_goal: "追查旧线索",
        scene_beats: [{}, {}],
      },
      original_consistency_gate: consistencyGate,
      revised_consistency_gate: revisedGate,
      replan_status: "replanned_clear",
      replan_attempts: 1,
      replan_result: { status: "replanned_clear" },
    });
  });

  return {
    get writerStartCalls() { return writerStartCalls; },
    get continueCalls() { return continueCalls; },
    get cancelCalls() { return cancelCalls; },
    get replanCalls() { return replanCalls; },
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

test("写作页可先重新规划并查看新计划，再显式继续写手任务", async ({ page }) => {
  const calls = await mockConsistencyWorkspace(page);

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/write?chapter=1`, { waitUntil: "networkidle" });

  const panel = page.getByTestId("generation-consistency-panel");
  await panel.getByTestId("generation-consistency-replan").click();
  await expect(panel).toContainText("新计划通过一致性检查");
  await expect(panel).toContainText("原计划问题");
  await expect(panel).toContainText("新计划摘要");
  await expect(panel.getByTestId("generation-consistency-replan")).toBeDisabled();
  await expect(panel.getByTestId("generation-consistency-continue")).toContainText("使用新计划继续");
  expect(calls.replanCalls).toBe(1);
  expect(calls.writerStartCalls).toBe(0);

  await panel.getByTestId("generation-consistency-continue").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${ENCODED_PROJECT_ID}/write\\?chapter=2$`));
  expect(calls.continueCalls).toBe(1);
  expect(calls.writerStartCalls).toBe(0);
});

test("连续生产显示自动重新规划进度", async ({ page }) => {
  await mockConsistencyWorkspace(page, { continuousStatus: "replanning" });

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/write?chapter=1`, { waitUntil: "networkidle" });

  await expect(page.getByTestId("continuous-generation-auto-recovery")).toContainText(
    "第 2 章发现一致性问题，正在自动重新规划",
  );
});

test("连续生产显示重新规划通过后继续生成", async ({ page }) => {
  await mockConsistencyWorkspace(page, { continuousStatus: "running" });

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/write?chapter=1`, { waitUntil: "networkidle" });

  await expect(page.getByTestId("continuous-generation-auto-recovery")).toContainText(
    "重新规划通过，继续生成",
  );
});

test("连续生产自动重新规划仍阻断时暂停并保留人工控制", async ({ page }) => {
  await mockConsistencyWorkspace(page, { continuousStatus: "awaiting_replanned_confirmation" });

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/write?chapter=1`, { waitUntil: "networkidle" });

  await expect(page.getByTestId("continuous-generation-auto-recovery")).toContainText(
    "重新规划后仍有一致性问题，已暂停",
  );
  const panel = page.getByTestId("generation-consistency-panel");
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("generation-consistency-replan")).toBeDisabled();
});
