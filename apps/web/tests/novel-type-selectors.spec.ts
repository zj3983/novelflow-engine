import { expect, test, type Page, type Route } from "@playwright/test";

type NovelTypeFixture = {
  id: string;
  name: string;
  description: string;
  builtin: boolean;
};

const genericType: NovelTypeFixture = {
  id: "generic_webnovel",
  name: "通用网文",
  description: "适合不绑定具体题材的长篇创作。",
  builtin: true,
};

const customType: NovelTypeFixture = {
  id: "sports_custom",
  name: "热血竞技",
  description: "围绕训练、比赛和团队关系推进。",
  builtin: false,
};

function novelTypeResponse(type: NovelTypeFixture) {
  return {
    ...type,
    keywords: [],
    core_promises: [],
    ledger_fields: [],
    rulebook: {
      progression_rules: [],
      economy_rules: [],
      quest_rules: [],
      faction_rules: [],
      panel_rules: [],
      chapter_formula: [],
      forbidden_breaks: [],
    },
    quality_checks: [],
    trope_templates: [],
  };
}

async function routeNovelTypes(
  page: Page,
  types: NovelTypeFixture[],
  options: { failures?: number } = {},
) {
  let requests = 0;
  await page.route("**/novel-types", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 204 });
      return;
    }
    requests += 1;
    if (requests <= (options.failures ?? 0)) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "novel_type_service_unavailable" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(types.map(novelTypeResponse)),
    });
  });
  return { requestCount: () => requests };
}

function projectFixture(typeId: string) {
  return {
    project_id: "file:selector-fixture",
    title: "试剑录",
    source_path: "",
    seed_outline: "",
    world_summary: "",
    current_focus: "",
    author_constraints: [],
    world_blueprint: { genre_plugin_ids: [typeId] },
    character_profiles: [],
    relationship_graph: [],
    enabled_skill_ids: [],
    status: "draft",
    pipeline_stage: "draft",
    active_story_id: "",
    branches: [],
    storage_source: "file",
  };
}

async function routeSettingsProject(page: Page, typeId: string) {
  let project = projectFixture(typeId);
  const updates: Array<Record<string, unknown>> = [];
  await page.route("**/file-projects/file%3Aselector-fixture", async (route: Route) => {
    if (route.request().method() === "PUT") {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      updates.push(payload);
      project = { ...project, ...payload };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  return updates;
}

test("新建页加载全局类型，优先通用类型并提交动态 ID", async ({ page }) => {
  await routeNovelTypes(page, [customType, genericType]);
  const creates: unknown[] = [];
  await page.route("**/file-projects", async (route) => {
    creates.push(route.request().postDataJSON());
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ next_path: "/projects/file%3Acreated/outline" }),
    });
  });

  await page.goto("/projects/new");
  const selector = page.getByLabel("小说类型");
  await expect(selector).toHaveValue("generic_webnovel");
  await expect(selector.getByRole("option", { name: "热血竞技" })).toHaveCount(1);
  await expect(page.getByText(genericType.description)).toBeVisible();

  await selector.selectOption(customType.id);
  await expect(page.getByText(customType.description)).toBeVisible();
  await page.getByRole("tab", { name: "建立空白小说" }).click();
  await page.getByLabel("小说名").fill("试剑录");
  await page.getByRole("button", { name: "创建小说" }).click();

  await expect(page).toHaveURL(/file%3Acreated\/outline$/);
  expect(creates).toEqual([{ mode: "blank", title: "试剑录", novel_type_id: customType.id, idea: "" }]);
});

test("新建页在没有通用类型时默认第一项", async ({ page }) => {
  await routeNovelTypes(page, [customType]);
  await page.goto("/projects/new");
  await expect(page.getByLabel("小说类型")).toHaveValue(customType.id);
});

test("新建页类型加载失败后可重试", async ({ page }) => {
  const api = await routeNovelTypes(page, [genericType, customType], { failures: 2 });
  await page.goto("/projects/new");

  await expect(page.getByRole("alert").filter({ hasText: "小说类型加载失败" })).toBeVisible();
  await expect(page.getByLabel("小说类型")).toBeDisabled();
  await expect(page.getByRole("button", { name: "创建小说" })).toBeDisabled();
  await page.getByRole("button", { name: "重新加载" }).click();

  await expect(page.getByLabel("小说类型")).toBeEnabled();
  await expect(page.getByLabel("小说类型")).toHaveValue("generic_webnovel");
  expect(api.requestCount()).toBe(3);
});

test("新建页遇到空类型库时明确提示并阻止创建", async ({ page }) => {
  await routeNovelTypes(page, []);
  await page.goto("/projects/new");

  await expect(page.getByText("小说类型库为空")).toBeVisible();
  await page.getByRole("textbox", { name: /^灵感/ }).fill("一个不会被提交的灵感");
  await expect(page.getByRole("button", { name: "创建小说" })).toBeDisabled();
});

test("设置页选中并保存自定义类型，描述和消息使用动态名称", async ({ page }) => {
  await routeNovelTypes(page, [genericType, customType]);
  const updates = await routeSettingsProject(page, genericType.id);
  await page.goto("/projects/file%3Aselector-fixture/settings");

  const selector = page.getByLabel("当前类型");
  await expect(selector.getByRole("option", { name: "热血竞技" })).toHaveCount(1);
  await expect(selector).toHaveValue(genericType.id);
  await expect(page.getByText(genericType.description)).toBeVisible();
  await selector.selectOption(customType.id);

  await expect(page.getByText(customType.description)).toBeVisible();
  await expect(page.getByText(/小说类型已保存为：热血竞技/)).toBeVisible();
  expect(updates).toEqual([{ world_blueprint: { genre_plugin_ids: [customType.id] } }]);
});

test("设置页保留已删除的当前类型，直到用户主动选择", async ({ page }) => {
  await routeNovelTypes(page, [genericType, customType]);
  const updates = await routeSettingsProject(page, "retired_type");
  await page.goto("/projects/file%3Aselector-fixture/settings");

  const selector = page.getByLabel("当前类型");
  await expect(selector).toHaveValue("retired_type");
  await expect(selector.getByRole("option", { name: "未知类型（retired_type）" })).toHaveCount(1);
  await expect(page.getByRole("alert").filter({ hasText: "项目引用的小说类型 retired_type 已不存在" })).toBeVisible();
  await page.waitForTimeout(100);
  expect(updates).toHaveLength(0);

  await selector.selectOption(customType.id);
  await expect.poll(() => updates.length).toBe(1);
  expect(updates[0]).toEqual({ world_blueprint: { genre_plugin_ids: [customType.id] } });
});

test("设置页类型加载失败后可重新加载", async ({ page }) => {
  const api = await routeNovelTypes(page, [genericType, customType], { failures: 2 });
  await routeSettingsProject(page, customType.id);
  await page.goto("/projects/file%3Aselector-fixture/settings");

  await expect(page.getByRole("alert").filter({ hasText: "小说类型加载失败" })).toBeVisible();
  await expect(page.getByLabel("当前类型")).toBeDisabled();
  await page.getByRole("button", { name: "重新加载" }).click();

  await expect(page.getByLabel("当前类型")).toHaveValue(customType.id);
  await expect(page.getByLabel("当前类型")).toBeEnabled();
  expect(api.requestCount()).toBe(3);
});
