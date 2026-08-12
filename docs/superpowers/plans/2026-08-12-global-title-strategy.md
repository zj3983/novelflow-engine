# Global Title Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one global, genre-aware strategy for book names and chapter titles, lock chapter titles at outline time, and keep title formulas out of writer prompts.

**Architecture:** A new pure `title_strategy.py` module owns title guidance, genre vocabulary, shape classification, and deterministic window validation. Opening-direction generation and chapter-outline generation consume that module; the director preserves the selected outline title instead of inventing another one, while the writer continues receiving only final project metadata and the director artifact.

**Tech Stack:** Python 3.12, Pydantic, pytest, FastAPI integration tests, existing runtime model gateway.

---

## File Structure

- Create `packages/story_core/title_strategy.py`: global title guidance, genre term selection, title-shape checks, and outline-window validation.
- Create `tests/story_core/test_title_strategy.py`: pure unit tests for cross-genre guidance and anti-template checks.
- Modify `packages/story_core/opening_directions.py`: add book-title guidance to all three opening direction candidates.
- Modify `packages/story_core/outline_planning_generation.py`: add chapter-title guidance and validate generated title windows.
- Modify `packages/story_core/agents/director/prompt.py`: require the director to preserve the title already selected by the chapter outline.
- Modify `packages/story_core/agents/director/agent.py`: make the deterministic outline shortcut and runtime path use the same locked title.
- Modify `tests/story_core/test_opening_directions.py`: verify every genre receives the global book-title strategy.
- Modify `tests/story_core/test_outline_planning_generation.py`: verify title guidance reaches chapter planning and invalid repeated title shapes fail validation.
- Modify `tests/story_core/test_modular_director_agent.py`: verify the director preserves the outline title.
- Modify `tests/story_core/test_modular_writer_agent.py`: prove title formulas and examples never enter the writer prompt.
- Modify `tests/story_core/test_pipeline_boundaries.py`: prove planning-only title strategy data stops at the director/writer boundary.

### Task 1: Add the pure global title strategy

**Files:**
- Create: `packages/story_core/title_strategy.py`
- Create: `tests/story_core/test_title_strategy.py`

- [ ] **Step 1: Write failing genre and shape tests**

