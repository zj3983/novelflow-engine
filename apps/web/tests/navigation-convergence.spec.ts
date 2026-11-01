import { expect, test } from "@playwright/test";

test("the main entry opens the project workbench and its settings", async ({ page }) => {
  await page.route(/\/projects\?lifecycle=active$/, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route(/\/file-projects\?lifecycle=active$/, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
      { project_id: "file:navigation", title: "导航验收作品", current_chapter: 3, status: "writing", storage_source: "file" },
    ]) });
  });

  await page.goto("/");
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("heading", { name: "我的作品" })).toBeVisible();
  await expect(page.getByRole("link", { name: "导航验收作品" })).toHaveAttribute("href", "/projects/file%3Anavigation");
  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav.getByRole("link", { name: "作品", exact: true })).toHaveAttribute("href", "/projects");
  await nav.getByRole("link", { name: "配置", exact: true }).click();
  await expect(page).toHaveURL(/\/config$/);
  await expect(page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "作品", exact: true })).toHaveAttribute("href", "/projects");
});

for (const retiredPath of ["/workspace", "/books", "/prototype/longform", "/longform/river-landscape.png"]) {
  test(`removed four-page workspace resource ${retiredPath} returns 404`, async ({ request }) => {
    expect((await request.get(retiredPath)).status()).toBe(404);
  });
}

test("the reserved new-project route does not show a fake project navigation", async ({ page }) => {
  await page.goto("/projects/new");
  await expect(page.getByRole("heading", { name: "新建小说" })).toBeVisible();

  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav.getByRole("link", { name: "作品" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "配置", exact: true })).toHaveAttribute("href", "/config");
  for (const label of ["全书规划", "写作", "故事设定"]) {
    await expect(nav.getByRole("link", { name: label, exact: true })).toHaveCount(0);
  }
});

test("chapter-writing URLs stay directly available with project navigation", async ({ page }) => {
  const encodedId = encodeURIComponent("file:legacy-direct-entry");
  const legacyPath = `/projects/${encodedId}/write`;
  await page.route(new RegExp(`/file-(?:projects|stories)/${encodedId}(?:[/?]|$)`), async (route) => {
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "fixture_not_found" }) });
  });

  const response = await page.goto(legacyPath, { waitUntil: "domcontentloaded" });
  expect(response?.status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`/projects/${encodedId}/write$`));
  await expect(page.getByRole("heading", { name: "章节", exact: true })).toBeVisible();

  const nav = page.getByRole("navigation", { name: "主导航" });
  await expect(nav.getByRole("link", { name: "章节", exact: true })).toHaveAttribute(
    "href",
    legacyPath,
  );
  await expect(nav.getByRole("link", { name: "章节", exact: true })).toHaveAttribute("aria-current", "page");
});
