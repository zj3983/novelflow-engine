import { expect, test, type Page, type Route } from "@playwright/test";

const BOOK_ID = "file:author-tools-regression";
const INITIAL_HISTORY = "幼时曾共同守船";
const CORS_HEADERS = {
  "access-control-allow-origin": "http://127.0.0.1:3100",
  "access-control-allow-credentials": "true",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type",
  "access-control-allow-private-network": "true",
};

type CommandRecord = { bookId: string; command: Record<string, unknown>; token: string };
type MockState = { selectedModuleIds: string[]; relationshipState: string };

function action(command: string, label: string) {
  return { command, token: `token:${command}`, label, enabled: true };
}

function createWorkspace(state: MockState) {
  const commands = {
    relationships: action("relationships", "保存人物关系"),
    "writing-abilities": action("writing-abilities", "保存本书写作能力"),
    "template-project-writer": action("template-project-writer", "保存为本书设置"),
    "template-global-writer": action("template-global-writer", "更新全局模板"),
    "template-restore-writer": action("template-restore-writer", "恢复使用全局模板"),
    "template-check-writer": action("template-check-writer", "普通检查"),
    "template-deep-check-writer": action("template-deep-check-writer", "深度检查"),
    "synopsis-save": action("synopsis-save", "保存作品简介"),
    "synopsis-generate": action("synopsis-generate", "生成作品简介"),
    "cover-generate": action("cover-generate", "生成封面"),
    "type-save": action("type-save", "保存作品类型"),
    "style-save": action("style-save", "保存文风"),
  };
  const moduleIds = state.selectedModuleIds;
  const book = {
    id: BOOK_ID,
    title: "交互语义回归书",
    genre: "奇幻",
    idea: "验证作者工具保存语义。",
    requirements: "",
    future: "",
    direction: "",
    plan: "",
    planAdopted: true,
    planningVolume: 1,
    chapters: [],
    notice: "",
    busy: false,
    canRetry: false,
    nextVolume: false,
    people: [
      { name: "林照", role: "主角", description: "", facts: [], performance: [] },
      { name: "陆遥", role: "同伴", description: "", facts: [], performance: [] },
    ],
    actions: commands,
    bookDetails: {
      title: "交互语义回归书",
      synopsis: "旧渡口的灯火每逢雨夜便会熄灭。",
      synopsisTags: ["旧案", "渡口", "奇幻", "伙伴"],
      coverAvailable: false,
      synopsisStatusLabel: "已有简介",
      coverStatusLabel: "尚无封面",
      novelTypeId: "",
      novelTypeOptions: [],
      writingStyle: "",
      writingStyleOptions: [],
      actions: {
        saveType: commands["type-save"],
        saveStyle: commands["style-save"],
        saveSynopsis: commands["synopsis-save"],
        generateSynopsis: commands["synopsis-generate"],
        generateCover: commands["cover-generate"],
      },
    },
    relationshipView: {
      items: [{
        source: "林照",
        target: "陆遥",
        relationship: "旧识",
        history: INITIAL_HISTORY,
        currentState: state.relationshipState,
        sharedInterestOrConflict: "寻找失踪的船主",
        trust: 42,
        tension: 30,
      }],
      save: commands.relationships,
    },
    writingTemplatesView: {
      templates: [{
        id: "writer",
        title: "整章正文写作",
        purpose: "正文写作",
        applicabilityLabel: "全部作品",
        activeForBook: true,
        content: "保留已经确认的事实。",
        placeholders: [],
        sourceLabel: "本书覆盖",
        usesBookOverride: true,
        actions: {
          saveProject: commands["template-project-writer"],
          saveGlobal: commands["template-global-writer"],
          restoreGlobal: commands["template-restore-writer"],
          check: commands["template-check-writer"],
          deepCheck: commands["template-deep-check-writer"],
        },
      }],
    },
    writingAbilitiesView: {
      packs: [{
        id: "demo-pack",
        name: "演示写作包",
        description: "按需选择具体模块。",
        available: true,
        selected: moduleIds.length > 0,
        modules: [
          { id: "root", title: "根写作能力", purpose: "包入口说明", selected: moduleIds.includes("demo-pack::root") },
          { id: "scene-craft", title: "场景拆解", purpose: "组织动作和场景变化", selected: moduleIds.includes("demo-pack::scene-craft") },
          { id: "dialogue", title: "对话节奏", purpose: "控制台词节奏", selected: moduleIds.includes("demo-pack::dialogue") },
        ],
      }],
      selectionModeLabel: "按模块选择",
      save: commands["writing-abilities"],
      managementLabel: "管理写作能力库",
    },
  };
  return {
    page: "story",
    bookId: BOOK_ID,
    storyTab: "人物",
    person: "林照",
    selectedChapter: undefined,
    books: [book],
    recycleBin: [],
    showNew: false,
    storageWarning: "",
  };
}

