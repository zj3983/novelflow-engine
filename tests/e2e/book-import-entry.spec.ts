import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from "node:child_process";
import path from "node:path";

// This repo keeps JS tooling scoped to `apps/web/`, so we import Playwright from there.
import { expect, test } from "../../apps/web/node_modules/@playwright/test";

const FIXTURE_PATH =
  "D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/fixtures/book-import-sample";

async function waitForHealthyApi(baseUrl: string, timeoutMs: number) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const response = await fetch(`${baseUrl}/health`, { method: "GET" });
      if (response.ok) return;
    } catch {
      // ignore
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error(`api_not_healthy_after_${timeoutMs}ms`);
}

let apiProcess: ChildProcessWithoutNullStreams | null = null;
let startedApi = false;

test.beforeAll(async () => {
  const baseUrl = "http://127.0.0.1:8000";
  try {
    await waitForHealthyApi(baseUrl, 800);
    startedApi = false;
    return;
  } catch {
    // proceed to spawn
  }

  const repoRoot = path.resolve(__dirname, "../..");

  apiProcess = spawn(
    "python",
    ["-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "8000"],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        PYTHONPATH: [repoRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
      },
      stdio: "pipe",
    },
  );
  startedApi = true;

  await waitForHealthyApi(baseUrl, 10_000);
});

test.afterAll(async () => {
  if (!startedApi || !apiProcess) return;

  apiProcess.kill();
  await new Promise((resolve) => setTimeout(resolve, 500));
  if (apiProcess.exitCode === null && apiProcess.pid) {
    spawnSync("taskkill", ["/PID", String(apiProcess.pid), "/T", "/F"]);
  }
});

test("book import entry loads an in-repo fixture into the workbench draft", async ({ page }) => {
  // The FastAPI app doesn't currently attach CORS headers, so browser fetches will fail.
  // Proxy through Playwright so we still exercise the real backend contract + filesystem scan.
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

    const upstream = await fetch(request.url(), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: request.postData() ?? "",
    });
    const body = await upstream.text();

    await route.fulfill({
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        "access-control-allow-origin": "*",
      },
      body,
    });
  });

  await page.goto("/");

  await expect(page.getByText("导入书籍目录", { exact: true })).toBeVisible();

  await page.getByLabel("本地目录路径", { exact: true }).fill(FIXTURE_PATH);
  await page.getByRole("button", { name: "校验目录", exact: true }).click();

  const report = page.locator('[aria-label="Book Import Report"]');
  await expect(report).toBeVisible();
  await expect(report).toContainText("已校验目录：");
  await expect(report).toContainText("可载入：是");
  await expect(report).toContainText("current_focus.md");

  await page.getByRole("button", { name: "载入到工作台", exact: true }).click();

  await expect(page.getByLabel("Outline Input")).toHaveValue(/导入的大纲内容/);
  await expect(page.getByLabel("Character Name 1")).toHaveValue("阿青");
});
