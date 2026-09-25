import { expect, test, type Route, type TestInfo } from "@playwright/test";

const projectId = "file:p-full-novel-workflow";
const encodedId = encodeURIComponent(projectId);
const projectPath = `/projects/${encodedId}`;
const projectIdea = "失业律师替陌生人追一笔旧账";

type FixtureOptions = {
  initialCandidate?: Record<string, unknown>;
  initialChapter?: number;
};

function completedChapter(chapterNumber: number, body = `第 ${chapterNumber} 章已确认正文。`) {
  return {
    chapter_number: chapterNumber,
    chapter_title: chapterNumber === 1 ? "雨夜遗嘱" : `旧账追查 ${chapterNumber}`,
    body,
    chapter_summary: {
      chapter_number: chapterNumber,
      summary: `律师查明第 ${chapterNumber} 章的一条旧账线索。`,
      facts: [],
      unresolved_threads: [],
    },
    next_outline: `继续核对第 ${chapterNumber + 1} 章的账目。`,
    quality_report: { ok: true, issues: [] },
  };
}

function reviewableCandidate(chapterNumber: number, hardBlocked = false) {
  const paragraphs = Array.from({ length: 13 }, (_, index) =>
    index === 12
      ? "第十三段是全文末段标记：律师在遗嘱背面找到了被涂掉的债主姓名。"
      : `第${index + 1}段：雨水沿着档案袋边缘滴落，律师逐项核对旧账留下的日期与签名。`,
  );
  return {
    schema_version: "candidate-draft/v1",
    candidate_id: `candidate-${chapterNumber}`,
    project_id: projectId,
    chapter_number: chapterNumber,
    chapter_title: `第 ${chapterNumber} 章候选稿`,
    body: paragraphs.join("\n\n"),
    context_snapshot_id: `canon-snapshot-${chapterNumber}`,
    quality_report: {
      ok: !hardBlocked,
      issues: hardBlocked ? ["canon.hard_blocker"] : [],
      writing_review: {
        pass: !hardBlocked,
        blocking: hardBlocked
          ? [{ code: "canon.hard_blocker", message: "遗嘱日期与已确认时间线冲突。", source: "canon", evidence: "snapshot-1" }]
          : [],
        warnings: [{ code: "review.warning.sample", message: "建议复核遗嘱递交时间。", source: "writing_review", evidence: "第2段" }],
      },
      modular_pipeline: {
        canon_review_snapshot: {
          as_of_chapter: chapterNumber - 1,
          state_source: "continuity_snapshot",
          bounded_state_available: true,
        },
        canon_preflight: {
          requested: ["债主身份"],
          prepared: ["债主身份"],
          missing: [],
        },
      },
    },
    revision_history: [],
    status: "pending",
    created_at: "2026-09-25T00:00:00Z",
    confirmed_at: "",
  };
}

const openingDirection = {
  id: "direction-1",
  title: "雨夜遗嘱",
  hook: "陌生人的遗嘱在雨夜生效。",
  logline: "一个失业律师收到陌生人的遗嘱后，必须查清旧账，否则会被当成伪造遗嘱的主谋。",
  protagonist_profile: "失业律师，擅长查证，但已经不愿再相信同行。",
  inciting_incident: "一份写着次日日期的遗嘱送到他的住处。",
  protagonist_goal: "查清旧账的真正债主。",
  main_conflict: "律师必须对抗伪造证据的前同事。",
  failure_stakes: "他会背上伪造遗嘱的罪名，证人也会被灭口。",
  growth_path: "从自保走向承担真相的代价。",
  excitement_point: "沿着遗嘱和旧账逐层翻出被改写的人生。",
  target_audience: "喜欢都市悬疑和职业查案的读者。",
  reader_promise: "每笔旧账解决一个现实困局，同时逼近伪造者。",
  ending_direction: "主角公开完整证据，并重新建立自己的事务所。",
  opening_promise: "每笔旧账都会牵出一段被改写的人生。",
  core_advantage: { name: "档案检索", type: "信息优势", ability: "提前发现账目中的矛盾", growth_rule: "逐步还原旧账链", limits: "一次只能查清一笔", early_payoff: "识破第一处涂改" },
  central_mystery: { surface_anomaly: "账目日期对不上", hidden_truth: "有人重写了债务记录", reality_impact: "证人被误认成债务人", reveal_path: ["核对遗嘱", "找到原始账本"] },
  initial_drive: { immediate_need: "洗清伪造遗嘱的嫌疑", trigger: "证人失联", short_term_goal: "找到旧账原件", failure_stakes: "被当成伪造者", long_term_transition: "从自保转向公开真相" },
};

