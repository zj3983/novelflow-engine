import { expect, test, type Page } from "@playwright/test";

async function voiceFixture(page: Page) {
  const project = {
    project_id: "file:writing-preferences-fixture",
    title: "写法设置测试",
    source_path: "",
    seed_outline: "",
    world_summary: "",
    current_focus: "",
    storage_source: "file",
    active_story_id: "file:writing-preferences-fixture",
    status: "writing",
    pipeline_stage: "world_ready",
    branches: [],
    world_blueprint: {
      genre_plugin_ids: ["generic_webnovel"],
      writing_style: "",
      writing_guidance: "",
      writing_reference: "",
      premise: "保留原来的故事想法",
    },
    author_constraints: [], character_profiles: [], relationship_graph: [], enabled_skill_ids: [],
  };
  const patches: Record<string, unknown>[] = [];
  let failNextSave = false;
  await page.route("**/novel-types", async (route) => {
    await route.fulfill({ json: [{ id: "generic_webnovel", name: "通用网文", description: "", builtin: true }] });
  });
  await page.route("**/file-projects/file%3Awriting-preferences-fixture", async (route) => {
    if (route.request().method() === "PUT") {
      const patch = route.request().postDataJSON() as { world_blueprint?: Record<string, unknown> };
      patches.push(patch.world_blueprint ?? {});
      if (failNextSave) {
        failNextSave = false;
        await route.fulfill({ status: 500, json: { detail: "save_failed" } });
        return;
      }
      project.world_blueprint = { ...project.world_blueprint, ...(patch.world_blueprint ?? {}) };
    }
    await route.fulfill({ json: project });
  });
  await page.route("**/file-stories/file%3Awriting-preferences-fixture/overview", async (route) => {
    await route.fulfill({ json: {
      story_id: project.active_story_id, current_chapter: 2, style: project.world_blueprint.writing_style,
      chapter_index: [], agent_runtime: { recent_events: [] }, characters: [], world_facts: [],
    } });
  });
  await page.goto("/projects/file%3Awriting-preferences-fixture/settings");
  return { project, patches, failNext: () => { failNextSave = true; } };
}

test("自定义写法和参考片段可保存刷新并清空，修改文风保留未保存文字", async ({ page }) => {
  const fixture = await voiceFixture(page);
  const guidance = page.getByLabel("自定义写法", { exact: true });
  const reference = page.getByLabel("参考片段", { exact: true });
  await guidance.fill("嘴上吐槽，行动谨慎。允许自然口语和适量网络梗。");
  await reference.fill("我超威，这给我干哪来了，这还是国内吗？");
  await page.getByLabel("当前文风").selectOption("幽默");
  await expect(page.getByText("文风已保存为：幽默。下一次写作会读取这个选择。")).toBeVisible();
  await expect(guidance).toHaveValue("嘴上吐槽，行动谨慎。允许自然口语和适量网络梗。");
  await page.getByRole("button", { name: "保存写法", exact: true }).click();
  await expect(page.getByText("写法已保存，续写、连写和重写都会读取。现有章节保持原样。")).toBeVisible();
  expect(fixture.patches.at(-1)).toEqual({
    writing_guidance: "嘴上吐槽，行动谨慎。允许自然口语和适量网络梗。",
    writing_reference: "我超威，这给我干哪来了，这还是国内吗？",
  });
  expect(fixture.project.world_blueprint.premise).toBe("保留原来的故事想法");
  await page.reload();
  await expect(guidance).toHaveValue(fixture.project.world_blueprint.writing_guidance);
  await expect(reference).toHaveValue(fixture.project.world_blueprint.writing_reference);
  await expect(page.getByLabel("当前文风")).toHaveValue("幽默");
  await guidance.fill("");
  await reference.fill("");
  await page.getByRole("button", { name: "保存写法", exact: true }).click();
  await expect.poll(() => fixture.project.world_blueprint.writing_guidance).toBe("");
  await expect.poll(() => fixture.project.world_blueprint.writing_reference).toBe("");
  expect(fixture.project.world_blueprint.writing_style).toBe("幽默");
});

test("写法保存失败保留草稿，可以重试且不需要选择预设文风", async ({ page }) => {
  const fixture = await voiceFixture(page);
  await page.getByLabel("自定义写法", { exact: true }).fill("只用自然口语，不强行抖包袱。");
  fixture.failNext();
  await page.getByRole("button", { name: "保存写法", exact: true }).click();
  await expect(page.getByText("写法保存失败，输入已保留，请重试。")).toBeVisible();
  await expect(page.getByLabel("自定义写法", { exact: true })).toHaveValue("只用自然口语，不强行抖包袱。");
  await page.getByRole("button", { name: "保存写法", exact: true }).click();
  await expect(page.getByText("写法已保存，续写、连写和重写都会读取。现有章节保持原样。")).toBeVisible();
  expect(fixture.project.world_blueprint.writing_style).toBe("");
  expect(fixture.project.world_blueprint.writing_guidance).toBe("只用自然口语，不强行抖包袱。");
});

test("章节页显示当前采用的本书写法并可返回设置", async ({ page }) => {
  const fixture = await voiceFixture(page);
  fixture.project.world_blueprint.writing_style = "幽默";
  fixture.project.world_blueprint.writing_guidance = "自然口语";
  fixture.project.world_blueprint.writing_reference = "一句接话示例";
  await page.goto("/projects/file%3Awriting-preferences-fixture/write");
  await expect(page.getByLabel("本书写法")).toContainText("后续写作采用：幽默 · 自定义写法 · 参考片段");
  await page.getByRole("link", { name: "调整写法", exact: true }).click();
  await expect(page.getByLabel("自定义写法", { exact: true })).toHaveValue("自然口语");
});
