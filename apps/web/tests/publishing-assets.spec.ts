import { expect, test, type Page, type Route } from "@playwright/test";

import * as api from "../lib/api";

const projectId = "file:publishing fixture";
const encodedId = encodeURIComponent(projectId);

function project(assets: unknown, storageSource: "file" | "sqlite" = "file") {
  return {
    project_id: projectId,
    title: "雾港来信",
    source_path: "D:/novels/mist-harbor",
    seed_outline: "",
    world_summary: "",
    current_focus: "",
    author_constraints: [],
    world_blueprint: {},
    character_profiles: [],
    relationship_graph: [],
    enabled_skill_ids: [],
    status: "writing",
    pipeline_stage: "writing",
    active_story_id: projectId,
    branches: [],
    storage_source: storageSource,
    publishing_assets: assets,
  };
}

const emptyAssets = { schema_version: "publishing-assets/v1", synopsis: null, cover: null };

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function routePublishingProject(page: Page, assets: unknown = emptyAssets, storageSource: "file" | "sqlite" = "file") {
  let current = project(assets, storageSource);
  let overviewReads = 0;
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    if (new URL(route.request().url()).pathname !== `/file-projects/${encodedId}`) {
      await route.fallback();
      return;
    }
    await fulfill(route, current);
  });
  await page.route(`**/file-stories/${encodedId}/overview`, async (route) => {
    overviewReads += 1;
    await fulfill(route, { story_id: projectId, chapter_count: 0, total_body_chars: 0, chapters: [], storage_source: "file" });
  });
  return {
    reads: () => overviewReads,
    update(nextAssets: unknown) { current = project(nextAssets, storageSource); },
  };
}

