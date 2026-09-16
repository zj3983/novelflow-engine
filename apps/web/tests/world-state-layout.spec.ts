import { expect, test } from "@playwright/test";

for (const width of [1440, 768, 360]) {
  test(`世界状态分类、折叠与章节选择适配 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    let writes = 0;
    const project = { project_id: "file:state-layout", title: "雾港纪事", active_story_id: "file:state-layout", storage_source: "file", world_blueprint: {}, author_constraints: [], character_profiles: [], branches: [] };
    const overview = {
      story_id: project.project_id, storage_source: "file", current_chapter: 2,
      world_snapshot: { current_focus: "追查消失的航船", time_state: { current_scene_time: "第二章章末" } },
      continuity_facts: [{ text: "灯塔每晚熄灭一次。", source_chapter: 1, status: "active" }, { text: "商会封锁了旧港。", source_chapter: 2, status: "active" }],
      chapters: [1, 2].map(n => ({ chapter_number: n, chapter_title: n === 1 ? "灯塔熄灭" : "旧港封锁", has_simulation: true })),
    };
    await page.route("**/file-projects/file%3Astate-layout", route => route.fulfill({ json: project }));
    await page.route("**/file-stories/file%3Astate-layout/**", route => {
      if (route.request().method() !== "GET") writes++;
      const url = route.request().url();
      const n = Number(url.split("/").pop());
      return route.fulfill({ json: url.endsWith("overview") ? overview : {
        chapter_number: n, chapter_title: n === 1 ? "灯塔熄灭" : "旧港封锁",
        simulation_status: { world_pulse: { latest: { summary: `第 ${n} 章：封港消息正在扩散。`, public_traces: ["码头贴出了封港告示。"], pressure_points: ["出港的时间越来越少。"], background_events: ["巡逻队正在暗中集结。"], hidden_state: { actor: "商会", action: "调集人手" }, market_order_book: { sell_pressure: "物资价格上涨" } } } },
      } });
    });
    await page.goto("/projects/file%3Astate-layout/sim");
    const nav = page.getByRole("navigation", { name: "世界状态分类" });
    await expect(page.getByText("第 2 章响应记录")).toBeVisible();
    await expect(page.getByText("码头贴出了封港告示。", { exact: true })).toBeVisible();
    await expect(page.getByText("巡逻队正在暗中集结。", { exact: true })).toBeHidden();
    await page.locator("summary").filter({ hasText: "后台变化" }).click();
    await expect(page.getByText("巡逻队正在暗中集结。", { exact: true })).toBeVisible();
    await page.getByLabel("响应章节").selectOption("1");
    await expect(page.getByText("第 1 章响应记录")).toBeVisible();
    await nav.getByRole("button", { name: /最新世界快照/ }).click();
    await expect(page.getByText("当前焦点: 追查消失的航船", { exact: true })).toBeVisible();
    await expect(page.getByText("第 1 章响应记录")).toBeHidden();
    await nav.getByRole("button", { name: /已确认事实/ }).click();
    await page.getByRole("searchbox", { name: "搜索已确认事实" }).fill("灯塔");
    await expect(page.getByText("灯塔每晚熄灭一次。", { exact: true })).toBeVisible();
    await expect(page.getByText("商会封锁了旧港。", { exact: true })).toHaveCount(0);
    await nav.getByRole("button", { name: /章节响应/ }).click();
    await expect(page.getByLabel("响应章节")).toHaveValue("1");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(writes).toBe(0);
    await page.screenshot({ path: `test-results/world-state-${width}.png`, fullPage: true });
  });
}
