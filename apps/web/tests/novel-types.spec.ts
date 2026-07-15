import { expect, test, type Page, type Route } from "@playwright/test";

type NovelTypeFixture = {
  id: string;
  name: string;
  description: string;
  keywords: string[];
  core_promises: string[];
  ledger_fields: string[];
  rulebook: Record<string, string[]>;
  quality_checks: string[];
  trope_templates: Array<Record<string, unknown>>;
  builtin: boolean;
};

const emptyRulebook = {
  progression_rules: [] as string[],
  economy_rules: [] as string[],
  quest_rules: [] as string[],
  faction_rules: [] as string[],
  panel_rules: [] as string[],
  chapter_formula: [] as string[],
  forbidden_breaks: [] as string[],
};

function fixtures(): NovelTypeFixture[] {
  return [
    {
      id: "xuanhuan",
      name: "玄幻",
      description: "力量成长与世界秘密递进。",
      keywords: ["玄幻", "升级"],
      core_promises: ["力量提升必须改变外部关系。"],
      ledger_fields: ["境界", "资源"],
      rulebook: {
        ...emptyRulebook,
        progression_rules: ["成长必须付出代价。"],
        chapter_formula: ["目标、阻力、变化。"],
      },
      quality_checks: ["力量一致"],
      trope_templates: [
        {
          id: "low_status_reversal",
          name: "低位反转",
          trigger: "公开受压",
          beats: ["承压", "验证"],
          payoff: "地位变化",
          avoid: "无代价碾压",
        },
      ],
      builtin: true,
    },
    {
      id: "sports",
      name: "竞技体育",
      description: "训练、比赛与团队关系。",
      keywords: ["联赛"],
      core_promises: ["胜负改变人物关系。"],
      ledger_fields: ["体能"],
      rulebook: { ...emptyRulebook },
      quality_checks: ["赛制一致"],
      trope_templates: [],
      builtin: false,
    },
  ];
}

async function mockNovelTypes(page: Page, options?: { deleteConflict?: boolean; saveValidationError?: boolean }) {
  let records = fixtures();
  const requests: Array<{ method: string; payload?: NovelTypeFixture }> = [];
  const corsHeaders = {
    "access-control-allow-methods": "GET, POST, PUT, DELETE, OPTIONS",
    "access-control-allow-headers": "content-type",
    "access-control-allow-private-network": "true",
  };

  await page.route(/^http:\/\/127\.0\.0\.1:8000\/novel-types(?:\/[^/?]+)?(?:\?.*)?$/, async (route: Route) => {
    const request = route.request();
    const method = request.method();
    const url = new URL(request.url());
    const responseHeaders = {
      ...corsHeaders,
      "access-control-allow-origin": request.headers().origin || "*",
    };
    const id = decodeURIComponent(url.pathname.split("/").filter(Boolean)[1] || "");

    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers: responseHeaders, body: "" });
      return;
    }

    if (method === "GET") {
      await route.fulfill({ status: 200, headers: { ...responseHeaders, "content-type": "application/json" }, body: JSON.stringify(records) });
      return;
    }

    if (method === "POST") {
      const payload = JSON.parse(request.postData() || "{}") as NovelTypeFixture;
      const created = { ...payload, builtin: false };
      requests.push({ method, payload });
      records = [...records, created];
      await route.fulfill({ status: 201, headers: { ...responseHeaders, "content-type": "application/json" }, body: JSON.stringify(created) });
      return;
    }

    if (method === "PUT") {
      const payload = JSON.parse(request.postData() || "{}") as NovelTypeFixture;
      if (options?.saveValidationError) {
        await route.fulfill({
          status: 422,
          headers: { ...responseHeaders, "content-type": "application/json" },
          body: JSON.stringify({ detail: [{ type: "string_pattern_mismatch", loc: ["body", "id"] }] }),
        });
        return;
      }
      const previous = records.find((record) => record.id === id)!;
      const updated = { ...payload, builtin: previous.builtin };
      requests.push({ method, payload });
      records = records.map((record) => (record.id === id ? updated : record));
      await route.fulfill({ status: 200, headers: { ...responseHeaders, "content-type": "application/json" }, body: JSON.stringify(updated) });
      return;
    }

    if (method === "DELETE" && options?.deleteConflict) {
      await route.fulfill({
        status: 409,
        headers: { ...responseHeaders, "content-type": "application/json" },
        body: JSON.stringify({ detail: "Novel type 'sports' is used by project(s): spring-league" }),
      });
      return;
    }

    requests.push({ method });
    records = records.filter((record) => record.id !== id);
    await route.fulfill({ status: 204, headers: responseHeaders, body: "" });
  });

  return { requests };
}

