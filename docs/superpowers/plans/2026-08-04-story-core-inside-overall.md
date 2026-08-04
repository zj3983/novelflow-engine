# Story Core Inside Overall Outline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `outline.overall` the only persisted source for story positioning, protagonist drive, core advantage, central mystery, and long-term direction.

**Architecture:** Extend `OverallOutline` with the missing structured core groups, then turn the existing story-core helpers into compatibility projections over `overall`. New opening selections write directly into the outline transaction. The outline page edits these fields inside the existing 总纲 tab, while planning and writing consume stage-specific slices derived from the outline.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, pytest, Next.js, React, TypeScript, Playwright.

---

### Task 1: Extend The Overall Outline Schema

**Files:**
- Modify: `packages/story_core/project_outline.py`
- Modify: `tests/story_core/test_project_outline.py`

- [ ] **Step 1: Write a failing round-trip test**

Add a test that normalizes an outline containing `positioning`, `protagonist_drive`, `core_advantage`, and `central_mystery`, then asserts every nested field survives unchanged.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pytest -q tests/story_core/test_project_outline.py -k overall_story_core`

Expected: validation fails because `OverallOutline` forbids the new fields.

- [ ] **Step 3: Add focused Pydantic models**

Define `StoryPositioning`, `ProtagonistDrive`, `OutlineCoreAdvantage`, and `OutlineCentralMystery`, then add them to `OverallOutline` with default factories. Keep existing flat fields such as `story`, `protagonist_goal`, `main_conflict`, `growth_path`, and `ending_direction` as the canonical nonduplicated fields.

- [ ] **Step 4: Preserve the fields in selected chapter context**

Add the four structured groups to `select_outline_context(...)["overall"]` so later stages can project from one normalized structure.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run: `pytest -q tests/story_core/test_project_outline.py -k overall_story_core`

Expected: PASS.

### Task 2: Replace Story Core Persistence With Overall Projections

**Files:**
- Modify: `packages/story_core/story_core_card.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `tests/story_core/test_story_core_card.py`
- Modify: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing compatibility tests**

Add tests proving that `story_core()` derives its response from `outline.overall`, `update_story_core()` updates the outline instead of creating `story_core.json`, and a legacy `story_core.json` only fills empty overall fields.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest -q tests/story_core/test_story_core_card.py tests/story_core/test_file_project_store.py -k "story_core or legacy_core"`

Expected: at least one test fails because the current store writes `.webnovel/story_core.json`.

- [ ] **Step 3: Add pure conversion helpers**

Implement `story_core_from_overall(overall, title)`, `merge_story_core_into_overall(overall, core)`, and stage projections that start from the normalized overall structure. Merge only into empty destinations so user-edited outline content wins.

- [ ] **Step 4: Change store ownership**

Make `story_core()` return the compatibility projection from `project_outline()["overall"]`. If empty fields can be filled from an old file, perform an idempotent outline migration under the project update lock. Make `update_story_core()` merge the submitted compatibility payload into `outline.overall` and write `outline.json` atomically without writing a core file.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run: `pytest -q tests/story_core/test_story_core_card.py tests/story_core/test_file_project_store.py -k "story_core or legacy_core"`

Expected: PASS.

### Task 3: Write New Opening Choices Directly Into Overall

**Files:**
- Modify: `packages/story_core/story_core_card.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `tests/story_core/test_opening_directions.py`
- Modify: `tests/api/test_file_project_creation_routes.py`

- [ ] **Step 1: Write a failing selection test**

Select an opening direction and assert that the resulting `outline.json` contains the complete core fields while `.webnovel/story_core.json` does not exist.

- [ ] **Step 2: Run the selection test and verify RED**

Run: `pytest -q tests/story_core/test_opening_directions.py tests/api/test_file_project_creation_routes.py -k "select and story_core"`

Expected: FAIL because the current transaction writes `story_core.json`.

- [ ] **Step 3: Seed complete overall content**

Update `outline_seed_from_story_core()` to populate the new structured overall groups and update `select_opening_direction()` to omit the standalone core file from its transaction.

