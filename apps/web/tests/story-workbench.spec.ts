import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page, type Route } from "@playwright/test";

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
  const tabpanel = page.getByRole("tabpanel");

  await expect(inspirationTab).toHaveAttribute("tabindex", "0");
  await expect(blankTab).toHaveAttribute("tabindex", "-1");
  await expect(inspirationTab).toHaveAttribute("aria-controls", "creation-form");
  await expect(blankTab).toHaveAttribute("aria-controls", "creation-form");
  await expect(tabpanel).toHaveAttribute("aria-labelledby", "creation-mode-inspiration");

  await inspirationTab.focus();
  await inspirationTab.press("ArrowRight");
  await expect(blankTab).toBeFocused();
  await expect(blankTab).toHaveAttribute("aria-selected", "true");
  await expect(blankTab).toHaveAttribute("tabindex", "0");
  await expect(inspirationTab).toHaveAttribute("tabindex", "-1");
  await expect(tabpanel).toHaveAttribute("aria-labelledby", "creation-mode-blank");

  await blankTab.press("ArrowRight");
  await expect(inspirationTab).toBeFocused();
  await inspirationTab.press("ArrowLeft");
  await expect(blankTab).toBeFocused();
  await blankTab.press("Home");
  await expect(inspirationTab).toBeFocused();
  await inspirationTab.press("End");
  await expect(blankTab).toBeFocused();
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
        stage_antagonist: "赵衡",
        long_term_antagonist_traces: ["旧名册被换过"],
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
        cast: ["林照", "赵衡"],
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
  await expect(page.getByText("章节计划仅剩 1 章，请先补充后续章节。", { exact: true })).toBeVisible();
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

  await page.getByLabel("本次生成补充要求").fill("阶段对手必须有现实利益");
  await page.getByRole("button", { name: "重新生成" }).click();
  await expect.poll(() => generationBody).toEqual({ mode: "regenerate", guidance: "阶段对手必须有现实利益" });
  await expect(page.getByLabel("本次生成补充要求")).toHaveValue("");
  await page.getByRole("tab", { name: "阶段大纲", exact: true }).click();
  await expect(page.getByLabel("阶段对手")).toHaveValue("赵衡");
  await page.getByRole("tab", { name: "章节大纲", exact: true }).click();
  await expect(page.getByLabel("出场人物")).toHaveValue("林照\n赵衡");
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
  const savedGraph = (savedBody as { relationship_graph: Array<Record<string, unknown>> }).relationship_graph;
  expect(savedGraph).toHaveLength(2);
  expect(savedGraph[0]).toMatchObject({ source: "林照", target: "赵衡", current_state: "公开对立" });
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