test("导航进入全局小说类型库，选择并保存内置类型", async ({ page }) => {
  const api = await mockNovelTypes(page);
  await page.goto("/novel-types", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("status")).toContainText("已载入");

  await expect(page.getByRole("link", { name: "小说类型", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: "全局小说类型库" })).toBeVisible();
  await expect(page.getByText("类型决定写作时加载的题材承诺、规则和检查；修改会影响之后使用该类型的生成。"))
    .toBeVisible();

  await expect(page.getByRole("button", { name: /玄幻/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("类型 ID")).toBeDisabled();
  await expect(page.getByRole("button", { name: "删除类型" })).toBeDisabled();

  await page.getByLabel("类型名称").fill("东方玄幻");
  await page.getByLabel("核心承诺（每行一项）").fill("每次成长都改变局势\n代价必须可见");
  await page.getByRole("button", { name: "保存修改" }).click();

  await expect.poll(() => api.requests.map((request) => request.method)).toContain("PUT");
  await expect(page.locator('p[aria-live="polite"]')).toContainText("已保存");
  expect(api.requests.at(-1)).toMatchObject({ method: "PUT" });
  expect(api.requests.at(-1)?.payload).toMatchObject({
    id: "xuanhuan",
    name: "东方玄幻",
    core_promises: ["每次成长都改变局势", "代价必须可见"],
  });
});

test("新建并删除自定义类型", async ({ page }) => {
  const api = await mockNovelTypes(page);
  await page.goto("/novel-types", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("status")).toContainText("已载入");

  await page.getByRole("button", { name: "新建类型" }).click();
  await page.getByLabel("类型 ID").fill("history");
  await page.getByLabel("类型名称").fill("历史架空");
  await page.getByLabel("关键词（每行一项）").fill("历史\n权谋");
  await page.getByLabel("套路模板（JSON 数组）").fill("[]");
  await page.getByRole("button", { name: "创建类型" }).click();

  await expect(page.getByRole("button", { name: /历史架空/ })).toBeVisible();
  await expect(page.getByLabel("类型 ID")).toBeDisabled();
  expect(api.requests.find((request) => request.method === "POST")?.payload).toMatchObject({
    id: "history",
    name: "历史架空",
    keywords: ["历史", "权谋"],
    trope_templates: [],
  });

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除类型" }).click();
  await expect(page.getByRole("button", { name: /历史架空/ })).toHaveCount(0);
  expect(api.requests.at(-1)).toEqual({ method: "DELETE" });
});

test("删除占用中的自定义类型时保留当前编辑", async ({ page }) => {
  await mockNovelTypes(page, { deleteConflict: true });
  await page.goto("/novel-types", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("status")).toContainText("已载入");
  await page.getByRole("button", { name: /竞技体育/ }).click();
  await page.getByLabel("类型名称").fill("竞技体育（修订）");

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "删除类型" }).click();

  await expect(page.locator('p[role="alert"]')).toContainText("该类型正被项目 spring-league 使用，暂时不能删除。");
  await expect(page.getByLabel("类型名称")).toHaveValue("竞技体育（修订）");
  await expect(page.getByRole("button", { name: /竞技体育/ })).toBeVisible();
});

test("无效套路模板会阻止保存并可重置草稿", async ({ page }) => {
  await mockNovelTypes(page);
  await page.goto("/novel-types", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("status")).toContainText("已载入");
  await page.getByLabel("类型名称").fill("临时名称");
  await page.getByLabel("套路模板（JSON 数组）").fill("{bad json}");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.locator('p[role="alert"]')).toContainText("套路模板必须是有效的 JSON 数组");

  await page.getByRole("button", { name: "取消 / 重置" }).click();
  await expect(page.getByLabel("类型名称")).toHaveValue("玄幻");
});

test("API 422 校验详情显示为自然中文", async ({ page }) => {
  await mockNovelTypes(page, { saveValidationError: true });
  await page.goto("/novel-types", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("status")).toContainText("已载入");

  await page.getByLabel("类型名称").fill("玄幻修订");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.locator('p[role="alert"]')).toContainText("提交内容未通过校验，请检查必填项、类型 ID 和每行内容。");
  await expect(page.getByLabel("类型名称")).toHaveValue("玄幻修订");
});

test("390px 宽度下列表与编辑器纵向排列且无横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockNovelTypes(page);
  await page.goto("/novel-types", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("status")).toContainText("已载入");

  const listBox = await page.getByLabel("小说类型列表").boundingBox();
  const editorBox = await page.getByLabel("小说类型编辑器").boundingBox();
  expect(listBox).not.toBeNull();
  expect(editorBox).not.toBeNull();
  expect(editorBox!.y).toBeGreaterThan(listBox!.y + listBox!.height - 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
