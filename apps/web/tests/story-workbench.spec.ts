import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const FIXTURE_PATH = path.resolve(__dirname, "../../../tests/fixtures/book-import-sample");

async function proxyBookImportRoutes(page: Page) {
  await page.route("**/book-import/**", async (route) => {
    const request = route.request();
    const sourcePath = FIXTURE_PATH;
    const read = (relativePath: string) => fs.readFileSync(path.join(sourcePath, relativePath), "utf-8");

    const scanPayload = {
      source_path: sourcePath,
      exists: true,
      missing_required_files: [],
      missing_optional_files: [],
      unusable_required_files: [],
      empty_files: [],
      present_files: [
        "author_intent.md",
        "book_rules.md",
        "character_matrix.md",
        "current_focus.md",
        "story_bible.md",
        "volume_outline.md",
      ],
      warnings: [],
      can_bootstrap: true,
    };

    const catalogPayload = {
      source_path: sourcePath,
      exists: true,
      can_bootstrap: true,
      sections: [
        {
          section_id: "source_docs",
          title: "源书目录",
          items: [
            {
              item_id: "source:author_intent.md",
              title: "author_intent.md",
              kind: "source_document",
              filename: "author_intent.md",
              path: `${sourcePath}/author_intent.md`,
              preview: "INTENT: Keep the opening grounded.",
              content: read("author_intent.md"),
              parsed_characters: [],
            },
          ],
        },
      ],
    };

    const bootstrapPayload = {
      report: scanPayload,
      draft: {
        source_path: sourcePath,
        outline: "VOLUME: A hidden ledger drives the plot.\n\nFOCUS: Start with the first clue.",
        summary: "导演预读：这本书会先从账本和匿名线索开始，逐步把宫廷压力抬起来。",
        characters: [
          { name: "Lin Yue", goal: "find the hidden ledger" },
          { name: "Su Wan", goal: "protect the witness" },
        ],
      },
    };

    if (request.method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "content-type",
        },
        body: "",
      });
      return;
    }

    if (request.url().includes("/book-import/catalog")) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify(catalogPayload),
      });
      return;
    }

    if (request.url().includes("/book-import/scan")) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify(scanPayload),
      });
      return;
    }

    if (request.method() === "POST" && request.url().includes("/book-import/bootstrap")) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify(bootstrapPayload),
      });
      return;
    }

    await route.fallback();
  });
}

async function seedMinimalDraft(page: Page) {
  await page.getByLabel("Outline Input").fill("A court ledger hides the first clue.");
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("find the hidden ledger");
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

test("projects page creates a blank file novel", async ({ page }) => {
  const requests: unknown[] = [];
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

test("homepage foregrounds story status and history before import", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("banner")).toBeVisible();
  await expect(page.locator(".simulation-board")).toBeVisible();
  await expect(page.locator('[aria-label="项目资料面板"]')).toBeVisible();
  await expect(page.locator(".creative-workbench__side")).toBeVisible();
  await expect(page.getByRole("banner").getByRole("button")).toBeVisible();
});

test("homepage top bar shows writing progress and core actions", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator(".workbench-topbar__eyebrow")).toBeVisible();
  await expect(page.locator(".workbench-topbar__summary")).toBeVisible();
  await expect(page.getByRole("banner").getByRole("link", { name: /查看配置/ })).toBeVisible();
});

