# 最终正文驱动写作闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让所有题材使用完整连续性输入，让长期剧情合同不串题材，并让人物、账本和下一章承接只从最终采用的正文回写。

**Architecture:** 保留现有 `StoryOrchestrator` 的计划、整章写作和一次修订骨架。新增独立的 `post_draft_memory.py`，负责构造最终正文记忆提示、校验证据和规范化更新；`orchestrator.py` 只负责调用模型和编排。`plot_contract.py` 通过题材分支生成长期合同。清理器只做表面清理，缺失场景由审稿和一次改稿解决。

**Tech Stack:** Python 3.11、Pydantic、pytest、FastAPI、Next.js 14、Codex CLI/OpenAI-compatible chat provider。

---

### Task 1: 建立恢复点并锁定题材连续性行为

**Files:**
- Modify: `tests/story_core/test_novel_type_catalog.py`
- Modify: `tests/story_core/test_longform_plan.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/plot_contract.py`

- [ ] **Step 1: 记录数据库和历史正文哈希**

Run the existing SQLite backup helper used in the worktree organization plan and save a new baseline to:

```text
%TEMP%\xiaoshuofish-post-draft-loop-baseline.json
```

The baseline must include project `p-xianxia-incense-test-2`, active story id, genre ids, chapter title, body length and SHA-256. Do not generate or rewrite a chapter.

- [ ] **Step 2: Add failing non-game director prompt tests**

Extend `tests/story_core/test_novel_type_catalog.py` so a `xuanhuan` story with a latest summary, unresolved thread and named supporting character asserts:

```python
prompt = StoryOrchestrator()._plan_prompt(story, 2)

assert "本章连续性材料" in prompt
assert "上一章" in prompt
assert "林照" in prompt
assert "周执事" in prompt
assert "千倍爆率" not in prompt
assert "铜币" not in prompt
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/story_core/test_novel_type_catalog.py -q
```

Expected: FAIL because the non-game branch does not include `chapter_seed`.

- [ ] **Step 3: Add failing genre-specific longform tests**

Extend `tests/story_core/test_longform_plan.py` with:

```python
def test_xuanhuan_longform_contract_has_no_webgame_opening_rules():
    story = StoryState(
        story_id="s-xuanhuan-longform",
        outline="林照守住祖祠断香炉，并逐步查清香火异动。",
        genre="xuanhuan",
        world_facts=["小说类型：xuanhuan"],
    )

    contract = build_longform_plot_contract(
        story,
        1,
        chapter_goal="守住今夜香火",
        game_story=False,
    )

    text = json.dumps(contract, ensure_ascii=False)
    assert "千倍爆率" not in text
    assert "铜币" not in text
    assert "守住今夜香火" in text
    assert contract["genre_mode"] == "xuanhuan"
```

Add matching tests for `xianxia`, `game_webnovel`, and unknown genre fallback.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/story_core/test_longform_plan.py -q
```

Expected: FAIL because `_arc_window` and `_pace_contract` are webgame-specific.

- [ ] **Step 4: Include the shared continuity packet in every director prompt**

Modify `StoryOrchestrator._plan_prompt` so the non-game branch includes:

```python
f"本章连续性材料：{_plain_prompt_json(chapter_seed)}"
```

Use the same shared schema for all genres. Keep game-only economy and panel instructions inside the game branch. Expand the director character snapshot from the first two global characters to the characters selected as active/relevant for the chapter, capped at four detailed cards.

- [ ] **Step 5: Split longform contracts by genre**

Refactor `plot_contract.py`:

```python
def _genre_mode(story: StoryState, game_story: bool) -> str: ...
def _arc_window(chapter_number: int, *, genre_mode: str) -> dict[str, str]: ...
def _pace_contract(chapter_number: int, level: int | None, *, genre_mode: str) -> dict[str, str]: ...
```

Rules:

- `game_webnovel`: preserve current level, task and resource snowball behavior.
- `xuanhuan`: use identity, strength system, faction pressure, opportunity and cost without inventing realm names.
- `xianxia`: use cultivation, cause-and-effect, sect/social order and resource cost without inventing realm names.
- unknown: use only goal, relationship, information, resource and risk changes.

Add `genre_mode` to the returned contract. User outline, `chapter_goal` and previous `next_focus` take priority over chapter-number defaults.

- [ ] **Step 6: Verify genre planning**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/story_core/test_novel_type_catalog.py tests/story_core/test_longform_plan.py tests/story_core/test_chapter_simulation_plan.py -q
```