test("publishing API encodes the file-project id and unwraps endpoint envelopes", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const clients = api as typeof api & {
    generateSynopsis: (id: string, guidance?: string) => Promise<unknown>;
    updateSynopsis: (id: string, payload: { tags: string[]; body: string }) => Promise<unknown>;
    generateCover: (id: string, guidance?: string) => Promise<unknown>;
    updateCoverPrompt: (id: string, prompt: string) => Promise<unknown>;
    renderCoverTitle: (id: string) => Promise<unknown>;
    coverImageUrl: (id: string, version: string, download?: boolean) => string;
  };
  try {
    globalThis.fetch = async (input, init) => {
      calls.push({ url: String(input), init });
      const url = String(input);
      const body = url.includes("synopsis")
        ? { synopsis: { tags: ["悬疑", "都市", "成长", "反转"], body: "简介", format: "fanqie", updated_at: "2026-07-31" } }
        : url.includes("render-title")
          ? { status: "ready", cover: { prompt: "提示词", image_version: "v2" } }
          : url.includes("cover-prompt")
            ? { cover: { prompt: "新提示词", image_version: "v1" } }
            : { status: "prompt_ready", reason: "image_provider_not_configured", cover: { prompt: "提示词" } };
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    };
    await expect(clients.generateSynopsis(projectId, "更克制")).resolves.toMatchObject({ body: "简介" });
    await expect(clients.updateSynopsis(projectId, { tags: ["悬疑", "都市", "成长", "反转"], body: "简介" })).resolves.toMatchObject({ body: "简介" });
    await expect(clients.generateCover(projectId, "夜色")).resolves.toMatchObject({ status: "prompt_ready" });
    await expect(clients.updateCoverPrompt(projectId, "新提示词")).resolves.toMatchObject({ prompt: "新提示词" });
    await expect(clients.renderCoverTitle(projectId)).resolves.toMatchObject({ image_version: "v2" });
    expect(clients.coverImageUrl(projectId, "v & 2", true)).toContain(`/file-projects/${encodedId}/publishing/cover.png?version=v%20%26%202&download=1`);
    expect(calls.map((call) => call.url)).toEqual(expect.arrayContaining([
      expect.stringContaining(`/file-projects/${encodedId}/publishing/synopsis`),
      expect.stringContaining(`/file-projects/${encodedId}/publishing/cover`),
      expect.stringContaining(`/file-projects/${encodedId}/publishing/cover-prompt`),
      expect.stringContaining(`/file-projects/${encodedId}/publishing/cover/render-title`),
    ]));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("file projects show independent empty synopsis and cover cards", async ({ page }) => {
  await routePublishingProject(page);
  const requests: string[] = [];
  await page.route(`**/file-projects/${encodedId}/publishing/**`, async (route) => {
    requests.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    await fulfill(route, { synopsis: { tags: ["悬疑", "都市", "成长", "反转"], body: "一封来信，牵出港口旧案。", format: "fanqie", updated_at: "2026-07-31" } });
  });
  await page.goto(`/projects/${encodedId}`);
  await expect(page.getByRole("heading", { name: "简介" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "封面" })).toBeVisible();
  await expect(page.getByRole("button", { name: "生成简介" })).toBeVisible();
  await expect(page.getByRole("button", { name: "生成封面" })).toBeEnabled();
  await page.getByRole("button", { name: "生成简介" }).click();
  await expect(page.getByText("一封来信，牵出港口旧案。")).toBeVisible();
  expect(requests).toEqual([`POST /file-projects/${encodedId}/publishing/synopsis`]);
  await expect(page.getByRole("button", { name: "生成封面" })).toBeEnabled();
});

test("prompt-ready cover remains editable without a broken image or generation on save", async ({ page }) => {
  await routePublishingProject(page, {
    schema_version: "publishing-assets/v1",
    synopsis: null,
    cover: { prompt: "港口、旧信、潮雾" },
  });
  const requests: string[] = [];
  await page.route(`**/file-projects/${encodedId}/publishing/**`, async (route) => {
    requests.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    await fulfill(route, { cover: { prompt: "港口、旧信、冷色潮雾" } });
  });
  await page.goto(`/projects/${encodedId}`);
  await expect(page.getByText("图像模型尚未配置")).toBeVisible();
  await expect(page.getByRole("link", { name: "前往配置" })).toHaveAttribute("href", "/config");
  await expect(page.getByRole("button", { name: "复制提示词" })).toBeVisible();
  await expect(page.locator("img")).toHaveCount(0);
  await page.getByRole("button", { name: "编辑提示词" }).click();
  await page.getByLabel("封面提示词").fill("港口、旧信、冷色潮雾");
  await page.getByRole("button", { name: "保存提示词" }).click();
  await expect(page.getByText("港口、旧信、冷色潮雾")).toBeVisible();
  expect(requests).toEqual([`PUT /file-projects/${encodedId}/publishing/cover-prompt`]);
});

test("synopsis editing validates, saves only PUT, and cancel preserves the asset", async ({ page }) => {
  await routePublishingProject(page, {
    schema_version: "publishing-assets/v1",
    synopsis: { tags: ["悬疑", "都市", "成长", "反转"], body: "旧简介仍然可见。", format: "fanqie", updated_at: "2026-07-30" },
    cover: null,
  });
  const requests: string[] = [];
  await page.route(`**/file-projects/${encodedId}/publishing/**`, async (route) => {
    requests.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    await fulfill(route, { synopsis: { tags: ["悬疑", "都市", "成长", "反转"], body: "新简介。", format: "fanqie", updated_at: "2026-07-31" } });
  });
  await page.goto(`/projects/${encodedId}`);
  await page.getByRole("button", { name: "编辑简介" }).click();
  await page.getByLabel("标签").fill("悬疑，都市");
  await page.getByRole("button", { name: "保存简介" }).click();
  await expect(page.getByText("标签需保留 4 至 8 个")).toBeVisible();
  await page.getByRole("button", { name: "取消" }).click();
  await expect(page.getByText("旧简介仍然可见。")).toBeVisible();
  await page.getByRole("button", { name: "编辑简介" }).click();
  await page.getByLabel("标签").fill("悬疑，都市，成长，反转");
  await page.getByLabel("简介正文").fill("新简介。");
  await page.getByRole("button", { name: "保存简介" }).click();
  await expect(page.getByText("新简介。")).toBeVisible();
  expect(requests).toEqual([`PUT /file-projects/${encodedId}/publishing/synopsis`]);
});

test("ready cover uses a versioned 3:4 image and rerenders stale title without regeneration", async ({ page }) => {
  await routePublishingProject(page, {
    schema_version: "publishing-assets/v1",
    synopsis: null,
    cover: { prompt: "港口、旧信", image_version: "final-v1", base_image_version: "base-v1", rendered_from_base_version: "base-v1", rendered_title: "旧书名" },
  });
  const requests: string[] = [];
  await page.route(`**/file-projects/${encodedId}/publishing/cover/render-title`, async (route) => {
    requests.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    await fulfill(route, { status: "ready", cover: { prompt: "港口、旧信", image_version: "final-v2", base_image_version: "base-v1", rendered_from_base_version: "base-v1", rendered_title: "雾港来信" } });
  });
  await page.goto(`/projects/${encodedId}`);
  const image = page.getByRole("img", { name: "雾港来信封面" });
  await expect(image).toHaveAttribute("src", new RegExp("cover\\.png\\?version=final-v1"));
  await expect(page.getByText("书名已变化，重新排版")).toBeVisible();
  await page.getByRole("button", { name: "重新排版" }).click();
  await expect(image).toHaveAttribute("src", new RegExp("cover\\.png\\?version=final-v2"));
  expect(requests).toEqual([`POST /file-projects/${encodedId}/publishing/cover/render-title`]);
  await expect(page.getByRole("link", { name: "下载封面" })).toHaveAttribute("href", new RegExp("cover\\.png\\?version=final-v2&download=1"));
});

test("publishing cards are not mounted for SQLite projects", async ({ page }) => {
  await routePublishingProject(page, emptyAssets, "sqlite");
  await page.route(`**/file-projects/${encodedId}`, async (route) => {
    await fulfill(route, { ...project(emptyAssets, "sqlite"), project_id: "sqlite-project" });
  });
  await page.goto(`/projects/${encodedId}`);
  await expect(page.getByRole("heading", { name: "简介" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "封面" })).toHaveCount(0);
});
