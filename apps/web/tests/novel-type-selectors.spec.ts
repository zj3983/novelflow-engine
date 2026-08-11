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

const commercialShuangwenPack = {
  schema_version: "skill-pack/v1",
  skill_id: "commercial-shuangwen",
  name: "商业爽文推进",
  version: "1.0.0",
  module_count: 5,
  modules: [],
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

function deferred() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
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

async function routeSkillPacks(
  page: Page,
  packs: unknown[] = [commercialShuangwenPack],
  options: { fail?: boolean } = {},
) {
  await page.route("**/skill-packs", async (route) => {
    await route.fulfill({
      status: options.fail ? 503 : 200,
      contentType: "application/json",
      body: JSON.stringify(options.fail ? { detail: "skill_pack_service_unavailable" } : packs),
    });
  });
}

function projectFixture(typeId?: string) {
  return {
    project_id: "file:selector-fixture",
    title: "试剑录",
    source_path: "",
    seed_outline: "",
    world_summary: "",
    current_focus: "",
    author_constraints: [],
    world_blueprint: typeId ? { genre_plugin_ids: [typeId] } : {},
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

async function routeSettingsProject(
  page: Page,
  typeId?: string,
  options: { saveFailures?: number } = {},
) {
  let project = projectFixture(typeId);
  const updates: Array<Record<string, unknown>> = [];
  let putCount = 0;
  await page.route("**/file-projects/file%3Aselector-fixture", async (route: Route) => {
    if (route.request().method() === "PUT") {
      putCount += 1;
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      updates.push(payload);
      if (putCount <= (options.saveFailures ?? 0)) {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "项目服务暂时不可用" }),
        });
        return;
      }
      project = { ...project, ...payload };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  return { updates, putCount: () => putCount };
}

test("新建页加载全局类型，优先通用类型并提交动态 ID", async ({ page }) => {
  await routeNovelTypes(page, [customType, genericType]);
  await routeSkillPacks(page);
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

test("新建页叙事增强默认关闭，勾选后随请求提交且不跟随题材", async ({ page }) => {
  await routeNovelTypes(page, [genericType, customType]);
  await routeSkillPacks(page);
  const creates: unknown[] = [];
  await page.route("**/file-projects", async (route) => {
    creates.push(route.request().postDataJSON());
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ next_path: "/projects/file%3Aenhanced/outline" }),
    });
  });

  await page.goto("/projects/new");
  const enhancement = page.getByRole("checkbox", { name: "商业爽文推进" });
  await expect(page.getByRole("heading", { name: "叙事增强" })).toBeVisible();
  await expect(enhancement).not.toBeChecked();
  await expect(page.getByText("需求、压制、反击、回报；按题材加载具体例子。")).toBeVisible();

  await page.getByLabel("小说类型").selectOption(customType.id);
  await expect(enhancement).not.toBeChecked();
  await enhancement.check();
  await page.getByRole("tab", { name: "建立空白小说" }).click();
  await page.getByLabel("小说名").fill("爽文试剑录");
  await page.getByRole("button", { name: "创建小说" }).click();

  await expect(page).toHaveURL(/file%3Aenhanced\/outline$/);
  expect(creates).toEqual([{
    mode: "blank",
    title: "爽文试剑录",
    novel_type_id: customType.id,
    idea: "",
    narrative_enhancement_ids: ["commercial-shuangwen"],
  }]);
});

test("新建页在叙事增强包未安装时显示不可用并禁用选择", async ({ page }) => {
  await routeNovelTypes(page, [genericType]);
  await routeSkillPacks(page, []);

  await page.goto("/projects/new");

  await expect(page.getByRole("checkbox", { name: "商业爽文推进" })).toBeDisabled();
  await expect(page.getByRole("alert").filter({ hasText: "未安装“商业爽文推进”叙事增强" }))
    .toContainText("未安装“商业爽文推进”叙事增强，当前不可用。");
});

test("新建页叙事增强列表加载失败时保持创建可用", async ({ page }) => {
  await routeNovelTypes(page, [genericType]);
  await routeSkillPacks(page, [], { fail: true });

  await page.goto("/projects/new");

  await expect(page.getByRole("checkbox", { name: "商业爽文推进" })).toBeDisabled();
  await expect(page.getByRole("alert").filter({ hasText: "叙事增强列表加载失败" }))
    .toContainText("叙事增强列表加载失败，“商业爽文推进”当前不可用。");
  await page.getByRole("textbox", { name: /^灵感/ }).fill("列表失败也可以创建");
  await expect(page.getByRole("button", { name: "创建小说" })).toBeEnabled();
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

test("新建请求完成前离开页面时不再导航", async ({ page }) => {
  await routeNovelTypes(page, [genericType]);
  const pendingCreate = deferred();
  const requestStarted = deferred();
  await page.route("**/file-projects", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      return;
    }
    requestStarted.release();
    await pendingCreate.promise;
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ next_path: "/projects/file%3Alate/outline" }),
    });
  });
  await page.route(/^http:\/\/127\.0\.0\.1:8000\/projects(?:\?.*)?$/, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/projects/new");
  await page.getByRole("tab", { name: "建立空白小说" }).click();
  await page.getByLabel("小说名").fill("迟到的响应");
  await page.getByRole("button", { name: "创建小说" }).click();
  await requestStarted.promise;

  await page.getByRole("main").getByRole("link", { name: "作品" }).click();
  await expect(page).toHaveURL(/\/projects$/);
  pendingCreate.release();
  await page.waitForTimeout(200);
  await expect(page).toHaveURL(/\/projects$/);
});