```python
from packages.story_core.title_strategy import (
    build_book_title_guidance,
    build_chapter_title_guidance,
    validate_chapter_title_window,
)


def test_game_guidance_contains_game_examples_but_xuanhuan_does_not():
    game = build_book_title_guidance("game_webnovel")
    xuanhuan = build_book_title_guidance("xuanhuan")
    assert "全服" in game
    assert "Boss" in game
    assert "全服" not in xuanhuan
    assert "Boss" not in xuanhuan
    assert "宗门" in xuanhuan


def test_chapter_guidance_requires_event_evidence_and_no_chapter_number():
    guidance = build_chapter_title_guidance("urban")
    assert "必须对应本章真实发生的事件" in guidance
    assert "不要重复写章节编号" in guidance


def test_three_identical_question_shapes_are_rejected():
    chapters = [
        {"chapter_number": 1, "title": "开局就要退婚？"},
        {"chapter_number": 2, "title": "第一次谈判就翻脸？"},
        {"chapter_number": 3, "title": "刚拿合同就反悔？"},
    ]
    try:
        validate_chapter_title_window(chapters, genre_id="urban")
    except ValueError as exc:
        assert str(exc) == "repeated_chapter_title_shape:question:1-3"
    else:
        raise AssertionError("expected repeated title shape rejection")
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `python -m pytest tests/story_core/test_title_strategy.py -q`

Expected: collection fails because `packages.story_core.title_strategy` does not exist.

- [ ] **Step 3: Implement the minimal strategy module**

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any


_GENRE_TERMS = {
    "game_webnovel": ("首杀", "副本", "Boss", "全服", "公会", "技能", "等级"),
    "xuanhuan": ("境界", "宗门", "功法", "秘境", "血脉", "因果"),
    "xianxia": ("境界", "宗门", "功法", "天劫", "飞升", "因果"),
    "urban": ("身份", "职业", "利益", "关系", "合同", "证据"),
    "suspense": ("证据", "证词", "嫌疑人", "时间线", "失踪", "真相"),
    "rules_mystery": ("规则", "禁忌", "代价", "污染", "倒计时", "异常"),
    "romance": ("关系", "误会", "选择", "承诺", "边界", "秘密"),
    "generic_webnovel": ("身份", "目标", "危机", "选择", "代价", "真相"),
}

_GAME_EXAMPLES = (
    "《网游：满级魔龙？给我回滚成野狗！》",
    "《让你玩游戏，你把世界底层代码黑了？》",
    "《地球旧服即将删档，我成了唯一管理员》",
)


def _terms(genre_id: str, extra_terms: Sequence[str] = ()) -> tuple[str, ...]:
    base = _GENRE_TERMS.get(genre_id, _GENRE_TERMS["generic_webnovel"])
    return tuple(dict.fromkeys((*base, *(str(item).strip() for item in extra_terms if str(item).strip()))))


def build_book_title_guidance(genre_id: str, *, extra_terms: Sequence[str] = ()) -> str:
    terms = "、".join(_terms(genre_id, extra_terms))
    examples = "\n".join(f"- {item}" for item in _GAME_EXAMPLES) if genre_id == "game_webnovel" else ""
    return (
        "书名从核心卖点或特殊能力、主角身份或反差、爽点或后果中选取两到三项，"
        "按自然中文重新组织，不要机械拼接标签。\n"
        f"当前题材可用词汇：{terms}。不要使用其他题材的专属词汇。"
        + (f"\n结构示例（只学结构，不得照抄）：\n{examples}" if examples else "")
    )


def build_chapter_title_guidance(genre_id: str, *, extra_terms: Sequence[str] = ()) -> str:
    terms = "、".join(_terms(genre_id, extra_terms))
    return (
        "章节标题必须对应本章真实发生的事件，从危机、反击、反差、悬念或不可逆转折中选一种。"
        "禁止使用‘新的开始’‘危机来临’等抽象概括，不得虚构正文不存在的卖点。"
        "默认不超过二十个汉字，不要重复写章节编号。相邻三章不要连续使用同一种问句或感叹句结构。"
        f"当前题材可用词汇：{terms}。"
    )


def _title_shape(title: str) -> str:
    text = re.sub(r"^第\s*[一二三四五六七八九十百千万\d]+\s*章[：:\s]*", "", title.strip())
    if text.endswith(("？", "?")):
        return "question"
    if text.endswith(("！", "!")):
        return "exclamation"
    return "statement"


def validate_chapter_title_window(chapters: Sequence[Mapping[str, Any]], *, genre_id: str) -> None:
    shapes = [(_title_shape(str(item.get("title") or item.get("chapter_title") or "")), int(item.get("chapter_number") or 0)) for item in chapters]
    for index in range(2, len(shapes)):
        window = shapes[index - 2:index + 1]
        if window[0][0] == window[1][0] == window[2][0] and window[0][0] in {"question", "exclamation"}:
            raise ValueError(f"repeated_chapter_title_shape:{window[0][0]}:{window[0][1]}-{window[2][1]}")
```

- [ ] **Step 4: Run unit tests**

