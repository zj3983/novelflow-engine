import { expect, test, type Page } from "@playwright/test";

const BOOK_ID = "file:navigation-convergence";

function workspace() {
  const book = {
    id: BOOK_ID,
    title: "导航验收作品",
    genre: "奇幻",
    idea: "验证普通作者导航。",
    requirements: "",
    future: "",
    direction: "沿线索查清旧案。",
    plan: "找到第一条线索。",
    planAdopted: false,
    planningVolume: 1,
    chapters: [],
    volumes: [{ number: 1, title: "第一卷", start: 1, goal: "找到第一条线索。" }],
    actions: {},
    notice: "",
    busy: false,
    canRetry: false,
    nextVolume: false,
  };
  return {
    mode: "live",
    books: [book],
    bookId: BOOK_ID,
    page: "books",
    showNew: false,
    storyTab: "人物",
    person: "",
    storageWarning: "",
    actions: {},
    links: { settings: "/config", import: "/projects?import=1" },
  };
}

async function installWorkspaceApi(page: Page) {
  await page.route("**/author-workspace?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(workspace()),
    });
  });
}

test("main entry opens the four author pages and settings", async ({ page }) => {
  await installWorkspaceApi(page);

  await page.goto("/");
  await expect(page).toHaveURL(/\/workspace(?:\?|$)/);
  const nav = page.getByRole("navigation", { name: "主要导航" });
  for (const label of ["作品", "全书规划", "写作", "故事设定"]) {
    await expect(nav.getByRole("button", { name: label, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "打开设置" })).toBeVisible();

  await nav.getByRole("button", { name: "全书规划" }).click();
  await expect(page.getByRole("heading", { name: "全书规划" })).toBeVisible();
  await nav.getByRole("button", { name: "写作" }).click();
  await expect(page.getByRole("heading", { name: "开始你的第一章" })).toBeVisible();
  await nav.getByRole("button", { name: "故事设定" }).click();
  await expect(page.getByRole("navigation", { name: "故事设定分类" })).toBeVisible();

  await page.getByRole("button", { name: "打开设置" }).click();
  await expect(page).toHaveURL(/\/config$/);
  await expect(page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "设置" })).toBeVisible();

  await page.goto("/books");
  await expect(page).toHaveURL(/\/workspace(?:\?|$)/);
});

test("the reserved new-project route does not show a fake project navigation", async ({ page }) => {
  await page.goto("/projects/new");
  await expect(page.getByRole("heading", { name: "新建小说" })).toBeVisible();

  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav.getByRole("link", { name: "作品" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "设置" })).toBeVisible();
  for (const label of ["全书规划", "写作", "故事设定"]) {
    await expect(nav.getByRole("link", { name: label, exact: true })).toHaveCount(0);
  }
});

test("legacy chapter-writing URLs stay directly available and link back to the workbench", async ({ page }) => {
  const encodedId = encodeURIComponent("file:legacy-direct-entry");
  const legacyPath = `/projects/${encodedId}/write`;
  await page.route(`**/file-projects/${encodedId}/product/write**`, async (route) => {
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "fixture_not_found" }) });
  });

  const response = await page.goto(legacyPath, { waitUntil: "domcontentloaded" });
  expect(response?.status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`/projects/${encodedId}/write$`));
  await expect(page.getByRole("heading", { name: "章节创作" })).toBeVisible();

  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav.getByRole("link", { name: "写作" })).toHaveAttribute(
    "href",
    `/workspace?book=${encodedId}&page=writing`,
  );
});
