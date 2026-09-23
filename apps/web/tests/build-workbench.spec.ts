import { expect, test } from "@playwright/test";

const projectId = "file:build-workbench-fixture";
const encodedId = encodeURIComponent(projectId);
const project = {
  project_id: projectId,
  title: "Build Workbench 验收项目",
  source_path: "",
  seed_outline: "",
  world_summary: "",
  current_focus: "",
  author_constraints: [],
  world_blueprint: {},
  character_profiles: [],
  relationship_graph: [],
  enabled_skill_ids: [],
  enabled_skill_module_ids: null,
  status: "draft",
  pipeline_stage: "environment_ready",
  active_story_id: "",
  storage_source: "file",
};

function task(index: number, overrides: Record<string, unknown> = {}) {
  const taskId = `task_${String(index).padStart(2, "0")}`;
  return {
    task_id: taskId,
    title: `构建任务 ${index}`,
    status: "completed",
    dependencies: index > 0 ? [`task_${String(index - 1).padStart(2, "0")}`] : [],
    reads: [`build.input_${index}`],
    owns: [`build.output_${index}`],
    artifact_revision: 1,
    artifact_source: index === 0 ? "llm" : index === 1 ? "ai_repair" : index === 2 ? "deterministic" : "llm",
    validation_status: "passed",
    diagnostics: [],
    provider: index === 0 ? "provider-x" : null,
    model: index === 0 ? "model-y" : null,
    prompt_call_id: index === 0 ? "prompt-call-z" : null,
    ...overrides,
  };
}

function graph(tasks: ReturnType<typeof task>[]) {
  return {
    schema_version: "build-workbench/v1",
    initialized: true,
    graph_id: "novelflow-project-build",
    graph_revision: 33,
    pipeline_stage: "environment_ready",
    tasks,
  };
}

async function routeProjectAndGraph(page, response: ReturnType<typeof graph>) {
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  let reads = 0;
  await page.route(`**/file-projects/${encodedId}/build-graph`, async (route) => {
    reads += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) });
  });
  return () => reads;
}

test("15 个完成任务显示正式状态、来源和版本，刷新后仍从后端读取", async ({ page }) => {
  const fixtureGraph = graph(Array.from({ length: 15 }, (_, index) => task(index)));
  const readCount = await routeProjectAndGraph(page, fixtureGraph);

  await page.goto(`/projects/${encodedId}/build`);

  await expect(page.getByText("environment_ready", { exact: true })).toBeVisible();
  await expect(page.getByText("15 / 15 已完成", { exact: true })).toBeVisible();
  await expect(page.locator("ol").getByRole("listitem")).toHaveCount(15);
  await expect(page.getByText("AI 生成", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("r1 · AI 修复", { exact: true })).toBeVisible();
  await expect(page.getByText("r1 · 系统生成", { exact: true })).toBeVisible();
  await expect(page.getByText("r1 · AI 生成", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("build.input_0", { exact: true })).toBeVisible();
  await expect(page.getByText("build.output_0", { exact: true })).toBeVisible();
  await expect(page.getByText("provider-x", { exact: true })).toBeVisible();
  await expect(page.getByText("model-y", { exact: true })).toBeVisible();
  await expect(page.getByText("prompt-call-z", { exact: true })).toBeVisible();

  const readsBeforeReload = readCount();
  await page.reload();
  await expect(page.getByText("15 / 15 已完成", { exact: true })).toBeVisible();
  expect(readCount()).toBeGreaterThan(readsBeforeReload);
});

test("失败、受阻、过期、运行中和待审核状态及诊断依赖清晰区分", async ({ page }) => {
  const fixtureGraph = graph([
    task(0, {
      task_id: "validation_failed",
      title: "校验失败任务",
      status: "validation_failed",
      validation_status: "failed",
      diagnostics: [{ code: "required_field_missing", path: "world.rules[0]", message: "规则名称不能为空", severity: "blocking" }],
    }),
    task(1, { task_id: "blocked", title: "受阻任务", status: "blocked", dependencies: ["validation_failed"], artifact_revision: null, artifact_source: null }),
    task(2, { task_id: "stale", title: "过期任务", status: "stale" }),
    task(3, { task_id: "running", title: "运行中任务", status: "running", artifact_revision: null, artifact_source: null }),
    task(4, { task_id: "review_required", title: "待审核任务", status: "review_required" }),
  ]);
  await routeProjectAndGraph(page, fixtureGraph);

  await page.goto(`/projects/${encodedId}/build`);
  await expect(page.locator("ol").getByRole("listitem")).toHaveCount(5);
  await expect(page.getByText("校验失败", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("受阻", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("已过期", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("进行中", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("待审核", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("required_field_missing", { exact: true })).toBeVisible();
  await expect(page.getByText("world.rules[0]", { exact: true })).toBeVisible();
  await expect(page.getByText("规则名称不能为空", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: /受阻任务/ }).click();
  await expect(page.getByRole("heading", { name: "受阻任务" })).toBeVisible();
  await expect(page.getByRole("button", { name: "校验失败任务 validation_failed", exact: true })).toBeVisible();
});
