# Simplified Chapter Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the default multi-agent review surface with one three-category report containing at most five actionable issues.

**Architecture:** Add a pure local aggregator over existing quality data, expose its result through current chapter APIs, and render it through one shared React component. Detailed legacy reviews remain stored for compatibility but no longer control the default UI.

**Tech Stack:** Python, Pydantic-compatible dictionaries, FastAPI, TypeScript, React, Playwright.

---

### Task 1: Review Aggregator

**Files:**
- Create: `packages/story_core/simplified_review.py`
- Create: `tests/story_core/test_simplified_review.py`

- [ ] Write failing tests for hard-blocking classification, deduplication, advisory issues, and the five-item limit.
- [ ] Run `pytest -q tests/story_core/test_simplified_review.py` and confirm failure.
- [ ] Implement `build_simplified_review(quality_report)` as a deterministic local function.
- [ ] Run the focused tests and confirm they pass.

### Task 2: API Compatibility

**Files:**
- Modify: `apps/api/routes/stories.py`
- Modify: `tests/api/test_story_routes.py`

- [ ] Write a failing route test asserting `quality_report.simplified_review` exists for legacy chapter data.
- [ ] Add the aggregator to `_quality_context` and serialized chapter bundles.
- [ ] Run the focused API tests and confirm they pass.

### Task 3: Unified Review UI

**Files:**
- Create: `apps/web/components/ws/SimplifiedReview.tsx`
- Modify: `apps/web/app/projects/[id]/write/page.tsx`
- Modify: `apps/web/app/projects/[id]/review/page.tsx`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] Add the simplified review TypeScript types and shared component.
- [ ] Replace separate AI, reader, editor, and reviewer cards with the shared component.
- [ ] Add UI assertions that only one report is shown and at most five issues render.
- [ ] Run frontend tests and production build.

### Task 4: Verification

**Files:**
- No new files.

- [ ] Run the full Python test suite.
- [ ] Restart backend and frontend services.
- [ ] Verify the current xianxia chapter through the live workbench.
