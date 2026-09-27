import { expect, test, type Page } from "@playwright/test";

// Stage A only: browser-local synthetic adapter, no API/model integration claim.
test.use({ viewport: { width: 1487, height: 1058 } });
async function openRiver(page: Page) {
  await page.goto("/prototype/longform");
  await page.getByRole("article").filter({ hasText: "渡河人" }).getByRole("button", { name: "继续写作" }).click();
}
async function aiRepair(page: Page) {
  await page.getByRole("button", { name: "让 AI 修改", exact: true }).click();
  await page.getByRole("button", { name: "修改并重新检查" }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeEnabled();
}
async function scenario(page: Page, name: string) {
  await page.getByRole("button", { name: "演示场景", exact: true }).click();
  await page.getByRole("button", { name, exact: true }).click();
}

test("新建、选择方向、调整并采纳规划、第一章人工确认", async ({ page }) => {
  const forbidden: string[] = [];
  page.on("request", r => { if (/file-projects|\/api\/|capabilities|openai\.com/.test(r.url())) forbidden.push(r.url()); });
  await page.goto("/prototype/longform");
  await expect(page.getByLabel("目标篇幅（万字）")).toHaveValue("90");
  await expect(page.getByLabel("每章目标字数")).toHaveValue("3000");
  await page.getByLabel("暂定书名").fill("江上新书");
  await page.getByLabel("故事想法").fill("一个摆渡少年寻找失踪家人的故事。");
  await page.getByLabel("必须遵守的写作要求").fill("不突然增加主角能力。");
  await page.getByRole("button", { name: "开始准备故事" }).click();
  await page.getByRole("button", { name: /沿河追寻/ }).click();
  await page.getByRole("button", { name: "调整规划", exact: true }).click();
  await page.getByLabel("修改内容").fill("找到旧信；学会合作；发现信中另有地址");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.getByText("规划已准备好，待你采纳")).toBeVisible();
  await page.getByRole("button", { name: "采纳本卷规划，开始第1章" }).click();
  await expect(page.getByRole("heading", { name: /第1章/ })).toBeVisible();
  await page.getByRole("button", { name: "只确认本章", exact: true }).click();
  await expect(page.getByText("已确认至第1章", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("正式章节 · 只读回看")).toBeVisible();
  expect(forbidden).toEqual([]);
});

test("硬冲突不能确认，手工改稿保留旧稿且必须重新检查", async ({ page }) => {
  await openRiver(page);
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "我来改写" }).click();
  await page.getByLabel("修改候选正文").fill("沈砚推开门，桌上只剩半封旧信。\n\n他把信收好，决定沿河寻找新的线索。");
  await page.reload();
  await expect(page.getByLabel("修改候选正文")).toContainText("桌上只剩半封旧信");
  await page.getByRole("button", { name: "保存改稿" }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: /查看保留的旧稿/ }).click();
  await expect(page.getByRole("dialog")).toContainText("看见了十年前离开的兄长");
  await page.getByRole("button", { name: "关闭对话框" }).click();
  await page.getByRole("button", { name: "重新检查", exact: true }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "只确认本章", exact: true }).click();
  await expect(page.getByText("已确认至第51章", { exact: true })).toBeVisible();
});

test("AI 改稿检查失败后保留改稿，可重新检查恢复", async ({ page }) => {
  await openRiver(page);
  await scenario(page, "下次检查失败");
  await page.getByRole("button", { name: "让 AI 修改", exact: true }).click();
  await page.getByRole("button", { name: "修改并重新检查" }).click();
  await expect(page.getByText("这次检查没有完成，改稿已保留。请重新检查后再确认。")).toBeVisible();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeDisabled();
  await expect(page.getByRole("main", { name: "正文阅读区" })).toContainText("来客早已离去");
  await page.reload();
  await page.getByRole("button", { name: "重试检查" }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeEnabled();
});

test("确认成功后下一章失败，不回滚、不重复确认，可重试", async ({ page }) => {
  await openRiver(page); await aiRepair(page);
  await scenario(page, "确认后续写失败");
  await page.getByRole("button", { name: "确认并继续下一章" }).click();
  await expect(page.getByText("本章已保存，下一章尚未开始。可以稍后重试。")).toBeVisible();
  await expect(page.getByText("已确认至第51章", { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "重试生成" }).click();
  await expect(page.getByRole("heading", { name: /第52章/ })).toBeVisible();
  await expect(page.getByText("已确认至第51章", { exact: true })).toBeVisible();
});

test("检查进行中刷新，不自动重启；主动重试才恢复", async ({ page }) => {
  await openRiver(page);
  await page.getByRole("button", { name: "让 AI 修改", exact: true }).click();
  await page.getByRole("button", { name: "修改并重新检查" }).click();
  await page.reload();
  await expect(page.getByText(/上次操作已中断/)).toBeVisible();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "重试检查" }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeEnabled();
});

test("卷末通过采纳新卷规划继续，前卷保留", async ({ page }) => {
  await openRiver(page); await scenario(page, "体验卷末");
  await page.getByRole("button", { name: "准备下一卷", exact: true }).click();
  await expect(page.getByText("规划已准备好，待你采纳")).toBeVisible();
  await page.getByRole("button", { name: "采纳本卷规划，开始第51章" }).click();
  await expect(page.getByRole("heading", { name: /第51章/ })).toBeVisible();
  await page.getByRole("button", { name: "故事设定", exact: true }).click();
  await page.getByRole("button", { name: "查看相关章节" }).last().click();
  await expect(page.getByRole("heading", { name: "第50章 渡口别离" })).toBeVisible();
  await expect(page.getByRole("main", { name: "正文阅读区" })).toContainText("他还不知道兄长的去向");
});

test("作者要求变更使候选重新等待检查；旧事实只有回看", async ({ page }) => {
  await openRiver(page); await aiRepair(page);
  await page.getByRole("button", { name: "故事设定", exact: true }).click();
  await page.getByRole("button", { name: "创作要求", exact: true }).click();
  await page.getByRole("button", { name: "修改作者要求" }).click();
  await page.getByLabel("修改内容").fill("主角不可突然掌握新能力。");
  await page.getByRole("button", { name: "保存修改" }).click();
  await page.getByRole("button", { name: "写作", exact: true }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "重新检查", exact: true }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeEnabled();
});

test("软建议需要明确选择，重复确认不会增加两章", async ({ page }) => {
  await openRiver(page); await aiRepair(page);
  await scenario(page, "体验可选建议");
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "保留原文，不采用此建议" }).click();
  await page.getByRole("button", { name: "只确认本章", exact: true }).dblclick();
  await expect(page.getByText("已确认至第51章", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("已确认至第51章", { exact: true })).toBeVisible();
});

