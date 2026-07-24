# Lightweight Chapter Planning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip the director model when a chapter has an actionable detailed outline, keep model planning only as a fallback, and derive summaries and ledger changes from the completed body.

**Architecture:** Add a focused chapter-planning module that converts `outline_context.chapter` into the legacy plan shape consumed by simulation and writing. The orchestrator selects this deterministic plan first and reuses the existing model path only when the outline is missing or incomplete. Existing persisted fields and API contracts remain readable while UI labels describe the stage as chapter planning.

**Tech Stack:** Python 3, Pydantic story models, pytest, Next.js 14, TypeScript, Playwright.

---

### Task 1: Build the deterministic chapter contract

**Files:**
- Create: `packages/story_core/chapter_planning.py`
- Create: `tests/story_core/test_chapter_planning.py`

- [ ] **Step 1: Write failing tests for actionable and incomplete outlines**

Add tests proving that a chapter with `goal` plus an outcome field produces a plan with `source="outline"`, ordered actions, obstacle, payoff, cost/state-change slots and hook, while a chapter without a goal or outcome returns `None`.

```python
def test_actionable_outline_builds_chapter_contract():
    context = {"project_snapshot": {"outline_context": {"chapter": {
        "chapter_number": 2,
        "title": "补齐委托",
        "goal": "补齐清道夫委托所需材料",
        "obstacle": "刷新点竞争激烈",
        "action": "夜烬换到侧坡连续清怪",
        "turn": "匿名寄售价格开始下滑",
        "payoff": "交付任务并升级",
        "ending_hook": "交易行出现新的收购单",
        "cast": ["夜烬"],
    }}}}
    plan = build_outline_chapter_plan(context, 2)
    assert plan["planning_source"] == "outline"
    assert plan["event_plan"]["ordered_actions"]
    assert plan["event_plan"]["chapter_satisfaction"]["visible_payoff"] == "交付任务并升级"
    assert plan["event_plan"]["chapter_end_hook"]["content"] == "交易行出现新的收购单"


def test_incomplete_outline_requires_model_fallback():
    context = {"project_snapshot": {"outline_context": {"chapter": {"goal": "继续升级"}}}}
    assert build_outline_chapter_plan(context, 2) is None
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/story_core/test_chapter_planning.py -q`

Expected: FAIL because `packages.story_core.chapter_planning` does not exist.

- [ ] **Step 3: Implement the minimum planner**

Implement:

```python
def build_outline_chapter_plan(director_context: dict[str, Any], chapter_number: int) -> dict[str, Any] | None:
    """Translate an actionable detailed outline into the existing writer-plan contract."""
```

Treat an outline as actionable only when the chapter number matches, `goal` is non-empty, and at least one of `action`, `turn`, or `payoff` is non-empty. Build ordered actions from the non-empty sequence `goal -> obstacle -> action -> turn -> payoff -> ending_hook`, without inventing new story facts. Return empty `memory_constraints` and no `chapter_summary`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/story_core/test_chapter_planning.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/chapter_planning.py tests/story_core/test_chapter_planning.py
git commit -m "feat: derive chapter contracts from outlines"
```

### Task 2: Select deterministic planning before model fallback

**Files:**
- Modify: `packages/story_core/orchestrator.py:5698-5958`
- Modify: `tests/story_core/test_orchestrator.py`
- Modify: `tests/story_core/test_director_plan_quality.py`

- [ ] **Step 1: Write a failing orchestration test**

Create a story with `outline_context.chapter` containing a complete chapter plan. Replace `_timed_chat` with a spy that fails if called with `agent="planner"`, allow the writer and memory calls, and assert generation reaches the writer with an outline-sourced plan. Add a second test showing an incomplete chapter outline still calls the planner once.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest tests/story_core/test_orchestrator.py -k "outline_planning or incomplete_outline" -q`

Expected: the actionable-outline test fails because the planner model is still called.

- [ ] **Step 3: Add the planning selector**

In `generate_next_chapter`, call `build_outline_chapter_plan(director_context, chapter_number)` before constructing the planning prompt. When it returns a plan:

- set `planning_source` to `outline`;
- skip `_plan_prompt`, planner `_timed_chat`, JSON parsing and director quality retries;
- continue through normalization, world response and writer stages;
- show workflow outputs with the contract fields and source.

When it returns `None`, keep the current model path but label it `model_fallback`. A planner failure must only block generation on this fallback path.

- [ ] **Step 4: Remove pre-draft summary and planned ledger authority**

