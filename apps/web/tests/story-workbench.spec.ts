import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const FIXTURE_PATH = path.resolve(__dirname, "../../../tests/fixtures/book-import-sample");

async function proxyBookImportRoutes(page: Page) {
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
          title: "源书目录",
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
        summary: "导演预读：这本书会先从账本和匿名线索开始，逐步把宫廷压力抬起来。",
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

async function seedMinimalDraft(page: Page) {
  await page.getByLabel("Outline Input").fill("A court ledger hides the first clue.");
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("find the hidden ledger");
}

test("homepage foregrounds story status and history before import", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("banner")).toBeVisible();
  await expect(page.locator(".simulation-board")).toBeVisible();
  await expect(page.locator('[aria-label="项目资料面板"]')).toBeVisible();
  await expect(page.locator(".creative-workbench__side")).toBeVisible();
  await expect(page.getByRole("banner").getByRole("button")).toBeVisible();
});

test("homepage top bar shows writing progress and core actions", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator(".workbench-topbar__eyebrow")).toBeVisible();
  await expect(page.locator(".workbench-topbar__summary")).toBeVisible();
  await expect(page.getByRole("banner").getByRole("link", { name: /查看配置/ })).toBeVisible();
});

test("imported book still exposes a browsable source panel", async ({ page }) => {
  await proxyBookImportRoutes(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle");

  const sourcePathInput = page.getByPlaceholder("例如：D:/novels/demo/story");
  await sourcePathInput.fill(FIXTURE_PATH);
  await page.getByRole("button", { name: "校验目录", exact: true }).click();

  await expect(page.locator('[aria-label="书籍导入报告"]')).toContainText("可载入");
  await expect(page.locator('[aria-label="导入内容浏览面板"]')).toBeVisible();
});

test("generated chapters surface in the homepage chapter workspace", async ({ page }) => {
  await page.goto("/");
  await seedMinimalDraft(page);
  await page.getByRole("banner").getByRole("button", { name: /开始生成第一章|继续生成下一章/ }).click();

  await expect(page.locator(".chapter-panel")).toContainText(/第\s*1\s*章/);
  await expect(page.locator(".chapter-panel")).toContainText("本章意图");
  await expect(page.locator(".chapter-panel")).toContainText("事件推进");
});

test("project author constraints persist after refresh", async ({ page }) => {
  await page.goto("/");
  await seedMinimalDraft(page);
  await page.getByRole("banner").getByRole("button", { name: /开始生成第一章|继续生成下一章/ }).click();

  await page.locator(".project-editor textarea").nth(2).fill("rule one\nrule two");
  await page.locator(".project-editor button.btn--primary").click();

  await expect(page.getByText("项目资料已保存到后端。")).toBeVisible();
  await page.reload();

  await expect(page.locator(".project-editor textarea").nth(2)).toHaveValue(/rule one/);
});