- [ ] **Step 4: Run the selection test and verify GREEN**

Run: `pytest -q tests/story_core/test_opening_directions.py tests/api/test_file_project_creation_routes.py -k "select and story_core"`

Expected: PASS.

### Task 4: Remove Duplicate Prompt Inputs

**Files:**
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/writing_packet.py`
- Modify: `tests/story_core/test_outline_planning_generation.py`
- Modify: `tests/story_core/test_writing_packet.py`

- [ ] **Step 1: Write failing context-boundary tests**

Assert that whole-book outline generation receives one `overall` object rather than `story_core`, `character_story_core`, and `planning_story_core`; assert that the writer packet contains only `logline`, `reader_promise`, and a chapter-relevant advantage limit alongside `outline_context`.

- [ ] **Step 2: Run context tests and verify RED**

Run: `pytest -q tests/story_core/test_outline_planning_generation.py tests/story_core/test_writing_packet.py -k "story_core or overall_context"`

Expected: FAIL because the current brief contains three story-core projections.

- [ ] **Step 3: Simplify outline generation input**

Replace the three story-core fields in `OutlinePlanningBrief` with one normalized `overall_context`. Character and world phases derive their needed slices from this object inside their own prompt builders.

- [ ] **Step 4: Keep the writer projection small**

Build the writing projection from `outline.overall` and retain only direction anchors needed to prevent drift. Do not append the complete overall object outside `outline_context`.

- [ ] **Step 5: Run context tests and verify GREEN**

Run: `pytest -q tests/story_core/test_outline_planning_generation.py tests/story_core/test_writing_packet.py -k "story_core or overall_context"`

Expected: PASS.

### Task 5: Merge The Editor Into The 总纲 Tab

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write a failing browser test**

Assert that the page has no standalone `故事核心` heading or `保存故事核心` button, that the 总纲 tab includes `一句话故事`, `核心优势`, and `核心秘密`, and that one `保存大纲` action persists all fields.

- [ ] **Step 2: Run the focused browser test and verify RED**

Run: `npm --prefix apps/web run test:e2e -- story-workbench.spec.ts -g "故事核心并入总纲"`

Expected: FAIL because the standalone editor still exists.

- [ ] **Step 3: Extend TypeScript outline contracts**

Add the four structured groups to `ProjectOutlineOverall`. Remove story-core fetch/update imports and local state from the outline page.

- [ ] **Step 4: Render core fields inside 总纲**

Move the relevant controls into the existing overall panel, grouping them with simple headings. Reuse the existing outline draft and save action so the page performs one update request.

- [ ] **Step 5: Run frontend checks and verify GREEN**

Run:

```powershell
npm --prefix apps/web run typecheck
npm --prefix apps/web run test:e2e -- story-workbench.spec.ts -g "故事核心并入总纲"
```

Expected: both commands PASS.

### Task 6: Migrate Existing Projects And Verify The Whole Flow

**Files:**
- Modify: only files required by failures caused by Tasks 1-5.

- [ ] **Step 1: Run the project migration once**

Load every active file project through the idempotent migration path. Verify `p-gou-webgame-restored` keeps its current overall, arcs, chapters, and generated first chapter.

- [ ] **Step 2: Run the backend regression suite**

Run:

```powershell
pytest -q tests/story_core/test_project_outline.py tests/story_core/test_story_core_card.py tests/story_core/test_opening_directions.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_writing_packet.py tests/story_core/test_file_project_store.py tests/api/test_file_project_creation_routes.py
```

Expected: PASS with no failures.

- [ ] **Step 3: Run frontend build and browser verification**

Run:

```powershell
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- story-workbench.spec.ts -g "故事核心并入总纲"
```

Expected: PASS.

- [ ] **Step 4: Verify prompt and storage boundaries**

Search for new writes to `story_core.json` and duplicate outline-generation inputs. Only legacy read compatibility and the read-only compatibility route may remain.

- [ ] **Step 5: Inspect the real project page**

Open `/projects/file%3Ap-gou-webgame-restored/outline`, edit one overall field, save, reload, and confirm the value persists without creating a standalone core file.
