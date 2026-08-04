# Director And World Response Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the director the only pre-draft plot planner and move world evolution to post-chapter state updates.

**Architecture:** Keep the existing director event plan and scene chain. Convert the former simulation stage into deterministic writing-context preparation: it projects the director plan, checks world/visibility boundaries, builds scene cards, and never generates a second set of world events. Preserve stored world-pulse data for post-chapter updates and rename workbench surfaces so they describe world state instead of another planning agent.

**Tech Stack:** Python 3, Pydantic, pytest, Next.js, TypeScript, Playwright.

---

### Task 1: Stop Pre-Draft World Event Generation

**Files:**
- Modify: `packages/story_core/pipeline/simulation_stage.py`
- Test: `tests/story_core/test_simulation_stage.py`

- [x] **Step 1: Write a failing test** asserting that an external-effect chapter records a deferred post-chapter world update and never calls `simulate_events`.
- [x] **Step 2: Run** `pytest -q tests/story_core/test_simulation_stage.py` and confirm the old simulation test fails.
- [x] **Step 3: Change `prepare_simulation_stage`** to keep director projection, scene-card building, style guidance, and the gate decision while forcing `world_events=[]`, `run_world_simulation=False`, and storing `world_update_deferred=True` plus the gate reason/triggers.
- [x] **Step 4: Run** `pytest -q tests/story_core/test_simulation_stage.py` and confirm both context-preparation cases pass.

### Task 2: Expose One Planning Stage

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/pipeline/chapter_pipeline.py`
- Test: `tests/story_core/test_orchestrator.py`
- Test: `tests/story_core/test_chapter_pipeline.py`

- [x] **Step 1: Update failing workflow assertions** to require `prepare_writing_context` and reject a separate `world_response` artifact.
- [x] **Step 2: Run** the two focused test files and confirm the old labels/stage order fail.
- [x] **Step 3: Replace the `prepare_scenes` workflow event** with `prepare_writing_context`, source it from context preparation, and remove the standalone “世界响应校验完成” progress artifact.
- [x] **Step 4: Remove the optional pre-draft `simulation` pipeline stage** so the stable order is context, plan, writing, quality gate, candidate output.
- [x] **Step 5: Run** the focused tests and confirm the director output still reaches scene cards and writer context.

### Task 3: Remove Duplicate Workbench Language

**Files:**
- Modify: `apps/web/components/ws/WorkspaceShell.tsx`
- Modify: `apps/web/app/projects/[id]/page.tsx`
- Modify: `apps/web/app/projects/[id]/sim/page.tsx`
- Modify: `apps/web/components/ws/WritingFlow.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [x] **Step 1: Update Playwright expectations** from “世界响应” to “世界状态” and remove expectations for a second plot-planning surface.
- [x] **Step 2: Rename navigation and overview labels** to “世界状态”.
- [x] **Step 3: Make the `/sim` page show confirmed world pulse, visible consequences, and hidden background state only; remove director-like plot, character-action, and scene-planning sections.
- [x] **Step 4: Rename workflow display text** from world simulation/preparing scenes to writing-context preparation.
- [x] **Step 5: Run the focused Playwright spec** against the local app.

### Task 4: Regression Verification

**Files:**
- Verify only.

- [x] **Step 1: Run** `pytest -q tests/story_core/test_simulation_stage.py tests/story_core/test_chapter_pipeline.py tests/story_core/test_orchestrator.py tests/story_core/test_world_pulse.py`.
- [x] **Step 2: Run** the relevant frontend type check and Playwright test.
- [x] **Step 3: Inspect one generated workflow trace** and confirm it contains one chapter plan, one writing-context preparation step, no pre-draft world event generation, and a post-chapter world-state update.