function graphTask(status: string, taskId = "story_core", title = "故事核心") {
  return {
    task_id: taskId,
    title,
    status,
    dependencies: [],
    reads: ["opening.direction"],
    owns: ["opening.story_core"],
    artifact_revision: status === "completed" ? 1 : null,
    artifact_source: status === "completed" ? "llm" : null,
    validation_status: status === "completed" ? "passed" : "pending",
    diagnostics: [],
    provider: null,
    model: null,
    prompt_call_id: null,
  };
}

function orchestrationJob(jobId: string, completedTaskIds: string[]) {
  return {
    schema_version: "build-orchestration-job/v1",
    job_id: jobId,
    project_id: projectId,
    mode: "continue",
    status: "completed",
    current_task_id: null,
    current_task_title: null,
    next_task_id: null,
    completed_task_ids: completedTaskIds,
    failure_task_id: null,
    diagnostics: [],
    error_code: null,
    materialized: true,
    pipeline_stage: "outline_ready",
  };
}

async function installSyntheticFileProject(page: Page, options: FixtureOptions = {}) {
  const project = {
    project_id: projectId,
    title: "未命名作品",
    source_path: "",
    seed_outline: projectIdea,
    world_summary: "",
    current_focus: "查清遗嘱背后的旧账。",
    author_constraints: [],
    world_blueprint: {},
    character_profiles: [],
    relationship_graph: [],
    enabled_skill_ids: [],
    enabled_skill_module_ids: null,
    status: "draft",
    pipeline_stage: "idea_pending",
    active_story_id: projectId,
    branches: [],
    storage_source: "file",
  };
  const story = {
    story_id: projectId,
    outline: "律师核查遗嘱和一笔被改写的旧账。",
    genre: "都市悬疑",
    style: "白描",
    current_chapter: options.initialChapter ?? 0,
    agent_settings: { mode: "LLM-assisted", global_model: "", character_model: "", director_model: "", writer_model: "", memory_model: "", temperature: 0.7, new_character_policy: "Director review" },
    agent_runtime: { recent_events: [] },
    author_constraints: [],
    world_facts: ["遗嘱日期与旧账记录存在矛盾。"],
    characters: [],
    history: [] as ReturnType<typeof completedChapter>[],
    parent_story_id: null,
    branched_from_chapter: null,
  };
  const chapters = new Map<number, ReturnType<typeof completedChapter>>();
  if ((options.initialChapter ?? 0) > 0) {
    for (let chapter = 1; chapter <= (options.initialChapter ?? 0); chapter += 1) {
      chapters.set(chapter, completedChapter(chapter));
    }
    story.history = [...chapters.values()];
  }

  let selectedDirection = false;
  let firstVolumePublished = false;
  let nextVolumePublished = false;
  let orchestrationCount = 0;
  let generationCount = 0;
  let graphState: Record<string, unknown> = {
    schema_version: "build-workbench/v1",
    initialized: false,
    opening_graph: false,
    opening_chapter_count: null,
    opening_execution_started: false,
    opening_planning_pending: false,
    opening_confirmed_through: 0,
    opening_next_volume_available: false,
    opening_plan_versions: [],
    graph_id: "synthetic-opening-graph",
    graph_revision: 1,
    pipeline_stage: "idea_pending",
    materialization_status: "not_materialized",
    tasks: [],
  };
  let candidate: Record<string, unknown> | null = options.initialCandidate ?? null;
  const confirmationRequests: string[] = [];
  const generationRequests: number[] = [];

  await page.route("**/novel-types", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
      { id: "urban", name: "都市现代", description: "现实利益与身份关系。", builtin: true },
    ]) });
  });
  await page.route("**/skill-packs", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/file-projects", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ ...project, next_path: `${projectPath}/setup` }),
    });
  });

  await page.route("**/file-projects/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const projectPrefix = `/file-projects/${encodedId}`;
    const method = request.method();
    const respond = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

    if (path === projectPrefix && method === "GET") return respond(project);
    if (path.startsWith(`${projectPrefix}/opening-directions`)) {
      if (path.endsWith("/select")) {
        selectedDirection = true;
        project.pipeline_stage = "outlining";
        return respond({
          brief: { schema_version: "opening-brief/v1", mode: "inspiration", novel_type_id: "urban", idea: projectIdea, working_title: "" },
          directions: [openingDirection],
          selected_id: openingDirection.id,
          pipeline_stage: "outlining",
          next_path: `${projectPath}/outline`,
        });
      }
      if (method === "POST") {
        return respond({
          brief: { schema_version: "opening-brief/v1", mode: "inspiration", novel_type_id: "urban", idea: projectIdea, working_title: "" },
          directions: [openingDirection],
          selected_id: "",
          pipeline_stage: "direction_ready",
          next_path: `${projectPath}/setup`,
        });
      }
      return respond({
        brief: { schema_version: "opening-brief/v1", mode: "inspiration", novel_type_id: "urban", idea: projectIdea, working_title: "" },
        directions: selectedDirection ? [openingDirection] : [],
        selected_id: selectedDirection ? openingDirection.id : "",
        pipeline_stage: selectedDirection ? "outlining" : "idea_pending",
        next_path: `${projectPath}/outline`,
      });
    }
    if (path === `${projectPrefix}/build-graph/orchestrations/current`) return respond(null);
    if (path === `${projectPrefix}/build-graph` && method === "GET") return respond(graphState);
    if (path.startsWith(`${projectPrefix}/build-graph/tasks/`) && method === "GET") {
      const taskId = path.split("/").at(-1) || "story_core";
      return respond({
        task_id: taskId,
        title: taskId === "story_core" ? "故事核心" : `第 ${taskId.split("_").at(-1)} 章细纲`,
        status: "completed",
        editable: false,
        artifact: { revision: 1, source: "synthetic", payload: { summary: "律师查清遗嘱旧账。" } },
        owns: ["opening.story_core"],
        validation_status: "passed",
        diagnostics: [],
        materialization_status: "current",
        materialization_marker: null,
      });
    }
    if (path === `${projectPrefix}/build-graph/opening` && method === "POST") {
      graphState = {
        ...graphState,
        initialized: true,
        opening_graph: true,
        opening_chapter_count: 3,
        opening_execution_started: false,
        opening_planning_pending: false,
        graph_revision: Number(graphState.graph_revision) + 1,
        pipeline_stage: "world_ready",
        materialization_status: "outdated",
        tasks: [graphTask("ready")],
      };
      return respond(graphState);
    }
    if (path === `${projectPrefix}/build-graph/opening/volume-detail` && method === "POST") {
      graphState = {
        ...graphState,
        opening_chapter_count: 50,
        graph_revision: Number(graphState.graph_revision) + 1,
        materialization_status: "outdated",
        tasks: [graphTask("completed"), graphTask("ready", "chapter_outline_01", "第1章细纲")],
      };
      return respond(graphState);
    }
    if (path === `${projectPrefix}/build-graph/opening/next-volume` && method === "POST") {
      graphState = {
        ...graphState,
        opening_chapter_count: 100,
        opening_planning_pending: true,
        opening_next_volume_available: false,
        graph_revision: Number(graphState.graph_revision) + 1,
        materialization_status: "outdated",
        opening_plan_versions: [{ version: 1, start_chapter: 1, end_chapter: 50 }, { version: 2, start_chapter: 51, end_chapter: 100 }],
        tasks: [graphTask("ready", "chapter_outline_51", "第51章细纲")],
      };
      return respond(graphState);
    }
    if (path === `${projectPrefix}/build-graph/orchestrations` && method === "POST") {
      orchestrationCount += 1;
      const tasks = (graphState.tasks as Array<Record<string, unknown>>).map((task) => ({ ...task, status: "completed", artifact_revision: 1, artifact_source: "synthetic", validation_status: "passed" }));
      const pendingNextVolume = graphState.opening_planning_pending === true;
      if (pendingNextVolume) {
        nextVolumePublished = true;
        graphState = { ...graphState, opening_planning_pending: false, opening_execution_started: true, opening_confirmed_through: 50, opening_next_volume_available: false, materialization_status: "current", pipeline_stage: "outline_ready", tasks };
      } else if (Number(graphState.opening_chapter_count) === 50 && graphState.opening_execution_started !== true) {
        firstVolumePublished = true;
        graphState = { ...graphState, materialization_status: "current", pipeline_stage: "outline_ready", tasks };
      } else {
        graphState = { ...graphState, materialization_status: "current", pipeline_stage: "outline_ready", tasks };
      }
      return respond(orchestrationJob(`synthetic-build-${orchestrationCount}`, tasks.map((task) => String(task.task_id))));
    }
    if (path.startsWith(`${projectPrefix}/build-graph/orchestrations/`) && method === "GET") {
      return respond(orchestrationJob(`synthetic-build-${orchestrationCount}`, (graphState.tasks as Array<Record<string, unknown>>).map((task) => String(task.task_id))));
    }
    if (path.endsWith("/continuous-generation-jobs/current")) return respond(null);
    if (path.endsWith("/writing-packet")) {
      return respond({
        chapter_direction_options: { options: [], recommended_id: "" },
        next_chapter_outline: "律师追查遗嘱背后的旧账。",
        next_chapter_outline_source: "synthetic",
        rolling_fill: null,
      });
    }
    if (path.endsWith("/outline/volume-workflow")) {
      const targetChapter = Number(url.searchParams.get("target_chapter")) || story.current_chapter + 1;
      if (targetChapter > 50 && story.current_chapter >= 50) {
        return respond({
          schema_version: "volume-workflow/v1",
          target_chapter: targetChapter,
          status: nextVolumePublished ? "detail_complete" : "volume_missing",
          detail_status: nextVolumePublished ? "detail_complete" : "missing",
          next_action: nextVolumePublished ? "generate_prose" : "design_next_volume",
          volume_id: nextVolumePublished ? "volume-2" : null,
          volume_range: nextVolumePublished ? [51, 100] : null,
        });
      }
      return respond({
        schema_version: "volume-workflow/v1",
        target_chapter: targetChapter,
        status: firstVolumePublished ? "detail_complete" : "detail_partial",
        detail_status: firstVolumePublished ? "detail_complete" : "partial",
        next_action: firstVolumePublished ? "generate_prose" : "generate_volume_detail",
        volume_id: "volume-1",
        volume_range: [1, 50],
      });
    }
    if (path.endsWith("/candidates") && method === "GET") {
      const requestedChapter = Number(url.searchParams.get("chapter_number"));
      const items = candidate && Number(candidate.chapter_number) === requestedChapter ? [candidate] : [];
      return respond({ schema_version: "candidate-list/v1", items });
    }
    if (path.includes("/candidates/") && path.endsWith("/confirm") && method === "POST") {
      const force = url.searchParams.get("force") === "true";
      confirmationRequests.push(force ? "force" : "normal");
      if (candidate && (candidate.quality_report as Record<string, unknown>).ok === false) {
        return respond({ detail: "candidate_hard_blocked" }, 422);
      }
      if (!candidate) return respond({ detail: "candidate_not_found" }, 404);
      const confirmed = { ...candidate, status: "confirmed", confirmed_at: "2026-09-25T00:05:00Z" };
      const chapterNumber = Number(candidate.chapter_number);
      if (chapterNumber === 1) {
        chapters.set(1, completedChapter(1, String(candidate.body)));
        // Model the already human-confirmed remainder of volume one so this browser journey can
        // exercise the real volume-end controls without generating 49 repetitive test chapters.
        for (let number = 2; number <= 50; number += 1) chapters.set(number, completedChapter(number));
        story.current_chapter = 50;
        story.history = [...chapters.values()];
        graphState = {
          ...graphState,
          opening_execution_started: true,
          opening_confirmed_through: 50,
          opening_next_volume_available: true,
          materialization_status: "in_use",
        };
      } else {
        chapters.set(chapterNumber, completedChapter(chapterNumber, String(candidate.body)));
        story.current_chapter = chapterNumber;
        story.history = [...chapters.values()];
      }
      candidate = null;
      return respond({ candidate: confirmed, project, story });
    }
    if (path.endsWith("/generation-jobs") && method === "POST") {
      generationCount += 1;
      const chapterNumber = story.current_chapter + 1;
      generationRequests.push(chapterNumber);
      candidate = reviewableCandidate(chapterNumber);
      return respond({
        job_id: `synthetic-generation-${generationCount}`,
        story_id: projectId,
        status: "completed",
        progress: "候选稿已生成",
        steps: [],
        chapter_number: chapterNumber,
        error: "",
        created_at: "2026-09-25T00:01:00Z",
        updated_at: "2026-09-25T00:01:00Z",
      }, 201);
    }
    if (path.endsWith("/overview")) {
      const chapterIndex = [...chapters.values()].map((chapter) => ({
        chapter_number: chapter.chapter_number,
        chapter_title: chapter.chapter_title,
        body_chars: chapter.body.replace(/\s+/g, "").length,
        summary: chapter.chapter_summary.summary,
        next_focus: chapter.next_outline,
        has_quality_report: true,
        has_simulation: false,
      }));
      return respond({
        story_id: projectId,
        outline: story.outline,
        genre: story.genre,
        style: story.style,
        current_chapter: story.current_chapter,
        agent_settings: story.agent_settings,
        agent_runtime: story.agent_runtime,
        author_constraints: [],
        world_facts: story.world_facts,
        characters: [],
        chapters: chapterIndex,
        chapter_count: chapterIndex.length,
        total_body_chars: 0,
        storage_source: "file",
      });
    }
    if (path.includes("/chapters/")) {
      const chapterNumber = Number(path.split("/chapters/").at(-1));
      const chapter = chapters.get(chapterNumber);
      return chapter ? respond(chapter) : respond({ detail: `chapter_not_found:${chapterNumber}` }, 404);
    }
    return route.fallback();
  });

  await page.route("**/file-stories/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/file-stories/${encodedId}/overview`) {
      const chapterIndex = [...chapters.values()].map((chapter) => ({
        chapter_number: chapter.chapter_number,
        chapter_title: chapter.chapter_title,
        body_chars: chapter.body.replace(/\s+/g, "").length,
        summary: chapter.chapter_summary.summary,
        next_focus: chapter.next_outline,
        has_quality_report: true,
        has_simulation: false,
      }));
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        story_id: projectId,
        outline: story.outline,
        genre: story.genre,
        style: story.style,
        current_chapter: story.current_chapter,
        agent_settings: story.agent_settings,
        agent_runtime: story.agent_runtime,
        author_constraints: [],
        world_facts: story.world_facts,
        characters: [],
        chapters: chapterIndex,
        chapter_count: chapterIndex.length,
        total_body_chars: 0,
        storage_source: "file",
      }) });
      return;
    }
    if (path.includes("/chapters/")) {
      const chapterNumber = Number(path.split("/chapters/").at(-1));
      const chapter = chapters.get(chapterNumber);
      await route.fulfill({
        status: chapter ? 200 : 404,
        contentType: "application/json",
        body: JSON.stringify(chapter ?? { detail: `chapter_not_found:${chapterNumber}` }),
      });
      return;
    }
    await route.fallback();
  });

  return {
    project,
    story,
    chapters,
    confirmationRequests,
    generationRequests,
    get graph() { return graphState; },
  };
}