test("file project outline edits three independent levels", async ({ page }) => {
  let savedBody: Record<string, unknown> | null = null;
  const outline = {
    schema_version: "project-outline/v1",
    source: "saved",
    overall: {
      story: "林照追查祖祠旧案。",
      protagonist_goal: "",
      main_conflict: "宗门有人阻止他追查。",
      growth_path: "从杂役成长为内门弟子。",
      ending_direction: "查清旧案。",
    },
    arcs: [
      {
        id: "opening",
        title: "祖祠阶段",
        start_chapter: 1,
        end_chapter: 8,
        goal: "找出纵火者",
        obstacle: "管事阻挠",
        payoff: "拿到旧名册",
        end_state: "进入外门调查",
      },
    ],
    chapters: [
      {
        chapter_number: 1,
        title: "守炉",
        goal: "检查断香炉",
        obstacle: "值夜弟子不配合",
        action: "核对香灰和名册",
        turn: "香灰里有内门令牌碎片",
        payoff: "确认有人来过",
        ending_hook: "脚印通向后山",
      },
    ],
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
  await page.route("**/file-stories/file%3Aoutline-fixture", async (route) => {
    const runtimeEntry = { mode: "LLM-assisted", source: "idle", fallback_reason: "", last_run_chapter: 0 };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        story_id: "file:outline-fixture",
        outline: outline.overall.story,
        genre: "玄幻",
        style: "白描",
        current_chapter: 0,
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
          character_agent: runtimeEntry,
          director_agent: runtimeEntry,
          writer_agent: runtimeEntry,
          memory_agent: runtimeEntry,
          outline_agent: runtimeEntry,
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
  await expect(page.getByRole("tab", { name: "总纲", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "阶段大纲", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "章节大纲", exact: true })).toBeVisible();
  await page.getByLabel("主角长期目标").fill("洗清父亲旧案");
  await page.getByRole("tab", { name: "阶段大纲", exact: true }).click();
  await expect(page.getByLabel("阶段名称")).toHaveValue("祖祠阶段");
  await page.getByRole("tab", { name: "章节大纲", exact: true }).click();
  await expect(page.getByLabel("暂定标题")).toHaveValue("守炉");
  await page.getByRole("button", { name: "保存大纲" }).click();

  expect(savedBody).toMatchObject({
    overall: { protagonist_goal: "洗清父亲旧案" },
    arcs: outline.arcs,
    chapters: outline.chapters,
  });
  expect(savedBody).not.toHaveProperty("source");
});

test("imported book still exposes a browsable source panel", async ({ page }) => {
  await proxyBookImportRoutes(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle");

  const sourcePathInput = page.getByPlaceholder("例如：D:/novels/demo/story");
  await sourcePathInput.fill(FIXTURE_PATH);
  await page.getByRole("button", { name: "校验目录", exact: true }).click();

  await expect(page.locator('[aria-label="书籍导入报告"]')).toContainText("可载入");
  await expect(page.locator('[aria-label="导入内容浏览面板"]')).toBeVisible();
});

test("generated chapters surface in the homepage chapter workspace", async ({ page }) => {
  await page.goto("/");
  await seedMinimalDraft(page);
  await page.getByRole("banner").getByRole("button", { name: /开始生成第一章|继续生成下一章/ }).click();

  await expect(page.locator(".chapter-panel")).toContainText(/第\s*\d+\s*章/);
  await expect(page.locator(".chapter-panel")).toContainText("本章意图");
  await expect(page.locator(".chapter-panel")).toContainText("事件推进");
});

test("chapter review panel can trigger an automatic revision", async ({ page }) => {
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
    const runtimeEntry = { mode: "LLM-assisted", source: "idle", fallback_reason: "", last_run_chapter: 0 };
    const agentRuntime = {
      character_agent: runtimeEntry,
      director_agent: runtimeEntry,
      writer_agent: runtimeEntry,
      memory_agent: runtimeEntry,
      outline_agent: runtimeEntry,
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

  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator(".chapter-panel")).toContainText("改稿安全报告");
  await expect(page.locator(".chapter-panel")).toContainText("整章快照：保留原稿");
  await expect(page.locator(".chapter-panel")).toContainText("现实入口：保留原稿");

  await page.getByRole("button", { name: "按审稿意见自动改稿" }).click();

  await expect(page.locator(".chapter-panel__prose")).toContainText("REVISED_BY_AGENT");
});

test("project author constraints persist after refresh", async ({ page }) => {
  await page.goto("/");
  await seedMinimalDraft(page);
  await page.getByRole("banner").getByRole("button", { name: /开始生成第一章|继续生成下一章/ }).click();

  await page.locator(".project-editor textarea").nth(2).fill("rule one\nrule two");
  await page.locator(".project-editor button.btn--primary").click();

  await expect(page.getByText("项目资料已保存到后端。")).toBeVisible();
  await page.reload();

  await expect(page.locator(".project-editor textarea").nth(2)).toHaveValue(/rule one/);
});