Expected: PASS with no genre contamination.

- [ ] **Step 7: Commit the planning repair**

```powershell
git add -- packages/story_core/orchestrator.py packages/story_core/plot_contract.py tests/story_core/test_novel_type_catalog.py tests/story_core/test_longform_plan.py tests/story_core/test_chapter_simulation_plan.py
git diff --cached --check
git commit -m "fix: keep chapter planning genre aware"
```

---

### Task 2: Add evidence-backed post-draft memory normalization

**Files:**
- Create: `packages/story_core/post_draft_memory.py`
- Create: `tests/story_core/test_post_draft_memory.py`

- [ ] **Step 1: Add failing evidence-validation tests**

Create tests for the wished-for API:

```python
from packages.story_core.post_draft_memory import (
    build_post_draft_memory_prompt,
    fallback_post_draft_memory,
    normalize_post_draft_memory,
)


def test_post_draft_memory_keeps_only_body_grounded_updates():
    body = "林照把断香炉搬回偏殿。周执事让他明早去账房回话。"
    payload = {
        "summary": "林照保住断香炉，并接到明早回话的要求。",
        "facts": [
            {"text": "断香炉已搬到偏殿", "evidence": "把断香炉搬回偏殿"},
            {"text": "林照得到三枚灵石", "evidence": "三枚灵石"},
        ],
        "unresolved_threads": [
            {"text": "账房为何找林照", "evidence": "明早去账房回话"},
        ],
        "next_focus": "明早去账房",
        "character_updates": [
            {"name": "林照", "emotion": "警惕", "goal": "明早去账房", "location": "偏殿", "evidence": "明早去账房回话"},
            {"name": "陌生人", "emotion": "愤怒", "evidence": "陌生人"},
        ],
        "ledger_updates": {"protagonist": {"location": "偏殿", "spirit_stones": 3}},
        "ledger_evidence": {
            "protagonist.location": "搬回偏殿",
            "protagonist.spirit_stones": "三枚灵石",
        },
    }

    result = normalize_post_draft_memory(payload, body=body, existing_character_names={"林照", "周执事"})

    assert result["facts"] == ["断香炉已搬到偏殿"]
    assert [item["name"] for item in result["character_updates"]] == ["林照"]
    assert result["ledger_updates"] == {"protagonist": {"location": "偏殿"}}
```

Also test normalized whitespace evidence, invalid payloads, missing evidence, and fallback behavior.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/story_core/test_post_draft_memory.py -q
```

Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement the isolated memory module**

Implement:

```python
def build_post_draft_memory_prompt(... ) -> str: ...
def normalize_post_draft_memory(payload: Any, *, body: str, existing_character_names: set[str]) -> dict[str, Any]: ...
def fallback_post_draft_memory(body: str, *, previous_next_focus: str = "") -> dict[str, Any]: ...
```

Requirements:

- Prompt states that only the final body is factual.
- Facts, threads, character updates and every flattened ledger path require evidence.
- Evidence matching normalizes whitespace and punctuation but does not use fuzzy semantic guesses.
- Unknown characters are ignored and reported in `rejected_updates`.
- Invalid data returns a normalized empty result rather than raising into generation.
- Fallback summary comes from the final body and contains no planned ledger or character changes.

- [ ] **Step 3: Verify the module**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/story_core/test_post_draft_memory.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit the memory boundary**

```powershell
git add -- packages/story_core/post_draft_memory.py tests/story_core/test_post_draft_memory.py
git diff --cached --check
git commit -m "feat: validate memory against final chapter prose"
```

---

### Task 3: Make final prose the only persisted chapter state

**Files:**
- Modify: `packages/story_core/memory.py`
- Modify: `packages/story_core/memory_agent.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `tests/story_core/test_memory_retrieval.py`
- Modify: `tests/story_core/test_orchestrator.py`
- Modify: `tests/story_core/test_generation_quality_guardrails.py`

