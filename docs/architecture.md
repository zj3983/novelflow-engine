# Architecture

The project is split into three thin layers:

- `packages/story_core`
  Holds the long-lived story state, chapter generation loop, memory compression, and bundle validation.
- `apps/api`
  Exposes create, generate, and rollback endpoints over the story engine.
- `apps/web`
  Provides a browser workbench for generating chapters and inspecting continuity data.

## Story loop

1. Read the current `StoryState`.
2. Generate the next chapter body and next-beat outline.
3. Compress the chapter into facts, unresolved threads, timeline events, and foreshadowing.
4. Validate that the generated bundle still has continuity anchors.
5. Return the bundle to the API and UI.
