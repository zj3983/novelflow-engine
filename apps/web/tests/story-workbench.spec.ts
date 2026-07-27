import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page, type Route } from "@playwright/test";

import playwrightConfig from "../playwright.config";
import * as workspaceProvider from "../components/ws/ProjectWorkspaceProvider";

import { ConfirmedFactsPanel } from "../components/ws/ConfirmedFactsPanel";
import {
  WorldEntitySaveStatus,
  addWorldEntity,
  createWorldEntitiesEditorState,
  editWorldEntity,
  markWorldEntitiesSaved,
  mergeWorldEntitiesProps,
  removeWorldEntity,
  saveWorldEntities,
  syncWorldEntitiesBlueprintStore,
  type WorldEntitiesBlueprintStore,
} from "../components/ws/WorldEntitiesEditor";
import {
  WORLD_BACKGROUND_FIELDS,
  createWorldBackgroundEditorState,
  editWorldBackgroundField,
  markWorldBackgroundSaved,
  mergeWorldBackgroundProps,
  saveWorldBackground,
} from "../components/ws/WorldBackgroundEditor";
import {
  WORLD_RULE_EDITOR_SECTIONS,
  createWorldRulesEditorState,
  editWorldRuleField,
  markWorldRuleSaved,
  mergeWorldRulesProps,
  saveWorldRules,
  syncWorldBlueprintStore,
} from "../components/ws/WorldRulesEditor";
import { type ImportedWorldBlueprint, type updateProject } from "../lib/api";
import { groupWorldFacts } from "../lib/worldDisplay";
import { buildWritingFlow, writingFlowPlanningSourceText } from "../components/ws/WritingFlow";
import { resolveChapterDirectionId } from "../lib/chapterDirections";

test("chapter planning source is shown in plain language", () => {
  expect(writingFlowPlanningSourceText({ planning_source: "outline" })).toBe("已有章节细纲");
  expect(writingFlowPlanningSourceText({ planning_source: "model_fallback" })).toBe("模型补全");
  expect(writingFlowPlanningSourceText({})).toBe("");
});

test("chapter direction selection tolerates an omitted options array", () => {
  expect(resolveChapterDirectionId("old", undefined, "recommended")).toBe("");
  expect(resolveChapterDirectionId("", [], "recommended")).toBe("");
  expect(resolveChapterDirectionId("old", [{ id: "next" }], "missing")).toBe("next");
});

test("写作流程只读取结构化步骤并展示资料来源", () => {
  const flow = buildWritingFlow([
    {
      message: "读取大纲完成",
      status: "done",
      stage: "read_outline",
      source: "context_loader",
      artifact: {
        workflow_step: {
          id: "read_outline",
          label: "读取大纲",
          reads: ["总纲", "第2章细纲", "上一章结尾"],
        },
        outputs: { chapter_goal: "推进灰狼坡任务" },
      },
    },
    { message: "模型请求耗时 2.1s", status: "done", stage: "writer", source: "llm" },
  ]);

  expect(flow).toHaveLength(1);
  expect(flow[0]).toMatchObject({
    key: "read_outline",
    label: "读取大纲",
    status: "done",
    reads: ["总纲", "第2章细纲", "上一章结尾"],
    outputs: { chapter_goal: "推进灰狼坡任务" },
  });
});

test("Playwright 配置统一读取浏览器可执行路径", () => {
  const use = playwrightConfig.use as { launchOptions?: { executablePath?: string } };
  const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH;

  if (executablePath) {
    expect(use.launchOptions?.executablePath).toBe(executablePath);
  } else {
    expect(use.launchOptions?.executablePath).toBeUndefined();
  }
});

test("浏览器测试使用独立的 Next 开发缓存目录", () => {
  const webServer = playwrightConfig.webServer as { env?: Record<string, string> };
  const port = process.env.PLAYWRIGHT_PORT || "3100";
  const nextConfigSource = fs.readFileSync(path.resolve(__dirname, "../next.config.mjs"), "utf-8");

  expect(webServer.env?.NEXT_DIST_DIR).toBe(`.next-e2e-${port}`);
  expect(nextConfigSource).toContain("process.env.NEXT_DIST_DIR");
});

test("切换项目时可见状态不会泄漏旧项目错误", () => {
  const selectProjectWorkspaceView = (
    workspaceProvider as unknown as {
      selectProjectWorkspaceView?: (input: {
        hasCurrentProject: boolean;
        project: unknown;
        story: unknown;
        loading: boolean;
        error: string | null;
      }) => { project: unknown; story: unknown; loading: boolean; error: string | null };
    }
  ).selectProjectWorkspaceView;

  expect(typeof selectProjectWorkspaceView).toBe("function");
  expect(selectProjectWorkspaceView?.({
    hasCurrentProject: true,
    project: null,
    story: null,
    loading: false,
    error: "旧项目加载失败",
  })).toEqual({ project: null, story: null, loading: false, error: "旧项目加载失败" });
  expect(selectProjectWorkspaceView?.({
    hasCurrentProject: false,
    project: { project_id: "file:failed-project" },
    story: { story_id: "file:failed-project" },
    loading: false,
    error: "旧项目加载失败",
  })).toEqual({ project: null, story: null, loading: true, error: null });
});

test("提示词工作台分开模板、上下文和真实调用", async ({ page }) => {
  const projectId = "file:prompt-workbench-fixture";
  const projectPath = `/projects/${encodeURIComponent(projectId)}`;
  let savedProjectTemplate = "";
  await page.route("**/file-projects/**", async (route) => {
    const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
    if (pathname.includes("/prompt-templates")) {
      if (route.request().method() === "PUT") {
        savedProjectTemplate = String((route.request().postDataJSON() as { content?: string }).content ?? "");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ key: "writer", title: "整章正文写作", stage: "writing", content: savedProjectTemplate, required_variables: ["output_section", "chapter_direction"], version: "sha256:saved", source: "project_override" }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "project-prompt-templates/v1",
          project_id: projectId,
          templates: [
            {
              key: "writer",
              title: "整章正文写作",
              stage: "writing",
              content: "{{output_section}}\n{{chapter_direction}}",
              required_variables: ["output_section", "chapter_direction"],
              version: "sha256:test",
              source: "global_default",
            },
          ],
        }),
      });
      return;
    }
    if (pathname.endsWith("/prompt-context")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "file-project-prompt-context/v1",
          project_id: projectId,
          chapter_number: 1,
          source: "current_project_context",
          modules: [
            { key: "character_context", title: "本章人物模块", stage: "人物角色卡", source: "character", content: "苏叶", chars: 2, available: true },
          ],
        }),
      });
      return;
    }
    if (pathname.endsWith("/prompt-calls")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          schema_version: "prompt-call-list/v1",
          project_id: projectId,
          chapter_number: 1,
          calls: [
            { call_id: "pc-test", chapter_number: 1, stage: "正文写作", agent: "writer", attempt: 1, status: "succeeded", provider: "openai", model: "deepseek-v4-flash", prompt_chars: 1200 },
          ],
        }),
      });
      return;
    }
    if (pathname.endsWith("/prompt-calls/pc-test")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ call_id: "pc-test", chapter_number: 1, stage: "正文写作", attempt: 1, status: "succeeded", user_prompt: "真实最终 Prompt", module_keys: ["character_context"] }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        project_id: projectId,
        title: "提示词测试",
        active_story_id: "",
        status: "draft",
        pipeline_stage: "idea_pending",
        branches: [],
        storage_source: "file",
      }),
    });
  });

  await page.goto(`${projectPath}/prompts`);
  await expect(page.getByRole("tab", { name: "提示词模板" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("原始模板")).toHaveValue(/\{\{chapter_direction\}\}/);
  await expect(page.getByText("苏叶", { exact: true })).toHaveCount(0);
  await page.getByLabel("原始模板").fill("项目模板\n{{output_section}}\n{{chapter_direction}}");
  await page.getByRole("button", { name: "保存为项目覆盖" }).click();
  await expect.poll(() => savedProjectTemplate).toContain("项目模板");

  await page.getByRole("tab", { name: "上下文模块" }).click();
  await expect(page).toHaveURL(`${projectPath}/prompts?view=context&chapter=1`);
  await expect(page.getByText("本章人物模块", { exact: true })).toBeVisible();

  await page.getByRole("tab", { name: "实际调用" }).click();
  await expect(page.getByText("第 1 次 · 正文写作", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "查看调用 pc-test" }).click();
  await expect(page.getByText("真实最终 Prompt", { exact: true })).toBeVisible();
});

test("地点草稿编辑保留附加字段，服务端刷新不覆盖未保存实体", () => {
  const blueprint = {
    locations: [{ name: "旧港", description: "旧描述", danger_level: "high" }],
    factions: [{ name: "巡夜会", description: "旧宗旨", influence: 7 }],
  } as ImportedWorldBlueprint;
  let state = createWorldEntitiesEditorState(blueprint);

  state = editWorldEntity(state, "locations", 0, "name", "新港");
  state = editWorldEntity(state, "factions", 0, "description", "未保存宗旨");
  state = mergeWorldEntitiesProps(state, {
    ...blueprint,
    locations: [{ name: "服务端港口", description: "服务端描述" }],
    factions: [{ name: "巡夜会", description: "服务端宗旨" }],
  });

  expect(state.drafts.locations[0]).toEqual({
    name: "新港",
    description: "旧描述",
    danger_level: "high",
  });
  expect(state.drafts.factions[0].description).toBe("未保存宗旨");
});

test("连续保存地点和阵营会基于最新蓝图且保留怪物卡", async () => {
  const blueprint = {
    locations: [{ name: "旧港", description: "旧描述", danger_level: "high" }],
    factions: [{ name: "旧阵营", description: "旧宗旨" }],
    monster_profiles: [{ id: "wolf", name: "灰狼" }],
  } as ImportedWorldBlueprint;
  const blueprintStore: WorldEntitiesBlueprintStore = { current: blueprint };
  const calls: Parameters<typeof updateProject>[] = [];
  const updater = (async (...args: Parameters<typeof updateProject>) => {
    calls.push(args);
    return { world_blueprint: args[1].world_blueprint } as Awaited<ReturnType<typeof updateProject>>;
  }) as typeof updateProject;

  await saveWorldEntities({
    projectId: "file:world-entities-fixture",
    field: "locations",
    entities: [{ ...blueprint.locations![0], name: "新港" }],
    blueprintStore,
    updater,
  });
  syncWorldEntitiesBlueprintStore(blueprintStore, blueprint);
  await saveWorldEntities({
    projectId: "file:world-entities-fixture",
    field: "factions",
    entities: [{ ...blueprint.factions![0], name: "新阵营" }],
    blueprintStore,
    updater,
  });

  expect(calls[0][1].world_blueprint).toEqual({
    locations: [{ name: "新港", description: "旧描述", danger_level: "high" }],
  });
  expect(calls[1][1].world_blueprint).toEqual({
    factions: [{ name: "新阵营", description: "旧宗旨" }],
  });
  expect(calls[0][2]).toEqual({ fallbackToMock: false });
  expect(calls[1][2]).toEqual({ fallbackToMock: false });
});

test("实体保存期间继续编辑不会误报成功", () => {
  let state = createWorldEntitiesEditorState({
    locations: [{ name: "旧港", description: "旧描述" }],
  });
  state = editWorldEntity(state, "locations", 0, "name", "提交名称");
  const submitted = state.drafts.locations;
  state = editWorldEntity(state, "locations", 0, "name", "请求期间新名称");
  state = markWorldEntitiesSaved(state, "locations", submitted);

  expect(state.statuses.locations).toBe("idle");
});

test("新增实体设置 dirty、清除成功状态并保留已有项附加字段", () => {
  let state = createWorldEntitiesEditorState({
    locations: [{ name: "旧港", description: "旧描述", danger_level: "high" }],
  });
  state = markWorldEntitiesSaved(state, "locations", state.drafts.locations);
  state = addWorldEntity(state, "locations");

  expect(state.dirty.locations).toBe(true);
  expect(state.statuses.locations).toBe("idle");
  expect(state.drafts.locations).toEqual([
    { name: "旧港", description: "旧描述", danger_level: "high" },
    { name: "", description: "" },
  ]);
});

test("删除实体设置 dirty、清除成功状态并保留其余项附加字段", () => {
  let state = createWorldEntitiesEditorState({
    factions: [
      { name: "旧阵营", description: "待删除", influence: 1 },
      { name: "巡夜会", description: "保留", influence: 7 },
    ],
  });
  state = markWorldEntitiesSaved(state, "factions", state.drafts.factions);
  state = removeWorldEntity(state, "factions", 0);

  expect(state.dirty.factions).toBe(true);
  expect(state.statuses.factions).toBe("idle");
  expect(state.drafts.factions).toEqual([
    { name: "巡夜会", description: "保留", influence: 7 },
  ]);
});

test("保存请求期间新增或删除实体不会把提交快照误报为成功", () => {
  let addedState = createWorldEntitiesEditorState({
    locations: [{ name: "旧港", description: "旧描述", danger_level: "high" }],
  });
  const addSubmitted = addedState.drafts.locations;
  addedState = addWorldEntity(addedState, "locations");
  addedState = markWorldEntitiesSaved(addedState, "locations", addSubmitted);
  expect(addSubmitted).toHaveLength(1);
  expect(addedState.statuses.locations).toBe("idle");
  expect(addedState.dirty.locations).toBe(true);
  expect(addedState.drafts.locations[0].danger_level).toBe("high");

  let removedState = createWorldEntitiesEditorState({
    factions: [
      { name: "旧阵营", description: "待删除", influence: 1 },
      { name: "巡夜会", description: "保留", influence: 7 },
    ],
  });
  const removeSubmitted = removedState.drafts.factions;
  removedState = removeWorldEntity(removedState, "factions", 0);
  removedState = markWorldEntitiesSaved(removedState, "factions", removeSubmitted);
  expect(removeSubmitted).toHaveLength(2);
  expect(removedState.statuses.factions).toBe("idle");
  expect(removedState.dirty.factions).toBe(true);
  expect(removedState.drafts.factions[0].influence).toBe(7);
});

