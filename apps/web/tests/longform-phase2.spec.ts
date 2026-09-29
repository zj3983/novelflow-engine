import { expect, test, type Page, type Route } from "@playwright/test";

const BOOK_ID = "file:phase2-workspace-regression";
const BODY = Array.from({ length: 45 }, (_, index) => `正文段落 ${index + 1}，记录渡口的变化与人物选择。`).join("\n\n");

function action(command: string, label: string) {
  return { command, token: `phase2-token-${command}`.padEnd(64, "x").slice(0, 64), label, enabled: true };
}

function workspace(candidate = false) {
  const chapters = Array.from({ length: 70 }, (_, index) => ({
    number: index + 1,
    title: index === 2 ? "雨夜来信" : index === 69 ? "船印回响" : `渡口记录 ${index + 1}`,
    body: index === 2 ? BODY : `第${index + 1}章正文。`,
  }));
  const book: Record<string, any> = {
    id: BOOK_ID, title: "阶段二交互回归", genre: "奇幻", idea: "核对阶段二页面行为。",
    requirements: "不改写已确认事实。", future: "追查船印来源。", direction: "沿河追查旧案。",
    plan: "查明船印来源，并找到留下线索的人。", planAdopted: true, planningVolume: 2,
    chapters, notice: "", busy: false, canRetry: false, nextVolume: false,
    volumes: [
      { number: 1, title: "旧渡口", start: 1, end: 50, goal: "找到第一条线索。", label: "已完成" },
      { number: 2, title: "河上暗潮", start: 51, end: 100, goal: "查明船印来源。", label: "当前准备" },
    ],
    planning: {
      editable: true,
      overall: { direction: "沿河追查旧案。", endingGoal: "兄弟重逢。", previousConnection: "第70章发现半枚船印。" },
      currentVolume: 2,
      volumes: [
        { number: 1, title: "旧渡口", startChapter: 1, endChapter: 50, goal: "找到第一条线索。", mainConflict: "封锁码头。", characterChanges: [], endingTurn: "", statusLabel: "已完成", editable: false },
        { number: 2, title: "河上暗潮", startChapter: 51, endChapter: 100, goal: "查明船印来源。", mainConflict: "线索互相矛盾。", characterChanges: ["主角开始信任同伴"], endingTurn: "", statusLabel: "当前准备", editable: true },
      ],
      upcomingChapters: [{ number: 71, title: "船印回响", goal: "找到第二条线索。", conflict: "证词互相矛盾。", progression: "前往旧档案馆。", foreshadowing: ["半枚船印"] }],
      authorReminders: [],
    },
    actions: {
      plan: action("plan", "保存规划修改"),
      "dissection-candidate": action("dissection-candidate", "体检待确认候选"),
      "dissection-chapter": action("dissection-chapter", "体检当前确认章节"),
      "dissection-reference": action("dissection-reference", "拆解参考书片段"),
      "ai-edit": action("ai-edit", "让 AI 修改"),
    },
    dissectionView: {
      modeLabel: "本书章节体检", selectedChapter: 70, candidateSourceToken: candidate ? "candidate-source-v1" : null,
      statusLabel: "尚未生成报告", report: null, candidateReport: null, reportIsReadOnly: true,
      actions: {
        inspectChapter: action("dissection-chapter", "体检当前确认章节"),
        inspectCandidate: action("dissection-candidate", "体检待确认候选"),
        inspectReference: action("dissection-reference", "拆解参考书片段"),
      },
    },
    foreshadowingView: { items: [], save: action("foreshadowing", "保存伏笔") },
    dynamicWorld: {
      currentSnapshot: { chapter: 70, entries: [{ label: "当前焦点", value: "追查船印" }] },
      availableChapters: [{ number: 70, title: "船印回响" }], selectedChapter: 70,
      chapterRecord: { chapter: 70, summary: "主角得到半枚船印。", nextChapterInformation: [{ text: "旧档案馆将在明日开放。", whoCanKnow: "持有通行证的人" }] },
      preparationInformation: { sourceChapter: 70, entries: [{ text: "旧档案馆将在明日开放。", whoCanKnow: "持有通行证的人" }] },
    },
  };
  if (candidate) book.candidate = { number: 71, title: "船印回响", body: "待检查的第71章候选正文。", label: "等待确认", canConfirm: true, needsCheck: false, checking: false, pastDrafts: [] };
  return {
    mode: "live", books: [book], bookId: BOOK_ID, page: "writing", selectedChapter: 3,
    showNew: false, storyTab: "人物", person: "林照", storageWarning: "", actions: {},
  };
}

