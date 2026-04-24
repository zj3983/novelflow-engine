import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "../../apps/web/node_modules/@playwright/test";

const FIXTURE_PATH = path.resolve(__dirname, "../fixtures/book-import-sample");

async function proxyBookImportRoutes(page: Page) {
  const createdProjects = new Map<string, Record<string, unknown>>();

  await page.route("**/projects**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());

    if (request.method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "GET, POST, PUT, OPTIONS",
          "access-control-allow-headers": "content-type",
        },
        body: "",
      });
      return;
    }

    if (request.method() === "GET" && url.pathname.endsWith("/projects")) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify(
          Array.from(createdProjects.values()).map((project) => ({
            project_id: project.project_id,
            title: project.title,
            status: project.status ?? "draft",
            active_story_id: project.active_story_id ?? "",
            current_chapter: 0,
            source_path: project.source_path ?? "",
          })),
        ),
      });
      return;
    }

    if (request.method() === "GET") {
      const projectId = decodeURIComponent(url.pathname.split("/").at(-1) ?? "");
      const project = createdProjects.get(projectId);
      if (!project) {
        await route.fulfill({ status: 404, body: JSON.stringify({ detail: "project_not_found" }) });
        return;
      }
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify(project),
      });
      return;
    }

    if (request.method() === "POST" && url.pathname.endsWith("/projects")) {
      const payload = JSON.parse(request.postData() ?? "{}");
      const project = {
        ...payload,
        source_path: payload.source_path ?? "",
        seed_outline: payload.seed_outline ?? "",
        world_summary: payload.world_summary ?? "",
        current_focus: payload.current_focus ?? "",
        author_constraints: payload.author_constraints ?? [],
        status: payload.active_story_id ? "simulating" : "draft",
        active_story_id: payload.active_story_id ?? "",
        branches: [],
      };
      createdProjects.set(project.project_id, project);
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify(project),
      });
      return;
    }

    await route.fallback();
  });

  await page.route("**/book-import/**", async (route) => {
    const request = route.request();
    const sourcePath = FIXTURE_PATH;
    const read = (relativePath: string) => fs.readFileSync(path.join(sourcePath, relativePath), "utf-8");

    const scanPayload = {
      source_path: sourcePath,
      exists: true,
      missing_required_files: [],
      missing_optional_files: [],
      unusable_required_files: [],
      empty_files: [],
      present_files: [
        "author_intent.md",
        "book_rules.md",
        "character_matrix.md",
        "current_focus.md",
        "story_bible.md",
        "volume_outline.md",
      ],
      warnings: [],
      can_bootstrap: true,
    };

    const catalogPayload = {
      source_path: sourcePath,
      exists: true,
      can_bootstrap: true,
      sections: [
        {
          section_id: "source_docs",
          title: "婧愪功鐩綍",
          items: [
            {
              item_id: "source:author_intent.md",
              title: "author_intent.md",
              kind: "source_document",
              filename: "author_intent.md",
              path: `${sourcePath}/author_intent.md`,
              preview: "INTENT: Keep the opening grounded.",
              content: read("author_intent.md"),
              parsed_characters: [],
            },
          ],
        },
      ],
    };

    const bootstrapPayload = {
      report: scanPayload,
      draft: {
        source_path: sourcePath,
        outline: "VOLUME: A hidden ledger drives the plot.\n\nFOCUS: Start with the first clue.",
        summary: "瀵兼紨棰勮锛氳繖鏈功浼氬厛浠庤处鏈拰鍖垮悕绾跨储寮€濮嬶紝閫愭鎶婂寤峰帇鍔涙姮璧锋潵銆?",
        characters: [
          { name: "Lin Yue", goal: "find the hidden ledger" },
          { name: "Su Wan", goal: "protect the witness" },
        ],
      },
    };

    if (request.method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "content-type",
        },
        body: "",
      });
      return;
    }

    if (request.url().includes("/book-import/catalog")) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify(catalogPayload),
      });
      return;
    }

    if (request.url().includes("/book-import/scan")) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify(scanPayload),
      });
      return;
    }

    if (request.method() === "POST" && request.url().includes("/book-import/bootstrap")) {
      await route.fulfill({
        status: 200,
        headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
        body: JSON.stringify(bootstrapPayload),
      });
      return;
    }

    await route.fallback();
  });
}

test("book import entry loads the workbench and generates the worldview", async ({ page }) => {
  await proxyBookImportRoutes(page);
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  await page.locator(".project-start__mode").nth(1).click();
  await expect(page.locator(".project-start__card").nth(1)).toHaveClass(/project-start__card--active/);
  const importPanel = page.locator(".book-import");
  await importPanel.locator("input").first().fill(FIXTURE_PATH);
  await importPanel.locator(".book-import__actions button").first().click();

  const report = page.locator('[aria-label="书籍导入报告"]');
  await expect(report).toBeVisible();
  await expect(report).toContainText("current_focus.md");
  await expect(page.locator(".book-import__next-step")).toContainText("载入并生成世界观");

  await importPanel.locator(".book-import__actions button").nth(1).click();

  await expect(page.locator(".creative-workbench")).toBeVisible();
  await expect(page.locator(".chapter-panel__title")).toContainText("开始生成第一章");
  await expect(page.locator('input[id^="character-name-"]').first()).not.toHaveValue("");
  await expect(page.locator(".workbench-overview-stack")).toBeVisible();
});