test("实体保存状态使用 polite live status，错误保持 alert", () => {
  const saving = JSON.stringify(WorldEntitySaveStatus({ status: "saving" }));
  const success = JSON.stringify(WorldEntitySaveStatus({ status: "success" }));
  const error = JSON.stringify(WorldEntitySaveStatus({ status: "error", error: "网络错误" }));

  expect(saving).toContain('"role":"status"');
  expect(saving).toContain('"aria-live":"polite"');
  expect(saving).toContain("保存中...");
  expect(success).toContain('"role":"status"');
  expect(success).toContain('"aria-live":"polite"');
  expect(success).toContain("保存成功");
  expect(error).toContain('"role":"alert"');
  expect(error).toContain("保存失败：网络错误");
});

test("世界事实完整分组并去掉章节来源前缀", () => {
  const projectFacts = Array.from({ length: 25 }, (_, index) => `项目事实${index + 1}`);
  const grouped = groupWorldFacts([
    ...projectFacts,
    "第2章事实：第二章唯一事实",
    "第1章事实：第一章事实甲",
    "第 1 章事实：第一章事实乙",
    "   ",
  ]);

  expect(grouped.projectFacts).toHaveLength(25);
  expect(grouped.projectFacts[24]).toBe("项目事实25");
  expect(grouped.chapters).toEqual([
    { chapterNumber: 1, facts: ["第一章事实甲", "第一章事实乙"] },
    { chapterNumber: 2, facts: ["第二章唯一事实"] },
  ]);
});

test("世界事实保留重复记录并严格匹配章节事实前缀", () => {
  const grouped = groupWorldFacts([
    "重复项目事实",
    "重复项目事实",
    "第3章事实: ASCII 事实",
    "第3章事实: ASCII 事实",
    "第3章事实-错误前缀",
    "第x章事实：错误章节号",
  ]);

  expect(grouped.projectFacts).toEqual([
    "重复项目事实",
    "重复项目事实",
    "第3章事实-错误前缀",
    "第x章事实：错误章节号",
  ]);
  expect(grouped.chapters).toEqual([
    { chapterNumber: 3, facts: ["ASCII 事实", "ASCII 事实"] },
  ]);
});

test("已确认事实面板真实渲染标题、只读说明和空状态", () => {
  const markup = JSON.stringify(ConfirmedFactsPanel({ facts: [] }));

  expect(markup).toContain("已确认事实");
  expect(markup).toContain("由章节回写，不在此处直接修改");
  expect(markup).toContain("暂无已确认事实");
  expect(markup).not.toContain("编辑");
  expect(markup).not.toContain("删除");
});

test("服务端刷新只同步未修改的世界背景和规则字段", () => {
  const original: ImportedWorldBlueprint = {
    premise: "旧前提",
    current_arc: "旧局势",
    world_rules: ["旧基础规则"],
    progression_rules: ["旧成长规则"],
  };
  let backgroundState = createWorldBackgroundEditorState("旧摘要", original);
  backgroundState = editWorldBackgroundField(backgroundState, "premise", "未保存前提");
  backgroundState = mergeWorldBackgroundProps(backgroundState, "服务端新摘要", {
    ...original,
    premise: "服务端新前提",
    current_arc: "服务端新局势",
  });
  expect(backgroundState.values).toEqual({
    world_summary: "服务端新摘要",
    premise: "未保存前提",
    current_arc: "服务端新局势",
  });

  let rulesState = createWorldRulesEditorState(original);
  rulesState = editWorldRuleField(rulesState, "world_rules", "未保存基础规则");
  rulesState = mergeWorldRulesProps(rulesState, {
    ...original,
    world_rules: ["服务端新基础规则"],
    progression_rules: ["服务端新成长规则"],
  });
  expect(rulesState.drafts.world_rules).toBe("未保存基础规则");
  expect(rulesState.drafts.progression_rules).toBe("服务端新成长规则");
});

test("规则服务端回显按语义确认 dirty 并同步规范文本", () => {
  let state = createWorldRulesEditorState({ world_rules: ["旧规则"] });
  state = editWorldRuleField(state, "world_rules", " 新规则 \n\n");
  state = mergeWorldRulesProps(state, { world_rules: ["新规则"] });

  expect(state.dirty.world_rules).toBe(false);
  expect(state.drafts.world_rules).toBe("新规则");
});

test("连续保存两个规则字段时在上一响应蓝图上合并", async () => {
  const staleBlueprint: ImportedWorldBlueprint = {
    world_rules: ["旧基础规则"],
    reality_bridge_rules: ["旧现实规则"],
    monster_profiles: [{ id: "wolf", name: "灰狼" }],
  };
  const blueprintStore = {
    current: staleBlueprint,
  };
  const calls: Parameters<typeof updateProject>[] = [];
  const updater = (async (...args: Parameters<typeof updateProject>) => {
    calls.push(args);
    return { world_blueprint: args[1].world_blueprint } as Awaited<ReturnType<typeof updateProject>>;
  }) as typeof updateProject;

  await saveWorldRules({
    projectId: "file:world-editor-fixture",
    field: "world_rules",
    text: "新基础规则",
    blueprintStore,
    updater,
  });
  syncWorldBlueprintStore(blueprintStore, staleBlueprint);
  await saveWorldRules({
    projectId: "file:world-editor-fixture",
    field: "reality_bridge_rules",
    text: "新现实规则",
    blueprintStore,
    updater,
  });

  expect(calls[0][1].world_blueprint).toEqual({ world_rules: ["新基础规则"] });
  expect(calls[1][1].world_blueprint).toEqual({ reality_bridge_rules: ["新现实规则"] });
});

test("保存成功后再次编辑会清除对应成功状态", () => {
  let backgroundState = createWorldBackgroundEditorState("摘要", {});
  backgroundState = markWorldBackgroundSaved(backgroundState, backgroundState.values);
  backgroundState = editWorldBackgroundField(backgroundState, "world_summary", "新摘要");
  expect(backgroundState.status).toBe("idle");

  let rulesState = createWorldRulesEditorState({ world_rules: ["规则"] });
  rulesState = markWorldRuleSaved(rulesState, "world_rules", rulesState.drafts.world_rules);
  rulesState = editWorldRuleField(rulesState, "world_rules", "新规则");
  expect(rulesState.statuses.world_rules).toBeUndefined();
});

test("保存请求期间的新编辑不会被完成响应标记为成功", () => {
  let backgroundState = createWorldBackgroundEditorState("旧摘要", { premise: "旧前提" });
  backgroundState = editWorldBackgroundField(backgroundState, "premise", "提交前提");
  const submittedBackground = { ...backgroundState.values };
  backgroundState = editWorldBackgroundField(backgroundState, "premise", "请求期间的新前提");
  backgroundState = markWorldBackgroundSaved(backgroundState, submittedBackground);
  expect(backgroundState.status).toBe("idle");

  let rulesState = createWorldRulesEditorState({ world_rules: ["旧规则"] });
  rulesState = editWorldRuleField(rulesState, "world_rules", "提交规则");
  const submittedRules = rulesState.drafts.world_rules;
  rulesState = editWorldRuleField(rulesState, "world_rules", "请求期间的新规则");
  rulesState = markWorldRuleSaved(rulesState, "world_rules", submittedRules);
  expect(rulesState.statuses.world_rules).toBeUndefined();
});

test("世界背景与分类规则编辑器保留蓝图其他字段并独立保存规则", async () => {
  const blueprint: ImportedWorldBlueprint = {
    premise: "旧世界前提",
    current_arc: "旧局势",
    world_rules: ["旧基础规则"],
    progression_rules: ["旧成长规则"],
    quest_rules: ["旧任务规则"],
    economy_rules: ["旧经济规则"],
    reality_bridge_rules: ["旧现实规则"],
    monster_profiles: [{ id: "wolf", name: "灰狼" }],
  };
  const calls: Parameters<typeof updateProject>[] = [];
  const updater = (async (...args: Parameters<typeof updateProject>) => {
    calls.push(args);
    return { world_blueprint: args[1].world_blueprint } as Awaited<ReturnType<typeof updateProject>>;
  }) as typeof updateProject;
  let savedCount = 0;

  expect(WORLD_BACKGROUND_FIELDS.map((field) => field.label)).toEqual(["项目摘要", "世界前提", "当前局势"]);

  await saveWorldBackground({
    projectId: "file:world-editor-fixture",
    worldSummary: "新项目摘要",
    premise: "新世界前提",
    currentArc: "新局势",
    blueprint,
    onSaved: () => { savedCount += 1; },
    updater,
  });
  expect(calls[0][1]).toEqual({
    world_summary: "新项目摘要",
    world_blueprint: { premise: "新世界前提", current_arc: "新局势" },
  });
  expect(calls[0][2]).toEqual({ fallbackToMock: false });

  const ruleSections = WORLD_RULE_EDITOR_SECTIONS.map((section) => ({
    title: section.title,
    wide: section.wide,
    fields: section.fields.map(({ field, label, buttonLabel }) => ({ field, label, buttonLabel })),
  }));
  expect(ruleSections).toEqual([
    {
      title: "基础规则",
      wide: true,
      fields: [{ field: "world_rules", label: "基础规则", buttonLabel: "保存基础规则" }],
    },
    {
      title: "成长体系",
      wide: true,
      fields: [
        { field: "power_system", label: "等级、职业与技能", buttonLabel: "保存力量体系" },
        { field: "progression_rules", label: "成长与战斗边界", buttonLabel: "保存成长规则" },
      ],
    },
    {
      title: "经济体系",
      wide: false,
      fields: [{ field: "economy_rules", label: "货币、价格与交易", buttonLabel: "保存经济体系" }],
    },
    {
      title: "任务体系",
      wide: false,
      fields: [{ field: "quest_rules", label: "任务类型、状态与奖励", buttonLabel: "保存任务体系" }],
    },
    {
      title: "阵营与面板",
      wide: true,
      fields: [
        { field: "faction_rules", label: "阵营规则", buttonLabel: "保存阵营规则" },
        { field: "panel_rules", label: "面板规则", buttonLabel: "保存面板规则" },
      ],
    },
    {
      title: "游戏影响现实",
      wide: true,
      fields: [{ field: "reality_bridge_rules", label: "游戏影响现实规则", buttonLabel: "保存游戏影响现实规则" }],
    },
    {
      title: "世界硬约束",
      wide: true,
      fields: [
        { field: "constraints", label: "世界硬约束", buttonLabel: "保存世界硬约束" },
        { field: "forbidden_breaks", label: "不可违反规则", buttonLabel: "保存不可违反规则" },
      ],
    },
  ]);
  expect(ruleSections.find((section) => section.title === "成长体系")?.fields).toHaveLength(2);
  expect(ruleSections.filter((section) => ["经济体系", "任务体系"].includes(section.title))).toHaveLength(2);
  expect(ruleSections.map((section) => section.title)).not.toContain("任务与经济");
  expect(WORLD_RULE_EDITOR_SECTIONS.flatMap((section) => section.fields.map((field) => field.field))).not.toContain("chapter_formula");

  await saveWorldRules({
    projectId: "file:world-editor-fixture",
    field: "reality_bridge_rules",
    text: " 新现实规则一 \n\n新现实规则二\n   ",
    blueprintStore: { current: blueprint },
    onSaved: () => { savedCount += 1; },
    updater,
  });
  expect(calls[1][1].world_blueprint).toEqual({ reality_bridge_rules: ["新现实规则一", "新现实规则二"] });
  expect(calls[1][2]).toEqual({ fallbackToMock: false });
  expect(savedCount).toBe(2);
});

function currentProjectFixture(projectId: string) {
  return {
    project_id: projectId,
    title: "灰狼坡纪事",
    source_path: "D:/novels/gray-wolf",
    seed_outline: "主角沿灰狼坡的线索追查失踪案。",
    world_summary: "现实与游戏线并行推进。",
    current_focus: "追查灰狼坡留下的交易线索。",
    author_constraints: [],
    world_blueprint: { premise: "游戏事件会留下现实痕迹", constraints: ["交易必须遵守市场规则"] },
    character_profiles: [],
    relationship_graph: [],
    enabled_skill_ids: [],
    status: "writing",
    pipeline_stage: "writing",
    active_story_id: projectId,
    branches: [],
    storage_source: "file",
  };
}

function currentStoryFixture(projectId: string, body = "林照在灰狼坡发现了一枚刻着商会印记的旧铜牌。") {
  return {
    story_id: projectId,
    outline: "沿交易线索查清失踪案。",
    genre: "网游",
    style: "白描",
    current_chapter: 1,
    agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
    agent_runtime: { recent_events: [] },
    author_constraints: [],
    world_facts: ["灰狼坡与临川商会存在旧交易"],
    characters: [],
    history: [{
      chapter_number: 1,
      chapter_title: "灰狼坡旧痕",
      body,
      chapter_summary: { chapter_number: 1, summary: "林照找到商会留下的线索。", facts: [], unresolved_threads: ["铜牌主人是谁"] },
      next_outline: "循着铜牌查到临川商会。",
      quality_report: { ok: true, issues: [] },
    }],
    parent_story_id: null,
    branched_from_chapter: null,
  };
}

async function routeCurrentFileProject(page: Page, fixtureName: string) {
  const projectId = `file:${fixtureName}`;
  const project = currentProjectFixture(projectId);
  const story = currentStoryFixture(projectId);
  const encodedId = encodeURIComponent(projectId);
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    if (route.request().method() === "PUT") {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      Object.assign(project, payload);
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route(`**/file-stories/${encodedId}`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(story) });
  });
  return { projectId, encodedId, project, story };
}

