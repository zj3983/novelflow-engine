import { expect, test } from "@playwright/test";
import { action, buildView, candidate, expectAuthorBoundary, fulfill, opaque, productRoutes, projectPath, status, writeView } from "./fixtures/creation-product";

test("产品主路径：准备故事、生成候选、人工确认、下一卷继续创作", async ({ page }, testInfo) => {
  let prepared = false; let confirmed = 0; let draft = false; let nextVolume = false;
  const submitted: string[] = [];
  const fixture = await productRoutes(page, {
    build: () => { const view = buildView(); view.status = status(prepared ? "准备完成" : "待准备", "准备好故事，再进入章节创作。");
      view.actions = prepared ? [{ ...action("前往章节创作", 2), href: `${projectPath}/write` }] : [action("生成开局规划", 1)];
      if (confirmed && !nextVolume) view.actions = [action("准备下一卷", 3)]; return view; },
    write: () => { const view = writeView(confirmed || 1); if (!confirmed) { view.chapter = undefined; view.chapters = []; }
      view.actions = draft ? [] : confirmed && !nextVolume ? [{ ...action("准备下一卷", 4), href: `${projectPath}/build` }] : [action(confirmed ? "生成下一章" : "生成第一章", 20)];
      if (draft) { view.candidate = candidate(confirmed + 1); view.status = status("待确认", "候选已生成，请人工确认。"); view.steps = view.steps.map((step) => ({ ...step, current: step.label === "人工确认" })); }
      return view; },
    post: async (body, route) => { submitted.push(body.token);
      if (body.token === opaque(1)) prepared = true;
      if (body.token === opaque(3)) nextVolume = true;
      if (body.token === opaque(20)) draft = true;
      if (body.token === opaque(31)) { confirmed += 1; draft = false; }
      await fulfill(route, {}); },
  });
  await page.goto(`${projectPath}/build`);
  await page.getByRole("button", { name: "生成开局规划" }).click();
  await page.getByRole("link", { name: "前往章节创作" }).click();
  await page.getByRole("button", { name: "生成第一章" }).click();
  await expect(page.getByLabel("候选稿", { exact: true })).toContainText("第 1 章候选正文");
  expect(confirmed).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("write-author-review.png"), fullPage: true });
  await page.getByRole("button", { name: "确认提交" }).click();
  await expect(page.locator("div.ws-reader__body")).toContainText("第 1 章正文");
  expect(confirmed).toBe(1);
  await page.reload();
  await page.getByRole("link", { name: "准备下一卷" }).click();
  await page.getByRole("button", { name: "准备下一卷" }).click();
  await page.getByRole("link", { name: "前往章节创作" }).click();
  await page.getByRole("button", { name: "生成下一章" }).click();
  await expect(page.getByLabel("候选稿", { exact: true })).toContainText("第 2 章候选正文");
  expect(confirmed).toBe(1);
  expect(submitted.filter((token) => token === opaque(31))).toHaveLength(1);
  await expectAuthorBoundary(page, fixture.forbidden);
});