- [ ] **Step 1: Add failing memory-application tests**

Add tests proving:

- `apply_post_chapter_updates` uses supplied final summary, facts, unresolved threads and next focus.
- It no longer writes “调查仍在继续推进”, `alert`, `wary`, or “迷局深处”.
- Character emotion, goal and location update only from validated `character_updates`.
- Existing relationships are not changed merely because a planned conflict named a character.

Run the focused memory tests and verify the old generic behavior fails the new assertions.

- [ ] **Step 2: Add a failing orchestrator ordering test**

Use a fake `_chat` that returns:

1. a plan containing a deliberately wrong planned fact;
2. a final body with a different actual result;
3. a memory payload grounded in the final body.

Assert that:

- the memory call happens after the final writer/revision body is selected;
- the memory prompt contains the selected body;
- persisted facts and ledger use the memory payload;
- planned `memory_constraints.ledger_updates` and simulated ledger deltas are not applied directly;
- the bundle exposes `memory_sync.status == "ok"`.

Add a second test where the memory call fails and assert `memory_sync.status == "fallback"` with no planned state updates.

- [ ] **Step 3: Refactor memory application**

Change `apply_post_chapter_updates` to accept a normalized post-draft memory result. Preserve timeline and memory index creation, but source them from final memory/body. Remove generic facts, locations and emotions.

Update `MemoryAgent` compatibility callers to construct the same normalized shape or use `fallback_post_draft_memory`.

- [ ] **Step 4: Integrate one Memory Agent call**

In `generate_next_chapter`:

1. Finish initial writing, optional expansion, optional style adaptation, review, optional one revision and optional compression.
2. Call `_timed_chat(..., agent="memory", json_mode=True)` with `build_post_draft_memory_prompt` and the selected final body.
3. Normalize the response against the body.
4. Apply only validated memory and ledger updates.
5. Do not apply planning `memory_constraints.ledger_updates` or scene-card ledger deltas directly.
6. Store `memory_sync` in `simulation_plan` and `quality_report`.

The plan-stage `chapter_summary` field may remain accepted for backward compatibility, but generation must not use it as persisted truth.

- [ ] **Step 5: Verify memory integration**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/story_core/test_post_draft_memory.py tests/story_core/test_memory_retrieval.py tests/story_core/test_orchestrator.py tests/story_core/test_generation_quality_guardrails.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit post-draft persistence**

```powershell
git add -- packages/story_core/memory.py packages/story_core/memory_agent.py packages/story_core/orchestrator.py tests/story_core/test_memory_retrieval.py tests/story_core/test_orchestrator.py tests/story_core/test_generation_quality_guardrails.py
git diff --cached --check
git commit -m "fix: persist state from final chapter prose"
```

---

### Task 4: Stop the sanitizer from writing fiction

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Modify: `tests/story_core/test_generation_quality_guardrails.py`
- Modify: `tests/story_core/test_world_state_delta.py`
- Modify: `tests/story_core/test_progression_lead_review.py`

- [ ] **Step 1: Replace insertion expectations with failing non-authoring tests**

Change sanitizer tests so bodies missing dialogue, emotion, outsider misread, NPC service or hooks remain missing after sanitation. Assert that formatting cleanup and safe terminology normalization still occur.

Representative assertion:

```python
cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
assert cleaned == body
assert "夜烬开口" not in cleaned
assert "心里" not in cleaned
```

Run focused tests. Expected: FAIL because current `_ensure_*` helpers insert prose.

- [ ] **Step 2: Remove authoring calls from `_sanitize_chapter_output`**

Stop calling helpers that add complete sentences or scenes:

- protagonist speech;
- emotion anchors;
- outsider misread;
- missing venom scene;
- NPC service boundary;
- progression hook;
- reality skill source, trigger anchor and NPC window when they create prose.

Keep non-authoring normalization and deletion-only safety rules. Retain detector functions where reviews still use them.