async function routeProjectLists(page: Page, projects: unknown[]) {
  await page.route("**/projects", async (route) => {
    if (route.request().resourceType() === "document") {
      await route.fallback();
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(projects) });
  });
  await page.route("**/file-projects", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
}

const OPENING_PROJECT_ID = "file:opening-setup";
const OPENING_PROJECT_PATH = `/projects/${encodeURIComponent(OPENING_PROJECT_ID)}`;

const openingBrief = {
  schema_version: "opening-brief/v1",
  mode: "inspiration",
  novel_type_id: "urban",
  idea: "失业律师替陌生人追一笔旧账",
  working_title: "",
};

const openingDirections = [
  {
    id: "direction-1",
    title: "雨夜遗嘱",
    hook: "陌生人的遗嘱在雨夜生效。",
    protagonist_goal: "查清旧账的真正债主。",
    main_conflict: "律师必须对抗伪造证据的前同事。",
    growth_path: "从自保走向承担真相的代价。",
    opening_promise: "每笔旧账都会牵出一段被改写的人生。",
  },
  {
    id: "direction-2",
    title: "夜班追债",
    hook: "午夜委托人只留下明天才会出现的欠条。",
    protagonist_goal: "在欠条兑现前找到失踪的委托人。",
    main_conflict: "旧律所和神秘债主同时封锁线索。",
    growth_path: "从不再相信任何人到重新选择同盟。",
    opening_promise: "追债过程不断反转债务人与受害者的身份。",
  },
  {
    id: "direction-3",
    title: "无名账本",
    hook: "一本没有姓名的账本记录着城市里尚未发生的交易。",
    protagonist_goal: "阻止下一笔致命交易。",
    main_conflict: "主角每改动一笔账，现实就会索取新的代价。",
    growth_path: "从利用规则翻身到主动打破规则。",
    opening_promise: "账本的每一页都将制造一次现实选择题。",
  },
];

function openingSetupPayload(
  {
    directions = [],
    selectedId = "",
    nextPath = `${OPENING_PROJECT_PATH}/setup`,
  }: { directions?: typeof openingDirections; selectedId?: string; nextPath?: string } = {},
) {
  return {
    brief: openingBrief,
    directions,
    selected_id: selectedId,
    pipeline_stage: selectedId ? "outlining" : directions.length > 0 ? "direction_ready" : "idea_pending",
    next_path: nextPath,
  };
}

async function routeOpeningProject(page: Page, handleOpeningRequest: (route: Route) => Promise<void>) {
  await page.route("**/file-projects/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname.includes("/opening-directions")) {
      await handleOpeningRequest(route);
      return;
    }
    if (request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          project_id: OPENING_PROJECT_ID,
          title: "未命名作品",
          source_path: "",
          seed_outline: openingBrief.idea,
          world_summary: "",
          current_focus: "",
          author_constraints: [],
          world_blueprint: {},
          character_profiles: [],
          relationship_graph: [],
          enabled_skill_ids: [],
          status: "draft",
          pipeline_stage: "idea_pending",
          active_story_id: "",
          branches: [],
          storage_source: "file",
        }),
      });
      return;
    }
    await route.abort();
  });
}

async function routeProjectCreationNovelTypes(page: Page) {
  await page.route("**/novel-types", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: "generic_webnovel", name: "通用网文", description: "通用创作规则。", builtin: true },
        { id: "xuanhuan", name: "东方玄幻", description: "力量成长与世界秘密。", builtin: true },
        { id: "urban", name: "都市现代", description: "现实利益与身份关系。", builtin: true },
      ]),
    });
  });
}

test("projects page creates entry beside the recent project", async ({ page }) => {
  const recentProject = {
    project_id: "file:p-recent",
    title: "照夜行",
    status: "draft",
    pipeline_stage: "draft",
    active_story_id: "file:p-recent",
    current_chapter: 0,
    source_path: "",
    storage_source: "file",
  };
  await page.addInitScript(() => window.localStorage.setItem("novel-autogrowth.last-project-id", "file:p-recent"));
  await routeProjectLists(page, [recentProject]);

  await page.goto("/projects");

  await expect(page.getByRole("link", { name: "新建小说" })).toBeVisible();
  await expect(page.getByRole("link", { name: "继续上次作品" })).toBeVisible();
});

test("projects page creates entry in the empty state", async ({ page }) => {
  await routeProjectLists(page, []);

  await page.goto("/projects");

  await expect(page.getByText("还没有作品")).toBeVisible();
  await expect(page.getByRole("link", { name: "新建小说" })).toHaveCount(2);
});

test("projects page creates tabs with complete keyboard navigation", async ({ page }) => {
  await page.goto("/projects/new");

  const inspirationTab = page.getByRole("tab", { name: "从灵感开书" });
  const blankTab = page.getByRole("tab", { name: "建立空白小说" });
  const continuationTab = page.getByRole("tab", { name: "续写已有小说" });
  const tabpanel = page.getByRole("tabpanel");

  await expect(inspirationTab).toHaveAttribute("tabindex", "0");
  await expect(blankTab).toHaveAttribute("tabindex", "-1");
  await expect(continuationTab).toHaveAttribute("tabindex", "-1");
  await expect(inspirationTab).toHaveAttribute("aria-controls", "creation-form");
  await expect(blankTab).toHaveAttribute("aria-controls", "creation-form");
  await expect(continuationTab).toHaveAttribute("aria-controls", "continuation-import");
  await expect(tabpanel).toHaveAttribute("aria-labelledby", "creation-mode-inspiration");

  await inspirationTab.focus();
  await inspirationTab.press("ArrowRight");
  await expect(blankTab).toBeFocused();
  await expect(blankTab).toHaveAttribute("aria-selected", "true");
  await expect(blankTab).toHaveAttribute("tabindex", "0");
  await expect(inspirationTab).toHaveAttribute("tabindex", "-1");
  await expect(tabpanel).toHaveAttribute("aria-labelledby", "creation-mode-blank");

  await blankTab.press("ArrowRight");
  await expect(continuationTab).toBeFocused();
  await expect(continuationTab).toHaveAttribute("aria-selected", "true");
  await continuationTab.press("ArrowRight");
  await expect(inspirationTab).toBeFocused();
  await inspirationTab.press("ArrowLeft");
  await expect(continuationTab).toBeFocused();
  await continuationTab.press("ArrowLeft");
  await expect(blankTab).toBeFocused();
  await blankTab.press("Home");
  await expect(inspirationTab).toBeFocused();
  await inspirationTab.press("End");
  await expect(continuationTab).toBeFocused();
});

test("projects page creates a single-column form without mobile overflow", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto("/projects/new");

  const layout = await page.locator(".ws-project-create__form").evaluate((form) => {
    const bounds = form.getBoundingClientRect();
    const root = document.documentElement;
    return {
      columns: getComputedStyle(form).gridTemplateColumns.trim().split(/\s+/),
      clientWidth: root.clientWidth,
      scrollWidth: root.scrollWidth,
      formLeft: bounds.left,
      formRight: bounds.right,
    };
  });

  expect(layout.columns).toHaveLength(1);
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth);
  expect(layout.formLeft).toBeGreaterThanOrEqual(0);
  expect(layout.formRight).toBeLessThanOrEqual(layout.clientWidth);
});

test("projects page creates a blank file novel", async ({ page }) => {
  const requests: unknown[] = [];
  await routeProjectCreationNovelTypes(page);
  await page.route("**/file-projects", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      return;
    }
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        project_id: "file:p-blank",
        title: "照夜行",
        storage_source: "file",
        status: "draft",
        pipeline_stage: "draft",
        current_chapter: 0,
        next_path: "/projects/file%3Ap-blank/outline",
      }),
    });
  });

  await page.goto("/projects/new");
  await expect(page.getByRole("tablist", { name: "创建方式" })).toBeVisible();
  await page.getByRole("tab", { name: "建立空白小说" }).click();
  await expect(page.getByRole("textbox", { name: /^灵感/ })).toHaveCount(0);
  await expect(page.getByLabel("小说名")).toHaveAttribute("maxlength", "120");
  await page.getByLabel("小说名").fill("照夜行");
  await page.getByLabel("小说类型").selectOption("xuanhuan");
  await page.getByRole("button", { name: "创建小说" }).click();

  await expect(page).toHaveURL(/file%3Ap-blank\/outline$/);
  expect(requests).toEqual([{ mode: "blank", title: "照夜行", novel_type_id: "xuanhuan", idea: "" }]);
});

test("projects page creates an inspiration novel and preserves input after failure", async ({ page }) => {
  const requests: unknown[] = [];
  let attempt = 0;
  await routeProjectCreationNovelTypes(page);
  await page.route("**/file-projects", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      return;
    }
    requests.push(route.request().postDataJSON());
    attempt += 1;
    if (attempt === 1) {
      await route.fulfill({
        status: 422,
        contentType: "application/json",
        body: JSON.stringify({ detail: "暂时无法建立作品" }),
      });
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        project_id: "file:p-idea",
        title: "未命名作品",
        storage_source: "file",
        status: "draft",
        pipeline_stage: "idea_pending",
        current_chapter: 0,
        next_path: "/projects/file%3Ap-idea/setup",
      }),
    });
  });

  await page.goto("/projects/new");
  await expect(page.getByRole("tab", { name: "从灵感开书" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("textbox", { name: /^灵感/ })).toHaveAttribute("maxlength", "1000");
  await expect(page.getByRole("button", { name: "创建小说" })).toBeDisabled();
  await page.getByLabel("小说类型").selectOption("urban");
  await page.getByRole("textbox", { name: /^灵感/ }).fill("失业律师替陌生人追一笔旧账");
  await page.getByRole("button", { name: "创建小说" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "创建失败" })).toHaveText("创建失败：暂时无法建立作品");
  await expect(page.getByRole("textbox", { name: /^灵感/ })).toHaveValue("失业律师替陌生人追一笔旧账");
  await page.getByRole("button", { name: "创建小说" }).click();

  await expect(page).toHaveURL(/file%3Ap-idea\/setup$/);
  expect(requests).toEqual([
    { mode: "inspiration", title: "", novel_type_id: "urban", idea: "失业律师替陌生人追一笔旧账" },
    { mode: "inspiration", title: "", novel_type_id: "urban", idea: "失业律师替陌生人追一笔旧账" },
  ]);
});

test("opening setup GET keeps the inspiration visible without auto-generation or mobile overflow", async ({ page }) => {
  const openingMethods: string[] = [];
  await routeOpeningProject(page, async (route) => {
    openingMethods.push(route.request().method());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(openingSetupPayload()) });
  });
  await page.setViewportSize({ width: 375, height: 667 });

  await page.goto(`${OPENING_PROJECT_PATH}/setup`);

  await expect(page.getByRole("heading", { name: "选择开篇方向" })).toBeVisible();
  await expect(page.getByText(openingBrief.idea)).toBeVisible();
  await expect(page.getByRole("button", { name: "生成故事方向" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "本次补充要求" })).toHaveCount(0);
  await expect(page.getByRole("radio")).toHaveCount(0);
  expect(openingMethods.length).toBeGreaterThan(0);
  expect(openingMethods.every((method) => method === "GET")).toBe(true);
  const viewport = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);
});

test("opening setup sends one-time regeneration guidance and clears it after success", async ({ page }) => {
  const generationBodies: unknown[] = [];
  const generationContentTypes: string[] = [];
  let releaseGeneration: (() => void) | undefined;
  const generationReleased = new Promise<void>((resolve) => {
    releaseGeneration = resolve;
  });
  await routeOpeningProject(page, async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(openingSetupPayload({ directions: openingDirections })),
      });
      return;
    }
    generationBodies.push(request.postDataJSON());
    generationContentTypes.push(request.headers()["content-type"] ?? "");
    await generationReleased;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(openingSetupPayload({ directions: openingDirections })),
    });
  });
  await page.setViewportSize({ width: 375, height: 667 });

  await page.goto(`${OPENING_PROJECT_PATH}/setup`);
  const guidance = page.getByRole("textbox", { name: "本次补充要求" });
  const regenerateButton = page.locator(".ws-opening-actions > button").first();
  await expect(guidance).toBeVisible();
  await expect(guidance).toHaveAttribute("maxlength", "1000");
  await expect(guidance).toHaveAttribute("rows", "3");
  await guidance.fill("  增强悬念，让主角更早陷入两难  ");
  await regenerateButton.click();
  await expect(guidance).toBeDisabled();
  await regenerateButton.evaluate((button: HTMLButtonElement) => {
    button.click();
    button.click();
  });
  await expect.poll(() => generationBodies.length).toBe(1);
  expect(generationBodies).toEqual([{ guidance: "增强悬念，让主角更早陷入两难" }]);
  expect(generationContentTypes).toEqual(["application/json"]);

  releaseGeneration?.();
  await expect(guidance).toBeEnabled();
  await expect(guidance).toHaveValue("");
  const viewport = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(viewport.scrollWidth).toBeLessThanOrEqual(viewport.clientWidth);
});

test("opening setup retains regeneration guidance after generation failure", async ({ page }) => {
  await routeOpeningProject(page, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(openingSetupPayload({ directions: openingDirections })),
      });
      return;
    }
    await route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: "opening_direction_generation_failed" }),
    });
  });

  await page.goto(`${OPENING_PROJECT_PATH}/setup`);
  const guidance = page.getByRole("textbox", { name: "本次补充要求" });
  await guidance.fill("保留都市感，减少玄幻设定");
  await page.getByRole("button", { name: "重新生成" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "故事方向暂时生成失败" })).toBeVisible();
  await expect(guidance).toHaveValue("保留都市感，减少玄幻设定");
});

