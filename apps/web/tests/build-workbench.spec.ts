import { expect, test, type Page } from "@playwright/test";

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

test.beforeEach(async ({ page }) => {
  await page.route(`**/file-projects/${encodedId}/build-graph/orchestrations/current`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "null" });
  });
});

test("完整开局图需要显式启用，刷新保留后端状态并支持同步作者输入", async ({ page }) => {
  const currentGraph = { ...graph([]), initialized: false, opening_graph: false };
  await routeProjectAndGraph(page, currentGraph);
  let writes = 0;
  await page.route(/\/build-graph\/opening(?:\/input)?$/, async (route) => {
    writes += 1;
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ expected_graph_revision: currentGraph.graph_revision });
    Object.assign(currentGraph, {
      initialized: true, opening_graph: true, graph_revision: currentGraph.graph_revision + 1,
      pipeline_stage: "world_ready", materialization_status: "outdated",
      tasks: [task(0, { task_id: "story_core", title: "故事核心", status: "ready", artifact_revision: null })],
    });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentGraph) });
  });
  await page.goto(`/projects/${encodedId}/build`);
  await expect(page.getByRole("button", { name: "启用完整开局图" })).toBeVisible();
  expect(writes).toBe(0);
  await page.getByRole("button", { name: "启用完整开局图" }).click();
  await expect(page.getByRole("heading", { name: "完整开局图已启用" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: "继续构建" })).toBeVisible();
  expect(writes).toBe(1);
  await page.getByRole("button", { name: "同步作者输入" }).click();
  await expect.poll(() => writes).toBe(2);
});

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
    materialization_status: "current",
    tasks,
  };
}

test("首卷扩展需显式操作，正文确认后规划动作锁定", async ({ page }) => {
  const currentGraph = { ...graph([task(0)]), opening_graph: true, opening_chapter_count: 3, opening_execution_started: false };
  await routeProjectAndGraph(page, currentGraph);
  let writes = 0;
  await page.route(/\/build-graph\/opening\/volume-detail$/, async (route) => {
    writes += 1;
    expect(route.request().postDataJSON()).toEqual({ expected_graph_revision: 33 });
    Object.assign(currentGraph, { opening_chapter_count: 50, graph_revision: 34 });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentGraph) });
  });
  await page.goto(`/projects/${encodedId}/build`);
  await expect(page.getByText(/细纲窗口：前 3 章/)).toBeVisible();
  expect(writes).toBe(0);
  await page.getByRole("button", { name: "补齐首卷细纲任务" }).click();
  await expect(page.getByText(/细纲窗口：前 50 章/)).toBeVisible();
  expect(writes).toBe(1);
  await expect(page.getByRole("link", { name: "前往正文候选与审查" })).toHaveAttribute("href", `/projects/${encodedId}/write`);
  Object.assign(currentGraph, { opening_execution_started: true, materialization_status: "in_use" });
  await page.reload();
  await expect(page.getByText("已用于正文，规划已锁定", { exact: true })).toBeVisible();
  for (const name of ["同步作者输入", "补齐首卷细纲任务", "继续构建", "重建过期项", "运行下一任务"]) {
    await expect(page.getByRole("button", { name, exact: true })).toBeDisabled();
  }
  expect(writes).toBe(1);
});

