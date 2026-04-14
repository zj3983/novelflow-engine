import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const FIXTURE_PATH =
  "D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/fixtures/book-import-sample";

async function proxyBookImportRoutes(page: Page) {
  await page.route("**/book-import/**", async (route) => {
    const request = route.request();
    const sourcePath = FIXTURE_PATH;
    const read = (relativePath: string) =>
      fs.readFileSync(path.join(sourcePath, relativePath), "utf-8");

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
            {
              item_id: "source:book_rules.md",
              title: "book_rules.md",
              kind: "source_document",
              filename: "book_rules.md",
              path: `${sourcePath}/book_rules.md`,
              preview: "RULES: Keep the opening grounded.",
              content: read("book_rules.md"),
              parsed_characters: [],
            },
            {
              item_id: "source:character_matrix.md",
              title: "character_matrix.md",
              kind: "source_document",
              filename: "character_matrix.md",
              path: `${sourcePath}/character_matrix.md`,
              preview: "Lin Yue / Su Wan",
              content: read("character_matrix.md"),
              parsed_characters: ["闃块潚", "闃跨櫧"],
            },
            {
              item_id: "source:current_focus.md",
              title: "current_focus.md",
              kind: "source_document",
              filename: "current_focus.md",
              path: `${sourcePath}/current_focus.md`,
              preview: "FOCUS: Start with the first clue.",
              content: read("current_focus.md"),
              parsed_characters: [],
            },
            {
              item_id: "source:story_bible.md",
              title: "story_bible.md",
              kind: "source_document",
              filename: "story_bible.md",
              path: `${sourcePath}/story_bible.md`,
              preview: "Story bible notes.",
              content: read("story_bible.md"),
              parsed_characters: [],
            },
            {
              item_id: "source:volume_outline.md",
              title: "volume_outline.md",
              kind: "source_document",
              filename: "volume_outline.md",
              path: `${sourcePath}/volume_outline.md`,
              preview: "Volume Outline",
              content: read("volume_outline.md"),
              parsed_characters: [],
            },
          ],
        },
        {
          section_id: "source_state",
          title: "状态文件",
          items: [
            {
              item_id: "state:chapter_summaries.json",
              title: "chapter_summaries.json",
              kind: "state_file",
              filename: "chapter_summaries.json",
              path: `${sourcePath}/state/chapter_summaries.json`,
              preview: "Chapter summary state",
              content: read("state/chapter_summaries.json"),
              parsed_characters: [],
            },
            {
              item_id: "state:manifest.json",
              title: "manifest.json",
              kind: "state_file",
              filename: "manifest.json",
              path: `${sourcePath}/state/manifest.json`,
              preview: "manifest",
              content: read("state/manifest.json"),
              parsed_characters: [],
            },
          ],
        },
        {
          section_id: "runtime_chapters",
          title: "杩愯绔犺妭",
          items: [
            {
              item_id: "runtime:chapter-0001.intent.md",
              title: "Chapter 1 路 intent",
              kind: "runtime_chapter_artifact",
              filename: "chapter-0001.intent.md",
              path: `${sourcePath}/runtime/chapter-0001.intent.md`,
              preview: "Open with the hidden ledger and the first clue.",
              chapter_number: 1,
              content: read("runtime/chapter-0001.intent.md"),
              parsed_characters: [],
            },
            {
              item_id: "runtime:chapter-0001.context.json",
              title: "Chapter 1 路 context",
              kind: "runtime_chapter_artifact",
              filename: "chapter-0001.context.json",
              path: `${sourcePath}/runtime/chapter-0001.context.json`,
              preview: "Context snapshot",
              chapter_number: 1,
              content: read("runtime/chapter-0001.context.json"),
              parsed_characters: [],
            },
            {
              item_id: "runtime:chapter-0001.rule-stack.yaml",
              title: "Chapter 1 路 rule stack",
              kind: "runtime_chapter_artifact",
              filename: "chapter-0001.rule-stack.yaml",
              path: `${sourcePath}/runtime/chapter-0001.rule-stack.yaml`,
              preview: "Rule stack",
              chapter_number: 1,
              content: read("runtime/chapter-0001.rule-stack.yaml"),
              parsed_characters: [],
            },
            {
              item_id: "runtime:chapter-0001.trace.json",
              title: "Chapter 1 路 trace",
              kind: "runtime_chapter_artifact",
              filename: "chapter-0001.trace.json",
              path: `${sourcePath}/runtime/chapter-0001.trace.json`,
              preview: "Trace",
              chapter_number: 1,
              content: read("runtime/chapter-0001.trace.json"),
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
        summary: "导演预读：这本书先从匿名线索切入，再把账本、证人和宫廷压力串起来。补充材料已识别完毕，可以直接进入首章。",
        characters: ["Lin Yue", "Su Wan"],
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
        headers: {
          "content-type": "application/json",
          "access-control-allow-origin": "*",
        },
        body: JSON.stringify(catalogPayload),
      });
      return;
    }

    if (request.url().includes("/book-import/scan")) {
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/json",
          "access-control-allow-origin": "*",
        },
        body: JSON.stringify(scanPayload),
      });
      return;
    }

    if (request.method() !== "POST") {
      await route.fallback();
      return;
    }

    if (request.url().includes("/book-import/bootstrap")) {
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/json",
          "access-control-allow-origin": "*",
        },
        body: JSON.stringify(bootstrapPayload),
      });
      return;
    }

    if (request.url().includes("/book-import/catalog")) {
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/json",
          "access-control-allow-origin": "*",
        },
        body: JSON.stringify(catalogPayload),
      });
      return;
    }

    await route.fallback();
  });
}

test("workbench shell renders the four-panel layout", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("region", { name: "大纲面板" })).toBeVisible();
  await expect(page.getByRole("region", { name: "章节草稿面板" })).toBeVisible();
  await expect(page.getByRole("region", { name: "角色状态面板" })).toBeVisible();
  await expect(page.getByRole("region", { name: "控制面板" })).toBeVisible();
});

test("book import sidebar renders a visible import entry", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.getByText("导入书籍目录", { exact: true })).toBeVisible();
  await expect(page.getByLabel("本地目录路径", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "校验目录", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "载入到工作台", exact: true })).toBeVisible();
});

test("imported book exposes a browsable directory view", async ({ page }) => {
  await proxyBookImportRoutes(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle");

  const sourcePathInput = page.getByPlaceholder("例如：D:/novels/demo/story");
  await sourcePathInput.fill(FIXTURE_PATH);
  await expect(sourcePathInput).toHaveValue(FIXTURE_PATH);
  await page.getByRole("button", { name: "校验目录", exact: true }).click();

  const report = page.locator('[aria-label="书籍导入报告"]');
  await expect(report).toBeVisible();
  await expect(report).toContainText("可载入");
  await expect(page.getByText("目录浏览器", { exact: true })).toBeVisible();
  await expect(page.getByText("工作台历史", { exact: true })).toBeVisible();
});

test("imported book can load and start from the import panel", async ({ page }) => {
  await proxyBookImportRoutes(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle");

  const sourcePathInput = page.getByPlaceholder("例如：D:/novels/demo/story");
  await sourcePathInput.fill(FIXTURE_PATH);
  await page.getByRole("button", { name: "校验目录", exact: true }).click();
  await expect(page.getByRole("button", { name: "载入到工作台", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "载入并开始", exact: true })).toBeVisible();
  await expect(page.getByText("目录浏览器", { exact: true })).toBeVisible();
});