test("新书从开局方向进入 Build，人工确认后跨卷继续候选审查", async ({ page }, testInfo: TestInfo) => {
  test.setTimeout(120_000);
  const fixture = await installSyntheticFileProject(page);
  const creationRequests: unknown[] = [];
  await page.route("**/file-projects", async (route) => {
    if (route.request().method() === "POST") creationRequests.push(route.request().postDataJSON());
    await route.fallback();
  });

  await page.goto("/projects/new");
  await page.getByLabel("小说类型").selectOption("urban");
  await page.getByRole("textbox", { name: /^灵感/ }).fill(projectIdea);
  await page.getByRole("button", { name: "创建小说" }).click();
  await expect(page).toHaveURL(new RegExp(`${encodedId}/setup$`));
  expect(creationRequests).toEqual([{ mode: "inspiration", title: "", novel_type_id: "urban", idea: projectIdea }]);

  await expect(page.getByRole("heading", { name: "选择故事核心" })).toBeVisible();
  await expect(page.getByLabel("连续生产")).toHaveCount(0);
  await page.getByRole("button", { name: "生成故事方向" }).click();
  await page.getByRole("radio", { name: /雨夜遗嘱/ }).check();
  await page.getByRole("button", { name: "采用这个方向" }).click();
  await expect(page).toHaveURL(new RegExp(`${encodedId}/outline$`));

  await page.getByRole("link", { name: "开书构建" }).click();
  await expect(page.getByRole("heading", { name: "构建故事到章节的完整开局" })).toBeVisible();
  await expect(page.getByLabel("连续生产")).toHaveCount(0);
  await page.getByRole("button", { name: "启用完整开局图" }).click();
  await expect(page.getByRole("heading", { name: "完整开局图已启用" })).toBeVisible();
  await page.getByRole("button", { name: "继续构建" }).click();
  await expect(page.getByText("全部任务已就绪，世界、角色和前 3 章细纲已发布。")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "完整开局图已启用" })).toBeVisible();

  await page.getByRole("link", { name: "章节" }).click();
  await expect(page.getByLabel("Opening Graph 构建入口")).toContainText("请在开书构建中完成正式规划");
  await expect(page.getByRole("button", { name: "生成第一章" })).toBeDisabled();
  await expect(page.getByLabel("连续生产")).toHaveCount(0);
  await page.getByRole("link", { name: "前往开书构建" }).click();
  await expect(page.getByRole("heading", { name: "完整开局图已启用" })).toBeVisible();
  await page.getByRole("button", { name: "补齐首卷细纲任务" }).click();
  await expect(page.getByText(/细纲窗口：前 50 章/)).toBeVisible();
  await page.getByRole("button", { name: "继续构建" }).click();
  await page.reload();
  await expect(page.getByText(/细纲窗口：前 50 章/)).toBeVisible();
  await expect(page.getByText("2 / 2 已完成", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "前往正文候选与审查" }).click();
  await expect(page.getByRole("button", { name: "生成第一章" })).toBeEnabled();
  await expect(page.getByLabel("连续生产")).toHaveCount(0);
  await page.getByRole("button", { name: "生成第一章" }).click();
  await expect(page.getByLabel("候选稿")).toBeVisible();
  expect(fixture.generationRequests).toEqual([1]);

  const candidatePanel = page.getByLabel("候选稿");
  await expect(candidatePanel).toContainText("第1段：雨水沿着档案袋边缘");
  await expect(candidatePanel).toContainText("第十三段是全文末段标记");
  const review = page.getByLabel("候选稿审查结果");
  await expect(review).toContainText("正文审查状态：有警告或修改建议");
  await expect(review.getByLabel("Canon 审查快照")).toContainText("0");
  await expect(review.getByLabel("Canon 审查快照")).toContainText("continuity_snapshot");
  await expect(review.getByLabel("Canon 审查快照")).toContainText("bounded_state_available");
  await expect(review.getByLabel("Canon 实体预检")).toContainText("债主身份");
  await expect(review.getByLabel("Canon 实体预检")).toContainText("prepared");
  await page.screenshot({ path: testInfo.outputPath("candidate-review.png"), fullPage: true });

  await page.getByRole("button", { name: "确认提交" }).click();
  await expect.poll(() => fixture.confirmationRequests).toEqual(["normal"]);
  await expect(page).toHaveURL(new RegExp(`${encodedId}/write\\?chapter=1$`));
  expect(fixture.story.current_chapter).toBe(50);

  await page.getByRole("link", { name: "开书构建" }).click();
  await expect(page.getByText("已用于正文，规划已锁定", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "扩展下一卷细纲任务" })).toBeVisible();
  await page.getByRole("button", { name: "扩展下一卷细纲任务" }).click();
  await expect(page.getByText("下一卷规划扩展中。完成并发布全部细纲之前，正文候选入口保持关闭。"))
    .toBeVisible();
  await page.getByRole("button", { name: "继续构建" }).click();
  await page.reload();
  await expect(page.getByText("规划版本：v1（第 1–50 章）、v2（第 51–100 章）")).toBeVisible();
  await expect(page.getByRole("link", { name: "前往正文候选与审查" })).toBeVisible();

  await page.getByRole("link", { name: "前往正文候选与审查" }).click();
  await expect(page.getByRole("button", { name: "生成下一章" })).toBeEnabled();
  await page.getByRole("button", { name: "生成下一章" }).click();
  await expect(page.getByLabel("下一章候选稿已保留")).toContainText("第 51 章候选稿已经生成并保留");
  await page.getByRole("link", { name: "查看第 51 章候选稿" }).click();
  await expect(page).toHaveURL(new RegExp(`${encodedId}/write\\?chapter=51$`));
  await expect(page.getByLabel("候选稿")).toContainText("第十三段是全文末段标记");
  await expect(page.getByLabel("候选稿审查结果").getByLabel("Canon 审查快照")).toContainText("50");
  expect(fixture.generationRequests).toEqual([1, 51]);
  expect(nextVolumeState(fixture.graph)).toBe("published");
});

function nextVolumeState(graph: Record<string, unknown>): string {
  return graph.opening_planning_pending === false && graph.opening_chapter_count === 100
    ? "published"
    : "pending";
}

test("Canon hard blocker 的强制确认被拒绝且候选保留", async ({ page }) => {
  const blockedCandidate = reviewableCandidate(1, true);
  const fixture = await installSyntheticFileProject(page, { initialChapter: 1, initialCandidate: blockedCandidate });
  await page.goto(`${projectPath}/write?chapter=1`);

  const candidatePanel = page.getByLabel("候选稿");
  await expect(candidatePanel).toBeVisible();
  const review = page.getByLabel("候选稿审查结果");
  await expect(review).toContainText("canon.hard_blocker");
  await expect(review).toContainText("遗嘱日期与已确认时间线冲突");
  await expect(candidatePanel.getByRole("button", { name: "仍然采用" })).toHaveCount(0);
  await candidatePanel.getByRole("button", { name: "确认提交" }).click();

  await expect.poll(() => fixture.confirmationRequests).toEqual(["normal"]);
  await expect(candidatePanel).toBeVisible();
  await expect(page.getByText("candidate_hard_blocked")).toBeVisible();
  expect(fixture.confirmationRequests).not.toContain("normal");
});