test("卷末显式扩展下一卷，刷新后显示版本和待构建任务", async ({ page }) => {
  const currentGraph = {
    ...graph([task(0)]), opening_graph: true, opening_chapter_count: 50,
    opening_execution_started: true, opening_planning_pending: false,
    opening_confirmed_through: 50, opening_next_volume_available: true,
    opening_plan_versions: [], materialization_status: "in_use",
  };
  await routeProjectAndGraph(page, currentGraph);
  let writes = 0;
  await page.route(/\/build-graph\/opening\/next-volume$/, async (route) => {
    writes += 1;
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ expected_graph_revision: 33 });
    Object.assign(currentGraph, {
      opening_chapter_count: 100, opening_planning_pending: true,
      opening_next_volume_available: false, graph_revision: 34,
      materialization_status: "outdated", pipeline_stage: "world_ready",
      opening_plan_versions: [{ version: 1, start_chapter: 1, end_chapter: 50 }],
      tasks: [task(0), task(1, { task_id: "chapter_outline_51", title: "第51章细纲", status: "ready", artifact_revision: null })],
    });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentGraph) });
  });
  await page.goto(`/projects/${encodedId}/build`);
  await expect(page.getByRole("button", { name: "扩展下一卷细纲任务" })).toBeVisible();
  expect(writes).toBe(0);
  await page.getByRole("button", { name: "扩展下一卷细纲任务" }).click();
  await expect(page.getByText("下一卷规划扩展中。完成并发布全部细纲之前，正文候选入口保持关闭。")).toBeVisible();
  await expect(page.getByRole("button", { name: "继续构建" })).toBeEnabled();
  await expect(page.getByText("规划版本：v1（第 1–50 章）")).toBeVisible();
  await page.reload();
  await expect(page.getByText("第51章细纲")).toBeVisible();
  expect(writes).toBe(1);
});

