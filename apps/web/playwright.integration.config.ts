import { mkdirSync } from "node:fs";
import path from "node:path";

import { defineConfig } from "@playwright/test";

const repositoryRoot = path.resolve(__dirname, "../..");
const configuredRunRoot = process.env.INTEGRATION_RUN_ROOT;
if (!configuredRunRoot) {
  throw new Error("Run this suite with .\\run-live-api-integration.ps1 so every process shares one isolated root.");
}
const runRoot = path.resolve(configuredRunRoot);
const projectsRoot = path.join(runRoot, "projects");
const configRoot = path.join(runRoot, "config");
const logsRoot = path.join(runRoot, "logs");
const outputRoot = path.join(runRoot, "playwright-output");

mkdirSync(runRoot, { recursive: true });
mkdirSync(projectsRoot, { recursive: true });
mkdirSync(configRoot, { recursive: true });
mkdirSync(logsRoot, { recursive: true });

const apiPort = Number(process.env.INTEGRATION_API_PORT || 8187);
const webPort = Number(process.env.INTEGRATION_WEB_PORT || 3187);
const apiBaseURL = `http://127.0.0.1:${apiPort}`;
const baseURL = `http://127.0.0.1:${webPort}`;
const apiRequestsLog = path.join(logsRoot, "api-requests.jsonl");
const syntheticAuditLog = path.join(logsRoot, "synthetic-injection.jsonl");

const integrationEnvironment = {
  ...process.env,
  NOVELFLOW_E2E_SYNTHETIC: "1",
  NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR: projectsRoot,
  NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS: projectsRoot,
  NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH: path.join(configRoot, "runtime_config.json"),
  NOVEL_AUTOGROWTH_DB_PATH: path.join(configRoot, "integration.sqlite3"),
  NOVEL_AUTOGROWTH_CORS_ORIGINS: baseURL,
  NOVEL_AUTOGROWTH_FRONTEND_URL: baseURL,
  NOVELFLOW_E2E_API_REQUESTS_LOG: apiRequestsLog,
  NOVELFLOW_E2E_SYNTHETIC_AUDIT_LOG: syntheticAuditLog,
  INTEGRATION_API_BASE_URL: apiBaseURL,
  INTEGRATION_PROJECTS_ROOT: projectsRoot,
  INTEGRATION_RUN_ROOT: runRoot,
  PYTHONPATH: [repositoryRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  PLAYWRIGHT_BASE_URL: baseURL,
  PLAYWRIGHT_PORT: String(webPort),
  NEXT_PUBLIC_API_BASE_URL: apiBaseURL,
  NEXT_DIST_DIR: `.next-e2e-live-${path.basename(runRoot)}`,
};

// The tests inspect these values in the Playwright worker. Each run receives
// fresh project storage, server logs, runtime config, and browser artifacts.
process.env.INTEGRATION_API_BASE_URL = apiBaseURL;
process.env.INTEGRATION_PROJECTS_ROOT = projectsRoot;
process.env.INTEGRATION_RUN_ROOT = runRoot;
process.env.INTEGRATION_API_REQUESTS_LOG = apiRequestsLog;
process.env.INTEGRATION_SYNTHETIC_AUDIT_LOG = syntheticAuditLog;

export default defineConfig({
  testDir: "./tests/integration",
  testMatch: ["**/*.spec.ts"],
  fullyParallel: false,
  workers: 1,
  timeout: 300_000,
  expect: { timeout: 15_000 },
  outputDir: outputRoot,
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH
      ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } }
      : {}),
  },
  webServer: [
    {
      command: `python -m uvicorn apps.web.tests.integration.synthetic_api:app --host 127.0.0.1 --port ${apiPort} --log-level warning`,
      cwd: repositoryRoot,
      env: integrationEnvironment,
      url: `${apiBaseURL}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: `npm exec -- next dev -p ${webPort}`,
      cwd: path.join(repositoryRoot, "apps", "web"),
      env: integrationEnvironment,
      url: baseURL,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