test("设置页未配置类型时优先选择通用类型", async ({ page }) => {
  await routeNovelTypes(page, [customType, genericType]);
  await routeSettingsProject(page);
  await page.goto("/projects/file%3Aselector-fixture/settings");

  await expect(page.getByLabel("当前类型")).toHaveValue(genericType.id);
  await expect(page.getByText(genericType.description)).toBeVisible();
  await expect(page.getByText(/未知类型/)).toHaveCount(0);
});

test("设置页未配置且没有通用类型时选择列表第一项", async ({ page }) => {
  await routeNovelTypes(page, [customType]);
  await routeSettingsProject(page);
  await page.goto("/projects/file%3Aselector-fixture/settings");

  await expect(page.getByLabel("当前类型")).toHaveValue(customType.id);
  await expect(page.getByText(customType.description)).toBeVisible();
});

test("设置页选中并保存自定义类型，描述和消息使用动态名称", async ({ page }) => {
  await routeNovelTypes(page, [genericType, customType]);
  const api = await routeSettingsProject(page, genericType.id);
  await page.goto("/projects/file%3Aselector-fixture/settings");

  const selector = page.getByLabel("当前类型");
  await expect(selector.getByRole("option", { name: "热血竞技" })).toHaveCount(1);
  await expect(selector).toHaveValue(genericType.id);
  await expect(page.getByText(genericType.description)).toBeVisible();
  await selector.selectOption(customType.id);

  await expect(page.getByText(customType.description)).toBeVisible();
  await expect(page.getByRole("status")).toContainText("小说类型已保存为：热血竞技");
  await expect(page.getByRole("status")).toHaveAttribute("aria-live", "polite");
  expect(api.updates).toEqual([{ world_blueprint: { genre_plugin_ids: [customType.id] } }]);
});

test("设置页保存失败后回滚选择并允许重试同一类型", async ({ page }) => {
  await routeNovelTypes(page, [genericType, customType]);
  const api = await routeSettingsProject(page, genericType.id, {
    saveFailures: 1,
  });
  await page.goto("/projects/file%3Aselector-fixture/settings");

  const selector = page.getByLabel("当前类型");
  await expect(selector).toHaveValue(genericType.id);
  await selector.selectOption(customType.id);

  const failure = page.getByRole("alert").filter({ hasText: "保存失败" });
  await expect(failure).toContainText("保存失败，请检查服务后重试。");
  await expect(failure).toHaveAttribute("aria-live", "assertive");
  await expect(selector).toHaveValue(genericType.id);
  expect(api.putCount()).toBe(1);

  await selector.selectOption(customType.id);
  await expect(page.getByRole("status")).toContainText("小说类型已保存为：热血竞技");
  await expect(selector).toHaveValue(customType.id);
  expect(api.putCount()).toBe(2);
});

test("设置页保留已删除的当前类型，直到用户主动选择", async ({ page }) => {
  await routeNovelTypes(page, [genericType, customType]);
  const api = await routeSettingsProject(page, "retired_type");
  await page.goto("/projects/file%3Aselector-fixture/settings");

  const selector = page.getByLabel("当前类型");
  await expect(selector).toHaveValue("retired_type");
  await expect(selector.getByRole("option", { name: "未知类型（retired_type）" })).toHaveCount(1);
  await expect(page.getByRole("alert").filter({ hasText: "项目引用的小说类型 retired_type 已不存在" })).toBeVisible();
  await page.waitForTimeout(100);
  expect(api.updates).toHaveLength(0);

  await selector.selectOption(customType.id);
  await expect.poll(() => api.updates.length).toBe(1);
  expect(api.updates[0]).toEqual({ world_blueprint: { genre_plugin_ids: [customType.id] } });
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

test("设置页小说类型卡片在短视口中保持完整的纵向布局", async ({ page }) => {
  await page.setViewportSize({ width: 1134, height: 375 });
  await routeNovelTypes(page, [genericType, customType]);
  await routeSettingsProject(page, customType.id);
  await page.goto("/projects/file%3Aselector-fixture/settings");

  const card = page.locator("section.ws-card").filter({ hasText: "小说类型" });
  await expect(card).toBeVisible();

  const layout = await card.evaluate((element) => {
    const field = element.querySelector("label");
    const description = Array.from(element.querySelectorAll("p")).find(
      (paragraph) => paragraph.textContent === "围绕训练、比赛和团队关系推进。",
    );
    if (!field || !description) throw new Error("小说类型字段或说明未渲染");

    const cardRect = element.getBoundingClientRect();
    const fieldRect = field.getBoundingClientRect();
    const descriptionRect = description.getBoundingClientRect();
    return {
      cardDisplay: getComputedStyle(element).display,
      fieldDisplay: getComputedStyle(field).display,
      fieldBottom: fieldRect.bottom,
      descriptionTop: descriptionRect.top,
      descriptionBottom: descriptionRect.bottom,
      cardBottom: cardRect.bottom,
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
    };
  });

  expect(layout.cardDisplay).toBe("grid");
  expect(layout.fieldDisplay).toBe("grid");
  expect(layout.descriptionTop).toBeGreaterThanOrEqual(layout.fieldBottom);
  expect(layout.descriptionBottom).toBeLessThanOrEqual(layout.cardBottom);
  expect(layout.scrollHeight).toBe(layout.clientHeight);
});
