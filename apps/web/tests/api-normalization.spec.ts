import { expect, test } from "@playwright/test";

import {
  fetchCurrentWorldBuildJob,
  normalizeProjectResponse,
  regenerateFileProjectChapter,
} from "../lib/api";

const legacyProject = {
  project_id: "file:legacy",
  title: "Legacy",
  source_path: "D:/novels/legacy",
  seed_outline: "",
  world_summary: "",
  current_focus: "",
  author_constraints: [],
  status: "draft",
  active_story_id: "file-story:legacy",
  branches: [],
};

test("project responses normalize missing and malformed publishing assets", () => {
  expect(normalizeProjectResponse(legacyProject).publishing_assets).toEqual({
    schema_version: "publishing-assets/v1",
    synopsis: null,
    cover: null,
  });
  expect(normalizeProjectResponse({ ...legacyProject, publishing_assets: [] }).publishing_assets).toEqual({
    schema_version: "publishing-assets/v1",
    synopsis: null,
    cover: null,
  });
});

test("publishing normalization preserves safe future data without aliases or unsafe keys", () => {
  const future = { palette: ["ink", "gold"], nested: { contrast: 0.8 } };
  const synopsisFuture = {
    marketing_angles: ["high concept", "slow-burn mystery"],
    visual_hook: "A red umbrella beneath a black tower",
    campaign: { audiences: ["mystery readers"] },
    campaign_path: "../../private-plan.json",
  };
  const synopsis = {
    tags: ["都市", "悬疑", "成长", "群像"],
    body: "简介",
    format: "fanqie",
    updated_at: "now",
    ...synopsisFuture,
  };
  const unsafeOwnFields = JSON.parse('{"__proto__":{"polluted":true},"constructor":{"polluted":true},"prototype":{"polluted":true}}') as object;
  for (const [key, value] of Object.entries(unsafeOwnFields)) {
    Object.defineProperty(synopsis, key, { configurable: true, enumerable: true, value });
  }
  const cover = {
    prompt: "noir city",
    width: -1,
    height: Number.NaN,
    model: "image-v2",
    future,
    thumbnail_path: "../../secret.png",
  };
  for (const [key, value] of Object.entries(unsafeOwnFields)) {
    Object.defineProperty(cover, key, { configurable: true, enumerable: true, value });
  }
  const publishingAssets = {
    schema_version: "future/v2",
    synopsis,
    cover,
    audiobook: { narrator: "Voice", chapters: [1, 2] },
  };
  for (const [key, value] of Object.entries(unsafeOwnFields)) {
    Object.defineProperty(publishingAssets, key, { configurable: true, enumerable: true, value });
  }
  const raw = {
    ...legacyProject,
    publishing_assets: publishingAssets,
  };

  const normalized = normalizeProjectResponse(raw);
  const { campaign_path: _unsafeCampaignPath, ...safeSynopsisFuture } = synopsisFuture;
  const assets = normalized.publishing_assets as unknown as {
    audiobook?: unknown;
    synopsis: typeof synopsisFuture & { tags: string[]; body: string; format: string; updated_at: string };
    cover: { future?: typeof future; width?: number; height?: number; thumbnail_path?: string; constructor?: unknown };
  };
  expect(assets.audiobook).toEqual({ narrator: "Voice", chapters: [1, 2] });
  expect(assets.cover).toMatchObject({ prompt: "noir city", model: "image-v2", future });
  expect(assets.cover.width).toBeUndefined();
  expect(assets.cover.height).toBeUndefined();
  expect(assets.cover.thumbnail_path).toBeUndefined();
  expect(Object.prototype.hasOwnProperty.call(assets.cover, "__proto__")).toBe(false);
  expect(Object.prototype.hasOwnProperty.call(assets.cover, "constructor")).toBe(false);
  expect(Object.prototype.hasOwnProperty.call(assets.cover, "prototype")).toBe(false);
  expect(assets.synopsis).toMatchObject(safeSynopsisFuture);
  expect(Object.prototype.hasOwnProperty.call(assets, "__proto__")).toBe(false);
  expect(Object.prototype.hasOwnProperty.call(assets, "constructor")).toBe(false);
  expect(Object.prototype.hasOwnProperty.call(assets, "prototype")).toBe(false);
  expect(Object.prototype.hasOwnProperty.call(assets.synopsis, "__proto__")).toBe(false);
  expect(Object.prototype.hasOwnProperty.call(assets.synopsis, "constructor")).toBe(false);
  expect(Object.prototype.hasOwnProperty.call(assets.synopsis, "prototype")).toBe(false);
  expect((assets.synopsis as { campaign_path?: string }).campaign_path).toBeUndefined();
  expect(({} as { polluted?: boolean }).polluted).toBeUndefined();

  future.palette[0] = "mutated-input";
  expect(assets.cover.future?.palette[0]).toBe("ink");
  assets.cover.future!.nested.contrast = 1;
  expect(future.nested.contrast).toBe(0.8);
  synopsisFuture.marketing_angles[0] = "mutated-input";
  expect(assets.synopsis.marketing_angles[0]).toBe("high concept");
  assets.synopsis.campaign.audiences[0] = "mutated-output";
  expect(synopsisFuture.campaign.audiences[0]).toBe("mystery readers");
});

test("publishing normalization keeps optional canonical cover fields", () => {
  const normalized = normalizeProjectResponse({
    ...legacyProject,
    publishing_assets: {
      cover: {
        prompt: "cover",
        width: 1024,
        height: 1536,
        mime_type: "image/png",
        image_version: "image-v1",
        base_image_version: "base-v1",
        rendered_from_base_version: "base-v1",
        rendered_title: "Legacy",
        updated_at: "now",
        schema_version: "cover/v1",
        base_path: "assets/cover-base.png",
        rendered_path: "assets/cover.png",
      },
    },
  });
  expect(normalized.publishing_assets.cover).toMatchObject({
    width: 1024,
    height: 1536,
    schema_version: "cover/v1",
    base_path: "assets/cover-base.png",
    rendered_path: "assets/cover.png",
  });
});

test("nested regeneration responses normalize legacy project publishing assets at the API boundary", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    project: { ...legacyProject, publishing_assets: { synopsis: "malformed", cover: [] } },
    story: {},
    generated: {},
  }), { status: 200, headers: { "content-type": "application/json" } });
  try {
    const result = await regenerateFileProjectChapter("file:legacy", 1);
    expect(result.project.publishing_assets).toEqual({
      schema_version: "publishing-assets/v1",
      synopsis: null,
      cover: null,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchCurrentWorldBuildJob returns null on 404 and exposes interrupted/conflicted statuses", async () => {
  const originalFetch = globalThis.fetch;
  const job = {
    schema_version: "world-build-job/v1",
    job_id: "wbg-rehydrate",
    project_id: "file:rehydrate",
    status: "interrupted",
    progress: "服务已重启，请重新开始补全",
    active_module_id: "core_rules",
    active_module_title: "核心规则",
    active_module_status: "interrupted",
    error: "",
    created_at: "2025-01-01T00:00:00+00:00",
    updated_at: "2025-01-01T00:00:00+00:00",
  };
  let called = 0;
  globalThis.fetch = async () => {
    called += 1;
    if (called === 1) {
      return new Response("not found", { status: 404 });
    }
    return new Response(JSON.stringify(job), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    expect(await fetchCurrentWorldBuildJob("file:missing")).toBeNull();
    const rehydrated = await fetchCurrentWorldBuildJob("file:rehydrate");
    expect(rehydrated?.status).toBe("interrupted");
    expect(rehydrated?.active_module_status).toBe("interrupted");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