test("opening setup generates three plain radio sections and selects the second direction once", async ({ page }) => {
  let generateRequests = 0;
  const selectionUrls: string[] = [];
  await routeOpeningProject(page, async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(openingSetupPayload()) });
      return;
    }
    if (new URL(request.url()).pathname.endsWith("/select")) {
      selectionUrls.push(request.url());
      await new Promise((resolve) => setTimeout(resolve, 150));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          openingSetupPayload({
            directions: openingDirections,
            selectedId: "direction-2",
            nextPath: `${OPENING_PROJECT_PATH}/outline`,
          }),
        ),
      });
      return;
    }
    generateRequests += 1;
    await new Promise((resolve) => setTimeout(resolve, 150));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(openingSetupPayload({ directions: openingDirections })),
    });
  });

  await page.goto(`${OPENING_PROJECT_PATH}/setup`);
  const generateButton = page.getByRole("button", { name: /生成/ });
  await generateButton.click();
  await expect(generateButton).toBeDisabled();
  await generateButton.evaluate((button: HTMLButtonElement) => {
    button.click();
    button.click();
  });

  const sections = page.locator("section.ws-opening-direction");
  await expect(sections).toHaveCount(3);
  await expect(page.getByRole("radio")).toHaveCount(3);
  await expect(page.locator(".ws-opening-direction.ws-card")).toHaveCount(0);
  expect(generateRequests).toBe(1);
  for (const [index, direction] of openingDirections.entries()) {
    const section = sections.nth(index);
    await expect(section).toContainText(direction.title);
    await expect(section).toContainText(`开篇钩子${direction.hook}`);
    await expect(section).toContainText(`主角目标${direction.protagonist_goal}`);
    await expect(section).toContainText(`主线冲突${direction.main_conflict}`);
    await expect(section).toContainText(`成长路径${direction.growth_path}`);
    await expect(section).toContainText(`开篇承诺${direction.opening_promise}`);
  }

  const adoptButton = page.getByRole("button", { name: /采用/ });
  await expect(adoptButton).toBeDisabled();
  await page.getByRole("radio", { name: /夜班追债/ }).check();
  await expect(adoptButton).toBeEnabled();
  await adoptButton.click();
  await expect(adoptButton).toBeDisabled();
  await adoptButton.evaluate((button: HTMLButtonElement) => {
    button.click();
    button.click();
  });

  await expect(page).toHaveURL(`${OPENING_PROJECT_PATH}/outline`);
  expect(selectionUrls).toHaveLength(1);
  expect(decodeURIComponent(new URL(selectionUrls[0]).pathname)).toContain(
    `/file-projects/${OPENING_PROJECT_ID}/opening-directions/direction-2/select`,
  );
});

test("opening setup ignores a delayed select response after navigating away", async ({ page }) => {
  let markSelectStarted: (() => void) | undefined;
  let markSelectFulfilled: (() => void) | undefined;
  let releaseSelect: (() => void) | undefined;
  const selectStarted = new Promise<void>((resolve) => {
    markSelectStarted = resolve;
  });
  const selectReleased = new Promise<void>((resolve) => {
    releaseSelect = resolve;
  });
  const selectFulfilled = new Promise<void>((resolve) => {
    markSelectFulfilled = resolve;
  });
  await routeProjectLists(page, []);
  await routeOpeningProject(page, async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(openingSetupPayload({ directions: openingDirections })),
      });
      return;
    }
    markSelectStarted?.();
    await selectReleased;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        openingSetupPayload({
          directions: openingDirections,
          selectedId: "direction-2",
          nextPath: `${OPENING_PROJECT_PATH}/outline`,
        }),
      ),
    });
    markSelectFulfilled?.();
  });

  await page.goto(`${OPENING_PROJECT_PATH}/setup`);
  await page.getByRole("radio", { name: /夜班追债/ }).check();
  await page.getByRole("button", { name: "采用这个方向" }).click();
  await selectStarted;
  await page.getByRole("link", { name: "我的作品" }).click();
  await expect(page).toHaveURL("/projects");

  releaseSelect?.();
  await selectFulfilled;
  await page.waitForTimeout(500);
  await expect(page).toHaveURL("/projects");
});

test("opening setup preserves the brief and offers recovery after a 502 generation error", async ({ page }) => {
  await routeOpeningProject(page, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(openingSetupPayload()) });
      return;
    }
    await route.fulfill({
      status: 502,
      contentType: "application/json",
      body: JSON.stringify({ detail: "opening_direction_generation_failed" }),
    });
  });

  await page.goto(`${OPENING_PROJECT_PATH}/setup`);
  await page.getByRole("button", { name: "生成故事方向" }).click();

  await expect(page.getByText(openingBrief.idea)).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "故事方向暂时生成失败" })).toHaveText(
    "故事方向暂时生成失败，请稍后重新试一次。",
  );
  await expect(page.getByRole("button", { name: "重新生成" })).toBeVisible();
  await expect(page.getByRole("link", { name: "手动填写总纲" })).toHaveAttribute(
    "href",
    `${OPENING_PROJECT_PATH}/outline`,
  );
});

test("opening setup immediately replaces the route when GET is already selected", async ({ page }) => {
  const openingMethods: string[] = [];
  await routeOpeningProject(page, async (route) => {
    openingMethods.push(route.request().method());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        openingSetupPayload({
          directions: openingDirections,
          selectedId: "direction-2",
          nextPath: `${OPENING_PROJECT_PATH}/outline`,
        }),
      ),
    });
  });

  await page.goto(`${OPENING_PROJECT_PATH}/setup`);

  await expect(page).toHaveURL(`${OPENING_PROJECT_PATH}/outline`);
  expect(openingMethods.length).toBeGreaterThan(0);
  expect(openingMethods.every((method) => method === "GET")).toBe(true);
});

test("project overview foregrounds writing status and recent chapter history", async ({ page }) => {
  const { encodedId } = await routeCurrentFileProject(page, "overview-status");
  await page.goto(`/projects/${encodedId}`, { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "灰狼坡纪事" })).toBeVisible();
  await expect(page.getByText(/第 1 章 · \d+ 字 · 写作中/)).toBeVisible();
  await expect(page.getByRole("link", { name: "第 1 章 · 灰狼坡旧痕" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "世界响应" })).toBeVisible();
  await expect(page.getByText("循着铜牌查到临川商会。", { exact: true })).toBeVisible();
});

test("write page shows current progress and core writing actions", async ({ page }) => {
  const { encodedId } = await routeCurrentFileProject(page, "write-actions");
  await page.goto(`/projects/${encodedId}/write?chapter=1`, { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "章节：第 1 章" })).toBeVisible();
  await expect(page.getByLabel("章节目录")).toContainText("1 章");
  await expect(page.getByRole("button", { name: "生成下一章" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "重新生成本章" })).toBeEnabled();
});

test("file project outline edits three levels and runs outline generation", async ({ page }) => {
  let savedBody: Record<string, unknown> | null = null;
  let generationBody: Record<string, unknown> | null = null;
  const outline = {
    schema_version: "project-outline/v1",
    source: "saved",
    overall: {
      story: "林照追查祖祠旧案。",
      protagonist_goal: "",
      main_conflict: "宗门有人阻止他追查。",
      growth_path: "从杂役成长为内门弟子。",
      ending_direction: "查清旧案。",
      core_ending_chapter: 150,
      extension_ceiling_chapter: 500,
      current_strategy: "observe",
      ending_contract: "现实线和游戏线都完成核心结局。",
    },
    arcs: [
      {
        id: "opening",
        title: "祖祠阶段",
        start_chapter: 1,
        end_chapter: 30,
        goal: "找出纵火者",
        obstacle: "管事阻挠",
        payoff: "拿到旧名册",
        end_state: "进入外门调查",
        stage_antagonist: "赵衡",
        long_term_antagonist_traces: ["旧名册被换过"],
        game_line_payoff: "进入内门并获得新功法。",
        reality_line_payoff: "解决住处和眼前收入问题。",
        extension_gate: {
          continue_route: "进入内门并扩大旧案。",
          close_route: "回收旧名册并转入最终审判。",
        },
      },
    ],
    chapters: Array.from({ length: 31 }, (_, index) => {
      const chapterNumber = index === 30 ? 40 : index + 1;
      return {
        chapter_number: chapterNumber,
        title: index === 0 ? "守炉" : `第 ${chapterNumber} 章细纲`,
        goal: "检查断香炉",
        obstacle: "值夜弟子不配合",
        action: "核对香灰和名册",
        turn: "香灰里有内门令牌碎片",
        payoff: "确认有人来过",
        ending_hook: "脚印通向后山",
        cast: ["林照", "赵衡"],
      };
    }),
  };
  const project = {
    project_id: "file:outline-fixture",
    title: "Outline Fixture",
    source_path: "",
    seed_outline: outline.overall.story,
    world_summary: "",
    current_focus: "",
    author_constraints: [],
    world_blueprint: {},
    character_profiles: [],
    relationship_graph: [],
    enabled_skill_ids: [],
    status: "simulating",
    pipeline_stage: "simulating",
    active_story_id: "file:outline-fixture",
    branches: [],
    storage_source: "file",
  };

  await page.route("**/file-projects/file%3Aoutline-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-projects/file%3Aoutline-fixture/outline", async (route) => {
    if (route.request().method() === "PUT") {
      savedBody = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...savedBody, source: "saved" }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(outline) });
  });
  await page.route("**/file-projects/file%3Aoutline-fixture/outline/generate", async (route) => {
    generationBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_version: "generated-outline-plan/v1",
        mode: generationBody.mode,
        outline: { ...outline, source: undefined },
        characters: [],
        source: "generated",
      }),
    });
  });
  await page.route("**/file-stories/file%3Aoutline-fixture", async (route) => {
    const runtimeEntry = { source: "idle", provider: "", model: "", fallback_reason: "", last_run_chapter: 0 };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        story_id: "file:outline-fixture",
        outline: outline.overall.story,
        genre: "玄幻",
        style: "白描",
        current_chapter: 20,
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
          planner: runtimeEntry,
          writer: runtimeEntry,
          memory: runtimeEntry,
          recent_events: [],
        },
        author_constraints: [],
        world_facts: [],
        characters: [],
        history: [],
        parent_story_id: null,
        branched_from_chapter: null,
      }),
    });
  });

  await page.goto("/projects/file%3Aoutline-fixture/outline");
  await expect(page.getByText("章节计划还剩 10 章，请补充下一批。", { exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "总纲", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "阶段大纲", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "章节大纲", exact: true })).toBeVisible();
  await expect(page.getByLabel("核心完结章数")).toHaveValue("150");
  await expect(page.getByLabel("最大扩展章数")).toHaveValue("500");
  await expect(page.getByRole("radio", { name: "观察中" })).toBeChecked();
  await page.getByLabel("最大扩展章数").fill("30");
  await expect(page.getByText("章节计划还剩 10 章，请补充下一批。", { exact: true })).toBeHidden();
  await expect(page.getByText("最大扩展章数不能小于核心完结章数。", { exact: true })).toBeVisible();
  await page.getByLabel("最大扩展章数").fill("500");
  await expect(page.getByText("章节计划还剩 10 章，请补充下一批。", { exact: true })).toBeVisible();
  await expect(page.getByText("最大扩展章数不能小于核心完结章数。", { exact: true })).toBeHidden();
  await page.getByRole("radio", { name: "收束" }).check();
  await page.getByLabel("主角长期目标").fill("洗清父亲旧案");
  await page.getByRole("tab", { name: "阶段大纲", exact: true }).click();
  await expect(page.getByLabel("阶段名称")).toHaveValue("祖祠阶段");
  await expect(page.getByLabel("游戏线阶段结果")).toHaveValue("进入内门并获得新功法。");
  await expect(page.getByLabel("现实线阶段结果")).toHaveValue("解决住处和眼前收入问题。");
  await expect(page.getByLabel("继续路线")).toHaveValue("进入内门并扩大旧案。");
  await expect(page.getByLabel("收束路线")).toHaveValue("回收旧名册并转入最终审判。");
  await page.getByLabel("收束路线").fill("");
  await page.getByRole("tab", { name: "总纲", exact: true }).click();
  await expect(page.getByRole("radio", { name: "收束" })).toBeDisabled();
  await expect(page.getByText("请先填写当前阶段的收束路线。", { exact: true })).toBeVisible();
  await page.getByLabel("核心完结章数").fill("");
  await page.getByRole("button", { name: "保存大纲" }).click();
  await expect(page.getByText("请输入有效的核心完结章数和最大扩展章数。", { exact: true })).toBeVisible();
  expect(savedBody).toBeNull();
  await page.getByLabel("核心完结章数").fill("150");
  await page.getByRole("tab", { name: "阶段大纲", exact: true }).click();
  await page.getByLabel("收束路线").fill("回收旧名册并转入最终审判。");
  await page.getByRole("tab", { name: "章节大纲", exact: true }).click();
  await expect(page.getByLabel("暂定标题").first()).toHaveValue("守炉");
  await page.getByRole("button", { name: "保存大纲" }).click();

  expect(savedBody).toMatchObject({
    overall: {
      protagonist_goal: "洗清父亲旧案",
      core_ending_chapter: 150,
      extension_ceiling_chapter: 500,
      current_strategy: "close",
    },
    arcs: outline.arcs,
    chapters: outline.chapters,
  });
  expect(savedBody).not.toHaveProperty("source");

  await page.getByLabel("本次生成补充要求").fill("阶段对手必须有现实利益");
  await page.getByRole("button", { name: "重新生成" }).click();
  await expect.poll(() => generationBody).toEqual({ mode: "regenerate", guidance: "阶段对手必须有现实利益" });
  await expect(page.getByLabel("本次生成补充要求")).toHaveValue("");
  await page.getByRole("tab", { name: "阶段大纲", exact: true }).click();
  await expect(page.getByLabel("阶段对手")).toHaveValue("赵衡");
  await page.getByRole("tab", { name: "章节大纲", exact: true }).click();
  await expect(page.getByLabel("出场人物").first()).toHaveValue("林照\n赵衡");
  await page.getByRole("tab", { name: "总纲", exact: true }).click();
  await page.setViewportSize({ width: 375, height: 760 });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth))
    .toBe(true);
});