- [ ] **Step 3: Verify sanitizer and review separation**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_world_state_delta.py tests/story_core/test_progression_lead_review.py -q
```

Expected: PASS. Missing content appears as review issues, not inserted text.

- [ ] **Step 4: Commit sanitizer cleanup**

```powershell
git add -- packages/story_core/orchestrator.py tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_world_state_delta.py tests/story_core/test_progression_lead_review.py
git diff --cached --check
git commit -m "fix: keep prose sanitizer non-authoring"
```

---

### Task 5: Trigger one targeted revision for AI flavor and dialogue

**Files:**
- Modify: `packages/story_core/simplified_review.py`
- Modify: `packages/story_core/writing_learning.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `tests/story_core/test_simplified_review.py`
- Modify: `tests/story_core/test_writing_learning.py`
- Modify: `tests/story_core/test_generation_quality_guardrails.py`

- [ ] **Step 1: Add failing review-gate tests**

Define the desired report:

```python
assert report["has_hard_errors"] is False
assert report["needs_revision"] is True
assert report["categories"]["dialogue"]["count"] == 1
```

AI味 and dialogue issues should trigger `needs_revision`. Ordinary prose advice should not. Preserve the five-item display limit.

- [ ] **Step 2: Add a failing one-revision orchestration test**

Mock local review results so the initial body has a dialogue or AI-flavor issue without hard errors. Assert the writer receives exactly one revision request, candidate safety chooses the better body, and no second revision call occurs.

- [ ] **Step 3: Implement the internal gate**

Add `DIALOGUE_TOKENS`, a `dialogue` category and `needs_revision` to `build_simplified_review`. Keep `pass` meaning “no hard continuity error” for UI compatibility. Change `generate_next_chapter` to trigger its existing single revision block on `needs_revision`.

- [ ] **Step 4: Record only accepted revision learning**

Add a helper in `writing_learning.py` that records a compact positive lesson only when `revision_safety.selected == "candidate"`. It should state the issue category, adopted change and protected facts. Do not store full reports or body excerpts.

- [ ] **Step 5: Verify review and learning behavior**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/story_core/test_simplified_review.py tests/story_core/test_writing_learning.py tests/story_core/test_generation_quality_guardrails.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the revision gate**

```powershell
git add -- packages/story_core/simplified_review.py packages/story_core/writing_learning.py packages/story_core/orchestrator.py tests/story_core/test_simplified_review.py tests/story_core/test_writing_learning.py tests/story_core/test_generation_quality_guardrails.py
git diff --cached --check
git commit -m "fix: revise clear prose failures once"
```

---

### Task 6: Full regression, data integrity and runtime verification

**Files:**
- Read: `%TEMP%\xiaoshuofish-post-draft-loop-baseline.json`
- Preserve: `apps/api/data/stories.db`

- [ ] **Step 1: Compile and run the complete Python suite**

```powershell
.\.venv\Scripts\python.exe -m compileall -q apps/api packages/story_core scripts
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: at least the current `854 passed`, with no failures.

- [ ] **Step 2: Run the frontend production build**

```powershell
npm.cmd run build --prefix apps/web
```

Expected: compile, type check and static generation succeed.

- [ ] **Step 3: Verify historical data hashes**

Read the baseline and assert project id, active story id, genre ids, chapter count, chapter titles, body lengths and SHA-256 values are unchanged.

- [ ] **Step 4: Verify prompts without generating official chapters**

Use local unit-level calls to build:

- a chapter 2 `xuanhuan` director prompt;
- a chapter 2 `game_webnovel` director prompt;
- both longform contracts;
- a post-draft memory prompt from an in-memory sample body.

Assert no cross-genre terms and no raw report fields leak into prose prompts.

- [ ] **Step 5: Restart services and smoke test**

Restart API on `127.0.0.1:8000` and web on `localhost:3000`, then verify:

```text
GET /health -> 200
GET /projects/p-xianxia-incense-test-2/write?chapter=1 -> 200
```

- [ ] **Step 6: Final repository check**

```powershell
git status --short
git log --oneline -8
code-review-graph update --brief
```

Expected: clean worktree, complete commits, updated code graph and unchanged novel data.
