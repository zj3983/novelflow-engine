# Continuation Whole-Book Outline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make continuation projects keep a whole-book overall/arc outline while limiting detailed chapter plans to chapters after the continuation point.

**Architecture:** Extend the existing outline planning brief with a continuation boundary and compact summaries loaded from imported chapter artifacts. The planner remains the only component that turns those facts into semantic historical arcs; the store validates and locks historical arcs, while the React page derives read-only state from the continuation boundary.

**Tech Stack:** Python 3, Pydantic, FastAPI file-project store, Next.js 14, React, TypeScript, Pytest, Playwright.

---

### Task 1: Supply whole-book continuation context to the outline planner

**Files:**
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] Add failing tests asserting that a continuation brief contains `continuation_start_chapter` and all imported chapter summaries, and that regenerate targets ten future chapters even when the old outline ceiling equals the current batch end.
- [ ] Run the focused tests and verify failures identify the missing continuation context and target-window behavior.
- [ ] Add strict continuation fields to `OutlinePlanningBrief`; load compact summaries from `.story-system/chapters/*.json`, bounded to the continuation point.
- [ ] Add continuation-specific prompt rules: overall covers original plus future; arcs include historical and future stages; detailed chapters equal only future targets; batch end is not the book ending.
- [ ] Run the focused tests until green.

### Task 2: Lock imported history while allowing future regeneration

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] Add failing tests proving regeneration preserves arcs ending on or before `continuation.start_after_chapter`, rejects generated changes to those arcs, and preserves committed chapter plans without preserving an invalid arc that crosses the continuation boundary.
- [ ] Run the focused tests and verify the historical arc can currently drift.
- [ ] Add continuation-boundary helpers and merge validation that preserve historical arcs exactly while replacing future/cross-boundary arcs.
- [ ] Make regenerate use a future target window independent of the previous batch ceiling; retain ordinary project behavior.
- [ ] Run focused store and outline validation tests until green.

### Task 3: Show historical and planned stages correctly

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Test: `tests/api/test_file_project_creation_routes.py`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] Add failing API and Playwright tests asserting the project response exposes the continuation point, historical arcs show `已发生` and have disabled fields/actions, future arcs show `规划中` and remain editable, and the total-outline hint explains whole-book coverage.
- [ ] Run the focused API and browser tests and verify they fail for the missing response field and UI state.
- [ ] Expose the sanitized continuation boundary in the project response/type and derive stage state in the outline page.
- [ ] Disable all historical stage inputs and deletion while leaving future controls unchanged.
- [ ] Run focused API and browser tests until green.

### Task 4: Repair the imported book through the production workflow

**Files:**
- Modify data only: `data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0/.webnovel/outline.json`
- Preserve: imported chapter bodies and committed chapter artifacts

- [ ] Snapshot hashes for imported chapters 1 through 145 and the existing outline.
- [ ] Regenerate the project outline with guidance requiring evidence-backed historical stages for chapters 1 through 141 and retaining future chapter plans from chapter 142 onward.
- [ ] Verify the overall covers original history, continuation point, future direction, and estimated ending; historical arcs cover chapters 1 through 141; detailed chapter plans contain no chapter at or below 141.
- [ ] Verify all imported and generated chapter body hashes are unchanged.

### Task 5: Full verification

**Files:**
- Verify only

- [ ] Run focused Python tests for continuation import, outline planning, and file-project storage.
- [ ] Run focused Playwright tests for the outline workspace.
- [ ] Run `npm run build` in `apps/web`.
- [ ] Run `git diff --check` and inspect the scoped diff without reverting unrelated worktree changes.