async function installWorkspaceMock(page: Page) {
  const state: MockState = { selectedModuleIds: [], relationshipState: "暂时合作" };
  const commands: CommandRecord[] = [];
  await page.route("**/author-workspace**", async (route: Route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS_HEADERS });
      return;
    }
    await route.fulfill({
      status: 200,
      headers: CORS_HEADERS,
      contentType: "application/json",
      body: JSON.stringify(createWorkspace(state)),
    });
  });
  await page.route("**/author-workspace/commands", async (route: Route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS_HEADERS });
      return;
    }
    const body = request.postDataJSON() as CommandRecord;
    commands.push(body);
    if (body.command.type === "writing-abilities") {
      state.selectedModuleIds = body.command.moduleIds as string[];
    }
    if (body.command.type === "relationships") {
      state.relationshipState = (body.command.items as Array<Record<string, string>>)[0].current_state;
    }
    await route.fulfill({
      status: 200,
      headers: CORS_HEADERS,
      contentType: "application/json",
      body: JSON.stringify({ bookId: BOOK_ID, message: "已保存。" }),
    });
  });
  return commands;
}

async function openWorkspace(page: Page, section: "story" | "books" = "story") {
  await page.goto(`/workspace?page=${section}&book=${encodeURIComponent(BOOK_ID)}`);
  await expect(page.getByRole("navigation", { name: "主要导航" })).toBeVisible();
}

test("module selection derives package IDs from selected modules and clears the package when its last module is disabled", async ({ page }) => {
  const commands = await installWorkspaceMock(page);
  await openWorkspace(page);
  await page.getByRole("button", { name: "创作要求" }).click();

  const sceneModule = page.getByRole("checkbox", { name: /场景拆解/ });
  await sceneModule.check();
  await page.getByRole("button", { name: "保存本书写作能力" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].command).toMatchObject({
    type: "writing-abilities",
    packIds: ["demo-pack"],
    moduleIds: ["demo-pack::scene-craft"],
  });

  await expect(sceneModule).toBeChecked();
  await sceneModule.uncheck();
  await page.getByRole("button", { name: "保存本书写作能力" }).click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1].command).toMatchObject({ type: "writing-abilities", packIds: [], moduleIds: [] });
});

test("existing relationship history is visibly read-only while current state remains editable", async ({ page }) => {
  const commands = await installWorkspaceMock(page);
  await openWorkspace(page);

  const history = page.getByLabel("关系来源或历史（只读）");
  await expect(history).toHaveAttribute("readonly", "");
  await expect(history).toHaveValue(INITIAL_HISTORY);
  await page.getByLabel("当前状态").fill("暂时合作，但仍互相试探");
  await page.getByRole("button", { name: "保存人物关系" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].command.items).toMatchObject([{
    origin: INITIAL_HISTORY,
    current_state: "暂时合作，但仍互相试探",
    shared_interest_or_conflict: "寻找失踪的船主",
  }]);
  await expect(page.getByText(/已有关系的来源或历史在创建后只读/)).toBeVisible();
  await expect(history).toHaveValue(INITIAL_HISTORY);
});

test("restoring a project template override has a separate project-only confirmation", async ({ page }) => {
  const commands = await installWorkspaceMock(page);
  await openWorkspace(page);
  await page.getByRole("button", { name: "创作要求" }).click();

  const globalConfirmation = page.getByRole("checkbox", { name: "我确认修改全局模板；使用全局模板的其他作品会受到影响" });
  const restoreConfirmation = page.getByRole("checkbox", { name: "我确认只移除本书的项目覆盖；全局模板和其他作品不会改变" });
  const updateGlobal = page.getByRole("button", { name: "更新全局模板" });
  const restoreProject = page.getByRole("button", { name: "恢复使用全局模板" });
  await expect(globalConfirmation).not.toBeChecked();
  await expect(restoreConfirmation).not.toBeChecked();
  await expect(updateGlobal).toBeDisabled();
  await expect(restoreProject).toBeDisabled();

  await restoreConfirmation.check();
  await expect(restoreProject).toBeEnabled();
  await expect(updateGlobal).toBeDisabled();
  await restoreProject.click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].command).toMatchObject({ type: "template-restore-writer", confirm: true });
});

test("synopsis and cover generation retain separate guidance", async ({ page }) => {
  const commands = await installWorkspaceMock(page);
  await openWorkspace(page, "books");
  await page.getByRole("button", { name: "作品资料" }).click();

  await page.getByLabel("简介生成补充要求").fill("简介突出渡口谜案和双主角关系。");
  await page.getByLabel("封面生成补充要求").fill("封面采用雨夜灯火，保留标题留白。");
  await page.getByRole("button", { name: "生成作品简介" }).click();
  await expect.poll(() => commands.length).toBe(1);
  expect(commands[0].command).toMatchObject({ type: "synopsis-generate", guidance: "简介突出渡口谜案和双主角关系。" });

  await page.getByRole("button", { name: "生成封面" }).click();
  await expect.poll(() => commands.length).toBe(2);
  expect(commands[1].command).toMatchObject({ type: "cover-generate", guidance: "封面采用雨夜灯火，保留标题留白。" });
});