test("concrete character card shows and saves factual profile fields", async ({ page }) => {
  let savedBody: Record<string, unknown> | null = null;
  const character = {
    name: "林照",
    role: "protagonist",
    character_tier: "protagonist",
    first_appearance: 1,
    identity_profile: {
      aliases: [], gender: "男", age: 19, birthplace: "青崖镇", origin: "守祠人之子",
      current_identity: "祖祠杂役", occupation: "守炉杂役", affiliation: "赤霄宗",
    },
    background_profile: {
      family: "父亲因旧案失踪", upbringing: "由祖祠老仆带大", education_or_training: "识字，会修香炉",
      formative_events: ["十三岁目睹父亲被带走"], arrival_reason: "留在祖祠查父亲旧案",
    },
    current_life_profile: {
      residence: "祖祠偏房", livelihood: "守炉换取月例", economic_state: "只能维持吃住",
      resources_and_ability: "熟悉祖祠旧物", authority_scope: "只能进外院", immediate_problem: "香炉断裂会被问责",
    },
    story_drive: {
      long_term_goal: "查清父亲旧案", immediate_goal: "找出断炉的人", motivation: "不愿父亲背着罪名消失",
      failure_stakes: "会被逐出祖祠并失去线索", hidden_matters: ["保留了一页旧名册"], main_conflict_reason: "赵衡要销毁旧账",
    },
    dialogue_examples: ["这炉子昨夜还好好的，谁动过，查值夜册就知道。"],
    relationship_notes: [{ target: "赵衡", relation_type: "管事与杂役", history: "赵衡曾经审过他父亲", current_attitude: "表面顺从，实际提防", shared_interest_or_conflict: "旧账册", known_facts: ["赵衡怕旧案重查"], unknown_facts: ["赵衡受谁指使"] }],
    goals: [], frozen: false, lifecycle_state: "active", last_proposed_chapter: 0, last_approved_chapter: 1, introduced_by: "outline", relationships: {},
  };
  const project = {
    project_id: "file:character-fixture", title: "Character Fixture", source_path: "", seed_outline: "祖祠旧案", world_summary: "",
    current_focus: "", author_constraints: [], world_blueprint: {}, character_profiles: [character], relationship_graph: [{ source: character.name, target: "赵衡", relation_type: "管事与杂役", current_state: "表面顺从，实际提防" }], enabled_skill_ids: [],
    status: "simulating", pipeline_stage: "world_ready", active_story_id: "file:character-fixture", branches: [], storage_source: "file",
  };

  await page.route("**/file-projects/file%3Acharacter-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-stories/file%3Acharacter-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: "file:character-fixture", outline: "祖祠旧案", genre: "玄幻", style: "白描", current_chapter: 1,
      agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
      agent_runtime: { recent_events: [] }, author_constraints: [], world_facts: [], characters: [character], history: [], parent_story_id: null, branched_from_chapter: null,
    }) });
  });
  await page.route("**/file-projects/**/characters/%E6%9E%97%E7%85%A7", async (route) => {
    savedBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...character, ...savedBody }) });
  });

  await page.goto("/projects/file%3Acharacter-fixture/characters");
  await expect(page.getByText("19岁", { exact: true })).toBeVisible();
  await expect(page.getByText("守祠人之子", { exact: true })).toBeVisible();
  await expect(page.getByText("会被逐出祖祠并失去线索", { exact: true })).toBeVisible();
  await expect(page.getByText("这炉子昨夜还好好的，谁动过，查值夜册就知道。", { exact: true })).toBeVisible();
  await expect(page.getByText("赵衡", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("职业").fill("守祠杂役");
  await page.getByRole("button", { name: "保存角色卡" }).click();
  await expect.poll(() => savedBody).toMatchObject({
    identity_profile: { age: 19, origin: "守祠人之子", occupation: "守祠杂役" },
    background_profile: { upbringing: "由祖祠老仆带大" },
    current_life_profile: { livelihood: "守炉换取月例" },
    story_drive: { immediate_goal: "找出断炉的人", failure_stakes: "会被逐出祖祠并失去线索" },
    dialogue_examples: ["这炉子昨夜还好好的，谁动过，查值夜册就知道。"],
  });
  expect(savedBody).not.toHaveProperty("relationship_notes");
});

test("relationship workspace defaults to protagonist and saves the canonical graph", async ({ page }) => {
  let savedBody: Record<string, unknown> | null = null;
  const characters = [
    { name: "林照", role: "protagonist", character_tier: "protagonist" },
    { name: "赵衡", role: "stage_antagonist", character_tier: "stage_antagonist" },
    { name: "周满", role: "supporting", character_tier: "supporting" },
  ];
  const project = {
    project_id: "file:relationship-fixture",
    title: "Relationship Fixture",
    active_story_id: "file:relationship-fixture",
    storage_source: "file",
    status: "simulating",
    pipeline_stage: "world_ready",
    branches: [],
    character_profiles: characters,
    relationship_graph: [
      { id: "rel-a", source: "林照", target: "赵衡", relation_type: "对手", current_state: "彼此提防", trust: 10, tension: 80 },
      { id: "rel-b", source: "赵衡", target: "周满", relation_type: "同僚", current_state: "暂时合作", trust: 45, tension: 20 },
    ],
  };

  await page.route("**/file-projects/file%3Arelationship-fixture", async (route) => {
    if (route.request().method() === "PUT") {
      savedBody = route.request().postDataJSON() as Record<string, unknown>;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-projects/file%3Arelationship-fixture/outline", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      schema_version: "project-outline/v1", source: "saved", overall: {}, arcs: [],
      chapters: [{ chapter_number: 2, title: "当面对质", goal: "查账", obstacle: "赵衡阻拦", action: "林照拿出证据", turn: "周满改口", payoff: "拿到名册", ending_hook: "幕后人现身", cast: ["林照", "赵衡"] }],
    }) });
  });
  await page.route("**/file-stories/file%3Arelationship-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: "file:relationship-fixture", current_chapter: 1, characters, history: [], world_facts: [], author_constraints: [], agent_runtime: { recent_events: [] },
    }) });
  });

  await page.goto("/projects/file%3Arelationship-fixture/relationships");

  await expect(page.getByRole("heading", { name: "人物关系" })).toBeVisible();
  await expect(page.getByRole("link", { name: "项目设置" })).toHaveAttribute(
    "href",
    "/projects/file%3Arelationship-fixture/settings",
  );
  await expect(page.getByRole("button", { name: "主角视角" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "林照", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "赵衡", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "周满", exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "全局" }).click();
  await expect(page.getByRole("button", { name: "周满", exact: true })).toBeVisible();
  await page.getByLabel("林照与赵衡的当前状态").fill("公开对立");
  await page.getByRole("button", { name: "保存关系图" }).click();

  await expect.poll(() => savedBody).not.toBeNull();
  const savedGraph = (savedBody as unknown as { relationship_graph: Array<Record<string, unknown>> }).relationship_graph;
  expect(savedGraph).toHaveLength(2);
  expect(savedGraph[0]).toMatchObject({ source: "林照", target: "赵衡", current_state: "公开对立" });
});

test("existing novel continuation exposes a browsable source panel", async ({ page }) => {
  await page.route("**/novel-types", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: "generic_webnovel", name: "通用网文", description: "通用规则", keywords: [], core_promises: [], ledger_fields: [], rulebook: {}, quality_checks: [], trope_templates: [], builtin: true }]),
    });
  });
  await page.route(/^http:\/\/127\.0\.0\.1:\d+\/continuation-imports\/list-sources$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        current_path: "D:/novels",
        directories: [{ name: "旧书目录", path: "D:/novels/旧书目录" }],
        files: [{ name: "旧书正文.txt", path: "D:/novels/旧书正文.txt" }],
      }),
    });
  });
  await page.goto("/projects/new", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("option", { name: "通用网文" })).toBeAttached({ timeout: 15_000 });
  const continuationTab = page.getByRole("tab", { name: "续写已有小说" });
  await continuationTab.click();
  await expect(continuationTab).toHaveAttribute("aria-selected", "true", { timeout: 15_000 });

  await expect(page.getByRole("heading", { name: "选择小说来源" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: /旧书目录/ })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: /旧书正文\.txt/ })).toBeVisible({ timeout: 15_000 });
});

test("generated chapters surface in the current writing workspace", async ({ page }) => {
  const { encodedId } = await routeCurrentFileProject(page, "generated-chapter");
  await page.goto(`/projects/${encodedId}/write?chapter=1`);

  await expect(page.locator(".ws-reader")).toContainText("灰狼坡旧痕");
  await expect(page.locator(".ws-reader__body")).toContainText("商会印记的旧铜牌");
  await expect(page.locator(".ws-reader__notes")).toContainText("章节摘要");
  await expect(page.locator(".ws-reader__notes")).toContainText("下一章焦点");
});

test("write page can regenerate the current file-project chapter", async ({ page }) => {
  const fixture = await routeCurrentFileProject(page, "regenerate-chapter");
  let regenerationPayload: Record<string, unknown> | null = null;
  await page.route(`**/file-projects/${fixture.encodedId}/generation-jobs`, async (route) => {
    regenerationPayload = route.request().postDataJSON() as Record<string, unknown>;
    fixture.story.history[0].body = "REGENERATED_CHAPTER: 商会规则和主角动机已经补全。";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ job_id: "job-regenerate", status: "completed", progress: "已完成", steps: [] }),
    });
  });
  await page.route("**/projects/*/agent-revise", async (route) => {
    const request = route.request();
    expect(request.method()).toBe("POST");
    const payload = request.postDataJSON() as {
      chapter_number?: number;
      instructions?: string[];
      include_body?: boolean;
    };
    expect(payload.chapter_number).toBe(1);
    expect(payload.include_body).toBe(true);
    expect(payload.instructions?.length).toBeGreaterThan(0);

    await route.fulfill({
      status: 200,
      headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
      body: JSON.stringify({
        schema_version: "agent-revision/v1",
        project: { project_id: "p-test", title: "Revision Test" },
        story: { story_id: "s-test", current_chapter: 1 },
        chapter: {
          chapter_number: 1,
          chapter_title: "第1章 修订后",
          body: "REVISED_BY_AGENT: market rules, NPC service boundary, and protagonist motive are now clearer.",
          body_chars: 82,
          quality_report: {
            ok: true,
            issues: [],
            writing_review: { pass: true, scores: { genre_rules: 8 }, issues: [], revision_plan: [] },
          },
        },
        review: {
          writing_review: { pass: true, scores: { genre_rules: 8 }, issues: [], revision_plan: [] },
        },
        revision: {
          changed: true,
          previous_body_chars: 20,
          revised_body_chars: 82,
          instructions: ["按审稿意见自动改稿"],
          source: "writer_agent",
        },
      }),
    });
  });

  await page.route("**/projects", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: "[]",
      });
      return;
    }
    await route.abort();
  });

  await page.addInitScript(() => {
    const agentRuntime = {
      planner: { source: "idle", provider: "", model: "", fallback_reason: "", last_run_chapter: 0 },
      writer: { source: "idle", provider: "", model: "", fallback_reason: "", last_run_chapter: 0 },
      memory: { source: "idle", provider: "", model: "", fallback_reason: "", last_run_chapter: 0 },
      recent_events: [],
    };
    window.localStorage.setItem(
      "novel-autogrowth-engine.project-snapshot",
      JSON.stringify({
        project_id: "p-test",
        title: "Revision Test",
        source_path: "",
        seed_outline: "A market clue opens the story.",
        world_summary: "A game world with visible market rules.",
        current_focus: "Revise chapter one.",
        author_constraints: [],
        world_blueprint: {},
        character_profiles: [],
        relationship_graph: [],
        status: "simulating",
        pipeline_stage: "simulating",
        active_story_id: "s-test",
        branches: [{ story_id: "s-test", current_chapter: 1, parent_story_id: null, branched_from_chapter: null }],
      }),
    );
    window.localStorage.setItem(
      "novel-autogrowth-engine.story-snapshot",
      JSON.stringify({
        story_id: "s-test",
        outline: "A player tests a strange market clue.",
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
        agent_runtime: agentRuntime,
        author_constraints: [],
        world_facts: [],
        parent_story_id: null,
        branched_from_chapter: null,
        characters: [
          {
            name: "Lin Yue",
            role: "protagonist",
            goals: ["test the market clue"],
            frozen: false,
            lifecycle_state: "active",
            last_proposed_chapter: 0,
            last_approved_chapter: 0,
            introduced_by: "",
            relationships: {},
          },
        ],
        history: [
          {
            chapter_number: 1,
            chapter_title: "第1章 原稿",
            body: "ORIGINAL_BY_AGENT: the chapter still lacks market rules.",
            chapter_intent: { primary_conflict: { collision: "market clue" }, next_focus: "revise" },
            character_moves: [{ name: "Lin Yue", action: "checks the market" }],
            memory_constraints: { must_keep_facts: ["market clue exists"], unresolved_threads: ["market rules"] },
            event_plan: { pivot: "market clue appears", stakes: "identity risk", next_focus: "revise" },
            simulation_status: { ok: true },
            next_outline: "continue after revision",
            chapter_summary: {
              chapter_number: 1,
              summary: "The protagonist finds a market clue.",
              facts: ["market clue exists"],
              unresolved_threads: ["market rules"],
            },
            quality_report: {
              ok: false,
              issues: ["writing_review"],
              revision_safety: {
                reviewer: "revision_safety/v1",
                accepted: false,
                selected: "original",
                reason: "candidate_worse_than_original",
                original_score: 90,
                candidate_score: 42,
                original_chars: 4200,
                candidate_chars: 1200,
              },
              segment_pipeline: {
                enabled: true,
                pass: false,
                segments: [
                  {
                    segment_key: "setup",
                    segment_title: "现实入口",
                    pass: false,
                    issues: ["局部改稿缩水"],
                    segment_revision_safety: {
                      reviewer: "segment_revision_safety/v1",
                      accepted: false,
                      selected: "original",
                      reason: "candidate_worse_than_original",
                      original_score: 60,
                      candidate_score: 20,
                    },
                  },
                ],
              },
              writing_review: {
                pass: false,
                scores: { genre_rules: 5 },
                issues: ["market rules are thin"],
                revision_plan: ["补足交易行规则"],
              },
            },
          },
        ],
      }),
    );
    window.sessionStorage.setItem("novel-autogrowth-engine.project-id", "p-test");
    window.sessionStorage.setItem("novel-autogrowth-engine.story-id", "s-test");
  });

  await page.goto(`/projects/${fixture.encodedId}/write?chapter=1`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "重新生成本章" }).click();

  await expect.poll(() => regenerationPayload).toMatchObject({ chapter_number: 1 });
  await expect(page.locator(".ws-reader__body")).toContainText("REGENERATED_CHAPTER");
});

