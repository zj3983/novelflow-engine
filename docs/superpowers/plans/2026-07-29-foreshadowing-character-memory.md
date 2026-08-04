# Foreshadowing And Character Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one persistent foreshadowing ledger and separate stable character profiles from chapter-updated character state, then expose both clearly in the workbench and writing packet.

**Architecture:** Put normalization, reconciliation, and retrieval in a focused `foreshadowing.py` domain module. `FileProjectStore` owns persistence after each accepted chapter and supplies a bounded selection to the writing packet. Existing character records remain canonical; chapter memory may update only dynamic fields, while the API and UI present static and dynamic sections separately.

**Tech Stack:** Python 3, Pydantic, FastAPI, pytest, Next.js, React, TypeScript, Playwright.

---

### Task 1: Canonical Foreshadowing Ledger

**Files:**
- Create: `packages/story_core/foreshadowing.py`
- Modify: `packages/story_core/models.py`
- Test: `tests/story_core/test_foreshadowing.py`

- [ ] **Step 1: Write failing ledger tests**

Add tests proving that a new unresolved thread becomes an open entry, a repeated thread updates `last_touched_chapter` without duplication, an absent thread remains open, and an explicit resolution records `resolved_chapter`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest tests/story_core/test_foreshadowing.py -q`

Expected: FAIL because `reconcile_foreshadowing` and the extended fields do not exist.

- [ ] **Step 3: Implement the minimal domain module**

Add backward-compatible fields to `ForeshadowingState`: `last_touched_chapter`, `payoff_plan`, and `resolved_chapter`. Implement deterministic text normalization, exact normalized matching, reconciliation, and open-item selection. Do not infer resolution from omission.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/story_core/test_foreshadowing.py -q`

Expected: PASS.

### Task 2: Chapter Sync And Bounded Writing Context

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/memory.py`
- Test: `tests/story_core/test_file_project_store.py`
- Test: `tests/story_core/test_memory_retrieval.py`

- [ ] **Step 1: Write failing persistence and packet tests**

Add one test that accepts two chapter summaries and verifies ledger persistence across both chapters. Add one test that verifies the writing packet contains at most eight open/reinforced entries and omits resolved entries and the full ledger.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest tests/story_core/test_file_project_store.py -k "foreshadowing" -q`

Expected: FAIL because `_sync_state_after_chapter` does not reconcile the ledger and the packet has no bounded `foreshadowing_context`.

- [ ] **Step 3: Connect chapter memory to the ledger**

Call the domain reconciler from `_sync_state_after_chapter` using the accepted chapter summary. Replace `build_foreshadowing`'s generic placeholder with selected real entries; when none exist, return an empty list. Add `foreshadowing_context` to the writing packet and do not copy the complete ledger into `state`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/story_core/test_file_project_store.py -k "foreshadowing" -q`

Expected: PASS.

### Task 3: Stable Character Profile And Dynamic Chapter State

**Files:**
- Modify: `packages/story_core/models.py`
- Modify: `packages/story_core/memory.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_character_chapter_state.py`

- [ ] **Step 1: Write failing character-state tests**

Create tests showing that chapter updates may change location, emotion, short-term goal, knowledge notes, physical condition, and last appearance chapter, while name, age, background, personality, voice, and long-term motivation remain unchanged.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest tests/story_core/test_character_chapter_state.py -q`

Expected: FAIL because chapter evidence and last-appearance updates are not yet recorded safely.

- [ ] **Step 3: Implement bounded chapter-state updates**

Record `last_appearance_chapter` and a bounded, deduplicated `recent_changes` evidence trail on the existing reality/game state layers. Apply structured position, goal, condition, knowledge, possession, or relationship changes only when they arrive through explicit state changes. Preserve old top-level compatibility fields, and never overwrite stable profile fields from chapter prose.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/story_core/test_character_chapter_state.py -q`

Expected: PASS.

### Task 4: File-Project API

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/api/test_file_project_routes.py`

- [ ] **Step 1: Write failing API tests**

Cover `GET /file-projects/{project_id}/foreshadowing` and `PUT /file-projects/{project_id}/foreshadowing`, including invalid status rejection and preservation of unrelated story state.

- [ ] **Step 2: Run route tests and verify RED**

Run: `pytest tests/api/test_file_project_routes.py -k "foreshadowing" -q`

Expected: FAIL with 404 because the routes do not exist.

- [ ] **Step 3: Add explicit ledger endpoints**

Return normalized ledger entries from GET. PUT accepts the complete edited ledger, validates with `ForeshadowingState`, saves only `state.foreshadowing`, and returns the normalized list.

- [ ] **Step 4: Run route tests and verify GREEN**

Run: `pytest tests/api/test_file_project_routes.py -k "foreshadowing" -q`

Expected: PASS.

### Task 5: Outline And Character Workbench UI

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify: `apps/web/app/projects/[id]/characters/page.tsx`
- Modify: `apps/web/app/globals.css`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing Playwright tests**

Add tests that open the outline page, select “伏笔”, edit a payoff plan and status, save, and observe the persisted values. Add a character-page test asserting separate “稳定档案” and “当前状态” headings.

- [ ] **Step 2: Run focused browser tests and verify RED**

Run: `npm --prefix apps/web test -- --grep "伏笔账本|角色当前状态"`

Expected: FAIL because the tab and sections are absent.

- [ ] **Step 3: Implement the UI**

Add typed fetch/update helpers. Extend the outline tabs with a flat ledger list, open/resolved filter, editable text/status/payoff plan, and one save action. Render the character detail using existing values grouped into stable and dynamic sections; do not add a new page or nested cards.

- [ ] **Step 4: Run focused browser tests and verify GREEN**

Run: `npm --prefix apps/web test -- --grep "伏笔账本|角色当前状态"`

Expected: PASS.

### Task 6: Current Project Migration And Verification

**Files:**
- Modify through application persistence: project `file:p-da2c16a6ee9440d6ad52cb402ead88a0`

- [ ] **Step 1: Reconcile existing unresolved threads**

Load the latest chapter summaries, run them through the canonical reconciler in chapter order, and save the resulting ledger without modifying chapter bodies.

- [ ] **Step 2: Run backend regression tests**

Run: `pytest tests/story_core/test_foreshadowing.py tests/story_core/test_character_chapter_state.py tests/story_core/test_memory_retrieval.py tests/story_core/test_file_project_store.py -q`

Expected: PASS.

- [ ] **Step 3: Build the frontend**

Run: `npm --prefix apps/web run build`

Expected: exit code 0.

- [ ] **Step 4: Verify the live workbench**

Open the current project's outline and character pages. Confirm the six existing open threads appear once, edits persist after refresh, character stable fields remain unchanged, and the next writing packet contains the bounded context.