test("提交时发现事实冲突，产品错误保留候选与人工确认边界", async ({ page }) => {
  const view = writeView(); view.candidate = candidate(1, true); view.status = view.candidate.review; view.actions = [];
  let confirmations = 0;
  const fixture = await productRoutes(page, { write: () => view, post: async (body, route) => {
    expect(body).toEqual({ token: opaque(31) }); confirmations += 1;
    await fulfill(route, { detail: { message: "这份候选仍有事实冲突，请修改后再确认。", impact: "候选已保留，正式章节未改变。" } }, 400);
  } });
  await page.goto(`${projectPath}/write`);
  await expect(page.getByLabel("正文写作路径")).toContainText("需要修改");
  await expect(page.getByRole("button", { name: "仍然采用" })).toHaveCount(0);
  expect(confirmations).toBe(0);
  await page.getByRole("button", { name: "确认提交" }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("正式章节未改变");
  await expect(page.getByLabel("候选稿", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("候选稿", { exact: true })).toBeVisible();
  expect(confirmations).toBe(1);
  await expectAuthorBoundary(page, fixture.forbidden);
});

test("质量警告只有明确采用动作才提交", async ({ page }) => {
  const view = writeView(); view.candidate = candidate(); view.candidate.review = status("有修改建议", "可以在阅读建议后决定是否采用。", "warning");
  view.candidate.actions = [action("仍然采用", 32), action("丢弃候选稿", 30)]; view.status = view.candidate.review;
  const tokens: string[] = [];
  await productRoutes(page, { write: () => view, post: async (body, route) => { tokens.push(body.token); view.candidate = undefined; await fulfill(route, {}); } });
  await page.goto(`${projectPath}/write`);
  expect(tokens).toEqual([]);
  await page.getByRole("button", { name: "仍然采用" }).click();
  await expect(page.getByLabel("候选稿", { exact: true })).toHaveCount(0);
  expect(tokens).toEqual([opaque(32)]);
});

for (const [label, token] of [["扩写本章", 21], ["重新生成本章", 22]] as const) {
  test(`${label}保留正式正文，候选经人工确认后更新`, async ({ page }) => {
    const view = writeView(); const original = view.chapter!.body;
    const tokens: string[] = [];
    await productRoutes(page, { write: () => view, post: async (body, route) => { tokens.push(body.token);
      if (body.token === opaque(token)) { view.candidate = candidate(1); view.candidate.body = "修改后的候选正文。"; }
      if (body.token === opaque(31)) { view.chapter!.body = view.candidate!.body; view.candidate = undefined; }
      await fulfill(route, {}); } });
    await page.goto(`${projectPath}/write?chapter=1`);
    await page.getByRole("button", { name: label }).click();
    await expect(page.locator("div.ws-reader__body")).toHaveText(original);
    await expect(page.getByLabel("候选稿", { exact: true })).toContainText("修改后的候选正文");
    await page.getByRole("button", { name: "确认提交" }).click();
    await expect(page.locator("div.ws-reader__body")).toContainText("修改后的候选正文");
    expect(tokens).toEqual([opaque(token), opaque(31)]);
  });
}

test("下一章候选保持自己的章节归属", async ({ page }) => {
  const fixture = await productRoutes(page, { write: (chapter) => {
    const view = writeView(1);
    if (chapter === 2) { view.chapter = undefined; view.candidate = candidate(2); }
    else view.actions = [{ ...action("查看第 2 章候选稿", 40), href: `${projectPath}/write?chapter=2` }];
    return view;
  } });
  await page.goto(`${projectPath}/write?chapter=1`);
  await expect(page.getByLabel("候选稿", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "查看第 2 章候选稿" }).click();
  await expect(page.getByLabel("候选稿", { exact: true })).toContainText("第 2 章候选正文");
  await expectAuthorBoundary(page, fixture.forbidden);
});

test("连续生成参数与停止按钮均由产品表单提供，刷新保留进度", async ({ page }) => {
  const view = writeView();
  view.forms = [{ title: "连续生成", fields: [{ key: opaque(61), label: "计划生成章数", value: "3", type: "number" }], actions: [action("开始连续生成", 60)] }];
  const bodies: unknown[] = [];
  await productRoutes(page, { write: () => view, post: async (body, route) => { bodies.push(body);
    if (body.token === opaque(60)) { view.forms = []; view.status = status("正在写作", "正在生成本批次候选。"); view.actions = [action("停止连续生成", 62), action("重新生成本章", 22, false)]; }
    else { view.actions = []; view.status = status("已停止", "已经保留完成的内容。"); }
    await fulfill(route, {}); } });
  await page.goto(`${projectPath}/write`);
  await page.getByRole("button", { name: "连续生成", exact: true }).click();
  await page.getByLabel("计划生成章数").fill("4");
  await page.getByRole("button", { name: "开始连续生成" }).click();
  await expect(page.getByRole("button", { name: "停止连续生成" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "重新生成本章" })).toBeDisabled();
  await page.getByRole("button", { name: "停止连续生成" }).click();
  await expect(page.getByLabel("正文写作路径")).toContainText("已停止");
  expect(bodies).toEqual([{ token: opaque(60), values: { [opaque(61)]: "4" } }, { token: opaque(62) }]);
});

test("目录加载保留可见正文，加载失败仍保留目录并禁用旧章动作", async ({ page }) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await productRoutes(page, { write: (chapter) => writeView(chapter ?? 1) });
  await page.route("**/product/write?chapter=2", async (route) => { await gate; await fulfill(route, { detail: { message: "暂时无法读取这一章，请重试。" } }, 503); });
  await page.goto(`${projectPath}/write?chapter=1`);
  await expect(page.locator("div.ws-reader__body")).toContainText("第 1 章正文");
  await page.getByRole("link", { name: /第 2 章 ·/ }).click();
  await expect(page.getByRole("button", { name: "重新生成本章" })).toBeDisabled();
  await expect(page.locator("div.ws-reader__body")).toContainText("第 1 章正文");
  release();
  await expect(page.locator("main").getByRole("alert")).toContainText("暂时无法读取这一章");
  await expect(page.getByLabel("章节目录")).toContainText("第2章标题");
  await expect(page.getByRole("button", { name: "重新生成本章" })).toBeDisabled();
});

test("目录搜索与翻页保留，点击可见章节只更新内容", async ({ page }) => {
  await productRoutes(page, { write: (number) => ({ ...writeView(number ?? 160), chapters: Array.from({ length: 160 }, (_, n) => ({ number: n + 1, title: `目录标题${n + 1}`, summary: "摘要" })) }) });
  await page.goto(`${projectPath}/write`);
  await expect(page.getByRole("link", { name: /第 160 章 ·/ })).toBeVisible();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByRole("link", { name: /第 80 章 ·/ })).toBeVisible();
  await page.getByPlaceholder("标题、章节号、摘要").fill("目录标题159");
  await page.getByRole("link", { name: /第 159 章 ·/ }).click();
  await expect(page.locator("div.ws-reader__body")).toContainText("第 159 章正文");
});