test("write page accepts three-stage runtime state", async ({ page }) => {
  await page.route("**/projects", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: "[]",
      });
      return;
    }
    await route.abort();
  });

  await page.addInitScript(() => {
    const agentRuntime = {
      planner: { source: "llm", provider: "openai", model: "planner-live", fallback_reason: "", last_run_chapter: 1 },
      writer: { source: "fallback", provider: "codexcli", model: "writer-live", fallback_reason: "timeout", last_run_chapter: 1 },
      memory: { source: "idle", provider: "", model: "", fallback_reason: "", last_run_chapter: 0 },
      recent_events: ["写作阶段：回退，第 1 章（timeout）"],
    };
    window.localStorage.setItem(
      "novel-autogrowth-engine.project-snapshot",
      JSON.stringify({
        project_id: "p-test",
        title: "Revision Test",
        source_path: "",
        seed_outline: "A market clue opens the story.",
        world_summary: "A game world with visible market rules.",
        current_focus: "Revise chapter one.",
        author_constraints: [],
        world_blueprint: {},
        character_profiles: [],
        relationship_graph: [],
        status: "simulating",
        pipeline_stage: "simulating",
        active_story_id: "s-test",
        branches: [{ story_id: "s-test", current_chapter: 1, parent_story_id: null, branched_from_chapter: null }],
      }),
    );
    window.localStorage.setItem(
      "novel-autogrowth-engine.story-snapshot",
      JSON.stringify({
        story_id: "s-test",
        outline: "A player tests a strange market clue.",
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
        agent_runtime: agentRuntime,
        author_constraints: [],
        world_facts: [],
        parent_story_id: null,
        branched_from_chapter: null,
        characters: [
          {
            name: "Lin Yue",
            role: "protagonist",
            goals: ["test the market clue"],
            frozen: false,
            lifecycle_state: "active",
            last_proposed_chapter: 0,
            last_approved_chapter: 0,
            introduced_by: "",
            relationships: {},
          },
        ],
        history: [
          {
            chapter_number: 1,
            chapter_title: "第1章 原稿",
            body: "ORIGINAL_BY_AGENT: the chapter still lacks market rules.",
            chapter_intent: { primary_conflict: { collision: "market clue" }, next_focus: "revise" },
            character_moves: [{ name: "Lin Yue", action: "checks the market" }],
            memory_constraints: { must_keep_facts: ["market clue exists"], unresolved_threads: ["market rules"] },
            event_plan: { pivot: "market clue appears", stakes: "identity risk", next_focus: "revise" },
            simulation_status: { ok: true },
            next_outline: "continue after revision",
            chapter_summary: {
              chapter_number: 1,
              summary: "The protagonist finds a market clue.",
              facts: ["market clue exists"],
              unresolved_threads: ["market rules"],
            },
            quality_report: {
              ok: false,
              issues: ["writing_review"],
              revision_safety: {
                reviewer: "revision_safety/v1",
                accepted: false,
                selected: "original",
                reason: "candidate_worse_than_original",
                original_score: 90,
                candidate_score: 42,
                original_chars: 4200,
                candidate_chars: 1200,
              },
              segment_pipeline: {
                enabled: true,
                pass: false,
                segments: [
                  {
                    segment_key: "setup",
                    segment_title: "现实入口",
                    pass: false,
                    issues: ["局部改稿缩水"],
                    segment_revision_safety: {
                      reviewer: "segment_revision_safety/v1",
                      accepted: false,
                      selected: "original",
                      reason: "candidate_worse_than_original",
                      original_score: 60,
                      candidate_score: 20,
                    },
                  },
                ],
              },
              writing_review: {
                pass: false,
                scores: { genre_rules: 5 },
                issues: ["market rules are thin"],
                revision_plan: ["补足交易行规则"],
              },
            },
          },
        ],
      }),
    );
    window.sessionStorage.setItem("novel-autogrowth-engine.project-id", "p-test");
    window.sessionStorage.setItem("novel-autogrowth-engine.story-id", "s-test");
  });

  await page.route("**/projects/p-test", async (route) => {
    const project = await page.evaluate(() => window.localStorage.getItem("novel-autogrowth-engine.project-snapshot"));
    await route.fulfill({ status: 200, contentType: "application/json", body: project ?? "{}" });
  });
  await page.route("**/stories/s-test", async (route) => {
    const story = await page.evaluate(() => window.localStorage.getItem("novel-autogrowth-engine.story-snapshot"));
    await route.fulfill({ status: 200, contentType: "application/json", body: story ?? "{}" });
  });

  await page.goto("/projects/p-test/write", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "章节：第 1 章" })).toBeVisible();
  await expect(page.locator(".ws-reader")).toContainText("ORIGINAL_BY_AGENT");
});

test("project world constraints persist after refresh", async ({ page }) => {
  const { encodedId } = await routeCurrentFileProject(page, "constraint-persistence");
  await page.goto(`/projects/${encodedId}/world`);

  const constraints = page.locator('section[aria-labelledby="constraints-world-rules-title"] textarea').first();
  await constraints.fill("规则一\n规则二");
  await page.getByRole("button", { name: "保存世界硬约束", exact: true }).click();
  await expect(constraints).toHaveValue("规则一\n规则二");
  await page.reload();

  await expect(page.locator('section[aria-labelledby="constraints-world-rules-title"] textarea').first()).toHaveValue("规则一\n规则二");
});

test("角色卡状态显示和编辑保存遵循网游插件", async ({ page }) => {
  let savedBody: Record<string, unknown> | null = null;
  let putCount = 0;
  const character = {
    name: "苏叶", role: "protagonist", goals: [], frozen: false, lifecycle_state: "active",
    last_proposed_chapter: 0, last_approved_chapter: 1, introduced_by: "outline", relationships: {},
    real_state: { current: { identity: "兼职店员", income: "兼职" }, recent_changes: [{ chapter: 2, fact: "开始接夜班" }] },
    game_state: { current: { game_id: "夜烬", level: 7, class_path: "元素法师", attributes: { 基础: { 力量: 12, 加成: ["专注", "精准"], 深层: { 来源: "装备" } } } }, recent_changes: [{ chapter: 3, fact: "完成隐藏任务" }] },
    game_panel: { game_id: "旧夜烬", level: 1, class_path: "旧职业" },
  };
  const project = {
    project_id: "file:dual-state-fixture", title: "网游标题但看插件", source_path: "", seed_outline: "", world_summary: "", current_focus: "",
    author_constraints: [], world_blueprint: { genre_plugin_ids: ["game_webnovel"] }, character_profiles: [], relationship_graph: [], enabled_skill_ids: [],
    status: "simulating", pipeline_stage: "world_ready", active_story_id: "file:dual-state-fixture", branches: [], storage_source: "file",
  };
  await page.route("**/file-projects/file%3Adual-state-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-stories/file%3Adual-state-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: "file:dual-state-fixture", current_chapter: 3, characters: [character], history: [], world_facts: [], author_constraints: [], agent_runtime: { recent_events: [] },
      agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
    }) });
  });
  await page.route("**/file-projects/file%3Adual-state-fixture/characters/%E8%8B%8F%E5%8F%B6", async (route) => {
    putCount += 1;
    savedBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...character, ...savedBody }) });
  });

  await page.goto("/projects/file%3Adual-state-fixture/characters");
  await expect(page.getByRole("heading", { name: "现实状态" })).toBeVisible();
  await expect(page.getByText("身份", { exact: true })).toBeVisible();
  await expect(page.getByText("兼职店员", { exact: true })).toBeVisible();
  await expect(page.getByText("第 2 章：开始接夜班", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "游戏状态" })).toBeVisible();
  await expect(page.getByText("旧夜烬", { exact: true })).toHaveCount(0);
  await expect(page.getByText("等级", { exact: true })).toBeVisible();
  await expect(page.getByText("基础：力量：12；加成：专注、精准；深层：来源：装备", { exact: true })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("[object Object]");
  await expect(page.getByText("第 3 章：完成隐藏任务", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("现实状态 JSON").fill(JSON.stringify({ current: { identity: "自由职业者" }, recent_changes: [] }));
  await page.getByLabel("游戏状态 JSON").fill(JSON.stringify({ current: { game_id: "夜烬", level: 8 }, recent_changes: [] }));
  await page.getByRole("button", { name: "保存角色卡" }).click();
  await expect.poll(() => putCount).toBe(1);
  expect(savedBody).toMatchObject({
    real_state: { current: { identity: "自由职业者" }, recent_changes: [] },
    game_state: { current: { game_id: "夜烬", level: 8 }, recent_changes: [] },
  });
});

test("非法状态 JSON 页面内报错且不发请求，非网游隐藏游戏状态", async ({ page }) => {
  let putCount = 0;
  const character = {
    name: "林照", role: "protagonist", goals: [], frozen: false, lifecycle_state: "active",
    last_proposed_chapter: 0, last_approved_chapter: 1, introduced_by: "outline", relationships: {},
    game_id: "不应显示的ID",
    real_state: { current: { occupation: "守祠人" }, recent_changes: [] },
    game_state: { current: { game_id: "不应显示", level: 9 }, recent_changes: [] },
  };
  const project = {
    project_id: "file:real-state-fixture", title: "网游字样但不是网游", source_path: "", seed_outline: "", world_summary: "", current_focus: "",
    author_constraints: [], world_blueprint: { genre_plugin_ids: ["xianxia"] }, character_profiles: [], relationship_graph: [], enabled_skill_ids: [],
    status: "simulating", pipeline_stage: "world_ready", active_story_id: "file:real-state-fixture", branches: [], storage_source: "file",
  };
  await page.route("**/file-projects/file%3Areal-state-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-stories/file%3Areal-state-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: "file:real-state-fixture", current_chapter: 1, characters: [character], history: [], world_facts: [], author_constraints: [], agent_runtime: { recent_events: [] },
      agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
    }) });
  });
  await page.route("**/file-projects/file%3Areal-state-fixture/characters/%E6%9E%97%E7%85%A7", async (route) => {
    putCount += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(character) });
  });

  await page.goto("/projects/file%3Areal-state-fixture/characters");
  await expect(page.getByRole("heading", { name: "现实状态" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "游戏状态" })).toHaveCount(0);
  await expect(page.getByText("不应显示", { exact: true })).toHaveCount(0);
  await expect(page.getByText("不应显示的ID", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("现实状态 JSON").fill("{invalid");
  await page.getByRole("button", { name: "保存角色卡" }).click();
  await expect(page.getByText("现实状态 JSON 格式错误", { exact: false })).toBeVisible();
  expect(putCount).toBe(0);
});

test("网游角色卡兼容仅有旧游戏面板的角色状态", async ({ page }) => {
  let savedBody: Record<string, unknown> | null = null;
  const character = {
    name: "顾行", role: "protagonist", goals: [], frozen: false, lifecycle_state: "active",
    last_proposed_chapter: 0, last_approved_chapter: 1, introduced_by: "outline", relationships: {},
    real_state: { current: { identity: "普通职员" }, recent_changes: [] },
    game_panel: { game_id: "旧夜烬", level: 4, class_path: "弓手" },
  };
  const project = {
    project_id: "file:legacy-panel-fixture", title: "兼容面板", source_path: "", seed_outline: "", world_summary: "", current_focus: "",
    author_constraints: [], world_blueprint: { genre_plugin_ids: ["game_webnovel"] }, character_profiles: [], relationship_graph: [], enabled_skill_ids: [],
    status: "simulating", pipeline_stage: "world_ready", active_story_id: "file:legacy-panel-fixture", branches: [], storage_source: "file",
  };
  await page.route("**/file-projects/file%3Alegacy-panel-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-stories/file%3Alegacy-panel-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: "file:legacy-panel-fixture", outline: "", genre: "game_webnovel", style: "升级流", current_chapter: 1,
      agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
      agent_runtime: { recent_events: [] }, author_constraints: [], world_facts: [], characters: [character], history: [], parent_story_id: null, branched_from_chapter: null,
    }) });
  });
  await page.route("**/file-projects/file%3Alegacy-panel-fixture/characters/*", async (route) => {
    savedBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...character, ...savedBody }) });
  });

  await page.goto("/projects/file%3Alegacy-panel-fixture/characters");
  await expect(page.getByRole("heading", { name: "游戏状态" })).toBeVisible();
  await expect(page.getByText("旧夜烬", { exact: true })).toHaveCount(2);
  await expect(page.getByText("4", { exact: true })).toHaveCount(2);
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await expect(page.getByLabel("游戏状态 JSON")).toBeVisible();
  await page.getByLabel("游戏状态 JSON").fill(JSON.stringify({ current: { game_id: "新夜烬", level: 5, class_path: "刺客" }, recent_changes: [] }));
  await page.getByRole("button", { name: "保存角色卡" }).click();
  await expect.poll(() => savedBody).toMatchObject({
    game_state: { current: { game_id: "新夜烬", level: 5, class_path: "刺客" }, recent_changes: [] },
    game_panel: { game_id: "新夜烬", level: 5, class_path: "刺客" },
  });
});

