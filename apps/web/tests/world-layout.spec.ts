import { expect, test } from "@playwright/test";

for (const width of [1440, 768, 360]) {
  test(`世界观分区保留草稿并适配 ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    let writes = 0;
    const project = {
      project_id: "file:world-layout", title: "雾港纪事", storage_source: "file",
      world_summary: "潮汐退去后，一座被遗忘的城市重新显露。", active_story_id: null,
      world_blueprint: { genre_plugin_ids: ["game_webnovel"], premise: "每次潮汐都会改变城市的道路。", world_rules: ["灯塔熄灭后不可出港。"] },
      character_profiles: [], relationship_graph: [], enabled_skill_ids: [], author_constraints: [], branches: [],
    };
    await page.route("**/file-projects/file%3Aworld-layout**", async route => {
      if (route.request().method() !== "GET") writes++;
      await route.fulfill({ json: route.request().url().includes("world-build-jobs") ? null : project });
    });
    await page.goto("/projects/file%3Aworld-layout/world");
    const nav = page.getByRole("navigation", { name: "世界观分类" });
    await expect(page.getByRole("heading", { name: "世界背景", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "世界规则", exact: true })).toBeHidden();
    await page.getByRole("textbox", { name: /项目摘要/ }).fill("尚未保存的世界摘要");
    await nav.getByRole("button", { name: /世界规则/ }).click();
    await page.getByRole("textbox", { name: /基础规则/ }).fill("尚未保存的基础规则");
    const growth = page.locator('details[aria-labelledby="progression-world-rules-title"]');
    await expect(growth).not.toHaveAttribute("open", "");
    await growth.locator("summary").click();
    await page.getByRole("textbox", { name: /等级、职业与技能/ }).fill("未保存的职业设定");
    await nav.getByRole("button", { name: /世界背景/ }).click();
    await expect(page.getByRole("textbox", { name: /项目摘要/ })).toHaveValue("尚未保存的世界摘要");
    await nav.getByRole("button", { name: /世界规则/ }).click();
    await expect(page.getByRole("textbox", { name: /基础规则/ })).toHaveValue("尚未保存的基础规则");
    await expect(page.getByRole("textbox", { name: /等级、职业与技能/ })).toHaveValue("未保存的职业设定");
    for (const label of ["地点与阵营", "装备图鉴", "怪物图鉴", "构建记录", "世界背景"]) {
      await nav.getByRole("button", { name: new RegExp(label) }).click();
      await expect(nav.getByRole("button", { name: new RegExp(label) })).toHaveAttribute("aria-current", "page");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
    expect(writes).toBe(0);
    await page.screenshot({ path: `test-results/world-layout-${width}.png`, fullPage: true });
  });
}
