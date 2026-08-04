# Game Opening Core And Long-Form Pacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured opening advantages, mysteries, motivations, and a scalable four-stage long-form outline rhythm for game webnovels without leaking game references into other genres or unrevealed truths into chapter writing.

**Architecture:** Extend the existing `story-core/v1` card additively with three nested models and stage-specific projections. Keep game-only opening examples in a focused genre reference module, keep long-form rhythm in `genre_outline_template.arc.pacing_stages`, and pass each module only to the generation stage that needs it.

**Tech Stack:** Python 3.11, Pydantic 2, FastAPI, Next.js 14, TypeScript, pytest, Playwright.

---

### Task 1: Structured opening core

**Files:**
- Modify: `packages/story_core/story_core_card.py`
- Modify: `packages/story_core/opening_directions.py`
- Test: `tests/story_core/test_story_core_card.py`
- Test: `tests/story_core/test_opening_directions.py`

- [ ] Add failing tests for `core_advantage`, `central_mystery`, and `initial_drive`, including old payload defaults and stage projections.
- [ ] Run the focused tests and confirm failures are caused by missing fields.
- [ ] Add strict nested Pydantic models, map opening directions into `StoryCoreCard`, and keep unrevealed `hidden_truth` out of planning and writing projections.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Game-only opening reference

**Files:**
- Create: `packages/story_core/opening_core_templates.py`
- Modify: `packages/story_core/opening_directions.py`
- Test: `tests/story_core/test_opening_core_templates.py`
- Test: `tests/story_core/test_opening_directions.py`

- [ ] Add failing tests showing game projects receive advantage, world-secret, and motivation references while xuanhuan and urban projects do not receive game examples.
- [ ] Run the focused tests and confirm the reference module and prompt key are missing.
- [ ] Implement the compact reference registry and include it only in the opening direction prompt.
- [ ] Require generated candidates to return all nested fields while preserving defaults for stored legacy candidates.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Scalable four-stage game outline

**Files:**
- Modify: `packages/story_core/outline_templates.py`
- Modify: `packages/story_core/novel_type_catalog.py`
- Modify: `packages/story_core/project_outline.py`
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `apps/web/lib/api.ts`
- Test: `tests/story_core/test_outline_templates.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_project_outline.py`

- [ ] Add failing tests for four ordered `pacing_stages`, absence from other genres, prompt compaction preservation, and valid `pacing_stage_id` values on game arcs.
- [ ] Run focused tests and confirm failures are caused by the missing pacing contract.
- [ ] Add the four reference stages with flexible chapter ranges and validate optional custom stage lists.
- [ ] Preserve stages in compact outline context, add `pacing_stage_id` to arcs, and require all four stages in order across core game arcs while scaling them to planned length.
- [ ] Run focused tests and confirm they pass.

### Task 4: Setup and story-core editing UI

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/setup/page.tsx`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify: `apps/web/app/globals.css`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] Add failing browser assertions for the three opening-core summaries and editable nested fields.
- [ ] Extend client types, show the three summaries on each candidate, and add grouped editors for nested story-core data.
- [ ] Run TypeScript and focused Playwright tests.

### Task 5: Integration and verification

**Files:**
- Modify fixtures in affected tests where generated opening directions now require nested fields.

- [ ] Run opening, story-core, template, outline planning, API, and writing packet test groups.
- [ ] Run `pytest -q`, `npx.cmd tsc --noEmit`, `npm.cmd run build`, and the workbench Playwright suite with four workers.
- [ ] Run `git diff --check` and verify the live frontend and backend return HTTP 200.
