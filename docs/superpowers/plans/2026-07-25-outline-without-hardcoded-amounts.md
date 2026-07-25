# Amount-Free AI Outlines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent AI-generated outline narrative fields from hardcoding monetary amounts while preserving amounts already established in prose and continuity state.

**Architecture:** Add a focused validator for generated overall, arc, and chapter narrative fields and invoke it from both opening and continuation validation paths. Reinforce the same contract in the outline-generation prompt, then update the current project's JSON outline source and Markdown mirrors without touching prose or state.

**Tech Stack:** Python 3.12, Pydantic, pytest, JSON and Markdown project storage.

---

### Task 1: Reject monetary hard anchors in all generated outline levels

**Files:**
- Modify: `tests/story_core/test_outline_planning.py`
- Modify: `packages/story_core/outline_planning.py`

- [ ] **Step 1: Write failing opening and continuation tests**

Add tests that place `担保交易到账1764.00元` and `手续费5%后余额332.60元` in generated chapter fields and expect `generated_outline_contains_monetary_amount:<chapter_number>:<field>`. Add a passing case containing `击杀5只灰狼，升到2级，扣除手续费后款项到账`.

- [ ] **Step 2: Verify the tests fail**

Run: `pytest tests/story_core/test_outline_planning.py -k monetary -v`

Expected: FAIL because generated outlines currently accept monetary hard anchors.

- [ ] **Step 3: Add shared generated-outline validation**

In `outline_planning.py`, detect explicit currency amounts, balances, and fee percentages in generated overall, arc, and chapter narrative fields. Exclude identifiers, character names, cast, trope IDs, chapter/range numbers, levels, quantities, durations, and unrelated gameplay percentages. Call the validator after Pydantic parsing in both generated-plan validation functions and raise a stable location error.

- [ ] **Step 4: Verify the focused tests pass**

Run: `pytest tests/story_core/test_outline_planning.py -k monetary -v`

Expected: PASS.

### Task 2: Tell the outline model not to emit monetary anchors

**Files:**
- Modify: `tests/story_core/test_outline_planning_generation.py`
- Modify: `packages/story_core/outline_planning_generation.py`

- [ ] **Step 1: Write a failing prompt-contract test**

Generate a plan with `RecordingRuntime` and assert that `prompt_context.validation_rules` and the system prompt state that chapter outlines may describe financial outcomes but must not contain exact currency amounts, balances, or fee percentages.

- [ ] **Step 2: Verify the prompt test fails**

Run: `pytest tests/story_core/test_outline_planning_generation.py -k monetary -v`

Expected: FAIL because the instruction is absent.

- [ ] **Step 3: Add the prompt rule**

Append the same concise amount-free rule to `validation_rules` for every mode and to the system message so providers that underweight JSON context still receive it.

- [ ] **Step 4: Verify generation tests pass**

Run: `pytest tests/story_core/test_outline_planning_generation.py -k monetary -v`

Expected: PASS.

### Task 3: Clean the current project's outline only

**Files:**
- Modify: `data/exported-projects/p-gou-webgame-restored/.webnovel/outline.json`
- Modify: `data/exported-projects/p-gou-webgame-restored/大纲/第1卷-详细大纲.md`

- [ ] **Step 1: Replace the chapter-one payoff in both representations**

Replace exact financial anchors throughout the current project's canonical overall, arc, and chapter narrative fields with qualitative plot outcomes, then synchronize the JSON source and Markdown mirrors.

- [ ] **Step 2: Verify outline and history boundaries**

Run: `rg -n "1764|332\\.60" data/exported-projects/p-gou-webgame-restored/.webnovel/outline.json data/exported-projects/p-gou-webgame-restored/大纲`

Expected: no matches.

Run: `rg -n "1764|332\\.60" data/exported-projects/p-gou-webgame-restored/chapters data/exported-projects/p-gou-webgame-restored/.webnovel/state.json`

Expected: matches remain, proving prose and continuity history were preserved.

### Task 4: Regression verification and commit

**Files:**
- Verify all files changed above.

- [ ] **Step 1: Run focused suites**

Run: `pytest tests/story_core/test_outline_planning.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_outline_markdown_sync.py -q`

Expected: all pass.

- [ ] **Step 2: Run formatting and diff checks**

Run: `git diff --check`

Expected: exit code 0.

- [ ] **Step 3: Verify the project page**

Reload `http://localhost:3000/projects/file%3Ap-gou-webgame-restored`, open the outline view, and confirm chapter one shows the amount-free payoff.

- [ ] **Step 4: Commit**

```bash
git add packages/story_core/outline_planning.py packages/story_core/outline_planning_generation.py tests/story_core/test_outline_planning.py tests/story_core/test_outline_planning_generation.py data/exported-projects/p-gou-webgame-restored/.webnovel/outline.json data/exported-projects/p-gou-webgame-restored/大纲/第1卷-详细大纲.md docs/superpowers/plans/2026-07-25-outline-without-hardcoded-amounts.md
git commit -m "fix: keep exact amounts out of generated outlines"
```
