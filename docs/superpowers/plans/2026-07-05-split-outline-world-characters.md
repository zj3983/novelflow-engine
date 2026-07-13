# Split Outline, World, and Characters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the project workbench into separate Outline, World, and Character Card pages.

**Architecture:** Keep existing data contracts unchanged. Move outline editing to `/outline`, character card display to `/characters`, and keep `/world` focused on world facts/rules/constraints.

**Tech Stack:** Next.js app router, React client pages, existing `ProjectWorkspaceProvider`, existing file-project API.

---

### Task 1: Add Dedicated Pages

**Files:**
- Create: `apps/web/app/projects/[id]/outline/page.tsx`
- Create: `apps/web/app/projects/[id]/characters/page.tsx`
- Modify: `apps/web/app/projects/[id]/world/page.tsx`

- [ ] Extract outline editing state and save behavior from `world/page.tsx` into the new outline page.
- [ ] Extract character card rendering from `world/page.tsx` into the new characters page.
- [ ] Replace `world/page.tsx` with a smaller world-only page showing rule cards, world facts, author constraints, and selected blueprint fields.

### Task 2: Update Navigation

**Files:**
- Modify: `apps/web/components/ws/WorkspaceShell.tsx`
- Modify: `apps/web/app/projects/[id]/page.tsx`

- [ ] Add nav entries for `大纲`, `世界观`, and `角色卡`.
- [ ] Point overview character links to `/characters`.
- [ ] Add or keep world links pointing to `/world`.

### Task 3: Verify

**Commands:**
- `npm run build` in `apps/web`
- `pytest tests\story_core -q` from repo root

**Expected:** Next build succeeds and story core tests remain green.
