# Manual Chapter Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-triggered `扩写本章` button that reuses the existing expansion model prompt and saves the result as a candidate.

**Architecture:** Add one explicit expansion operation at the store boundary, route it through the existing file-generation job worker, and reuse the current candidate lifecycle. The normal writer and reviewer paths remain unchanged and cannot trigger expansion.

**Tech Stack:** Python, FastAPI, Pydantic, Next.js, TypeScript, Playwright, pytest

---

### Task 1: Store Expansion Boundary

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] Add failing tests for a one-call expansion that creates a `regenerate` candidate and leaves the confirmed Markdown unchanged.
- [ ] Add failing tests rejecting chapters at or above 3800 characters, empty output, shorter output, and output above 5700 characters.
- [ ] Implement `FileProjectStore.expand_chapter` using `_render_expansion_length_prompt`, the configured writer runtime, prompt logging, and `_save_candidate_from_bundle`.
- [ ] Run the focused store tests and confirm they pass.

### Task 2: Background Job Operation

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `apps/web/lib/api.ts`
- Test: `tests/api/test_story_routes.py`

- [ ] Add a failing route test that submits `{chapter_number: 1, operation: "expand"}` and expects `store.expand_chapter(1)`.
- [ ] Extend the generation job request with `operation: "generate" | "regenerate" | "expand"` while preserving existing payload compatibility.
- [ ] Dispatch expansion through the existing single-worker job and expose an `expandFileProjectChapter` API helper.
- [ ] Run route tests and confirm they pass.

### Task 3: Write-Page Button

**Files:**
- Modify: `apps/web/app/projects/[id]/write/page.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] Add a failing Playwright test that shows `扩写本章` only for an existing chapter below 3800 characters.
- [ ] Assert the button posts `operation=expand`, polls the existing job, and displays the returned candidate.
- [ ] Implement the button with an icon, disabled/running state, and existing candidate-panel loading.
- [ ] Run Playwright, TypeScript, and focused backend regression tests.

