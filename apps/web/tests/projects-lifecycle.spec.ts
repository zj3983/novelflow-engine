import { expect, test, type Page } from "@playwright/test";

type Lifecycle = "active" | "archived" | "trashed";

async function mockProjects(page: Page) {
  const projects: Record<Lifecycle, Array<Record<string, unknown>>> = {
    active: [{ project_id: "file:p-active", title: "正在写的书", status: "writing", current_chapter: 12, source_path: "", active_story_id: "p-active", storage_source: "file", project_lifecycle: "active" }],
    archived: [{ project_id: "p-archived", title: "已经归档的书", status: "paused", current_chapter: 30, source_path: "", active_story_id: "s-archived", storage_source: "sqlite", project_lifecycle: "archived" }],
    trashed: [{ project_id: "file:p-trashed", title: "准备删除的书", status: "paused", current_chapter: 4, source_path: "", active_story_id: "p-trashed", storage_source: "file", project_lifecycle: "trashed" }],
  };

  await page.route("**/projects**", async (route) => {
    const url = new URL(route.request().url());
    if (url.port !== "8000") {
      await route.fallback();
      return;
    }
    const lifecycle = (url.searchParams.get("lifecycle") || "active") as Lifecycle;
    if (route.request().method() === "GET" && url.pathname.endsWith("/projects")) {
      await route.fulfill({ json: projects[lifecycle].filter((item) => item.storage_source === "sqlite") });
      return;
    }
    await route.fallback();
  });
  await page.route(/\/file-projects(?:\/|\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    const lifecycle = (url.searchParams.get("lifecycle") || "active") as Lifecycle;
    if (route.request().method() === "GET" && url.pathname.endsWith("/file-projects")) {
      await route.fulfill({ json: projects[lifecycle].filter((item) => item.storage_source === "file") });
      return;
    }
    const match = url.pathname.match(/\/file-projects\/(.+?)\/(archive|trash|restore)$/);
    if (route.request().method() === "POST" && match) {
      const id = decodeURIComponent(match[1]);
      for (const values of Object.values(projects)) {
        const index = values.findIndex((item) => item.project_id === id);
        if (index >= 0) values.splice(index, 1);
      }
      await route.fulfill({ json: { project_id: id, project_lifecycle: match[2] === "archive" ? "archived" : "active" } });
      return;
    }
    if (route.request().method() === "DELETE") {
      projects.trashed = [];
      await route.fulfill({ json: { deleted: true } });
      return;
    }
    await route.fallback();
  });
}

test("projects page separates active archived and trashed novels", async ({ page }) => {
  await mockProjects(page);
  await page.goto("/projects");

  await expect(page.getByText("正在写的书")).toBeVisible();
  await page.getByRole("button", { name: "已归档" }).click();
  await expect(page.getByText("已经归档的书")).toBeVisible();
  await page.getByRole("button", { name: "回收站", exact: true }).click();
  await expect(page.getByText("准备删除的书")).toBeVisible();
});

test("permanent deletion requires the exact novel title", async ({ page }) => {
  await mockProjects(page);
  await page.goto("/projects");
  await page.getByRole("button", { name: "回收站", exact: true }).click();
  await page.getByRole("button", { name: "彻底删除《准备删除的书》" }).click();

  const dialog = page.getByRole("dialog", { name: "彻底删除小说" });
  await expect(dialog).toBeVisible();
  const confirm = dialog.getByRole("button", { name: "彻底删除" });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("输入完整书名").fill("准备删除的书");
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(page.getByText("准备删除的书")).toHaveCount(0);
});