test("非网游项目概览不读取旧游戏面板等级", async ({ page }) => {
  const character = {
    name: "林照", role: "protagonist", goals: [], frozen: false, lifecycle_state: "active",
    last_proposed_chapter: 0, last_approved_chapter: 1, introduced_by: "outline", relationships: {},
    game_panel: { game_id: "不应展示", level: 9 },
  };
  const project = {
    project_id: "file:overview-real-fixture", title: "现实概览", source_path: "", seed_outline: "", world_summary: "", current_focus: "",
    author_constraints: [], world_blueprint: { genre_plugin_ids: ["xianxia"] }, character_profiles: [character], relationship_graph: [], enabled_skill_ids: [],
    status: "simulating", pipeline_stage: "world_ready", active_story_id: "file:overview-real-fixture", branches: [], storage_source: "file",
  };
  await page.route("**/file-projects/file%3Aoverview-real-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-stories/file%3Aoverview-real-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: "file:overview-real-fixture", outline: "", genre: "xianxia", style: "白描", current_chapter: 1,
      agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
      agent_runtime: { recent_events: [] }, author_constraints: [], world_facts: [], characters: [character], history: [], parent_story_id: null, branched_from_chapter: null,
    }) });
  });

  await page.goto("/projects/file%3Aoverview-real-fixture");
  await expect(page.getByRole("heading", { name: "角色卡" })).toBeVisible();
  await expect(page.getByText("9级", { exact: true })).toHaveCount(0);
  await expect(page.getByText("不应展示", { exact: true })).toHaveCount(0);
});

test("世界观页面显示并编辑怪物图鉴", async ({ page }) => {
  let savedBlueprint: Record<string, unknown> | null = null;
  const project = {
    project_id: "file:monster-fixture", title: "怪物图鉴测试", source_path: "", seed_outline: "", world_summary: "", current_focus: "",
    author_constraints: [],
    world_blueprint: {
      genre_plugin_ids: ["game_webnovel"],
      monster_profiles: [{
        id: "gray-wolf", name: "灰狼", category: "野兽", rank: "普通", level: "Lv.3", hp: "80",
        attack_mode: "扑咬", skills: [], traits: ["听觉敏锐"], habitats: ["灰狼坡"],
        drops: ["灰狼毒腺", "粗糙狼皮"], first_appearance_chapter: 1, status: "active",
      }],
    },
    character_profiles: [], relationship_graph: [], enabled_skill_ids: [], status: "simulating", pipeline_stage: "world_ready",
    active_story_id: "file:monster-fixture", branches: [], storage_source: "file",
  };
  await page.route("**/file-projects/file%3Amonster-fixture", async (route) => {
    if (route.request().method() === "PUT") {
      const payload = route.request().postDataJSON() as { world_blueprint?: Record<string, unknown> };
      savedBlueprint = payload.world_blueprint ?? null;
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...project, world_blueprint: savedBlueprint }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-stories/file%3Amonster-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: "file:monster-fixture", outline: "", genre: "网游", style: "白描", current_chapter: 1,
      agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
      agent_runtime: { recent_events: [] }, author_constraints: [], world_facts: [], characters: [], history: [], parent_story_id: null, branched_from_chapter: null,
    }) });
  });

  await page.goto("/projects/file%3Amonster-fixture/world");
  await expect(page.getByRole("heading", { name: "怪物图鉴" })).toBeVisible();
  await expect(page.getByText("灰狼", { exact: true })).toBeVisible();
  await expect(page.getByText("野兽 · 普通 · Lv.3", { exact: true })).toBeVisible();
  await expect(page.getByText("Lv.Lv.3", { exact: true })).toHaveCount(0);
  await expect(page.getByText("扑咬", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "编辑灰狼" }).click();
  await page.getByLabel("怪物生命").fill("90");
  await page.getByRole("button", { name: "保存怪物卡" }).click();
  await expect.poll(() => savedBlueprint).toMatchObject({ monster_profiles: [{ name: "灰狼", hp: "90" }] });
});

const structuredPowerSystemSpec = {
  name: "神域六职体系",
  origin: ["觉醒石连接神域权限"],
  attributes: [
    { name: "力量", effect: "提高近战伤害" },
    { name: "智力", effect: "提高法术强度" },
  ],
  stages: [
    { name: "见习者", level: 1, entry: "完成觉醒", change: "解锁基础技能", failure: "重新训练" },
    { name: "正式职业", level: 10, entry: "完成导师试炼", change: "解锁职业资源", failure: "冷却七日" },
    { name: "进阶职业", level: 20, entry: "完成转职任务", change: "选择首个分支", failure: "损失转职材料" },
    { name: "专精职业", level: 30, entry: "通过专精考核", change: "解锁专精循环", failure: "专精声望下降" },
    { name: "传奇职业", level: 60, entry: "完成传奇仪式", change: "建立领域", failure: "领域核心受损" },
  ],
  paths: [
    { name: "战士", role: "前排承伤", core_resource: "怒气", branches: ["盾卫", "狂战士"] },
    { name: "法师", role: "远程元素输出", core_resource: "法力", branches: ["烈焰法师", "冰霜法师"] },
    { name: "游侠", role: "远程机动输出", core_resource: "专注", branches: ["神射手", "驭兽游侠"] },
    { name: "盗贼", role: "近战爆发", core_resource: "连击点", branches: ["刺客", "影舞者"] },
    { name: "牧师", role: "治疗与净化", core_resource: "信仰", branches: ["圣愈者", "审判官"] },
    { name: "召唤师", role: "召唤物协同", core_resource: "契约槽", branches: ["兽群使", "元素契约师"] },
  ],
  skills: ["技能书与导师授予技能"],
  equipment: ["装备受职业与等级限制"],
  resources: ["首领掉落职业材料"],
  advancement: ["等级、任务和材料同时满足"],
  costs: ["透支职业资源会造成虚弱"],
  counters: ["沉默克制持续施法"],
  boundaries: ["不得无条件跨越两个阶段"],
  social_impact: ["公会按职业配置队伍"],
  visibility: ["敌人只能看到公开等级", "<script>不可执行</script>"],
  continuity_ledger: ["level", "class_path", "skills", "equipment"],
};

async function mockWorldPowerPage(
  page: Page,
  id: string,
  worldBlueprint: Record<string, unknown>,
) {
  const encodedId = encodeURIComponent(`file:${id}`);
  const project = {
    project_id: `file:${id}`,
    title: "力量体系展示测试",
    source_path: "",
    seed_outline: "",
    world_summary: "",
    current_focus: "",
    author_constraints: [],
    world_blueprint: worldBlueprint,
    character_profiles: [],
    relationship_graph: [],
    enabled_skill_ids: [],
    status: "simulating",
    pipeline_stage: "world_ready",
    active_story_id: `file:${id}`,
    branches: [],
    storage_source: "file",
  };
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route(`**/file-stories/${encodedId}`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: `file:${id}`,
      outline: "",
      genre: "网游",
      style: "白描",
      current_chapter: 1,
      agent_settings: {},
      agent_runtime: { recent_events: [] },
      author_constraints: [],
      world_facts: [],
      characters: [],
      history: [],
      parent_story_id: null,
      branched_from_chapter: null,
    }) });
  });
}

test("世界观展示结构化力量体系的完整章节、六职业与分支", async ({ page }) => {
  await mockWorldPowerPage(page, "structured-power", {
    power_system: ["旧版力量摘要不得重复显示"],
    power_system_spec: structuredPowerSystemSpec,
  });
  await page.goto("/projects/file%3Astructured-power/world");

  const structured = page.getByLabel("结构化力量体系");
  await expect(structured).toBeVisible();
  for (const heading of [
    "体系总览", "力量来源", "属性", "阶段与晋升", "职业与路线", "技能与装备",
    "资源与代价", "克制与边界", "社会影响", "信息可见性", "连续性账本",
  ]) {
    await expect(structured.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }
  await expect(structured.getByRole("heading", { name: "属性分配", exact: true })).toHaveCount(0);
  for (const name of ["战士", "法师", "游侠", "盗贼", "牧师", "召唤师", "烈焰法师", "冰霜法师", "兽群使", "元素契约师"]) {
    await expect(structured.getByText(name, { exact: true })).toBeVisible();
  }
  await expect(page.getByText("力量体系需要补全", { exact: true })).toHaveCount(0);
  await expect(page.locator("p, li, dd, dt").filter({ hasText: "旧版力量摘要不得重复显示" })).toHaveCount(0);
  await expect(page.getByLabel("等级、职业与技能")).toHaveValue("旧版力量摘要不得重复显示");
  await expect(structured.locator(".ws-card")).toHaveCount(0);
  await expect(structured.getByText("<script>不可执行</script>", { exact: true })).toBeVisible();
  await expect(page.locator("script").filter({ hasText: "不可执行" })).toHaveCount(0);
});

test("世界观展示启用的自由属性分配规则", async ({ page }) => {
  await mockWorldPowerPage(page, "attribute-allocation", {
    power_system_spec: {
      ...structuredPowerSystemSpec,
      attribute_allocation: {
        mode: "free",
        points_per_level: 5,
        starting_level: 1,
        base_attributes: { 力量: 5, 敏捷: 5, 体质: 5, 智力: 5, 精神: 5, 幸运: 5 },
        allow_carry: true,
        respec_rule: "每周可在主城重置一次，消耗洗点券。",
      },
    },
  });
  await page.goto("/projects/file%3Aattribute-allocation/world");

  const section = page.getByLabel("结构化力量体系").getByRole("heading", { name: "属性分配", exact: true }).locator("..");
  await expect(section).toBeVisible();
  await expect(section.getByText("自由分配", { exact: true })).toBeVisible();
  await expect(section.getByText("5", { exact: true })).toHaveCount(7);
  await expect(section.getByText("是", { exact: true })).toBeVisible();
  await expect(section.getByText("每周可在主城重置一次，消耗洗点券。", { exact: true })).toBeVisible();
});

test("世界观仅在旧力量摘要存在时提示需要补全", async ({ page }) => {
  await mockWorldPowerPage(page, "legacy-power", { power_system: ["旧版力量规则"] });
  await page.goto("/projects/file%3Alegacy-power/world");
  await expect(page.getByText("力量体系需要补全", { exact: true })).toBeVisible();

  await mockWorldPowerPage(page, "empty-power", {});
  await page.goto("/projects/file%3Aempty-power/world");
  await expect(page.getByText("力量体系需要补全", { exact: true })).toHaveCount(0);
});

test("世界观安全忽略数组和标量力量体系规格", async ({ page }) => {
  await mockWorldPowerPage(page, "array-power", { power_system_spec: [{ name: "错误数组" }] });
  await page.goto("/projects/file%3Aarray-power/world");
  await expect(page.getByRole("heading", { name: "世界规则" })).toBeVisible();
  await expect(page.getByLabel("结构化力量体系")).toHaveCount(0);

  await mockWorldPowerPage(page, "scalar-power", { power_system_spec: "错误标量" });
  await page.goto("/projects/file%3Ascalar-power/world");
  await expect(page.getByRole("heading", { name: "世界规则" })).toBeVisible();
  await expect(page.getByLabel("结构化力量体系")).toHaveCount(0);
});

test("世界观将残缺力量体系规格标记为需要补全", async ({ page }) => {
  await mockWorldPowerPage(page, "incomplete-power", { power_system_spec: { name: "临时体系" } });
  await page.goto("/projects/file%3Aincomplete-power/world");

  await expect(page.getByLabel("结构化力量体系")).toHaveCount(0);
  await expect(page.getByText("力量体系需要补全", { exact: true })).toBeVisible();

  await mockWorldPowerPage(page, "malformed-power", {
    power_system_spec: {
      ...structuredPowerSystemSpec,
      stages: [{ name: "空阶段" }],
      paths: [{ name: "单一路线", branches: ["唯一分支"] }],
    },
  });
  await page.goto("/projects/file%3Amalformed-power/world");
  await expect(page.getByLabel("结构化力量体系")).toHaveCount(0);
  await expect(page.getByText("力量体系需要补全", { exact: true })).toBeVisible();
});

test("结构化力量体系在 360px 宽度内换行且无横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await mockWorldPowerPage(page, "mobile-power", { power_system_spec: structuredPowerSystemSpec });
  await page.goto("/projects/file%3Amobile-power/world");

  const structured = page.getByLabel("结构化力量体系");
  await expect(structured).toBeVisible();
  const bounds = await structured.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(360);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("世界观真实路由常驻展示完整编辑区并在刷新时保留草稿", async ({ page }) => {
  let savedPayload: { world_summary?: string; world_blueprint?: Record<string, unknown> } = {};
  let projectGetCount = 0;
  let completedProjectGetCount = 0;
  const monsterProfiles = [{ id: "gray-wolf", name: "灰狼", hp: "80" }];
  const project = {
    project_id: "file:world-page-fixture", title: "世界观集成测试", source_path: "", seed_outline: "",
    world_summary: "旧项目摘要", current_focus: "", author_constraints: ["不应显示为页面标题"],
    world_blueprint: {
      premise: "旧世界前提",
      current_arc: "旧局势",
      world_rules: ["基础世界规则"],
      locations: [{ name: "旧港", description: "沿海聚落" }],
      factions: [{ name: "巡夜会", description: "维护夜间秩序" }],
      monster_profiles: monsterProfiles,
    },
    character_profiles: [], relationship_graph: [], enabled_skill_ids: [], status: "simulating",
    pipeline_stage: "world_ready", active_story_id: "file:world-page-fixture", branches: [], storage_source: "file",
  };
  await page.route("**/file-projects/file%3Aworld-page-fixture", async (route) => {
    if (route.request().method() === "PUT") {
      savedPayload = route.request().postDataJSON() as typeof savedPayload;
      project.world_summary = savedPayload.world_summary ?? project.world_summary;
      project.world_blueprint = { ...project.world_blueprint, ...(savedPayload.world_blueprint ?? {}) };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
      return;
    }
    projectGetCount += 1;
    if (projectGetCount > 1) await new Promise((resolve) => setTimeout(resolve, 350));
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
    completedProjectGetCount += 1;
  });
  await page.route("**/file-stories/file%3Aworld-page-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: "file:world-page-fixture", outline: "", genre: "网游", style: "白描", current_chapter: 1,
      agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
      agent_runtime: { recent_events: [] }, author_constraints: [],
      world_facts: Array.from({ length: 25 }, (_, index) => `项目事实${index + 1}`),
      characters: [], history: [], parent_story_id: null, branched_from_chapter: null,
    }) });
  });

  await page.setViewportSize({ width: 901, height: 900 });
  await page.goto("/projects/file%3Aworld-page-fixture/world");

  for (const heading of ["世界背景", "世界规则", "地点", "阵营", "怪物图鉴", "已确认事实"]) {
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }
  const orderedSections = page.locator([
    "#world-background-title",
    "#basic-world-rules-title",
    "#progression-world-rules-title",
    "#economy-world-rules-title",
    "#quest-world-rules-title",
    "#faction-panel-world-rules-title",
    "#reality-world-rules-title",
    "#constraints-world-rules-title",
    "#world-entities-title",
    "#monster-bestiary-title",
    "#confirmed-facts-title",
  ].join(", "));
  await expect(orderedSections).toHaveCount(11);
  await expect(orderedSections).toHaveText([
    "世界背景",
    "基础规则",
    "成长体系",
    "经济体系",
    "任务体系",
    "阵营与面板",
    "游戏影响现实",
    "世界硬约束",
    "地点与阵营",
    "怪物图鉴",
    "已确认事实",
  ]);
  for (const buttonName of ["保存力量体系", "保存成长规则", "保存经济体系", "保存任务体系"]) {
    await expect(page.getByRole("button", { name: buttonName, exact: true })).toBeVisible();
  }

  const progressionSection = page.locator('section[aria-labelledby="progression-world-rules-title"]');
  await expect(progressionSection).toHaveClass(/ws-form-grid__wide/);
  const progressionTextareas = progressionSection.locator("textarea");
  await expect(progressionTextareas).toHaveCount(2);
  const desktopWidths = await progressionTextareas.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().width),
  );
  expect(desktopWidths.every((width) => width >= 200)).toBe(true);

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileBounds = await progressionTextareas.evaluateAll((elements) =>
    elements.map((element) => {
      const bounds = element.getBoundingClientRect();
      return { left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom };
    }),
  );
  expect(mobileBounds[1].top).toBeGreaterThan(mobileBounds[0].bottom);
  expect(mobileBounds.every(({ left, right }) => left >= 0 && right <= 390)).toBe(true);
  await expect(page.getByText("项目事实25", { exact: true })).toBeVisible();
  await expect(page.getByText("作者约束", { exact: true })).toHaveCount(0);

  const summary = page.getByLabel("项目摘要");
  const unsavedRule = page.locator("label.ws-search").filter({ hasText: "基础规则" }).locator("textarea").first();
  await summary.fill("保存后的项目摘要");
  await unsavedRule.fill("尚未保存的规则草稿");
  await page.getByRole("button", { name: "保存世界背景" }).click();
  await expect.poll(() => savedPayload.world_summary).toBe("保存后的项目摘要");
  await page.waitForTimeout(100);
  await expect(summary).toBeVisible();
  await expect(summary).toHaveValue("保存后的项目摘要");
  await expect(unsavedRule).toHaveValue("尚未保存的规则草稿");
  await expect.poll(() => completedProjectGetCount).toBeGreaterThan(1);
  await expect(unsavedRule).toHaveValue("尚未保存的规则草稿");
  expect(savedPayload.world_blueprint).toEqual({ premise: "旧世界前提", current_arc: "旧局势" });
  expect(project.world_blueprint).toMatchObject({ monster_profiles: monsterProfiles });
});

