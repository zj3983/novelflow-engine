# Lazy Chapter Loading Design

## Problem

File-backed projects currently load `ProjectResponse` and then a complete `StoryResponse` in the shared workspace provider. The story response hydrates every chapter, including body text and quality reports, before any project page can render.

For the imported 142-chapter novel this makes navigation take tens of seconds. Increasing frontend timeouts only hides the symptom. Payload size and server work continue to grow with every chapter, so the current design cannot scale to long-running novels.

## Goals

- Make project overview and navigation usable in about one second on a local workstation.
- Load one chapter in about one second without work proportional to the total chapter count.
- Keep directory browsing practical for novels with at least 1,000 chapters.
- Preserve current generation, regeneration, review, prompt, and non-file-project behavior.
- Keep the existing full-story endpoint temporarily for compatibility.

## Non-Goals

- Replacing file storage with a database.
- Redesigning the chapter reader UI.
- Adding remote synchronization or multi-user caching.
- Reworking generation prompts or chapter quality rules.

## API Design

### Story Overview

Add `GET /file-stories/{story_id}/overview`.

The response contains story-level state required by shared project pages:

- `story_id`, `genre`, `style`, and `current_chapter`
- agent settings and runtime state
- author constraints, writing lessons, world facts, and characters
- `chapter_count`
- a lightweight `chapters` directory

Each directory entry contains only:

- `chapter_number`
- `chapter_title`
- `body_chars`
- short chapter summary
- short next-focus text
- whether a quality report exists and its simplified status when already persisted

It must not include chapter body text, scene cards, event plans, updated story snapshots, or full quality reports. The implementation reads each chapter JSON once and does not call chapter display hydration.

### Chapter Detail

Add `GET /file-stories/{story_id}/chapters/{chapter_number}`.

This endpoint returns one existing `ChapterBundle`, including hydrated display fields and its complete quality report. A missing story or chapter returns `404` with the existing file-story error conventions.

The amount of work must be independent of total chapter count except for locating the project directory. Direct project lookup should be used when the public file ID names the project directory.

### Compatibility

Keep `GET /file-stories/{story_id}` unchanged during migration. Existing callers and tests may continue using the full response. New workspace code must not use it for file projects.

## Frontend Data Flow

### Workspace Provider

For file projects, `ProjectWorkspaceProvider` loads:

1. project details;
2. story overview after the active story ID is known.

For non-file projects, it keeps the existing `fetchStory` behavior.

The context exposes project data plus an overview-compatible story object and refresh version. It does not download every chapter body.

### Chapter Page

The write page uses the lightweight directory for search, pagination, titles, summaries, and character counts. It fetches chapter detail using the requested `chapter` query value. If no chapter is requested, it fetches `current_chapter`.

Changing the query parameter fetches only the newly selected chapter. The previous chapter can remain visible while the next detail is loading, with a local loading state that does not blank the entire workspace.

After generation or regeneration:

- refresh project and story overview;
- fetch only the generated or regenerated chapter detail;
- do not fetch the legacy full story response.

### Other Pages

Overview, world, characters, relationships, outline, and settings use story-level overview data. Pages that require a complete chapter, such as review and chapter-specific prompt views, fetch that chapter through the detail endpoint.

## Types

Introduce explicit frontend types rather than representing directory entries as body-less `ChapterBundle` objects:

- `FileStoryOverview`
- `ChapterIndexEntry`
- `ChapterDetailResponse` or the existing `ChapterBundle`

This prevents accidental assumptions that an overview entry contains body text or a full quality report.

## Error Handling

- Project and overview errors remain workspace-level errors.
- Chapter-detail errors render inside the chapter content area while leaving navigation and the directory usable.
- Requests use existing abort and timeout handling, but normal operation must complete well below the timeout.
- A chapter deleted between overview and detail requests produces a clear `chapter_not_found` message and permits selecting another chapter.

## Performance Constraints

Automated tests must verify structural performance properties instead of relying only on wall-clock timing:

- overview generation never calls full chapter hydration;
- chapter detail hydrates exactly one chapter;
- project summary reads each chapter file at most once;
- file workspace code does not call the legacy full-story endpoint.

Manual verification on the 142-chapter imported project must record:

- project endpoint duration;
- overview endpoint duration and payload size;
- one chapter-detail endpoint duration and payload size;
- visible time to project overview and chapter reader.

Acceptance targets on the local development machine are about one second for overview and one second for a chapter detail. The critical scaling requirement is that chapter-detail latency does not increase with total chapter count.

## Testing

Backend tests cover:

- overview schema and omission of chapter bodies;
- directory ordering, character counts, summaries, and quality status;
- one-chapter detail parity with the existing hydrated chapter;
- 404 behavior;
- no hydration during overview and exactly one hydration during detail.

Frontend tests cover:

- file projects use overview instead of the legacy full story call;
- chapter pages request the selected chapter only;
- chapter switching preserves the directory and updates the body;
- generation and regeneration refresh only overview and target detail;
- non-file projects retain current behavior.

Type checking and focused API/UI tests run before browser verification against the imported 142-chapter project.

## Rollout

1. Add backend overview and chapter-detail endpoints with tests.
2. Add frontend API types and clients.
3. Migrate the workspace provider and chapter page.
4. Migrate review and prompt pages that need chapter details.
5. Verify all project pages and generation refresh flows.
6. Keep the legacy full-story endpoint until all internal callers are removed; deletion is a separate change.
