# Project Archive And Trash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add archive, recycle-bin restore, and guarded permanent deletion for both SQLite and file-backed novels.

**Architecture:** Store lifecycle independently from the writing workflow status. SQLite projects keep lifecycle fields inside their existing JSON document. File projects keep active and archived directories in place, while trashed projects move under the export root's `.trash` directory with recovery metadata. The frontend merges both backends through one lifecycle-aware API layer.

**Tech Stack:** FastAPI, Pydantic, SQLite JSON persistence, filesystem-backed projects, Next.js/React, Playwright, pytest.

---

### Task 1: Define and persist project lifecycle

**Files:**
- Modify: `packages/story_core/models.py`
- Modify: `apps/api/storage.py`
- Test: `tests/api/test_story_routes.py`

1. Add lifecycle fields with backward-compatible defaults.
2. Add filtered project listing and lifecycle updates to storage.
3. Verify old JSON projects load as active.

### Task 2: Add SQLite lifecycle routes

**Files:**
- Modify: `apps/api/routes/stories.py`
- Test: `tests/api/test_story_routes.py`

1. Add active-job protection.
2. Add archive, trash, and restore routes.
3. Require exact-title confirmation before permanent deletion.

### Task 3: Add filesystem recycle-bin behavior

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Test: `tests/api/test_file_project_creation_routes.py`

1. List projects by lifecycle, including `.trash` only when requested.
2. Archive by metadata update.
3. Trash by moving the project directory and recording its original location.
4. Restore with destination-conflict protection.
5. Permanently delete only validated descendants of `.trash` after exact-title confirmation.
6. Block lifecycle mutations while a generation job is active.

### Task 4: Add frontend lifecycle controls

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/page.tsx`
- Modify: `apps/web/app/globals.css`
- Test: `apps/web/tests/projects-lifecycle.spec.ts`

1. Add lifecycle types and backend-aware action helpers.
2. Add tabs for active, archived, and trashed novels.
3. Add archive, trash, restore, and permanent-delete controls.
4. Use an in-app confirmation modal; permanent deletion requires typing the title.
5. Clear the remembered last project when it is moved out of active work.

### Task 5: Verify end to end

1. Run focused backend lifecycle tests.
2. Run frontend build and lifecycle Playwright tests.
3. Run the full backend suite.
4. Restart the local services if needed and verify the projects page in the browser.