test("世界观并发保存使用局部蓝图且跨编辑器更新互不覆盖", async ({ page }) => {
  let projectGetCount = 0;
  let refreshPending = false;
  let rulePutStarted = false;
  let rulePutCompleted = false;
  let backgroundPutStarted = false;
  let failWrites = false;
  let releaseRulePut!: () => void;
  let releaseBackgroundPut!: () => void;
  let releaseRefresh!: () => void;
  const rulePutGate = new Promise<void>((resolve) => { releaseRulePut = resolve; });
  const backgroundPutGate = new Promise<void>((resolve) => { releaseBackgroundPut = resolve; });
  const refreshGate = new Promise<void>((resolve) => { releaseRefresh = resolve; });
  const project = {
    project_id: "file:world-concurrent-fixture", title: "并发保存测试", source_path: "", seed_outline: "",
    world_summary: "旧摘要", current_focus: "", author_constraints: [],
    world_blueprint: {
      premise: "旧前提", current_arc: "旧局势", world_rules: ["旧规则"],
      locations: [{ name: "旧港", description: "旧描述" }], factions: [],
      monster_profiles: [{ id: "wolf", name: "灰狼" }],
    },
    character_profiles: [], relationship_graph: [], enabled_skill_ids: [], status: "simulating",
    pipeline_stage: "world_ready", active_story_id: "file:world-concurrent-fixture", branches: [], storage_source: "file",
  };
  await page.route("**/file-projects/file%3Aworld-concurrent-fixture", async (route) => {
    if (route.request().method() === "PUT") {
      if (failWrites) {
        await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "write_failed" }) });
        return;
      }
      const payload = route.request().postDataJSON() as {
        world_summary?: string;
        world_blueprint?: Record<string, unknown>;
      };
      if (payload.world_blueprint?.world_rules) {
        rulePutStarted = true;
        await rulePutGate;
      }
      if (payload.world_blueprint?.premise) {
        backgroundPutStarted = true;
        await backgroundPutGate;
      }
      if (payload.world_summary !== undefined) project.world_summary = payload.world_summary;
      project.world_blueprint = { ...project.world_blueprint, ...(payload.world_blueprint ?? {}) };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
      if (payload.world_blueprint?.world_rules) rulePutCompleted = true;
      return;
    }
    projectGetCount += 1;
    if (rulePutCompleted) {
      refreshPending = true;
      await refreshGate;
      refreshPending = false;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-stories/file%3Aworld-concurrent-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      story_id: "file:world-concurrent-fixture", outline: "", genre: "网游", style: "白描", current_chapter: 1,
      agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
      agent_runtime: { recent_events: [] }, author_constraints: [], world_facts: [], characters: [], history: [],
      parent_story_id: null, branched_from_chapter: null,
    }) });
  });

  await page.goto("/projects/file%3Aworld-concurrent-fixture/world");
  await expect.poll(async () => page.locator("body").innerText()).toContain("世界规则");
  const ruleEditor = page.locator("label.ws-search").filter({ hasText: "基础规则" }).locator("textarea").first();
  await ruleEditor.fill("并发新规则");
  await page.getByRole("button", { name: "保存基础规则" }).click();
  await expect.poll(() => rulePutStarted).toBe(true);
  const ruleSaving = page.getByRole("status").filter({ hasText: "保存中" });
  await expect(ruleSaving).toHaveAttribute("aria-live", "polite");
  releaseRulePut();
  await expect.poll(() => project.world_blueprint.world_rules).toEqual(["并发新规则"]);
  await expect.poll(() => refreshPending).toBe(true);
  await expect(page.locator('section[aria-labelledby="world-rules-title"]').getByRole("status").filter({ hasText: "保存成功" })).toBeVisible();

  await page.getByLabel("世界前提").fill("并发新前提");
  await page.getByRole("button", { name: "保存世界背景" }).click();
  await expect.poll(() => backgroundPutStarted).toBe(true);
  const backgroundSaving = page.getByRole("status").filter({ hasText: "保存中" });
  await expect(backgroundSaving).toHaveAttribute("aria-live", "polite");
  releaseBackgroundPut();
  await expect.poll(() => project.world_blueprint.premise).toBe("并发新前提");
  await expect(page.locator('section[aria-labelledby="world-background-title"]').getByRole("status").filter({ hasText: "保存成功" })).toBeVisible();

  const locations = page.locator('section[aria-labelledby="world-locations-title"]');
  await locations.getByLabel("名称").fill("并发新港");
  await locations.getByRole("button", { name: "保存地点" }).click();
  await expect.poll(() => project.world_blueprint.locations).toEqual([{ name: "并发新港", description: "旧描述" }]);
  expect(project.world_blueprint).toMatchObject({
    world_rules: ["并发新规则"], premise: "并发新前提",
    locations: [{ name: "并发新港" }], monster_profiles: [{ id: "wolf", name: "灰狼" }],
  });

  failWrites = true;
  await page.getByLabel("世界前提").fill("失败背景");
  await page.getByRole("button", { name: "保存世界背景" }).click();
  await expect(page.locator('section[aria-labelledby="world-background-title"]').getByRole("alert").filter({ hasText: "保存失败" })).toBeVisible();
  await ruleEditor.fill("失败规则");
  await page.getByRole("button", { name: "保存基础规则" }).click();
  await expect(page.locator('section[aria-labelledby="world-rules-title"]').getByRole("alert").filter({ hasText: "保存失败" })).toBeVisible();
  releaseRefresh();
});

test("项目加载成功但故事加载失败时仍显示项目并报告故事错误", async ({ page }) => {
  let storyRequestStarted = false;
  let releaseStory!: () => void;
  const storyGate = new Promise<void>((resolve) => { releaseStory = resolve; });
  const project = {
    project_id: "file:story-failure-fixture", title: "项目仍可见", source_path: "", seed_outline: "",
    world_summary: "项目数据已加载", current_focus: "", author_constraints: [], world_blueprint: {},
    character_profiles: [], relationship_graph: [], enabled_skill_ids: [], status: "simulating",
    pipeline_stage: "world_ready", active_story_id: "file:missing-story", branches: [], storage_source: "file",
  };
  await page.route("**/file-projects/file%3Astory-failure-fixture", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-stories/file%3Amissing-story", async (route) => {
    storyRequestStarted = true;
    await storyGate;
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "story_failed" }) });
  });

  await page.goto("/projects/file%3Astory-failure-fixture/world");

  await expect.poll(() => storyRequestStarted).toBe(true);
  await expect(page.getByRole("heading", { name: "世界背景" })).toBeVisible();
  await expect(page.getByLabel("项目摘要")).toHaveValue("项目数据已加载");
  releaseStory();
  await expect(page.getByText(/故事加载失败/)).toBeVisible();
});

test("项目文风可以选择也可以清空", async ({ page }) => {
  const project = {
    project_id: "file:style-settings-fixture",
    title: "文风设置测试",
    source_path: "",
    seed_outline: "",
    world_summary: "",
    current_focus: "",
    author_constraints: [],
    world_blueprint: { genre_plugin_ids: ["web_game_leveling"], writing_style: "" },
    character_profiles: [],
    relationship_graph: [],
    enabled_skill_ids: [],
    status: "writing",
    pipeline_stage: "world_ready",
    active_story_id: "file:style-settings-fixture",
    branches: [],
    storage_source: "file",
  };
  const savedStyles: string[] = [];

  await page.route("**/novel-types", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "web_game_leveling",
          name: "网游升级",
          description: "网游规则",
          keywords: [],
          core_promises: [],
          ledger_fields: [],
          rulebook: {
            progression_rules: [], economy_rules: [], quest_rules: [], faction_rules: [],
            panel_rules: [], chapter_formula: [], forbidden_breaks: [],
          },
          quality_checks: [],
          trope_templates: [],
          builtin: true,
        },
      ]),
    });
  });
  await page.route("**/file-projects/file%3Astyle-settings-fixture", async (route) => {
    if (route.request().method() === "PUT") {
      const payload = route.request().postDataJSON() as { world_blueprint?: { writing_style?: string } };
      project.world_blueprint = { ...project.world_blueprint, ...(payload.world_blueprint ?? {}) };
      savedStyles.push(project.world_blueprint.writing_style || "");
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/file-stories/file%3Astyle-settings-fixture", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        story_id: "file:style-settings-fixture",
        outline: "",
        genre: "网游",
        style: project.world_blueprint.writing_style,
        current_chapter: 1,
        agent_settings: {},
        agent_runtime: { recent_events: [] },
        author_constraints: [],
        world_facts: [],
        characters: [],
        history: [],
      }),
    });
  });

  await page.goto("/projects/file%3Astyle-settings-fixture/settings");
  const styleSelect = page.getByLabel("当前文风");
  await expect(styleSelect).toHaveValue("");

  await styleSelect.selectOption("幽默");
  await expect(page.getByText("文风已保存为：幽默。下一次写作会读取这个选择。")).toBeVisible();
  await expect.poll(() => savedStyles).toContain("幽默");

  await styleSelect.selectOption("");
  await expect(page.getByText("已清空文风选择。下一次写作不会注入额外文风。")).toBeVisible();
  await expect.poll(() => savedStyles.at(-1)).toBe("");
});
