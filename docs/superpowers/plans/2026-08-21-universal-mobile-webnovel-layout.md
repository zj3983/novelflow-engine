# Universal Mobile Webnovel Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mobile-friendly paragraph formatting the default for every novel while keeping game-panel formatting genre-specific.

**Architecture:** Keep the universal prose layout contract in one shared module and load it from both writer entry points, remove the duplicate layout contract from the optional commercial-shuangwen skill, and align deterministic prose review with the same contract. The writer remains the only producer of prose; review reports violations without rewriting.

**Tech Stack:** Python 3.11, pytest, Markdown skill packs.

---

### Task 1: Add the universal writer layout contract

**Files:**
- Add: `packages/story_core/prose_layout.py`
- Modify: `packages/story_core/agents/writer/prompt.py`
- Modify: `packages/story_core/genre_stages/common_writer.py`
- Test: `tests/story_core/test_modular_writer_agent.py`
- Test: `tests/story_core/test_writer_prompt_method.py`

- [x] **Step 1: Write the failing test**

Add a test that builds the baseline writer prompt without skills and asserts it contains these ideas: ordinary paragraphs use one or two complete sentences, dialogue changes paragraph with the speaker, impact-only short paragraphs, and no telegraphic fragments.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/story_core/test_modular_writer_agent.py -k universal_mobile_layout -q`

Expected: FAIL because the baseline prompt lacks the universal layout contract.

- [x] **Step 3: Write minimal implementation**

Add these rules under `## 成稿要求` in `build_writer_prompt`:

```python
"- 普通叙述段通常写一至两句完整的话；场景、动作、观察或话题变化时换段。\n"
"- 对话独立成段，换说话人就换段；同一人的完整发言不机械拆碎。\n"
"- 单句短段只用于真正的转折、揭晓、打断或冲击；换行不能代替完整语法和自然语气。\n"
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/story_core/test_modular_writer_agent.py -k "universal_mobile_layout or clipped_character_speech" -q`

Expected: PASS.

### Task 2: Align deterministic prose review

**Files:**
- Modify: `packages/story_core/prose_rule_review.py`
- Modify: `packages/story_core/prose_style_review.py`
- Modify: `packages/story_core/genre_stages/postprocess.py`
- Test: `tests/story_core/test_prose_style_review.py`
- Test: `tests/story_core/test_generation_quality_guardrails.py`

- [x] **Step 1: Write failing review tests**

Add one test proving a chapter made of complete one-to-two-sentence paragraphs is accepted, and one test proving repeated telegraphic fragments such as `窗坏。瓦落。门锁坏。` are reported.

- [x] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/story_core/test_prose_style_review.py -k paragraph -q`

Expected: the complete short-paragraph sample is incorrectly rejected or telegraphic prose is not detected.

- [x] **Step 3: Replace the long-paragraph quota**

Remove the rule requiring a four-to-six-sentence block every five paragraphs. Change `review_paragraph_form` and `review_prose_style` to report repeated ultra-short fragments rather than short-paragraph ratio. Remove the postprocessor that merges valid one-to-two-sentence paragraphs. Keep all review return schemas unchanged.

- [x] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/story_core/test_prose_style_review.py tests/story_core/test_generation_quality_guardrails.py -q`

Expected: PASS.

### Task 3: Remove duplicate commercial-shuangwen layout control

**Files:**
- Modify: `data/skill-packs/commercial-shuangwen/skills/writer-execution/SKILL.md`
- Modify: `tests/story_core/test_commercial_shuangwen_skill.py`

- [x] **Step 1: Change the skill contract test**

Assert the optional skill still includes pressure, counterattack and payoff instructions, but no longer contains universal paragraph or dialogue-layout rules.

- [x] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/story_core/test_commercial_shuangwen_skill.py -k layout -q`

Expected: FAIL while duplicate rules remain.

- [x] **Step 3: Remove only duplicate layout bullets**

Keep the concrete commercial payoff example. Delete paragraph-length, dialogue paragraph and short-impact paragraph bullets. Keep the game-panel example out of this generic narrative skill because panel rendering belongs to the game genre module.

- [x] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/story_core/test_commercial_shuangwen_skill.py -q`

Expected: PASS.

### Task 4: Verify genre isolation and real writing packet

**Files:**
- Test: `tests/story_core/test_genre_prompt_isolation.py`
- Test: `tests/story_core/test_writer_prompt_method.py`

- [x] **Step 1: Run focused prompt suites**

Run: `python -m pytest tests/story_core/test_modular_writer_agent.py tests/story_core/test_commercial_shuangwen_skill.py tests/story_core/test_prose_style_review.py tests/story_core/test_genre_prompt_isolation.py tests/story_core/test_writer_prompt_method.py -q`

Expected: PASS.

- [x] **Step 2: Inspect the current project's writing packet**

Request chapter 2 writing packet for `file:p-319ffcae3c66490c88f42b922bbf6b7e`. Confirm the universal rules appear once and that game-panel guidance remains present only through the game genre context.

- [x] **Step 3: Review the diff**

Run: `git diff -- packages/story_core/agents/writer/prompt.py packages/story_core/prose_rule_review.py data/skill-packs/commercial-shuangwen/skills/writer-execution/SKILL.md tests/story_core/test_modular_writer_agent.py tests/story_core/test_prose_style_review.py tests/story_core/test_commercial_shuangwen_skill.py`

Expected: no unrelated refactor and no existing chapter rewrite.
