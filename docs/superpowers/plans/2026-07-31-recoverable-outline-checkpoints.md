# Recoverable Outline Checkpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist outline foundation, character roster, and chapter window independently so failed generation resumes from the failed phase.

**Architecture:** A project-local checkpoint store owns phase status and atomic payload files. The outline generator accepts cached phase payloads and emits a callback after every phase; the file-project store validates the generation fingerprint, persists callbacks, and combines all phases only after complete validation. The outline page polls a read-only checkpoint endpoint during its existing generation request.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, Next.js, TypeScript, pytest, Playwright.

---

### Task 1: Checkpoint data store

**Files:**
- Create: `packages/story_core/outline_generation_checkpoints.py`
- Test: `tests/story_core/test_outline_generation_checkpoints.py`

- [ ] Write failing tests for atomic phase save, ordered invalidation from a requested phase, status/error timestamps, and fingerprint mismatch reset.
- [ ] Run `python -m pytest tests/story_core/test_outline_generation_checkpoints.py -q`; expect import failure.
- [ ] Implement `OutlineCheckpointStore` with phases `outline_foundation`, `character_roster`, `chapter_window`, a manifest JSON, and one payload JSON per completed phase.
- [ ] Run the test file and expect all tests to pass.

### Task 2: Resumable generator phases

**Files:**
- Modify: `packages/story_core/outline_planning_generation.py`
- Test: `tests/story_core/test_outline_planning_generation.py`

- [ ] Add failing tests proving cached phases skip model calls, a failed chapter phase leaves foundation and roster reusable, and restart from `character_roster` invalidates roster plus chapter only.
- [ ] Run the focused tests and verify failure.
- [ ] Extend `generate` with `phase_payloads` and `phase_callback`; validate cached payloads with `GeneratedOutlineFoundation`, `GeneratedCharacterRoster`, and `GeneratedChapterWindow` before reuse, then callback with each newly validated payload.
- [ ] Run the focused tests and expect them to pass.

### Task 3: File-project orchestration and API

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/file_projects.py`
- Test: `tests/api/test_file_project_creation_routes.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] Add failing tests for resume after phase failure, fingerprint reset after guidance or outline context changes, final atomic merge, and GET checkpoint status.
- [ ] Run the focused tests and verify failure.
- [ ] Add `restart_from` to the generation request, wire the checkpoint store into `generate_outline_plan`, expose `GET /file-projects/{project_id}/outline/generation-checkpoints`, and keep checkpoints when final merge fails.
- [ ] Run the focused tests and expect them to pass.

### Task 4: Workbench progress

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] Add a Playwright test that starts generation, polls three named phases, displays elapsed/error information, and retries only the failed phase.
- [ ] Run the focused Playwright test and verify failure.
- [ ] Add checkpoint API types and polling UI. Keep the generation request asynchronous in the browser so polling continues while the POST remains open.
- [ ] Run focused Playwright tests and `npm run build` under `apps/web`.

### Task 5: Integrated verification

**Files:**
- No production file changes.

- [ ] Run `python -m pytest -q` and require zero failures.
- [ ] Run the web build and relevant Playwright suites.
- [ ] Restart the API and generate a temporary xuanhuan project; confirm three persisted phases, non-game `current_state`, no game-state terminology, and successful resume without repeating completed model calls.
