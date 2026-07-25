# Webgame Language Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a scene-aware MMO language library that gives the writer only the player-facing vocabulary needed by the current chapter.

**Architecture:** Language cards live with the `game_webnovel` genre and are selected by deterministic trigger scoring over the chapter plan. The orchestrator renders at most three compact cards into the existing writer craft section. Prose review remains a backstop for backend terms; it does not choose vocabulary.

**Tech Stack:** Python 3.12, dataclasses, pytest, existing story-core prompt composition.

---

### Task 1: Define scene language cards and deterministic selection

**Files:**
- Modify: `packages/story_core/genre_types/game_webnovel.py`
- Test: `tests/story_core/test_game_webnovel_language.py`

- [x] **Step 1: Write failing tests for task, combat, trade and nonmatching selection**

Create tests that call `select_game_language_cards()` with plans containing `接任务`, `灰狼战斗`, or `求购单`, then assert that `quest`, `combat`, or `trade` is selected. Assert `base` is always present, selection has at most three cards, and a non-game plan gets no scene-specific match.

- [x] **Step 2: Run the focused test and confirm import failure**

Run: `python -m pytest tests/story_core/test_game_webnovel_language.py -q`

Expected: FAIL because `select_game_language_cards` does not exist.

- [x] **Step 3: Implement immutable language cards**

Add `GameLanguageCard` with `card_id`, `trigger_terms`, `preferred`, `avoid`, and `example`. Add cards for `base`, `login_server`, `quest`, `combat`, `loot_inventory`, `trade`, and `group_dungeon`. Implement deterministic scoring, always returning `base` plus the two highest positive matches.

- [x] **Step 4: Run the focused test**

Run: `python -m pytest tests/story_core/test_game_webnovel_language.py -q`

Expected: PASS.

### Task 2: Inject only selected cards into writer context

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_writer_prompt_method.py`

- [x] **Step 1: Write failing prompt-selection tests**

Build a trade plan and assert the method card contains `求购单` but not dungeon vocabulary. Build a combat plan and assert it contains `仇恨/脱战` but not `一口价`.

- [x] **Step 2: Pass the plan into `_web_game_writing_method_lines`**

Change the helper to accept `plan`, call `select_game_language_cards(plan)`, and render compact preferred/avoid/example lines. Update all callers while preserving the chapter-one phase hint.

- [x] **Step 3: Run writer prompt tests**

Run: `python -m pytest tests/story_core/test_writer_prompt_method.py -q`

Expected: PASS.

### Task 3: Verify review guardrails and regression safety

**Files:**
- Modify: `tests/story_core/test_prose_style_review.py` only if coverage is missing
- Verify: `data/exported-projects/p-gou-webgame-restored/.story-system/chapters/0001.json`

- [x] **Step 1: Verify backend terms fail and player terms pass**

Run: `python -m pytest tests/story_core/test_prose_style_review.py -q`

Expected: PASS for both existing cases.

- [x] **Step 2: Review the current first chapter locally**

Call `review_prose_style` for chapter 1 and assert the issue list is empty.

- [x] **Step 3: Run the complete story-core suite**

Run: `python -m pytest tests/story_core -q`

Expected: all tests pass.
