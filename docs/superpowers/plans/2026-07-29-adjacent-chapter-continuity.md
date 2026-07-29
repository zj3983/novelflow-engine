# Adjacent Chapter Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chapter generation and historical rewrites use the real previous ending, confirmed facts, and an optional next-opening boundary, then block obvious character-presence and Chinese-fragment regressions.

**Architecture:** Add one focused continuity module that builds a serializable interface and reviews deterministic violations. `FileProjectStore` supplies adjacent persisted chapters; the orchestrator exposes the same interface to director, writer, and review stages. The interface is transient under `outline_context` and never becomes a world fact.

**Tech Stack:** Python 3.11+, Pydantic story models, pytest, FastAPI file-project storage, Next.js/TypeScript workbench.

---

### Task 1: Build The Continuity Interface

**Files:**
- Create: `packages/story_core/chapter_continuity.py`
- Create: `tests/story_core/test_chapter_continuity.py`

- [ ] **Step 1: Write failing interface tests**

```python
from packages.story_core.chapter_continuity import build_continuity_interface


def test_interface_uses_previous_tail_and_confirmed_facts():
    result = build_continuity_interface(
        144,
        previous={"chapter_number": 143, "body": "开头" + "中" * 1200 + "沈墨璃离开神殿。", "chapter_summary": {"facts": ["沈墨璃离开神殿。"]}},
        next_chapter=None,
    )
    assert result["previous_tail"].endswith("沈墨璃离开神殿。")
    assert result["previous_facts"] == ["沈墨璃离开神殿。"]
    assert "next_opening" not in result


def test_interface_includes_next_opening_for_historical_rewrite():
    result = build_continuity_interface(
        144,
        previous=None,
        next_chapter={"chapter_number": 145, "body": "下一章开头" + "后" * 900},
    )
    assert result["next_chapter_number"] == 145
    assert result["next_opening"].startswith("下一章开头")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/story_core/test_chapter_continuity.py -q`

Expected: collection fails because `packages.story_core.chapter_continuity` does not exist.

- [ ] **Step 3: Implement the compact transient interface**

```python
FACT_PRIORITY = ["已发生剧情", "本章计划", "静态人物设定", "后续旧稿"]


def build_continuity_interface(target_chapter, *, previous=None, next_chapter=None):
    result = {"fact_priority": FACT_PRIORITY}
    # Copy the previous body tail and structured facts/threads with fixed limits.
    # Copy the next body opening only when a persisted next chapter is supplied.
    return result
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/story_core/test_chapter_continuity.py -q`

Expected: all tests pass.

### Task 2: Supply Adjacent Chapters During File-Project Generation

**Files:**
- Modify: `packages/story_core/file_project_store.py:5235-5358`
- Modify: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write a failing file-store test**

```python
def test_regeneration_direction_payload_contains_adjacent_chapter_interface(file_project_store):
    payload = file_project_store._story_state_payload_for_direction(
        file_project_store._regeneration_base_state(144, file_project_store.state()),
        file_project_store.project(),
        144,
    )
    interface = payload["outline_context"]["continuity_interface"]
    assert interface["previous_chapter_number"] == 143
    assert "沈墨璃离开" in " ".join(interface["previous_facts"])
    assert interface["next_chapter_number"] == 145
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pytest tests/story_core/test_file_project_store.py -k adjacent_chapter_interface -q`

Expected: `continuity_interface` is missing.

- [ ] **Step 3: Inject the transient interface**

In `_story_state_payload_for_direction`, read chapters `target_chapter - 1` and `target_chapter + 1` when present, call `build_continuity_interface`, and assign the result to a copied `outline_context["continuity_interface"]`. Missing chapter files must return `None` rather than fail generation.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pytest tests/story_core/test_file_project_store.py -k adjacent_chapter_interface -q`

Expected: test passes.

### Task 3: Give Director And Writer The Same Interface

**Files:**
- Modify: `packages/story_core/orchestrator.py:2150-2180`
- Modify: `packages/story_core/orchestrator.py:5226-5378`
- Modify: `packages/story_core/orchestrator.py:2468-2585`
- Modify: `tests/story_core/test_writer_prompt_method.py`
- Modify: `tests/story_core/test_chapter_seed.py`

- [ ] **Step 1: Write failing prompt tests**

```python
def test_writer_prompt_uses_adjacent_interface_instead_of_summary_opening(story):
    story.outline_context["continuity_interface"] = {
        "previous_tail": "沈墨璃踏入密道，殿门合拢。",
        "previous_facts": ["沈墨璃离开神殿。"],
        "next_opening": "第145章旧稿开头。",
        "fact_priority": ["已发生剧情", "本章计划", "静态人物设定", "后续旧稿"],
    }
    prompt = Orchestrator()._render_body_prompt(story, 144, minimal_plan())
    assert "相邻章节接口" in prompt
    assert "沈墨璃离开神殿" in prompt
    assert "后续旧稿不能覆盖已发生剧情" in prompt
