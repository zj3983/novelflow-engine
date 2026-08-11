import { expect, test, type Page, type Route } from "@playwright/test";

const skillPack = {
  schema_version: "skill-pack/v1",
  skill_id: "commercial-shuangwen",
  name: "Commercial Shuangwen",
  version: "1.0.0",
  description: "Focused writing methods.",
  module_count: 2,
  modules: [
    { module_id: "writer-execution", title: "Writer Execution", purposes: ["writer"] },
    { module_id: "genre-examples", title: "Genre Examples", purposes: ["writer"] },
  ],
};

type SelectionMode = "legacy_all" | "explicit";

function projectResponse(
  projectId: string,
  moduleIds: string[] | null,
  selectionMode?: SelectionMode,
) {
  return {
    project_id: projectId,
    title: "Skill Selection Test",
    source_path: "",
    seed_outline: "",
    world_summary: "",
    current_focus: "",
    author_constraints: [],
    world_blueprint: {},
    character_profiles: [],
    relationship_graph: [],
    enabled_skill_ids: ["commercial-shuangwen"],
    enabled_skill_module_ids: moduleIds,
    ...(selectionMode ? { skill_module_selection_mode: selectionMode } : {}),
    status: "draft",
    pipeline_stage: "draft",
    active_story_id: "",
    branches: [],
    publishing_assets: { schema_version: "publishing-assets/v1", synopsis: null, cover: null },
  };
}

async function routeSkillsProject(
  page: Page,
  projectId: string,
  initialProject: ReturnType<typeof projectResponse>,
) {
  let project = initialProject;
  const updates: Array<Record<string, unknown>> = [];
  await page.route(`**/projects/${projectId}`, async (route: Route) => {
    if (route.request().method() === "PUT") {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      updates.push(payload);
      project = {
        ...project,
        ...payload,
        skill_module_selection_mode: "explicit",
      };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(project) });
  });
  await page.route("**/skill-packs", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([skillPack]) });
  });
  return updates;
}

test("legacy mode renders every enabled pack module selected and expands the first toggle", async ({ page }) => {
  const projectId = "ui-legacy-skills";
  const updates = await routeSkillsProject(
    page,
    projectId,
    projectResponse(projectId, [], "legacy_all"),
  );

  await page.goto(`/projects/${projectId}/skills`);
  const toggles = page.locator('.ws-skill-module input[type="checkbox"]');
  await expect(toggles).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    await expect(toggles.nth(index)).toBeChecked();
  }

  await toggles.first().click();
  await expect.poll(() => updates.length).toBe(1);
  expect(updates[0]).toMatchObject({
    enabled_skill_ids: ["commercial-shuangwen"],
    enabled_skill_module_ids: [
      "commercial-shuangwen::writer-execution",
      "commercial-shuangwen::genre-examples",
    ],
  });
});

test("explicit empty mode renders no selected modules", async ({ page }) => {
  const projectId = "ui-explicit-empty-skills";
  await routeSkillsProject(page, projectId, projectResponse(projectId, [], "explicit"));

  await page.goto(`/projects/${projectId}/skills`);
  const toggles = page.locator('.ws-skill-module input[type="checkbox"]');
  await expect(toggles).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    await expect(toggles.nth(index)).not.toBeChecked();
  }
  await expect(page.getByText("0 个模块启用")).toBeVisible();
});

test("older responses without a mode flag retain null-based legacy behavior", async ({ page }) => {
  const projectId = "ui-old-backend-skills";
  await routeSkillsProject(page, projectId, projectResponse(projectId, null));

  await page.goto(`/projects/${projectId}/skills`);
  const toggles = page.locator('.ws-skill-module input[type="checkbox"]');
  await expect(toggles).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    await expect(toggles.nth(index)).toBeChecked();
  }
});
