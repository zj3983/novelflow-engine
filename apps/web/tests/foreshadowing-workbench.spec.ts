import { expect, test, type Page, type Route } from "@playwright/test";

const PROJECT_ID = "file:foreshadowing fixture";
const ENCODED_PROJECT_ID = encodeURIComponent(PROJECT_ID);

const outline = {
  schema_version: "project-outline/v1",
  source: "saved",
  overall: {
    story: "林照追查祖祠旧案。",
    protagonist_goal: "查清父亲旧案",
    main_conflict: "旧案证据被持续销毁",
    growth_path: "从独自查案到学会结盟",
    ending_direction: "公开旧案真相",
    core_ending_chapter: 120,
    extension_ceiling_chapter: 300,
    current_strategy: "observe",
    ending_contract: "旧案必须得到裁决",
  },
  arcs: [],
  chapters: [],
};

const character = {
  name: "林照",
  role: "protagonist",
  lifecycle_state: "active",
  identity_profile: { age: 19, occupation: "守祠杂役" },
  background_profile: { family: "父亲因旧案失踪" },
  current_life_profile: {
    residence: "祖祠偏房",
    livelihood: "守炉换取月例",
    economic_state: "仅够温饱",
    resources_and_ability: "熟悉祖祠旧物",
    authority_scope: "只能进入外院",
    immediate_problem: "香炉断裂会被追责",
  },
  story_drive: {
    long_term_goal: "查清父亲旧案",
    immediate_goal: "核对值夜册",
    motivation: "替父亲洗清罪名",
    failure_stakes: "失去最后一条线索",
    hidden_matters: ["藏有半页旧名册"],
    main_conflict_reason: "赵衡试图销毁旧账",
  },
  core_motivation: "替父亲洗清罪名",
  location: "祖祠",
  current_emotion: "警惕",
  goals: ["核对值夜册"],
  memory: ["令牌碎片证据"],
  real_state: {
    current: { location: "祖祠", emotion: "警惕", immediate_goal: "核对值夜册", memory: ["令牌碎片证据"] },
    recent_changes: [{ chapter: 4, fact: "在香灰中发现令牌碎片" }],
  },
  game_state: {
    current: { location: "祖祠", emotion: "警惕", level: 3 },
    recent_changes: [],
  },
};

const relationship = {
  id: "lin-zhao",
  source: "林照",
  target: "赵衡",
  relation_type: "管事与杂役",
  history: "赵衡曾审过林父",
  shared_interest_or_conflict: "旧案证据归属",
  current_state: "表面合作，暗中提防",
  trust: 20,
  tension: 80,
  changes: [{ chapter_number: 4, summary: "因令牌碎片互相试探", trust: 20, tension: 80 }],
};

function fulfill(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockWorkspace(page: Page, characters = [character]) {
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}`, (route) => fulfill(route, {
    project_id: PROJECT_ID,
    title: "伏笔测试项目",
    active_story_id: PROJECT_ID,
    storage_source: "file",
    status: "simulating",
    pipeline_stage: "world_ready",
    branches: [],
    character_profiles: characters,
    relationship_graph: [relationship],
    world_blueprint: { genre_plugin_ids: ["game_webnovel"] },
  }));
  await page.route(`**/file-stories/${ENCODED_PROJECT_ID}/overview`, (route) => fulfill(route, {
    story_id: PROJECT_ID,
    outline: outline.overall.story,
    genre: "玄幻",
    style: "白描",
    current_chapter: 4,
    agent_settings: { mode: "LLM-assisted", temperature: 0.7 },
    agent_runtime: { recent_events: [] },
    author_constraints: [],
    world_facts: [],
    characters,
    history: [],
    parent_story_id: null,
    branched_from_chapter: null,
  }));
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/outline`, (route) => fulfill(route, outline));
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/outline/rolling`, (route) => fulfill(route, {
    schema_version: "rolling-outline/v1",
    chapters: [],
  }));
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/outline/volume-workflow**`, (route) => fulfill(route, {
    schema_version: "volume-workflow/v1",
    target_chapter: 5,
    status: "detail_complete",
    detail_status: "detail_complete",
    next_action: "generate_next_chapter",
    volume_id: "volume-1",
    volume_range: [1, 60],
  }));
}

