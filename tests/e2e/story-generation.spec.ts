// This repo keeps JS tooling scoped to `apps/web/`, so we import Playwright from there.
import { expect, test, type Page } from "../../apps/web/node_modules/@playwright/test";

async function seedMinimalDraft(page: Page) {
  await page.getByLabel("Outline Input").fill("A court ledger hides the first clue.");
  await page.getByLabel("Character Name 1").fill("Lin Yue");
  await page.getByLabel("Character Goal 1").fill("find the hidden ledger");
}

test("generate next chapter updates the homepage history and detail panels", async ({ page }) => {
  await page.goto("/");
  await seedMinimalDraft(page);
  await page.getByRole("banner").getByRole("button", { name: /开始生成第一章|继续生成下一章/ }).click();

  await expect(page.locator(".chapter-panel")).toContainText(/第\s*1\s*章/);
  await expect(page.locator(".chapter-panel")).toContainText("章节摘要");
  await expect(page.locator(".chapter-panel")).toContainText("本章意图");
  await expect(page.locator(".chapter-panel")).toContainText("角色行动");
  await expect(page.locator(".chapter-panel")).toContainText("事件推进");
  await expect(page.locator(".creative-workbench__side")).toContainText("角色群像");
  await expect(page.locator(".creative-workbench__side")).toContainText("关系变化");
  await expect(page.locator(".chapter-panel")).toContainText("下一步");
});

test("second chapter reuses previous fact and foreshadowing in prose", async ({ page }) => {
  await page.goto("/");
  await seedMinimalDraft(page);
  await page.getByRole("banner").getByRole("button", { name: /开始生成第一章|继续生成下一章/ }).click();
  await page.getByRole("banner").getByRole("button", { name: "继续生成下一章" }).click();

  await expect(page.locator(".chapter-panel")).toContainText(/第\s*2\s*章/);
  await expect(page.locator(".chapter-panel")).toContainText("质量检查");
  await expect(page.locator(".chapter-panel")).toContainText("本章状态正常");
});

test("author constraints flow into the next simulation guardrails", async ({ page }) => {
  await page.goto("/");
  await seedMinimalDraft(page);
  await page.getByRole("banner").getByRole("button", { name: /开始生成第一章|继续生成下一章/ }).click();

  await page.locator(".project-editor textarea").nth(2).fill("rule one\nrule two");
  await page.locator(".project-editor button.btn--primary").click();
  await expect(page.locator(".project-editor")).toContainText("项目资料已保存到后端。");

  await page.getByRole("banner").getByRole("button", { name: "继续生成下一章" }).click();

  await expect(page.locator(".simulation-board")).toContainText("作者约束");
  await expect(page.locator(".simulation-board")).toContainText("rule one / rule two");
});