```

- [ ] **Step 2: Run prompt tests and verify RED**

Run: `pytest tests/story_core/test_writer_prompt_method.py -k adjacent_interface -q`

Expected: interface text is absent.

- [ ] **Step 3: Render a short dedicated section**

Extend `_director_prompt_outline_context` with a compact `continuity_interface`. Add `_writer_continuity_section(story)` and place it before general author constraints. Stop labeling the free-form summary as “上一章留下”; keep it only as a recap after the interface.

- [ ] **Step 4: Reject plans that directly violate an explicit departure fact**

Extract names from facts matching `姓名 + 离开/前往/踏入...消失`. If a director move places that name in the current scene without a return/赶回/抵达 action, append a concrete quality issue.

- [ ] **Step 5: Run prompt and director tests**

Run: `pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_chapter_seed.py -q`

Expected: all tests pass.

### Task 4: Block Character Reappearance And Chinese Fragments

**Files:**
- Modify: `packages/story_core/chapter_continuity.py`
- Modify: `packages/story_core/orchestrator.py:3558-4125`
- Modify: `packages/story_core/simplified_review.py`
- Modify: `tests/story_core/test_chapter_continuity.py`
- Modify: `tests/story_core/test_generation_quality_guardrails.py`
- Modify: `tests/story_core/test_simplified_review.py`

- [ ] **Step 1: Write failing review tests**

```python
def test_review_blocks_departed_character_speaking_without_return():
    interface = {"previous_facts": ["沈墨璃离开神殿，前往沈家。"]}
    review = review_continuity_interface("沈墨璃落在林修身侧。\n“我回来了。”", interface)
    assert review["hard_error"] is True


@pytest.mark.parametrize("line", [
    "这一次她自己做出的选择。",
    "她的意思实打实。",
    "修，便是在替对方铺路。",
])
def test_review_flags_compressed_chinese_fragments(line):
    assert review_chinese_fragments(line)
```

- [ ] **Step 2: Run review tests and verify RED**

Run: `pytest tests/story_core/test_chapter_continuity.py tests/story_core/test_generation_quality_guardrails.py -k "departed or compressed_chinese" -q`

Expected: new checks are missing.

- [ ] **Step 3: Implement narrow deterministic checks**

Only treat a departed character as returned when the body gives an explicit return transition before their first action/dialogue. Detect the listed grammatical shapes without adding a general short-sentence ban. Merge blocking continuity issues into `_review_chapter_body` and make `_should_run_full_revision` treat them as revision-required.

- [ ] **Step 4: Run review tests and verify GREEN**

Run: `pytest tests/story_core/test_chapter_continuity.py tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_simplified_review.py -q`

Expected: all tests pass.

### Task 5: Expose Downstream Rewrite Status And Verify End To End

**Files:**
- Modify: `packages/story_core/file_project_store.py:4989-5033`
- Modify: `apps/web/lib/api.ts:483-535`
- Modify: `apps/web/app/projects/[id]/write/page.tsx:190-220`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing API/UI tests**

Add a store test asserting that a historical rewrite with a detected next-interface conflict returns `downstream_rewrite_required: true` and `downstream_chapter_number: 145`. Add a workbench test asserting that the chapter page shows “第145章需要同步重写” from those fields.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `pytest tests/story_core/test_file_project_store.py -k downstream_rewrite -q`

Run: `npm --prefix apps/web test -- --runInBand story-workbench.spec.ts`

Expected: fields and notice are missing.

- [ ] **Step 3: Persist and display the warning**

Copy downstream status from the writing review into `quality_report`, expose typed optional fields in `api.ts`, and render one compact warning near the existing quality summary. Do not delete downstream chapters automatically.

- [ ] **Step 4: Run focused and regression verification**

Run: `pytest tests/story_core/test_chapter_continuity.py tests/story_core/test_file_project_store.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_simplified_review.py -q`

Run: `npm --prefix apps/web test -- --runInBand story-workbench.spec.ts`

Run: `python -m compileall packages/story_core`

Expected: all commands exit 0.
