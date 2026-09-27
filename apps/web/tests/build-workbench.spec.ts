import { expect, test } from "@playwright/test";
import { action, buildView, expectAuthorBoundary, fulfill, opaque, productRoutes, projectPath, status } from "./fixtures/creation-product";

test("故事准备只请求产品页面，并以服务端文案与动作展示", async ({ page }, testInfo) => {
  const view = buildView();
  const fixture = await productRoutes(page, { build: () => view });
  await page.goto(`${projectPath}/build`);
  await expect(page.getByRole("heading", { name: "准备故事" })).toBeVisible();
  await expect(page.getByLabel("当前创作阶段")).toBeInViewport();
  await expect(page.getByRole("button", { name: "继续准备故事" })).toBeEnabled();
  expect(fixture.requests.filter((item) => item.body)).toHaveLength(0);
  await expectAuthorBoundary(page, fixture.forbidden);
  await page.screenshot({ path: testInfo.outputPath("build-author-product.png"), fullPage: true });
});

test("创作动作只发送不透明令牌，刷新恢复服务端进度", async ({ page }) => {
  const view = buildView();
  const bodies: unknown[] = [];
  const fixture = await productRoutes(page, { build: () => view, post: async (body, route) => {
    bodies.push(body); view.status = status("准备完成", "现在可以生成第一章候选。", "success");
    view.actions = [{ ...action("前往章节创作", 2), href: `${projectPath}/write` }];
    await fulfill(route, { message: "故事准备完成。" });
  } });
  await page.goto(`${projectPath}/build`);
  await page.getByRole("button", { name: "继续准备故事" }).click();
  await expect(page.getByRole("link", { name: "前往章节创作" })).toBeVisible();
  expect(bodies).toEqual([{ token: opaque(1) }]);
  await page.reload();
  await expect(page.getByLabel("当前创作阶段")).toContainText("准备完成");
  await expectAuthorBoundary(page, fixture.forbidden);
});

test("我来修改使用作者字段，失败保留修改且修复动作不覆盖草稿", async ({ page }) => {
  const view = buildView(); let writes = 0;
  await productRoutes(page, { build: () => view, post: async (body, route) => {
    expect(body).toEqual({ token: opaque(15), values: { [opaque(13)]: "只有暴雨才关闭集市。" } });
    writes += 1;
    if (writes === 1) return fulfill(route, { detail: { message: "请补充规则对人物的影响。", impact: "修改仍保留在编辑区。" } }, 400);
    view.selected!.paragraphs = ["只有暴雨才关闭集市。"];
    await fulfill(route, { message: "修改已保存。" });
  } });
  await page.goto(`${projectPath}/build`);
  await page.getByRole("button", { name: "我来修改" }).click();
  await page.getByLabel("世界规则", { exact: true }).fill("只有暴雨才关闭集市。");
  await expect(page.getByRole("button", { name: "让 AI 修复" })).toBeDisabled();
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("请补充规则对人物的影响");
  await expect(page.getByLabel("世界规则", { exact: true })).toHaveValue("只有暴雨才关闭集市。");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.getByText("只有暴雨才关闭集市。", { exact: true })).toBeVisible();
  expect(writes).toBe(2);
});

test("选择准备内容只使用服务端不透明选择值", async ({ page }) => {
  const view = buildView();
  view.parts.push({ selection: opaque(50), title: "主角目标", status: status("待准备", "确定主角追求什么。") });
  const selected: Array<string | null> = [];
  await productRoutes(page, { build: (selection) => { selected.push(selection); return selection === opaque(50) ? { ...view, selected: { selection, title: "主角目标", paragraphs: ["查清遗嘱背后的旧账。"], issues: [], actions: [] } } : view; } });
  await page.goto(`${projectPath}/build`);
  await page.getByRole("button", { name: /主角目标/ }).click();
  await expect(page.getByLabel("当前准备内容")).toContainText("查清遗嘱背后的旧账");
  expect(selected).toEqual([null, opaque(50)]);
});

test("长审查建议可展开，页面不提供工程详情入口", async ({ page }) => {
  const view = buildView();
  view.selected!.issues = Array.from({ length: 5 }, (_, n) => ({ message: `需要补充第${n + 1}条世界规则。`, suggestion: "说明它如何影响人物。", tone: "warning" as const }));
  const fixture = await productRoutes(page, { build: () => view });
  await page.goto(`${projectPath}/build`);
  await expect(page.getByText("需要补充第5条世界规则。", { exact: true })).not.toBeVisible();
  await page.getByText("查看全部审查建议（5）", { exact: true }).click();
  await expect(page.getByText("需要补充第5条世界规则。", { exact: true })).toBeVisible();
  await expect(page.locator("pre")).toHaveCount(0);
  await expectAuthorBoundary(page, fixture.forbidden);
});

test("页面按服务端刷新提示更新，不推断内部运行状态", async ({ page }) => {
  const view = buildView(); let reads = 0;
  view.refresh_after_ms = 500;
  await productRoutes(page, { build: () => { reads += 1; return reads < 2 ? view : { ...view, refresh_after_ms: undefined, status: status("准备完成", "可以开始创作。", "success") }; } });
  await page.goto(`${projectPath}/build`);
  await expect(page.getByLabel("当前创作阶段")).toContainText("准备完成");
  expect(reads).toBeGreaterThanOrEqual(2);
});

test("读取失败只显示产品错误且可重新读取", async ({ page }) => {
  const fixture = await productRoutes(page, { build: () => buildView() });
  let broken = true;
  await page.route("**/product/build", async (route) => broken ? fulfill(route, { detail: "internal.preflight.private" }, 500) : route.fallback());
  await page.goto(`${projectPath}/build`);
  await expect(page.locator("main").getByRole("alert")).toContainText("这次操作未能完成");
  await expect(page.locator("main").getByRole("alert")).not.toContainText("internal");
  broken = false;
  await page.getByRole("button", { name: "重新读取" }).click();
  await expect(page.getByLabel("当前创作阶段")).toBeVisible();
  await expectAuthorBoundary(page, fixture.forbidden);
});


test("编辑期间停止自动刷新，取消一个表单不会解除其他草稿保护", async ({ page }) => {
  const view = buildView(); let reads = 0;
  view.refresh_after_ms = 500;
  view.forms = [{ title: "补充创作要求", fields: [{ key: opaque(80), label: "创作要求", value: "", type: "textarea" }], actions: [action("保存创作要求", 81)] }];
  await productRoutes(page, { build: () => { reads += 1; return view; } });
  await page.goto(`${projectPath}/build`);
  await page.getByRole("button", { name: "我来修改" }).click();
  const readsAtEdit = reads;
  await page.waitForTimeout(700);
  expect(reads).toBe(readsAtEdit);
  await page.getByLabel("世界规则", { exact: true }).fill("修改中的设定。");
  await page.getByRole("button", { name: "补充创作要求" }).click();
  await page.getByLabel("创作要求", { exact: true }).fill("先处理主角动机。");
  await page.getByLabel("补充创作要求", { exact: true }).getByRole("button", { name: "取消修改" }).click();
  await expect(page.getByRole("button", { name: "继续准备故事" })).toBeDisabled();
  await expect(page.getByLabel("世界规则", { exact: true })).toHaveValue("修改中的设定。");
  await page.getByLabel("我来修改", { exact: true }).getByRole("button", { name: "取消修改" }).click();
  await expect(page.getByRole("button", { name: "继续准备故事" })).toBeEnabled();
});