test("复制当前章节标题和正文", async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(Navigator.prototype, "clipboard", { configurable: true, get: () => ({ writeText: async (text: string) => { (window as unknown as { copied: string }).copied = text; } }) }); });
  await productRoutes(page, { write: () => writeView(1) });
  await page.goto(`${projectPath}/write?chapter=1`);
  await page.getByRole("button", { name: "复制章节" }).click();
  await expect(page.getByRole("button", { name: "已复制" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { copied: string }).copied)).toBe("第 1 章 第1章标题\n\n第 1 章正文，只属于当前选择。");
});

test("窄屏目录有高度上限，页面不横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 667, height: 882 });
  const view = writeView(1); view.chapters = Array.from({ length: 80 }, (_, n) => ({ number: n + 1, title: `目录标题${n + 1}`, summary: "摘要" }));
  await productRoutes(page, { write: () => view });
  await page.goto(`${projectPath}/write`);
  await expect(page.getByLabel("章节目录")).toBeVisible();
  const dimensions = await page.locator(".ws-chapter-list").evaluate((element) => ({ client: element.clientHeight, scroll: element.scrollHeight }));
  expect(dimensions.client).toBeLessThanOrEqual(440); expect(dimensions.scroll).toBeGreaterThan(dimensions.client);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("下一步规划与已确认状态直接使用服务端产品映射", async ({ page }) => {
  const view = writeView(); view.status = status("需要准备", "请先补齐下一卷规划。", "warning");
  view.actions = [{ ...action("准备下一卷", 70), href: `${projectPath}/build` }, action("生成下一章", 20, false)];
  const fixture = await productRoutes(page, { write: () => view, build: () => buildView() });
  await page.goto(`${projectPath}/write`);
  await expect(page.getByRole("button", { name: "生成下一章" })).toBeDisabled();
  await page.getByRole("link", { name: "准备下一卷" }).click();
  await expect(page.getByRole("heading", { name: "准备故事" })).toBeVisible();
  await expectAuthorBoundary(page, fixture.forbidden);
});


test("硬阻断由服务端禁用确认，页面没有绕过入口", async ({ page }) => {
  const view = writeView(); view.candidate = candidate(1, true); view.status = view.candidate.review;
  view.candidate.actions.find((item) => item.label === "确认提交")!.enabled = false;
  const fixture = await productRoutes(page, { write: () => view });
  await page.goto(`${projectPath}/write`);
  await expect(page.getByRole("button", { name: "确认提交" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "仍然采用" })).toHaveCount(0);
  await expect(page.getByLabel("正文写作路径")).toContainText("需要修改");
  expect(fixture.requests.filter((item) => item.body)).toHaveLength(0);
  await expectAuthorBoundary(page, fixture.forbidden);
});


for (const operation of ["生成下一章", "重新生成本章"]) {
  test(`${operation}完成前离开写作页不会刷新或跳回`, async ({ page }) => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    await productRoutes(page, { build: () => buildView(), write: (number) => writeView(number ?? 1), post: async (_body, route) => { await gate; await fulfill(route, { redirect: `${projectPath}/write?chapter=99` }); } });
    await page.goto(`${projectPath}/write?chapter=1`);
    await page.getByRole("button", { name: operation }).click();
    await page.getByRole("link", { name: "开书构建", exact: true }).click();
    await expect(page.getByRole("heading", { name: "准备故事" })).toBeVisible();
    release();
    await page.waitForTimeout(150);
    await expect(page).toHaveURL(new RegExp("/build$"));
  });
}
