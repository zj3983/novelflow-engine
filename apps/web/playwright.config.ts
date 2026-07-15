import { defineConfig } from "@playwright/test";

const port = process.env.PLAYWRIGHT_PORT || "3100";
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${port}`;

export default defineConfig({
  // We keep E2E tests in repo-root `tests/e2e` but also retain local UI shell tests in `apps/web/tests`.
  // testDir resolves relative to this config file (apps/web).
  testDir: "../..",
  testMatch: ["apps/web/tests/**/*.spec.ts", "tests/e2e/**/*.spec.ts"],
  testIgnore: [".worktrees/**"],
  fullyParallel: true,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `npx next dev -p ${port}`,
    cwd: __dirname,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
