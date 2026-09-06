# Adaptive Chapter Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual expansion with one chapter-polish action that automatically expands, shortens, or expression-polishes against the shared chapter-length policy.

**Architecture:** Keep the existing file-project candidate boundary and background job runner. Add adaptive mode selection inside `FileProjectStore`, reuse the existing expansion and compression renderers, add a focused expression-polish renderer, and expose `polish` through the API and web client while accepting `expand` only as a legacy alias.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, Next.js, TypeScript, Playwright.

---

### Task 1: Lock the adaptive backend contract

**Files:**
- Modify: `tests/story_core/test_file_project_store.py`
- Modify: `tests/api/test_story_routes.py`

- [ ] Add tests proving short chapters receive an expansion prompt, long chapters receive a compression prompt, and in-range chapters receive an expression-polish prompt.
- [ ] Add route tests proving new jobs store `operation: "polish"` and old `expand` payloads remain readable.
- [ ] Run the focused tests and confirm they fail because adaptive polishing is not implemented.

### Task 2: Implement adaptive polishing

**Files:**
- Modify: `packages/story_core/chapter_generation_workflow.py`
- Modify: `packages/story_core/genre_stages/length_prompts.py`
- Modify: `packages/story_core/prompt_templates.py`
- Modify: `apps/api/routes/file_projects.py`

- [ ] Add one mode selector using the shared `CHAPTER_TARGET_MIN_CHARS` and `CHAPTER_TARGET_MAX_CHARS` constants.
- [ ] Render expansion, compression, or expression-polish prompts without changing chapter facts or the locked ending.
- [ ] Validate that expansion grows, compression shrinks, and expression polish remains within a bounded length delta.
- [ ] Save every result as an unconfirmed candidate and record selected mode plus before/after character counts in progress artifacts.
- [ ] Run focused store and route tests until green.

### Task 3: Replace the web action

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/write/page.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] Change the client request to `operation: "polish"`.
- [ ] Rename button and loading text to “润色本章” and “润色中...”.
- [ ] Keep candidate confirmation and discard behavior unchanged.
- [ ] Run the focused Playwright test and TypeScript production build.

### Task 4: Regression verification

**Files:**
- Test only.

- [ ] Run the affected Python test modules.
- [ ] Run the complete backend suite.
- [ ] Run the frontend production build.
- [ ] Confirm no generated runtime files or project data were added to source control.