test("归档与恢复、旧作品目标未设置、重置仅影响原型", async ({ page }) => {
  await page.goto("/prototype/longform");
  await expect(page.getByRole("article").filter({ hasText: "山海旧事" })).toContainText("目标篇幅未设置");
  await page.getByRole("article").filter({ hasText: "南城来信" }).getByRole("button", { name: "归档", exact: true }).click();
  await page.getByRole("button", { name: "查看已归档作品" }).click();
  await page.getByRole("button", { name: "恢复作品" }).click();
  await page.getByRole("button", { name: "返回我的作品" }).click();
  await expect(page.getByRole("article").filter({ hasText: "南城来信" })).toBeVisible();
  await page.getByRole("button", { name: "重置演示", exact: true }).click();
  await page.getByRole("button", { name: "确认重置演示" }).click();
  await expect(page.getByRole("article")).toHaveCount(3);
});

test("四页窄屏操作，没有横向溢出或工程详情入口", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openRiver(page);
  for (const name of ["写作", "全书规划", "故事设定"] as const) {
    await page.getByRole("button", { name, exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await expect(page.locator("body")).not.toContainText(/artifact|revision|stale|validation_failed|provenance|preflight|raw JSON|provider protocol/);
  }
  await page.getByRole("button", { name: "写作", exact: true }).click();
  await aiRepair(page);
  await page.getByRole("button", { name: "只确认本章", exact: true }).click();
  await expect(page.getByText("已确认至第51章", { exact: true })).toBeVisible();
});

test("目录操作只滚动目录，不移动正文阅读位置", async ({ page }) => {
  await openRiver(page);
  const prose = page.getByRole("main", { name: "正文阅读区" });
  await prose.evaluate(el => { el.scrollTop = 80; });
  const before = await prose.evaluate(el => el.scrollTop);
  await page.getByRole("button", { name: "第1卷 渡口", exact: true }).click();
  expect(await prose.evaluate(el => el.scrollTop)).toBe(before);
});

test("另一标签页变更后，旧页面提示刷新并拒绝覆盖", async ({ page, context }) => {
  await openRiver(page);
  const other = await context.newPage();
  await other.goto("/prototype/longform");
  await other.getByRole("button", { name: "故事设定", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "演示已在另一标签页更新" })).toBeVisible();
  await expect(page.getByRole("button", { name: "让 AI 修改", exact: true })).toBeDisabled();
});

test("首次生成失败后可以重试，不产生正式章节", async ({ page }) => {
  await openRiver(page); await scenario(page, "体验卷末");
  await page.getByRole("button", { name: "准备下一卷", exact: true }).click();
  await scenario(page, "下次生成失败");
  await page.getByRole("button", { name: "采纳本卷规划，开始第51章" }).click();
  await expect(page.getByText("这次生成没有完成，已确认正文未改变。可以重试。")).toBeVisible();
  await expect(page.getByText("已确认至第50章", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "重试生成" }).click();
  await expect(page.getByRole("heading", { name: /第51章/ })).toBeVisible();
});

test("规划改变后旧采纳失效，候选也要重检", async ({ page }) => {
  await openRiver(page); await aiRepair(page);
  await page.getByRole("button", { name: "全书规划", exact: true }).click();
  await page.getByRole("button", { name: "调整规划", exact: true }).click();
  await page.getByLabel("修改内容").fill("先寻找渡口证人；学会信任；留下新的线索");
  await page.getByRole("button", { name: "保存修改" }).click();
  await page.getByRole("button", { name: "写作", exact: true }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "全书规划", exact: true }).click();
  await page.getByRole("button", { name: "采纳规划，回到候选稿" }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "重新检查", exact: true }).click();
  await expect(page.getByRole("button", { name: "只确认本章", exact: true })).toBeEnabled();
});
