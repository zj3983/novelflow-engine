import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

type ObservedApiResponse = {
  method: string;
  path: string;
  status: number;
  marker: string | null;
};

type JsonResponse = { status: number; body: any };

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Use run-live-api-integration.ps1 to provide ${name}.`);
  return value;
}

const apiBaseURL = requiredEnv("INTEGRATION_API_BASE_URL");
const projectRoot = requiredEnv("INTEGRATION_PROJECTS_ROOT");
const apiRequestsLog = requiredEnv("INTEGRATION_API_REQUESTS_LOG");
const syntheticAuditLog = requiredEnv("INTEGRATION_SYNTHETIC_AUDIT_LOG");

function collectApiResponses(page: Page): { responses: ObservedApiResponse[]; settled: Promise<void>[] } {
  const responses: ObservedApiResponse[] = [];
  const settled: Promise<void>[] = [];
  page.on("response", (response) => {
    if (!response.url().startsWith(apiBaseURL)) return;
    settled.push((async () => {
      responses.push({
        method: response.request().method(),
        path: new URL(response.url()).pathname,
        status: response.status(),
        marker: await response.headerValue("x-novelflow-integration-server"),
      });
    })());
  });
  return { responses, settled };
}

function readJsonLines(filePath: string): any[] {
  try {
    return readFileSync(filePath, "utf8")
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function browserGetJson(page: Page, url: string): Promise<JsonResponse> {
  return await page.evaluate(async (target) => {
    const response = await fetch(target, { cache: "no-store" });
    return { status: response.status, body: await response.json() };
  }, url);
}

async function waitForOrchestrationCompletion(page: Page, projectPrefix: string) {
  await expect.poll(async () => {
    const response = await browserGetJson(page, `${projectPrefix}/build-graph/orchestrations/current`);
    return response.status === 200 ? response.body?.status : null;
  }, {
    message: "the real API orchestration must finish before the browser continues",
    timeout: 240_000,
    intervals: [1_000, 2_000, 3_000],
  }).toBe("completed");
}

async function waitForCandidate(page: Page, chapterNumber: number) {
  const candidate = page.getByLabel("候选稿", { exact: true });
  await expect(candidate).toBeVisible();
  await expect(candidate).toContainText(new RegExp(`第\\s*${chapterNumber}\\s*章`));
  return candidate;
}

async function assertBrowserHitRealApi(
  settled: Promise<void>[],
  responses: ObservedApiResponse[],
  pathSuffix: string,
  method: string,
  expectedStatus?: number,
) {
  await Promise.all(settled);
  const matching = responses.filter((item) => item.method === method && item.path.endsWith(pathSuffix));
  expect(matching, `${method} ${pathSuffix} must reach the isolated FastAPI server`).not.toHaveLength(0);
  expect(matching.every((item) => item.marker === "synthetic"), "response marker must come from the real test server").toBe(true);
  if (expectedStatus !== undefined) {
    expect(matching.some((item) => item.status === expectedStatus)).toBe(true);
  }
  const serverRequests = readJsonLines(apiRequestsLog);
  expect(serverRequests.some((item) => item.method === method && item.path.endsWith(pathSuffix))).toBe(true);
}

test("live API: create, plan, preserve blocked candidate, confirm once, refresh, and continue", async ({ page }) => {
  test.setTimeout(360_000);
  const { responses, settled } = collectApiResponses(page);
  const idea = "失业律师收到陌生人的遗嘱后，必须核清一笔被改写的旧账。";

  await page.goto("/projects/new");
  await page.getByLabel("小说类型").selectOption("urban");
  await page.getByRole("textbox", { name: /^灵感/ }).fill(idea);
  await page.getByRole("button", { name: "创建小说" }).click();
  await expect(page).toHaveURL(/\/projects\/file%3A[^/]+\/setup$/);

  const projectId = decodeURIComponent(new URL(page.url()).pathname.split("/")[2]);
  const projectPrefix = `${apiBaseURL}/file-projects/${encodeURIComponent(projectId)}`;
  await expect(page.getByRole("heading", { name: "选择故事核心" })).toBeVisible();
  await page.getByRole("button", { name: "生成故事方向" }).click();
  await page.getByRole("radio", { name: /雨夜遗嘱/ }).check();
  await page.getByRole("button", { name: "采用这个方向" }).click();
  await expect(page).toHaveURL(new RegExp(`${encodeURIComponent(projectId)}/outline$`));

  await page.getByRole("link", { name: "开书构建" }).click();
  await expect(page.getByRole("heading", { name: "构建故事到章节的完整开局" })).toBeVisible();
  await page.getByRole("button", { name: "启用完整开局图" }).click();
  await expect(page.getByRole("heading", { name: "完整开局图已启用" })).toBeVisible();
  await page.getByRole("button", { name: "继续构建" }).click();
  await waitForOrchestrationCompletion(page, projectPrefix);
  await expect(page.getByText("全部任务已就绪，世界、角色和前 3 章细纲已发布。", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "完整开局图已启用" })).toBeVisible();
  await expect(page.getByText(/细纲窗口：前 3 章/)).toBeVisible();
  await page.getByRole("link", { name: "前往正文候选与审查" }).click();
  await expect(page.getByRole("button", { name: "生成第一章" })).toBeEnabled();

  await page.getByRole("button", { name: "生成第一章" }).click();
  const blockedCandidate = await waitForCandidate(page, 1);
  await expect(blockedCandidate).toContainText("合成 Canon blocker");
  await expect(page.getByLabel("候选稿审查结果")).toContainText("canon.hard_blocker");

  const beforeConfirmation = await browserGetJson(page, `${projectPrefix}/candidates?chapter_number=1`);
  expect(beforeConfirmation.status).toBe(200);
  const blockedId = beforeConfirmation.body.items.find((item: any) => item.status === "pending")?.candidate_id;
  expect(blockedId).toBeTruthy();
  const rejectedConfirmationResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/candidates/${blockedId}/confirm`)
      && response.request().method() === "POST",
  );
  await blockedCandidate.getByRole("button", { name: "确认提交" }).click();
  const rejectedConfirmation = await rejectedConfirmationResponse;
  expect(rejectedConfirmation.status()).toBe(400);
  expect((await rejectedConfirmation.json()).detail).toContain("canon.hard_blocker");
  await expect(blockedCandidate).toBeVisible();

  const blockedProject = await browserGetJson(page, projectPrefix);
  expect(blockedProject.status).toBe(200);
  expect(blockedProject.body.branches[0].current_chapter).toBe(0);
  const afterRejectedConfirmation = await browserGetJson(page, `${projectPrefix}/candidates?chapter_number=1`);
  const retainedBlocked = afterRejectedConfirmation.body.items.find((item: any) => item.candidate_id === blockedId);
  expect(retainedBlocked?.status).toBe("pending");

  await page.reload();
  const recoveredCandidate = await waitForCandidate(page, 1);
  await expect(recoveredCandidate).toContainText("合成 Canon blocker");
  await recoveredCandidate.getByRole("button", { name: "丢弃候选稿" }).click();
  await expect(page.getByLabel("候选稿", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "生成第一章" }).click();

  const cleanCandidate = await waitForCandidate(page, 1);
  await expect(cleanCandidate).not.toContainText("合成 Canon blocker");
  const generatedOnce = await browserGetJson(page, `${projectPrefix}/candidates?chapter_number=1`);
  const cleanId = generatedOnce.body.items.find((item: any) => item.status === "pending")?.candidate_id;
  expect(cleanId).toBeTruthy();
  const confirmedResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/candidates/${cleanId}/confirm`)
      && response.request().method() === "POST",
  );
  await cleanCandidate.getByRole("button", { name: "确认提交" }).click();
  const confirmed = await confirmedResponse;
  expect(confirmed.status()).toBe(200);
  await expect(page).toHaveURL(new RegExp(`${encodeURIComponent(projectId)}/write\\?chapter=1$`));

  const afterHumanConfirmation = await browserGetJson(page, projectPrefix);
  expect(afterHumanConfirmation.body.branches[0].current_chapter).toBe(1);
  const confirmedCandidates = await browserGetJson(page, `${projectPrefix}/candidates?chapter_number=1`);
  expect(confirmedCandidates.body.items.filter((item: any) => item.status === "confirmed").map((item: any) => item.candidate_id)).toEqual([cleanId]);

  await page.reload();
  await expect(page.locator(".ws-reader__body")).toContainText("律师核对第1章");
  await expect(page.getByRole("button", { name: "生成下一章" })).toBeEnabled();
  await page.getByRole("button", { name: "生成下一章" }).click();
  const chapterTwoCandidate = await waitForCandidate(page, 2);
  await expect(chapterTwoCandidate).toBeVisible();
  const afterRefresh = await browserGetJson(page, projectPrefix);
  expect(afterRefresh.body.branches[0].current_chapter).toBe(1);

  await assertBrowserHitRealApi(settled, responses, "/file-projects", "POST", 201);
  await assertBrowserHitRealApi(settled, responses, "/build-graph/opening", "POST", 200);
  await assertBrowserHitRealApi(settled, responses, "/build-graph/orchestrations", "POST", 200);
  await assertBrowserHitRealApi(settled, responses, "/generation-jobs", "POST", 200);
  await assertBrowserHitRealApi(settled, responses, `/candidates/${blockedId}/confirm`, "POST");
  await assertBrowserHitRealApi(settled, responses, `/candidates/${cleanId}/confirm`, "POST", 200);

  const syntheticEvents = readJsonLines(syntheticAuditLog);
  expect(syntheticEvents.some((item) => item.kind === "model" && item.task_id === "story_core")).toBe(true);
  expect(syntheticEvents.some((item) => item.kind === "candidate" && item.chapter_number === 1 && item.hard_blocked)).toBe(true);
  expect(syntheticEvents.some((item) => item.kind === "candidate" && item.chapter_number === 2 && !item.hard_blocked)).toBe(true);
  expect(readJsonLines(apiRequestsLog).some((item) => item.method === "POST" && item.path.endsWith(`/candidates/${blockedId}/confirm`) && item.status_code >= 400)).toBe(true);
  expect(readJsonLines(apiRequestsLog).filter((item) => item.method === "POST" && item.path.endsWith(`/candidates/${cleanId}/confirm`))).toHaveLength(1);
  await test.info().attach("real-api-requests.jsonl", { path: apiRequestsLog, contentType: "application/x-ndjson" });
  await test.info().attach("synthetic-injection-audit.jsonl", { path: syntheticAuditLog, contentType: "application/x-ndjson" });
});

test("live API: cross-volume planning from a labeled synthetic confirmed-volume fixture", async ({ page }) => {
  test.setTimeout(360_000);
  const seedOutput = execFileSync(
    "python",
    [path.join(__dirname, "seed_end_of_volume.py"), projectRoot],
    { encoding: "utf8", env: process.env },
  );
  const fixture = JSON.parse(seedOutput) as { label: string; project_id: string; confirmed_through: number };
  expect(fixture.label).toBe("SYNTHETIC VALID END-OF-VOLUME FIXTURE");
  expect(fixture.confirmed_through).toBe(50);

  const { responses, settled } = collectApiResponses(page);
  const encodedId = encodeURIComponent(fixture.project_id);
  await page.goto(`/projects/${encodedId}/build`);
  const graph = await browserGetJson(page, `${apiBaseURL}/file-projects/${encodedId}/build-graph`);
  expect(graph.status).toBe(200);
  expect(graph.body.opening_confirmed_through).toBe(50);
  expect(graph.body.opening_next_volume_available).toBe(true);
  await expect(page.getByRole("button", { name: "扩展下一卷细纲任务" })).toBeVisible();

  await page.getByRole("button", { name: "扩展下一卷细纲任务" }).click();
  await expect(page.getByText("下一卷规划扩展中。完成并发布全部细纲之前，正文候选入口保持关闭。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续构建" }).click();
  await waitForOrchestrationCompletion(page, `${apiBaseURL}/file-projects/${encodedId}`);
  await expect(page.getByText(/规划版本：v1（第 1–50 章）、v2（第 51–60 章）/)).toBeVisible();
  await page.getByRole("link", { name: "前往正文候选与审查" }).click();
  await expect(page.getByRole("button", { name: "生成下一章" })).toBeEnabled();
  await page.getByRole("button", { name: "生成下一章" }).click();
  const candidate = await waitForCandidate(page, 51);
  await expect(candidate).toContainText("律师核对第51章");

  await assertBrowserHitRealApi(settled, responses, "/build-graph/opening/next-volume", "POST", 200);
  await assertBrowserHitRealApi(settled, responses, "/build-graph/orchestrations", "POST", 200);
  await assertBrowserHitRealApi(settled, responses, "/generation-jobs", "POST", 200);
  const syntheticEvents = readJsonLines(syntheticAuditLog);
  expect(syntheticEvents.some((item) => item.kind === "model" && item.task_id === "chapter_outline_51")).toBe(true);
  expect(syntheticEvents.some((item) => item.kind === "candidate" && item.chapter_number === 51 && !item.hard_blocked)).toBe(true);
  await test.info().attach("real-api-requests.jsonl", { path: apiRequestsLog, contentType: "application/x-ndjson" });
  await test.info().attach("synthetic-injection-audit.jsonl", { path: syntheticAuditLog, contentType: "application/x-ndjson" });
});
