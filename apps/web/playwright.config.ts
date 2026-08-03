import path from "node:path";

import { defineConfig } from "@playwright/test";

const port = process.env.PLAYWRIGHT_PORT || "3100";
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${port}`;
const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH;
const repoRoot = path.resolve(__dirname, "../..").replaceAll("\\", "/");

export default defineConfig({
  // The active file-project workbench suite lives with the web app. The repo-root
  // tests/e2e suite targets the retired single-page story editor and is kept only
  // as migration reference.
  testDir: "../..",
  testMatch: ["apps/web/tests/**/*.spec.ts"],
  testIgnore: [`${repoRoot}/.worktrees/**`],
  fullyParallel: true,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL,
    trace: "retain-on-failure",
    ...(executablePath ? { launchOptions: { executablePath } } : {}),
  },
  webServer: {
    command: `npx next dev -p ${port}`,
    cwd: __dirname,
    env: {
      ...process.env,
      NEXT_DIST_DIR: `.next-e2e-${port}`,
    },
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
