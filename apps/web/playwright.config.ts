import { defineConfig } from "@playwright/test";

export default defineConfig({
  // We keep E2E tests in repo-root `tests/e2e` but also retain local UI shell tests in `apps/web/tests`.
  // testDir resolves relative to this config file (apps/web).
  testDir: "../..",
  testMatch: ["apps/web/tests/**/*.spec.ts", "tests/e2e/**/*.spec.ts"],
  fullyParallel: true,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    cwd: __dirname,
    url: "http://127.0.0.1:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