test("伏笔 tab 独立加载、编辑并保存标准化返回", async ({ page }) => {
  await mockWorkspace(page);
  let savedItems: Array<Record<string, unknown>> | null = null;
  const initialItems = [{
    text: "断香炉中藏着内门令牌碎片",
    first_chapter: 2,
    last_touched_chapter: 4,
    status: "open",
    payoff_plan: "在内门考核时指向赵衡",
    resolved_chapter: null,
  }];
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/foreshadowing`, async (route) => {
    if (route.request().method() === "PUT") {
      const requestItems = route.request().postDataJSON().items as Array<Record<string, unknown>>;
      savedItems = requestItems;
      return fulfill(route, {
        items: requestItems.map((item) => ({ ...item, text: String(item.text).trim() })),
      });
    }
    return fulfill(route, { items: initialItems });
  });

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/outline`);
  await page.getByRole("tab", { name: "伏笔", exact: true }).click();
  await expect(page.getByRole("heading", { name: "伏笔账本" })).toBeVisible();
  await expect(page.getByLabel("伏笔内容")).toHaveValue("断香炉中藏着内门令牌碎片");
  await page.getByLabel("回收计划").fill("  第十二章借令牌锁定赵衡  ");
  await page.getByLabel("状态").selectOption("resolved");
  await page.getByRole("button", { name: "保存伏笔" }).click();

  await expect.poll(() => savedItems).toEqual([{
    ...initialItems[0],
    status: "resolved",
    payoff_plan: "  第十二章借令牌锁定赵衡  ",
    resolved_chapter: 4,
  }]);
  await page.getByRole("button", { name: "已结束", exact: true }).click();
  await expect(page.getByLabel("伏笔内容")).toHaveValue("断香炉中藏着内门令牌碎片");
  await expect(page.getByLabel("回收章")).toHaveValue("4");
  await expect(page.getByLabel("首次章")).toHaveAttribute("min", "0");
  await expect(page.getByLabel("最近推进章")).toHaveAttribute("min", "2");
  await expect(page.getByLabel("回收章")).toHaveAttribute("min", "4");
});

test("伏笔保存期间锁定所有编辑入口", async ({ page }) => {
  await mockWorkspace(page);
  let releasePut: (() => void) | undefined;
  const putGate = new Promise<void>((resolve) => { releasePut = resolve; });
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/foreshadowing`, async (route) => {
    const items = [{ text: "旧名册缺页", first_chapter: 1, last_touched_chapter: 4, status: "open", payoff_plan: "找到持有人", resolved_chapter: null }];
    if (route.request().method() === "PUT") {
      await putGate;
      return fulfill(route, { items: route.request().postDataJSON().items });
    }
    return fulfill(route, { items });
  });

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/outline`);
  await page.getByRole("tab", { name: "伏笔", exact: true }).click();
  await page.getByRole("button", { name: "保存伏笔" }).click();
  const panel = page.getByRole("tabpanel", { name: "伏笔" });
  await expect(panel.getByLabel("伏笔内容")).toBeDisabled();
  await expect(panel.getByLabel("状态")).toBeDisabled();
  await expect(panel.getByLabel("首次章")).toBeDisabled();
  await expect(panel.getByLabel("最近推进章")).toBeDisabled();
  await expect(panel.getByLabel("回收计划")).toBeDisabled();
  await expect(panel.getByRole("button", { name: "新增伏笔" })).toBeDisabled();
  await expect(panel.getByRole("button", { name: "删除伏笔" })).toBeDisabled();
  releasePut?.();
  await expect(panel.getByLabel("伏笔内容")).toBeEnabled();
});

test("伏笔保存前校验章节范围且非法数据不发 PUT", async ({ page }) => {
  await mockWorkspace(page);
  let putCount = 0;
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/foreshadowing`, async (route) => {
    if (route.request().method() === "PUT") {
      putCount += 1;
      return fulfill(route, route.request().postDataJSON());
    }
    return fulfill(route, { items: [] });
  });

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/outline`);
  await page.getByRole("tab", { name: "伏笔", exact: true }).click();
  await page.getByRole("button", { name: "新增伏笔" }).click();
  await page.getByRole("button", { name: "保存伏笔" }).click();
  await expect(page.getByText("第 1 条伏笔：伏笔内容不能为空。", { exact: true })).toBeVisible();
  expect(putCount).toBe(0);

  await page.getByLabel("伏笔内容").fill("旧名册缺页");
  await page.getByLabel("首次章").fill("3");
  await page.getByLabel("最近推进章").fill("2");
  await page.getByRole("button", { name: "保存伏笔" }).click();
  await expect(page.getByText("第 1 条伏笔：最近推进章不能小于首次章。", { exact: true })).toBeVisible();
  expect(putCount).toBe(0);

  await page.getByLabel("最近推进章").fill("6");
  await page.getByLabel("状态").selectOption("resolved");
  await page.getByRole("button", { name: "已结束", exact: true }).click();
  await page.getByLabel("回收章").fill("5");
  await page.getByRole("button", { name: "保存伏笔" }).click();
  await expect(page.getByText("第 1 条伏笔：回收章不能小于最近推进章。", { exact: true })).toBeVisible();
  expect(putCount).toBe(0);
});

