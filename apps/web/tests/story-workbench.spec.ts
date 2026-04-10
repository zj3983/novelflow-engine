import { expect, test } from "@playwright/test";

test("workbench shell renders the four-panel layout", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("大纲", { exact: true })).toBeVisible();
  await expect(page.getByText("章节草稿", { exact: true })).toBeVisible();
  await expect(page.getByText("角色状态", { exact: true })).toBeVisible();
  await expect(page.getByText("控制区", { exact: true })).toBeVisible();
});

test("book import sidebar can scan and bootstrap the workbench draft", async ({ page }) => {
  await page.route("**/book-import/**", async (route) => {
    const request = route.request();

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

    if (request.method() !== "POST") {
      await route.fallback();
      return;
    }

    const url = request.url();

    if (url.includes("/book-import/scan")) {
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/json",
          "access-control-allow-origin": "*",
        },
        body: JSON.stringify({
          source_path: "D:/novels/demo",
          exists: true,
          missing_required_files: [],
          missing_optional_files: [],
          unusable_required_files: [],
          empty_files: [],
          present_files: ["current_focus.md", "volume_outline.md", "character_matrix.md"],
          warnings: [],
          can_bootstrap: true,
        }),
      });
      return;
    }

    if (url.includes("/book-import/bootstrap")) {
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": "application/json",
          "access-control-allow-origin": "*",
        },
        body: JSON.stringify({
          report: {
            source_path: "D:/novels/demo",
            exists: true,
            missing_required_files: [],
            missing_optional_files: [],
            unusable_required_files: [],
            empty_files: [],
            present_files: ["current_focus.md", "volume_outline.md", "character_matrix.md"],
            warnings: [],
            can_bootstrap: true,
          },
          draft: {
            source_path: "D:/novels/demo",
            outline: "导入的大纲内容",
            summary: "导入的概要内容",
            characters: ["阿青", "陆离"],
          },
        }),
      });
      return;
    }

    await route.fallback();
  });

  await page.goto("/");

  await expect(page.getByText("导入书籍目录", { exact: true })).toBeVisible();

  await page.getByLabel("本地目录路径", { exact: true }).fill("D:/novels/demo");
  await page.getByRole("button", { name: "校验目录", exact: true }).click();
  await expect(page.getByText("current_focus.md", { exact: false })).toBeVisible();
  await expect(page.getByText("可载入", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "载入到工作台", exact: true }).click();
  await expect(page.getByLabel("Outline Input")).toHaveValue("导入的大纲内容");
  await expect(page.getByLabel("Character Name 1")).toHaveValue("阿青");
});