async function installMock(page: Page, withCandidate = false) {
  const commands: Record<string, any>[] = [];
  await page.route("**/author-workspace/commands", async (route: Route) => {
    const body = route.request().postDataJSON() as { command: Record<string, any> };
    commands.push(body.command);
    const product = body.command.type === "dissection-candidate" ? {
      modeLabel: "待确认候选体检", candidateSourceToken: "candidate-source-v1", sourceToken: "candidate-source-v1",
      report: { statusLabel: "体检完成", sections: [{ title: "下一版改法", items: ["先核对旧档案馆开放时间。"] }] },
    } : undefined;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ bookId: BOOK_ID, message: "已保存。", ...(product ? { product } : {}) }) });
  });
  await page.route("**/author-workspace?**", async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(workspace(withCandidate)) });
  });
  return commands;
}

test("chapter search filters the directory, keeps the prose position, and copy leaves the chapter unchanged", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const commands = await installMock(page);
  await page.goto(`/workspace?page=writing&book=${encodeURIComponent(BOOK_ID)}&chapter=3`);
  const prose = page.getByRole("main", { name: "正文阅读区" });
  await expect(page.getByRole("heading", { name: "第3章　雨夜来信" })).toBeVisible();
  await prose.evaluate((node) => { node.scrollTop = 260; });
  await page.getByLabel("搜索章节").fill("船印回响");
  await expect(page.getByText("找到 2 个章节")).toBeVisible();
  await expect(page.getByRole("heading", { name: "第3章　雨夜来信" })).toBeVisible();
  await expect.poll(() => prose.evaluate((node) => node.scrollTop)).toBe(260);
  await page.getByRole("button", { name: "复制当前章节正文" }).click();
  await expect(page.getByRole("status")).toContainText("已复制第3章正文");
  expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n")).toBe(BODY);
  expect(commands).toHaveLength(0);
  await page.getByLabel("章节目录").getByRole("button", { name: /第70章/ }).click();
  await expect(page.getByRole("heading", { name: "第70章　船印回响" })).toBeVisible();
});

test("planning edits submit structured fields and related foreshadowing opens its story tab", async ({ page }) => {
  const commands = await installMock(page);
  await page.goto(`/workspace?page=planning&book=${encodeURIComponent(BOOK_ID)}`);
  await page.getByRole("button", { name: "调整规划内容" }).click();
  await expect(page.getByLabel("前文衔接")).toHaveAttribute("readonly", "");
  await page.getByLabel("全书方向").fill("沿河追查被抹去的旧账。");
  await page.getByLabel("第2卷主要冲突").fill("新证据推翻了旧证词。");
  await page.getByRole("button", { name: "保存规划修改" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0]).toMatchObject({
    type: "plan",
    patch: {
      overall: { direction: "沿河追查被抹去的旧账。" },
      volumes: [{ number: 1 }, { number: 2, mainConflict: "新证据推翻了旧证词。" }],
    },
  });
  await page.getByLabel("编辑全书规划").getByRole("button", { name: "查看伏笔线索" }).click();
  await expect(page).toHaveURL(/page=story.*tab=%E4%BC%8F%E7%AC%94%E7%BA%BF%E7%B4%A2/);
  await expect(page.getByRole("heading", { name: "伏笔线索" })).toBeVisible();
});

test("world preparation information exposes who can know it", async ({ page }) => {
  await installMock(page);
  await page.goto(`/workspace?page=writing&book=${encodeURIComponent(BOOK_ID)}&chapter=3`);
  await expect(page.getByText("下一章角色可获知")).toBeVisible();
  await expect(page.getByText("旧档案馆将在明日开放。").first()).toBeVisible();
  await expect(page.getByText(/可知范围：持有通行证的人/)).toBeVisible();
  await page.getByRole("button", { name: "查看第70章世界变化" }).click();
  await expect(page).toHaveURL(/page=story.*tab=%E4%B8%96%E7%95%8C%E8%A7%84%E5%88%99/);
  await page.getByRole("button", { name: "故事设定" }).click();
  await page.getByRole("button", { name: "世界规则" }).click();
  await expect(page.getByRole("heading", { name: "第70章 · 主角得到半枚船印。" })).toBeVisible();
});

test("candidate inspection survives refresh and its report source token is sent with AI edit", async ({ page }) => {
  const commands = await installMock(page, true);
  await page.goto(`/workspace?page=writing&book=${encodeURIComponent(BOOK_ID)}&chapter=70`);
  await page.getByRole("button", { name: "体检待确认候选" }).click();
  await expect(page.getByText("先核对旧档案馆开放时间。")).toBeVisible();
  await page.getByRole("button", { name: "使用报告修改当前候选" }).click();
  const editor = page.getByRole("dialog", { name: "让 AI 修改" });
  await expect(editor.getByLabel("修改要求")).toContainText("先核对旧档案馆开放时间。");
  await editor.getByRole("button", { name: "修改并重新检查" }).click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1]).toMatchObject({ type: "ai-edit", dissectionSourceToken: "candidate-source-v1" });
});
