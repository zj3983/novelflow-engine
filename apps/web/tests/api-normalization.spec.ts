import { expect, test } from "@playwright/test";

import { normalizeProjectResponse, regenerateFileProjectChapter } from "../lib/api";

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
  const raw = {
    ...legacyProject,
    publishing_assets: {
      schema_version: "future/v2",
      synopsis: { tags: ["都市", "悬疑", "成长", "群像"], body: "简介", format: "fanqie", updated_at: "now" },
      cover: {
        prompt: "noir city",
        width: -1,
        height: Number.NaN,
        model: "image-v2",
        future,
        thumbnail_path: "../../secret.png",
        constructor: { polluted: true },
      },
      audiobook: { narrator: "Voice", chapters: [1, 2] },
      __proto__: { polluted: true },
    },
  };

  const normalized = normalizeProjectResponse(raw);
  const assets = normalized.publishing_assets as unknown as {
    audiobook?: unknown;
    cover: { future?: typeof future; width?: number; height?: number; thumbnail_path?: string; constructor?: unknown };
  };
  expect(assets.audiobook).toEqual({ narrator: "Voice", chapters: [1, 2] });
  expect(assets.cover).toMatchObject({ prompt: "noir city", model: "image-v2", future });
  expect(assets.cover.width).toBeUndefined();
  expect(assets.cover.height).toBeUndefined();
  expect(assets.cover.thumbnail_path).toBeUndefined();
  expect(Object.prototype.hasOwnProperty.call(assets.cover, "constructor")).toBe(false);

  future.palette[0] = "mutated-input";
  expect(assets.cover.future?.palette[0]).toBe("ink");
  assets.cover.future!.nested.contrast = 1;
  expect(future.nested.contrast).toBe(0.8);
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