Stop requesting or consuming `chapter_summary` and planned `ledger_updates` as authoritative planning output. Normalize memory constraints from current story state, pass no `planned_summary` into `_extract_final_body_memory`, and keep `_apply_ledger_updates` driven by `post_draft_memory` only.

- [ ] **Step 5: Run orchestration and quality tests**

Run: `pytest tests/story_core/test_orchestrator.py tests/story_core/test_director_plan_quality.py tests/story_core/test_chapter_simulation_plan.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/story_core/orchestrator.py tests/story_core/test_orchestrator.py tests/story_core/test_director_plan_quality.py
git commit -m "refactor: make model planning a fallback"
```

### Task 3: Slim the fallback prompt and writer contract

**Files:**
- Modify: `packages/story_core/prompt_templates.py:51-100`
- Modify: `packages/story_core/orchestrator.py:1400-1475,4308-4343`
- Modify: `tests/story_core/test_novel_type_catalog.py`
- Modify: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: Write failing prompt tests**

Assert the planning fallback prompt requests only `character_moves`, `chapter_intent`, and `event_plan`; it must not request `chapter_summary` or `ledger_updates`. Assert the writer direction section contains the compact goal, obstacle, ordered actions, payoff, cost/state change and hook, but does not contain the full legacy plan dump.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/story_core/test_novel_type_catalog.py tests/story_core/test_writer_prompt_method.py -k "director or planning or compact" -q`

Expected: FAIL because the current templates still request summary and ledger fields.

- [ ] **Step 3: Update prompt templates and compaction**

Rename template titles to “章节规划补全”, reduce requested JSON fields, and keep compatibility keys internally. Update writer compaction so only the chapter contract fields enter `chapter_direction`; do not append the full director JSON or model-only metadata.

- [ ] **Step 4: Run prompt tests and verify GREEN**

Run: `pytest tests/story_core/test_novel_type_catalog.py tests/story_core/test_writer_prompt_method.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/prompt_templates.py packages/story_core/orchestrator.py tests/story_core/test_novel_type_catalog.py tests/story_core/test_writer_prompt_method.py
git commit -m "refactor: slim chapter planning prompts"
```

### Task 4: Make the workflow transparent without “director” terminology

**Files:**
- Modify: `apps/web/components/ws/WritingFlow.tsx`
- Modify: `apps/web/app/projects/[id]/sim/page.tsx`
- Modify: `apps/api/routes/stories.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/web/tests/story-workbench.spec.ts`
- Modify: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing UI and API tests**

Assert workflow stage `director_plan` is displayed as “章节规划”, its artifact exposes `planning_source`, and the simulation page uses “章节目标/章节计划明细”. Preserve the internal stage key for old jobs.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/api/test_story_routes.py -k "prompt or workflow" -q`

Run: `npm.cmd run test:e2e -- --grep "章节规划"`

Expected: FAIL because the existing labels still say “导演”.

- [ ] **Step 3: Update labels and visible artifacts**

Keep `director_plan` as the compatibility identifier, but change visible labels, prompt titles and descriptions. Display either “来源：已有章节细纲” or “来源：模型补全”. Do not rename stored historical keys.

- [ ] **Step 4: Run backend and frontend tests**

Run: `pytest tests/api/test_story_routes.py -q`

Run: `npm.cmd run test:e2e -- --grep "章节规划"`

Run: `npm.cmd run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/ws/WritingFlow.tsx apps/web/app/projects/[id]/sim/page.tsx apps/api/routes/stories.py packages/story_core/file_project_store.py apps/web/tests/story-workbench.spec.ts tests/api/test_story_routes.py
git commit -m "feat: expose chapter planning sources"
```

### Task 5: Regression verification

**Files:**
- Test only

- [ ] **Step 1: Run the story-core suite**

Run: `pytest tests/story_core -q`

Expected: PASS.

- [ ] **Step 2: Run the API suite**

Run: `pytest tests/api -q`

Expected: PASS.

- [ ] **Step 3: Run the frontend build and focused browser suite**

Run: `npm.cmd run build`

Run: `npm.cmd run test:e2e -- --grep "章节规划|write page|写作流程"`

Expected: PASS.

- [ ] **Step 4: Verify a real project job**

Generate or regenerate one chapter in `file:p-gou-webgame-restored`. Confirm the workbench shows “章节规划 / 来源：已有章节细纲”, no planner prompt call is recorded for that chapter, the writer receives the compact contract, and memory updates appear only after the body finishes.

- [ ] **Step 5: Commit any verification-only fixture updates**

Only if fixtures changed intentionally:

```bash
git add <intentional fixture paths>
git commit -m "test: cover lightweight chapter planning flow"
```
