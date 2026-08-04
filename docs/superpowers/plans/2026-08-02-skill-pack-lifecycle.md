# Skill Pack Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make imported Skill packs installed-but-disabled by default, allow per-project and per-module enable/disable, and support safe pack or single-module uninstall without touching story content.

**Architecture:** Keep Skill pack files in the global registry. Keep project selection in each project's `enabled_skill_ids` and explicit `skill_id::module_id` keys. Pack uninstall removes the registry directory; module uninstall removes only its module directory. Both operations scrub references from every project.json/state.json; prompt assembly remains driven only by the project's explicit enabled selection.

**Tech Stack:** FastAPI, Python pathlib/JSON persistence, Next.js/React, pytest, TypeScript.

---

### Task 1: Backend lifecycle behavior

**Files:**
- Modify: `packages/story_core/skill_packs.py`
- Modify: `apps/api/routes/skill_packs.py`
- Test: `tests/story_core/test_skill_packs.py`
- Test: `tests/api/test_skill_pack_routes.py`

- [x] Write failing tests for uninstalling an installed pack and scrubbing project references.
- [x] Run the focused tests and confirm they fail because uninstall behavior is absent.
- [x] Add a registry removal helper with path validation and an exported-project reference scrubber.
- [x] Add `DELETE /skill-packs/{skill_id}` returning the removed pack summary and affected project count.
- [x] Add `DELETE /skill-packs/{skill_id}/modules/{module_id}`; preserve the root Skill and other modules, and reject root-module deletion.
- [x] Scrub the removed module from explicit project selections while preserving legacy pack-level projects.
- [x] Run focused backend tests.

### Task 2: Frontend project skill controls

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/skills/page.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts` or a focused skill page test

- [x] Add the uninstall API client.
- [x] Show installed/active status separately and add a confirmation-gated uninstall action.
- [x] Keep enable/disable as a project-only operation and refresh project state after uninstall.
- [x] Add a separate uninstall action to each submodule row; keep the root module uninstallable only as part of whole-pack uninstall.
- [x] Add UI coverage for disabled-by-default and uninstall confirmation behavior.

### Task 3: Verification

**Files:**
- No production changes.

- [x] Run focused Python tests.
- [x] Run the focused frontend test or TypeScript check.
- [x] Inspect the diff to ensure no story正文、大纲、角色卡 files are deleted.