Run: `python -m pytest tests/story_core/test_title_strategy.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the strategy module**

```powershell
git add packages/story_core/title_strategy.py tests/story_core/test_title_strategy.py
git commit -m "feat: add global title strategy"
```

### Task 2: Apply the book-title strategy to opening directions

**Files:**
- Modify: `packages/story_core/opening_directions.py`
- Modify: `tests/story_core/test_opening_directions.py`

- [ ] **Step 1: Add a failing prompt-capture test**

Add a gateway fixture that captures the `opening_directions` request, generate once with `game_webnovel` and once with `xuanhuan`, then assert:

```python
assert game_context["title_strategy"]["guidance"].find("全服") >= 0
assert "Boss" not in xuanhuan_context["title_strategy"]["guidance"]
assert "宗门" in xuanhuan_context["title_strategy"]["guidance"]
```

- [ ] **Step 2: Run the targeted test and verify failure**

Run: `python -m pytest tests/story_core/test_opening_directions.py -q`

Expected: failure because `title_strategy` is absent from the opening prompt context.

- [ ] **Step 3: Inject genre-aware guidance**

Import `build_book_title_guidance`, then add this field when constructing `prompt_context`:

```python
"title_strategy": {
    "purpose": "book_title_candidates",
    "guidance": build_book_title_guidance(validated_brief.novel_type_id),
},
```

Extend the system prompt with:

```python
"每个 direction.title 都是一个可直接使用的书名候选，必须执行 title_strategy；"
"三个候选不能只替换一个名词，且不得照抄示例。"
```

- [ ] **Step 4: Run opening-direction tests**

Run: `python -m pytest tests/story_core/test_opening_directions.py tests/story_core/test_file_project_creation.py -q`

Expected: all tests pass and blank inspiration projects still adopt the selected direction title.

- [ ] **Step 5: Commit opening integration**

```powershell
git add packages/story_core/opening_directions.py tests/story_core/test_opening_directions.py
git commit -m "feat: apply title strategy when opening books"
```

### Task 3: Generate and validate chapter titles at outline time

**Files:**
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `tests/story_core/test_outline_planning_generation.py`

- [ ] **Step 1: Write failing prompt and validator tests**

Capture the `chapter_window` request and assert:

```python
assert "chapter_title_strategy" in chapter_context
assert "必须对应本章真实发生的事件" in chapter_context["chapter_title_strategy"]
```

Add a generated three-chapter window with three question titles and assert generation raises an error containing `repeated_chapter_title_shape`.

- [ ] **Step 2: Run the targeted tests and verify failure**

Run: `python -m pytest tests/story_core/test_outline_planning_generation.py -q`

Expected: prompt assertion and repeated-shape rejection test fail.

- [ ] **Step 3: Add guidance to chapter context**

Resolve the existing `effective_novel_type_id`, import the strategy helpers, and add:

```python
"chapter_title_strategy": build_chapter_title_guidance(effective_novel_type_id),
```

Extend the chapter system prompt with:

```python
"Generate chapter.title from the concrete events in that chapter and follow prompt_context.chapter_title_strategy. "
```

- [ ] **Step 4: Validate the returned window before persistence**

Inside `validate_chapter_window_contracts`, after existing contract checks, call:

```python
validate_chapter_title_window(
    [chapter.model_dump(mode="python") for chapter in result.chapters],
    genre_id=effective_novel_type_id,
)
```

Use the existing single JSON-repair retry. Do not silently replace titles in Python because a fallback title could contradict the chapter events.

- [ ] **Step 5: Run outline tests**

Run: `python -m pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_outline_planning.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit chapter-outline integration**

```powershell
git add packages/story_core/outline_planning_generation.py tests/story_core/test_outline_planning_generation.py
git commit -m "feat: generate chapter titles from detailed outlines"
```

### Task 4: Stop the director from renaming planned chapters

**Files:**
- Modify: `packages/story_core/agents/director/prompt.py`
- Modify: `packages/story_core/agents/director/agent.py`
- Modify: `tests/story_core/test_modular_director_agent.py`

- [ ] **Step 1: Write a failing preservation test**

Build a `DirectorContext` whose target nearby outline has `title="管你是龙是虫，给我退回去！"`. Make the runtime respond with `chapter_title="临时改名"`, then assert:

```python
artifact = agent.plan(context)
assert artifact.chapter_title == "管你是龙是虫，给我退回去！"
```

- [ ] **Step 2: Run the test and verify failure**

Run: `python -m pytest tests/story_core/test_modular_director_agent.py -q`

Expected: returned title is `临时改名`.

- [ ] **Step 3: Add one target-title helper and lock the result**

In `agents/director/agent.py`, add:

```python
def _planned_chapter_title(context: DirectorContext) -> str:
    for entry in context.nearby_outline:
        if int(entry.get("number") or entry.get("chapter_number") or 0) == context.chapter_number:
            return str(entry.get("title") or entry.get("chapter_title") or "").strip()
    return ""
```

After parsing or constructing the artifact, replace only the title when a planned title exists:

```python
planned_title = _planned_chapter_title(context)
if planned_title:
    artifact = artifact.model_copy(update={"chapter_title": planned_title})
```