async function routeProjectAndGraph(page: Page, response: ReturnType<typeof graph>) {
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  let reads = 0;
  await page.route(`**/file-projects/${encodedId}/build-graph`, async (route) => {
    reads += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(response) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph/tasks/**`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const taskId = route.request().url().split("/build-graph/tasks/")[1];
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      task_id: taskId,
      title: taskId,
      status: "completed",
      editable: false,
      artifact: { revision: 1, source: "llm", payload: { label: "Initial" } },
      owns: ["build.output"],
      validation_status: "passed",
      diagnostics: [],
      materialization_status: "current",
      materialization_marker: null,
    }) });
  });
  return () => reads;
}

test("模型预检展示服务端结果，且预览不启动任务执行", async ({ page }) => {
  const currentGraph = graph([
    task(0, { task_id: "world_model", title: "世界规则", dependencies: [], reads: [], owns: ["world.rules"] }),
  ]);
  await routeProjectAndGraph(page, currentGraph);
  let preflightCalls = 0;
  let executionCalls = 0;
  await page.route(`**/file-projects/${encodedId}/build-graph/tasks/**`, async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        task_id: "world_model", title: "世界规则", status: "completed", editable: true,
        artifact: { revision: 1, source: "llm", payload: { label: "Initial" } },
        owns: ["world.rules"], validation_status: "passed", diagnostics: [],
        materialization_status: "current", materialization_marker: null,
      }) });
    } else if (request.url().endsWith("/preflight")) {
      preflightCalls += 1;
      expect(request.postDataJSON()).toEqual({ expected_revision: 1, operation: "rerun" });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        task_id: "world_model", operation: "rerun", preflight_report: {
          status: preflightCalls === 1 ? "READY" : "BLOCKED",
          reason: preflightCalls === 1 ? "within_context_limit" : "max_output_limit_not_enforceable_by_adapter",
          provider: "provider-x",
          protocol: "codex_cli", requested_model: "model-y", resolved_model: null,
          estimates: { required_input_tokens: 241, optional_input_tokens: 0, reserved_output_tokens: 1024, safety_margin_tokens: 128 },
          output_budget: preflightCalls === 1
            ? { policy: "best_effort", mode: "estimate_only", enforced: false, requested_tokens: 1024, estimated_tokens: 1024, uncertainty: "实际响应可能超过预算估算值。" }
            : { policy: "required", mode: "blocked_unenforceable", enforced: false, requested_tokens: 1024, estimated_tokens: 1024, uncertainty: "此请求要求 provider 强制执行输出上限。" },
          estimate_method: "utf8_bytes_div3_v1", capabilities: { json_mode: { state: "unknown", source: "unknown" } },
          output_enforcement: { state: "unsupported", source: "repository_adapter_contract", method: "cli_has_no_per_request_output_limit" },
          limits: {}, effective_preflight_guards: {}, unknown_capability_policy: "continue_bounded_without_claiming_support",
          unknown_limit_policy: { action: "bounded_legacy_compatibility_guard" }, adjustments: [], repair_actions: [],
        },
      }) });
    } else {
      executionCalls += 1;
      await route.fallback();
    }
  });

  await page.goto(`/projects/${encodedId}/build`);
  await page.getByRole("button", { name: /世界规则/ }).click();
  await page.getByRole("button", { name: "预检完整重跑" }).click();
  await expect(page.getByText("模型预检：READY · within_context_limit", { exact: true })).toBeVisible();
  await expect(page.getByText(/utf8_bytes_div3_v1/)).toBeVisible();
  await expect(page.getByText(/当前协议无法强制执行输出预算/)).toBeVisible();
  await page.getByText("能力来源、限额和兼容策略").click();
  await expect(page.getByText(/output_budget/)).toBeVisible();
  await expect(page.getByText(/output_enforcement/)).toBeVisible();
  await page.getByRole("button", { name: "预检完整重跑" }).click();
  await expect(page.getByText(/模型预检：BLOCKED/)).toBeVisible();
  await expect(page.getByText(/此请求要求执行输出硬上限.*模型调用已在执行前阻断/)).toBeVisible();
  expect(preflightCalls).toBe(2);
  expect(executionCalls).toBe(0);
});

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

test("人工编辑先校验再保存，刷新后显示新 revision 与 stale 下游", async ({ page }) => {
  let currentGraph = graph([
    task(0, { task_id: "world_model", title: "世界规则", dependencies: [], reads: [], owns: ["world.rules"] }),
    task(1, { task_id: "downstream", title: "下游设定", dependencies: ["world_model"], reads: ["world.rules"], owns: ["world.detail"] }),
  ]);
  currentGraph.materialization_status = "current";
  let saved = false;
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentGraph) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph/tasks/**`, async (route) => {
    const request = route.request();
    const taskId = request.url().split("/build-graph/tasks/")[1];
    if (request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        task_id: taskId,
        title: taskId,
        status: "completed",
        editable: taskId === "world_model",
        artifact: { revision: saved ? 2 : 1, source: saved ? "human" : "llm", payload: { label: saved ? "Edited" : "Initial" } },
        owns: ["world.rules"],
        validation_status: "passed",
        diagnostics: [],
        materialization_status: saved ? "outdated" : "current",
        materialization_marker: { artifact_revisions: { world_model: 1 } },
      }) });
    } else if (request.method() === "POST" && request.url().endsWith("/validate")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ passed: true, disposition: "PASS_AUTO", diagnostics: [] }) });
    } else if (request.method() === "PATCH") {
      saved = true;
      currentGraph = {
        ...currentGraph,
        graph_revision: 35,
        pipeline_stage: "world_ready",
        materialization_status: "outdated",
        tasks: currentGraph.tasks.map((item) => item.task_id === "world_model"
          ? { ...item, artifact_revision: 2, artifact_source: "human" }
          : { ...item, status: "stale" }),
      };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        artifact: { revision: 2, source: "human", payload: { label: "Edited" } },
        pipeline_stage: "world_ready",
        materialization_status: "outdated",
      }) });
    } else await route.fallback();
  });

  await page.goto(`/projects/${encodedId}/build`);
  await page.getByRole("button", { name: /世界规则/ }).click();
  await page.getByRole("button", { name: "人工编辑" }).click();
  const editor = page.getByRole("textbox", { name: "Artifact JSON draft" });
  await editor.fill('{"label":"Edited"}');
  await page.getByRole("button", { name: "校验" }).click();
  await expect(page.getByText("校验通过 · PASS_AUTO")).toBeVisible();
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByText("world_ready", { exact: true })).toBeVisible();
  await expect(page.getByText("上游修改后，以下任务已过期")).toBeVisible();
  await expect(page.getByText("旧物化结果已过期").first()).toBeVisible();
  await expect(page.getByText("r2 · 人工编辑", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("r2 · 人工编辑", { exact: true })).toBeVisible();
});

test("AI 修复阻止覆盖本地草稿，并在成功后刷新后端 revision", async ({ page }) => {
  let currentGraph = graph([
    task(0, { task_id: "world_model", title: "世界规则", dependencies: [], reads: [], owns: ["world.rules"] }),
  ]);
  let repaired = false;
  let repairAttempts = 0;
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentGraph) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph/tasks/**`, async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        task_id: "world_model", title: "世界规则", status: "completed", editable: true,
        artifact: { revision: repaired ? 2 : 1, source: repaired ? "ai_repair" : "llm", payload: { label: repaired ? "Repaired" : "Initial" } },
        owns: ["world.rules"], validation_status: "passed", diagnostics: [],
        materialization_status: repaired ? "outdated" : "current", materialization_marker: null,
      }) });
    } else if (request.method() === "POST" && request.url().endsWith("/repair")) {
      repairAttempts += 1;
      if (repairAttempts === 1) {
        await new Promise((resolve) => setTimeout(resolve, 350));
        await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: {
          passed: false,
          diagnostics: [{ code: "task.repair_out_of_scope", path: "payload", message: "修复响应包含未授权字段" }],
        } }) });
        return;
      }
      repaired = true;
      currentGraph = { ...currentGraph, graph_revision: 34, pipeline_stage: "world_ready", materialization_status: "outdated",
        tasks: currentGraph.tasks.map((item) => ({ ...item, artifact_revision: 2, artifact_source: "ai_repair" })) };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        artifact: { revision: 2, source: "ai_repair", payload: { label: "Repaired" } }, pipeline_stage: "world_ready", materialization_status: "outdated",
      }) });
    } else await route.fallback();
  });

  await page.goto(`/projects/${encodedId}/build`);
  await page.getByRole("button", { name: /世界规则/ }).click();
  await page.getByRole("button", { name: "人工编辑" }).click();
  await page.getByRole("textbox", { name: "Artifact JSON draft" }).fill('{"label":"unsaved"}');
  await page.getByRole("button", { name: "AI 修复", exact: true }).click();
  await expect(page.getByText("当前有未保存的 JSON 草稿。请先保存或取消草稿，再运行 AI 修复。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "取消" }).click();
  await page.getByRole("button", { name: "AI 修复", exact: true }).click();
  await expect(page.getByRole("button", { name: "AI 修复中…", exact: true })).toBeDisabled();
  await expect(page.getByText("task.repair_out_of_scope", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "AI 修复", exact: true }).click();
  await expect(page.getByText("r2 · AI 修复", { exact: true })).toBeVisible();
  await expect(page.getByText("旧物化结果已过期").first()).toBeVisible();
});

test("完整重跑发送当前 revision，成功后刷新完整产物并显示 stale 下游", async ({ page }) => {
  let currentGraph = graph([
    task(0, { task_id: "world_model", title: "世界规则", dependencies: [], reads: [], owns: ["world.rules"] }),
    task(1, { task_id: "downstream_model", title: "下游设定", status: "completed", artifact_revision: 1 }),
  ]);
  let rerun = false;
  let requestBody: Record<string, unknown> | null = null;
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentGraph) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph/tasks/**`, async (route) => {
    const request = route.request();
    if (request.method() === "GET") {
      const taskId = request.url().split("/build-graph/tasks/")[1];
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        task_id: taskId,
        title: taskId,
        status: "completed",
        editable: taskId === "world_model",
        artifact: taskId === "world_model"
          ? { revision: rerun ? 2 : 1, source: "llm", payload: { label: rerun ? "Regenerated" : "Initial" } }
          : { revision: 1, source: "llm", payload: { detail: "Downstream" } },
        owns: ["world.rules"],
        validation_status: "passed",
        diagnostics: [],
        materialization_status: rerun ? "outdated" : "current",
        materialization_marker: { artifact_revisions: { world_model: 1 } },
      }) });
    } else if (request.method() === "POST" && request.url().endsWith("/rerun")) {
      requestBody = request.postDataJSON() as Record<string, unknown>;
      rerun = true;
      currentGraph = {
        ...currentGraph,
        graph_revision: 34,
        pipeline_stage: "world_ready",
        materialization_status: "outdated",
        tasks: currentGraph.tasks.map((item) => item.task_id === "world_model"
          ? { ...item, artifact_revision: 2, artifact_source: "llm" }
          : { ...item, status: "stale" }),
      };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        artifact: { revision: 2, source: "llm", payload: { label: "Regenerated" } },
        pipeline_stage: "world_ready",
        materialization_status: "outdated",
      }) });
    } else await route.fallback();
  });

  await page.goto(`/projects/${encodedId}/build`);
  await page.getByRole("button", { name: /世界规则/ }).click();
  await expect(page.getByRole("button", { name: "完整重跑", exact: true })).toBeVisible();
  await expect(page.getByText("完整重生成此任务；成功后下游会标记为过期，不会自动重跑。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "完整重跑", exact: true }).click();
  await expect(page.getByText("r2 · AI 生成", { exact: true })).toBeVisible();
  await expect(page.getByText("上游修改后，以下任务已过期")).toBeVisible();
  expect(requestBody).toEqual({ expected_revision: 1 });
});

test("重建过期项显示运行任务、完成任务与重新物化结果", async ({ page }) => {
  let currentGraph = {
    ...graph([
      task(0, { task_id: "world_model", title: "世界规则", artifact_revision: 2, artifact_source: "human", dependencies: [] }),
      task(1, { task_id: "downstream_model", title: "下游设定", status: "stale" }),
    ]),
    pipeline_stage: "world_ready",
    materialization_status: "outdated",
  };
  const jobId = "wbo-1234567890abcdef1234567890abcdef";
  let jobReads = 0;
  let requestedMode = "";
  const running = {
    schema_version: "build-orchestration-job/v1", job_id: jobId, project_id: projectId,
    mode: "rebuild_stale", status: "running", current_task_id: "downstream_model",
    current_task_title: "下游设定", next_task_id: "downstream_model",
    completed_task_ids: [], failure_task_id: null, diagnostics: [], error_code: null,
    materialized: false, pipeline_stage: "world_ready",
  };
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph`, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(currentGraph) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph/tasks/**`, async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    const taskId = route.request().url().split("/build-graph/tasks/")[1];
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      task_id: taskId, title: taskId, status: "completed", editable: false,
      artifact: { revision: 1, source: "llm", payload: {} }, owns: [],
      validation_status: "passed", diagnostics: [], materialization_status: "outdated", materialization_marker: null,
    }) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph/orchestrations`, async (route) => {
    requestedMode = (route.request().postDataJSON() as { mode: string }).mode;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(running) });
  });
  await page.route(`**/file-projects/${encodedId}/build-graph/orchestrations/${jobId}`, async (route) => {
    jobReads += 1;
    if (jobReads >= 3) {
      currentGraph = {
        ...currentGraph, pipeline_stage: "environment_ready", materialization_status: "current",
        tasks: currentGraph.tasks.map((item) => item.task_id === "downstream_model"
          ? { ...item, status: "completed", artifact_revision: 2, artifact_source: "llm" } : item),
      };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(jobReads < 3 ? running : {
      ...running, status: "completed", current_task_id: null, current_task_title: null,
      next_task_id: null, completed_task_ids: ["downstream_model"], materialized: true,
      pipeline_stage: "environment_ready",
    }) });
  });

  await page.goto(`/projects/${encodedId}/build`);
  await page.getByRole("button", { name: "重建过期项" }).click();
  await expect(page.getByText("当前任务：下游设定")).toBeVisible();
  await expect(page.getByText("本次构建已结束")).toBeVisible();
  await expect(page.getByText("已完成任务：下游设定")).toBeVisible();
  await expect(page.getByText("全部任务已就绪，世界设定已重新物化。")).toBeVisible();
  await expect(page.getByText("environment_ready", { exact: true })).toBeVisible();
  expect(requestedMode).toBe("rebuild_stale");
});
