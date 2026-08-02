import { expect, test } from "@playwright/test";

import { fetchProject } from "../lib/api";

test("fetchProject safely loads a legacy mock project without publishing assets", async () => {
  const projectId = "legacy-local-project";
  const storedProject = {
    project_id: projectId,
    title: "Legacy Local Project",
    source_path: "D:/novels/legacy-local",
    seed_outline: "",
    world_summary: "",
    current_focus: "",
    author_constraints: [],
    status: "draft",
    active_story_id: "",
    branches: [],
  };
  const storage = new Map<string, string>([
    ["novel-autogrowth-engine.projects", JSON.stringify([[projectId, storedProject]])],
  ]);
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalFetch = globalThis.fetch;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => storage.set(key, value),
      },
    },
  });
  globalThis.fetch = async () => new Response("null", { status: 200, headers: { "content-type": "application/json" } });

  try {
    const project = await fetchProject(projectId);
    expect(project.publishing_assets).toEqual({
      schema_version: "publishing-assets/v1",
      synopsis: null,
      cover: null,
    });
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else delete (globalThis as { window?: unknown }).window;
  }
});