Change the director prompt section to say the target outline title is locked and must be copied unchanged. The director remains responsible for chapter goal, scene beats, ending state, hook, and entity requirements.

- [ ] **Step 4: Run director and pipeline tests**

Run: `python -m pytest tests/story_core/test_modular_director_agent.py tests/story_core/test_modular_pipeline_e2e.py -q`

Expected: all tests pass and both shortcut/runtime director paths preserve the same title.

- [ ] **Step 5: Commit director title locking**

```powershell
git add packages/story_core/agents/director/prompt.py packages/story_core/agents/director/agent.py tests/story_core/test_modular_director_agent.py
git commit -m "fix: preserve chapter titles selected by outline"
```

### Task 5: Prove title formulas never reach the writer

**Files:**
- Modify: `tests/story_core/test_modular_writer_agent.py`
- Modify: `tests/story_core/test_pipeline_boundaries.py`
- Modify: `tests/story_core/test_modular_pipeline_e2e.py`

- [ ] **Step 1: Add writer-boundary assertions**

Generate a project whose outline contains a final title and whose planning request used the global strategy. Build the writer prompt and assert:

```python
assert "核心卖点/能力" not in writer_prompt
assert "章节标题必须对应" not in writer_prompt
assert "满级魔龙" not in writer_prompt
assert "chapter_title_strategy" not in writer_prompt
assert project_title in writer_prompt
```

- [ ] **Step 2: Run boundary tests**

Run: `python -m pytest tests/story_core/test_modular_writer_agent.py tests/story_core/test_pipeline_boundaries.py tests/story_core/test_modular_pipeline_e2e.py -q`

Expected: all tests pass without production changes. If they fail, remove title-strategy data at the context builder boundary rather than filtering strings inside `build_writer_prompt`.

- [ ] **Step 3: Commit boundary tests**

```powershell
git add tests/story_core/test_modular_writer_agent.py tests/story_core/test_pipeline_boundaries.py tests/story_core/test_modular_pipeline_e2e.py
git commit -m "test: keep title strategy out of writer prompts"
```

### Task 6: Run cross-genre acceptance and regression tests

**Files:**
- Modify only if a regression test exposes a real defect in files already listed above.

- [ ] **Step 1: Run the focused Python suite**

Run:

```powershell
python -m pytest `
  tests/story_core/test_title_strategy.py `
  tests/story_core/test_opening_directions.py `
  tests/story_core/test_outline_planning_generation.py `
  tests/story_core/test_modular_director_agent.py `
  tests/story_core/test_modular_writer_agent.py `
  tests/story_core/test_pipeline_boundaries.py `
  tests/story_core/test_modular_pipeline_e2e.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run API and new-book regressions**

Run:

```powershell
python -m pytest tests/api/test_file_project_creation_routes.py tests/story_core/test_file_project_creation.py -q
```

Expected: all tests pass; project creation and outline endpoints preserve their existing response schemas.

- [ ] **Step 3: Run one real four-genre prompt smoke test**

Using a fake model gateway, generate opening and chapter-planning requests for `game_webnovel`, `xuanhuan`, `urban`, and `suspense`. Verify:

```text
game_webnovel -> may contain 全服/Boss
xuanhuan -> contains 宗门/功法 and no 全服/Boss
urban -> contains 合同/证据 and no 全服/Boss
suspense -> contains 证据/嫌疑人 and no 全服/Boss
writer prompt -> contains none of the strategy text in every case
```

Expected: all four cases pass without network access.

- [ ] **Step 4: Check formatting and unintended changes**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only files in this plan and pre-existing unrelated worktree changes are present.

- [ ] **Step 5: Commit any final test-only adjustments**

```powershell
git add packages/story_core/title_strategy.py packages/story_core/opening_directions.py packages/story_core/outline_planning_generation.py packages/story_core/agents/director/prompt.py packages/story_core/agents/director/agent.py tests/story_core/test_title_strategy.py tests/story_core/test_opening_directions.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_modular_director_agent.py tests/story_core/test_modular_writer_agent.py tests/story_core/test_pipeline_boundaries.py tests/story_core/test_modular_pipeline_e2e.py
git commit -m "test: verify global title strategy end to end"
```