test("大纲 tabs 关联 panel 并支持键盘切换焦点", async ({ page }) => {
  await mockWorkspace(page);
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/foreshadowing`, (route) => fulfill(route, { items: [] }));
  await page.goto(`/projects/${ENCODED_PROJECT_ID}/outline`);

  const overall = page.getByRole("tab", { name: "总纲", exact: true });
  await expect(overall).toHaveAttribute("id", "outline-tab-overall");
  await expect(overall).toHaveAttribute("aria-controls", "outline-panel-overall");
  await expect(overall).toHaveAttribute("tabindex", "0");
  await expect(page.locator("#outline-panel-overall")).toHaveAttribute("aria-labelledby", "outline-tab-overall");
  await overall.focus();
  await overall.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "阶段大纲", exact: true })).toBeFocused();
  await expect(page.getByRole("tab", { name: "阶段大纲", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "阶段大纲", exact: true }).press("End");
  const foreshadowing = page.getByRole("tab", { name: "伏笔", exact: true });
  await expect(foreshadowing).toBeFocused();
  await expect(foreshadowing).toHaveAttribute("aria-controls", "outline-panel-foreshadowing");
  await expect(page.locator("#outline-panel-foreshadowing")).toHaveAttribute("aria-labelledby", "outline-tab-foreshadowing");
  await foreshadowing.press("Home");
  await expect(overall).toBeFocused();
});

test("伏笔账本支持新增、筛选和删除", async ({ page }) => {
  await mockWorkspace(page);
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/foreshadowing`, (route) => fulfill(route, { items: [] }));

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/outline`);
  await page.getByRole("tab", { name: "伏笔", exact: true }).click();
  await expect(page.getByText("暂无伏笔记录。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "未回收", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "新增伏笔" }).click();
  await expect(page.getByLabel("首次章")).toHaveValue("5");
  await expect(page.getByLabel("最近推进章")).toHaveValue("5");
  await expect(page.getByLabel("状态")).toHaveValue("open");
  await page.getByLabel("伏笔内容").fill("旧名册缺失的一页");
  await expect(page.getByRole("button", { name: "删除伏笔" })).toHaveAttribute("title", "删除伏笔");
  await page.getByRole("button", { name: "删除伏笔" }).click();
  await expect(page.getByText("暂无伏笔记录。", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 375, height: 760 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("伏笔 GET 失败不阻止大纲显示和编辑", async ({ page }) => {
  await mockWorkspace(page);
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/foreshadowing`, (route) => fulfill(route, { detail: "ledger unavailable" }, 503));

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/outline`);
  await expect(page.getByRole("tab", { name: "总纲", exact: true })).toBeVisible();
  await expect(page.getByLabel("核心故事")).toHaveValue("林照追查祖祠旧案。");
  await page.getByLabel("核心故事").fill("林照继续追查祖祠旧案。");
  await page.getByRole("tab", { name: "伏笔", exact: true }).click();
  await expect(page.getByText(/伏笔加载失败.*ledger unavailable/)).toBeVisible();
});

test("角色卡动态与稳定字段真正分区、去重且仍可编辑保存", async ({ page }) => {
  let savedBody: Record<string, unknown> | null = null;
  const keyWarnings: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && /unique.*key|same key/i.test(message.text())) keyWarnings.push(message.text());
  });
  await mockWorkspace(page);
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/characters/%E6%9E%97%E7%85%A7`, async (route) => {
    savedBody = route.request().postDataJSON() as Record<string, unknown>;
    return fulfill(route, { ...character, ...savedBody });
  });

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/characters`);
  const characterCard = page.locator(".ws-character-card").first();
  await expect(characterCard).toBeVisible();
  await expect(characterCard.locator("xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' ws-card ')]")).toHaveCount(0);
  const current = page.locator('section[aria-label="当前状态"]');
  const stable = page.locator('section[aria-label="稳定档案"]');

  await expect(current.getByRole("heading", { name: "当前状态", exact: true })).toBeVisible();
  await expect(current.getByText("章后只更新出场证据和明确状态事件", { exact: true })).toBeVisible();
  for (const value of ["祖祠", "警惕"]) {
    await expect(current.getByText(value, { exact: true })).toHaveCount(2);
    await expect(stable.getByText(value, { exact: true })).toHaveCount(0);
  }
  for (const value of ["核对值夜册", "令牌碎片证据"]) {
    await expect(current.getByText(value, { exact: true })).toHaveCount(1);
    await expect(stable.getByText(value, { exact: true })).toHaveCount(0);
  }
  for (const value of ["祖祠偏房", "守炉换取月例", "仅够温饱", "熟悉祖祠旧物", "只能进入外院", "香炉断裂会被追责"]) {
    await expect(current.getByText(value, { exact: true })).toHaveCount(1);
    await expect(stable.getByText(value, { exact: true })).toHaveCount(0);
  }
  await expect(current.getByText("表面合作，暗中提防", { exact: true })).toHaveCount(1);
  await expect(current.getByText("因令牌碎片互相试探", { exact: true })).toHaveCount(1);
  await expect(stable.getByText("表面合作，暗中提防", { exact: true })).toHaveCount(0);

  await expect(stable.getByRole("heading", { name: "稳定档案", exact: true })).toBeVisible();
  await expect(stable.getByText("不随章节自动改写", { exact: true })).toBeVisible();
  for (const value of ["守祠杂役", "查清父亲旧案", "失去最后一条线索", "藏有半页旧名册", "赵衡试图销毁旧账", "赵衡曾审过林父", "旧案证据归属"]) {
    await expect(stable.getByText(value, { exact: true })).toHaveCount(1);
    await expect(current.getByText(value, { exact: true })).toHaveCount(0);
  }

  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await current.getByLabel("眼前麻烦").fill("香炉断裂且账册失踪");
  await current.getByLabel("当前目标").fill("找到缺失账册");
  await page.getByRole("button", { name: "保存角色卡" }).click();
  await expect.poll(() => savedBody).toMatchObject({
    current_life_profile: { immediate_problem: "香炉断裂且账册失踪", residence: "祖祠偏房" },
    story_drive: { immediate_goal: "找到缺失账册", long_term_goal: "查清父亲旧案", motivation: "替父亲洗清罪名" },
  });
  await page.setViewportSize({ width: 375, height: 760 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  expect(keyWarnings).toEqual([]);
});

test("角色历史检查展示时间线并以结构化计划运行一致性检查", async ({ page }) => {
  await mockWorkspace(page);
  let postedPlan: Record<string, unknown> | null = null;
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/characters/%E6%9E%97%E7%85%A7/timeline`, (route) => fulfill(route, {
    character_name: "林照",
    start_chapter: null,
    end_chapter: null,
    history_status: "available",
    events_in_range: 2,
    events: [
      {
        event_id: "character-event-location-4",
        chapter_number: 4,
        character_name: "林照",
        category: "location",
        title: "位置变化",
        summary: "位置变化：祖祠 → 北境",
        before: "祖祠",
        after: "北境",
        source: "character_state",
        source_id: "character.current_state.history.0.location",
        confidence: "confirmed",
        metadata: {},
      },
      {
        event_id: "character-event-skill-5",
        chapter_number: 5,
        character_name: "林照",
        category: "skill",
        title: "获得技能",
        summary: "获得技能：御剑术",
        before: null,
        after: "御剑术",
        source: "progression_ledger",
        source_id: "progression_ledger.protagonist.history.0.skills",
        confidence: "confirmed",
        metadata: {},
      },
    ],
  }));
  await page.route(`**/file-projects/${ENCODED_PROJECT_ID}/characters/%E6%9E%97%E7%85%A7/consistency-check`, async (route) => {
    postedPlan = route.request().postDataJSON() as Record<string, unknown>;
    return fulfill(route, {
      character_name: "林照",
      target_chapter: 5,
      historical_boundary: 4,
      warnings: [{
        code: "SKILL_NOT_YET_ACQUIRED",
        severity: "warning",
        character_name: "林照",
        target_chapter: 5,
        message: "第5章计划使用技能“御火诀”，但历史记录显示该技能尚未获得。",
        expected: "御火诀",
        observed: { acquired_chapter: 8 },
        evidence: { source: "progression_ledger" },
        source: "progression_ledger",
        suggestion: "确认技能获得章节。",
      }],
    });
  });

  await page.goto(`/projects/${ENCODED_PROJECT_ID}/characters`);
  const panel = page.locator(".ws-character-inspection");
  await expect(panel.getByRole("heading", { name: "历史检查", exact: true })).toBeVisible();
  await expect(panel.getByTestId("character-timeline-event")).toHaveCount(2);
  await expect(panel.getByTestId("character-timeline-event").first()).toContainText("第 5 章");
  await panel.getByRole("tab", { name: "一致性", exact: true }).click();
  await panel.getByLabel("结构化计划 JSON").fill(JSON.stringify({ skills_used: ["御火诀"] }));
  await panel.getByRole("button", { name: "运行一致性检查", exact: true }).click();
  await expect(panel.getByTestId("character-consistency-warning")).toContainText("SKILL_NOT_YET_ACQUIRED");
  await expect.poll(() => postedPlan).toMatchObject({
    target_chapter: 5,
    planned_context: { character_name: "林照", skills_used: ["御火诀"] },
  });
});
