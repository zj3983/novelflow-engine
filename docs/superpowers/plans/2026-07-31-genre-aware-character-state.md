# Genre-Aware Character State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace non-game dual-state character cards with one structured `current_state` while preserving game-story `real_state` and `game_state`.

**Architecture:** Add genre-aware normalization at the character persistence boundary. Non-game legacy strings and `real_state` envelopes migrate into `current_state`; game projects retain the existing dual-state helpers. Writer projection and the character page consume the genre-specific shape.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, Next.js, TypeScript, Playwright, pytest.

---

### Task 1: State normalization and migration

**Files:**
- Modify: `packages/story_core/dual_state.py`
- Modify: `packages/story_core/models.py`
- Test: `tests/story_core/test_dual_state.py`

- [ ] Add failing tests proving non-game cards convert a legacy `real_state` envelope and a legacy string `current_state` into `{current, recent_changes}`, prefer explicit structured `current_state`, and remove game-only namespaces.
- [ ] Run `python -m pytest tests/story_core/test_dual_state.py -q`; expect the new tests to fail because generic state normalization is absent.
- [ ] Add `current_state: dict` to `CharacterState` and implement `normalize_character_state(card, is_game_story)` so non-game output contains only structured `current_state`, while game output delegates to `normalize_dual_state`.
- [ ] Run the same test file and expect all tests to pass.

### Task 2: Persistence and writer projection

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/dual_state.py`
- Test: `tests/story_core/test_file_project_store.py`
- Test: `tests/story_core/test_dual_state.py`

- [ ] Add failing tests proving non-game project state and saved character cards contain `current_state` but no `real_state` or `game_state`, and writer cards expose only `state_context.current_state`.
- [ ] Run the focused tests and verify the old dual-state output fails them.
- [ ] Route `_normalize_character_persistence_card`, `_completed_character_card`, state updates, and scene projection through the genre-aware normalizer. Preserve all existing game ledger behavior.
- [ ] Run the focused tests and expect them to pass.

### Task 3: API and character page

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/lib/worldDisplay.ts`
- Modify: `apps/web/app/projects/[id]/characters/page.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] Add a Playwright test where a xuanhuan card has legacy `real_state`; expect the page to show one “当前状态” editor and no “现实状态” or “游戏状态”. Keep the existing game dual-state test.
- [ ] Run the focused Playwright test and verify it fails.
- [ ] Add structured `current_state` types, migrate the page display/edit payload by project genre, and keep game-story dual editors unchanged.
- [ ] Run the focused Playwright tests and `npm run build` under `apps/web`.

### Task 4: Existing project migration regression

**Files:**
- Test: `tests/api/test_file_project_creation_routes.py`
- Test: `tests/api/test_project_context_sync.py`

- [ ] Add API tests for reading and saving an existing non-game card with legacy `real_state`, asserting idempotent `current_state` migration and no duplicated recent changes.
- [ ] Run the tests, implement any missing persistence cleanup, and rerun until green.
