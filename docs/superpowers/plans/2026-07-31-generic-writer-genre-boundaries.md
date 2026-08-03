# Generic Writer And Genre Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the common writer prompt genuinely genre-neutral while loading web-game writing methods only for web-game projects.

**Architecture:** Keep the existing five-section writer prompt and current model-call count. The common writer craft function will contain only cross-genre scene-writing principles; `web_game_author_craft.py` will own web-game vocabulary and mechanics, and the orchestrator will inject that compact genre card only when `_story_game_context()` is true. Tests will enforce both positive inclusion for games and negative isolation for other genres.

**Tech Stack:** Python 3, pytest, existing `StoryOrchestrator`, runtime novel-type profiles, prompt template system.

---

## File Map

- Modify `packages/story_core/orchestrator.py`: reduce the universal writer system/craft prompts and delegate web-game craft rendering to the genre module.
- Modify `packages/story_core/web_game_author_craft.py`: expose one compact writer-facing web-game method renderer and keep all game-specific prose guidance there.
- Modify `packages/story_core/chapter_governance.py`: remove duplicated prose guidance from governance while retaining genre-specific fact and continuity checks.
- Modify `tests/story_core/test_writer_prompt_method.py`: add unit and whole-prompt boundary tests.
- Modify `tests/story_core/test_novel_type_runtime_integration.py`: verify runtime novel types do not inherit web-game craft.

### Task 1: Lock The Universal Writer Boundary With Tests

**Files:**
- Modify: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: Import the universal craft helper for direct tests**

Add `_writer_craft_section` to the existing import from `packages.story_core.orchestrator`.

```python
from packages.story_core.orchestrator import (
    StoryOrchestrator,
    _writer_craft_section,
    _web_game_writing_method_lines,
)
```

- [ ] **Step 2: Write a failing test for the nine universal craft principles**

```python
def test_universal_writer_craft_is_short_and_genre_neutral():
    lines = _writer_craft_section(
        {},
        {},
        include_genre_method=False,
        is_game=False,
        chapter_number=1,
        plan={},
        style_guidance={},
    )
    text = "\n".join(lines)

    for expected in (
        "经历、眼前利益和性格",
        "配角有自己的目的",
        "关键冲突、转折和结果写成现场",
        "对话符合人物关系、处境和目的",
        "情绪放进动作、停顿、语气、回避和选择",
        "环境跟着人物行动出现",
        "完整的现代中文句子",
        "具体动作、物件和后果",
        "场景结束时发生看得见的变化",
    ):
        assert expected in text

    for forbidden in (
        "玩家",
        "NPC",
        "怪物",
        "面板",
        "等级",
        "技能",
        "装备",
        "任务",
        "掉落",
        "背包",
        "拍卖行",
        "铜币",
        "每300字",
        "每500字",
        "80%",
    ):
        assert forbidden not in text
    assert len(lines) <= 11
```

- [ ] **Step 3: Write a failing system-prompt isolation test**

```python
def test_writer_system_prompt_is_genre_neutral():
    prompt = StoryOrchestrator._model_system_prompt(False, agent="writer")

    assert "只输出正在发生的小说正文" in prompt
    assert "不解释创作规则" in prompt
    assert "面板" not in prompt
    assert "任务" not in prompt
    assert "NPC" not in prompt
```

- [ ] **Step 4: Write a failing whole-prompt isolation test for three genres**

```python
@pytest.mark.parametrize("genre", ["都市", "东方玄幻", "仙侠"])
def test_non_game_writer_prompts_do_not_receive_web_game_craft(genre):
    story = StoryState(
        story_id=f"s-neutral-{genre}",
        outline="主角必须在今天解决眼前冲突。",
        genre=genre,
        style="",
    )

    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {"event_plan": {"chapter_title": "第一次选择"}},
    )

    for forbidden in (
        "网游写法方法卡",
        "怪物面板",
        "背包",
        "拍卖行",
        "一口价",
        "掉落",
        "玩家和NPC",
    ):
        assert forbidden not in prompt
```

- [ ] **Step 5: Run the new tests and verify they fail for the current leaks**

Run:

```powershell
pytest tests/story_core/test_writer_prompt_method.py -k "universal_writer_craft_is_short or writer_system_prompt_is_genre_neutral or non_game_writer_prompts_do_not_receive_web_game_craft" -q
```

Expected: failures show that the universal craft/system prompt still contains game-specific wording and lacks the new compact principles.

- [ ] **Step 6: Commit the failing boundary tests**

```powershell
git add tests/story_core/test_writer_prompt_method.py
git commit -m "test: define generic writer prompt boundaries"
```

### Task 2: Simplify The Universal Writer Prompt

**Files:**
- Modify: `packages/story_core/orchestrator.py:5591-5635`
- Modify: `packages/story_core/orchestrator.py:5941-5950`
- Test: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: Replace the universal craft body with nine cross-genre principles**

Keep the existing function signature because prompt assembly and tests already call it. Replace only its universal `lines` list with:

```python
lines = [
    "## 正文写法",
    "人物按自己的经历、眼前利益和性格行动，选择要有当场可见的原因。",
    "配角有自己的目的、判断和反应，不只负责递信息或配合主角。",
    "关键冲突、转折和结果写成正在发生的现场，不用概述代替过程。",
    "对话符合人物关系、处境和目的，并推动信息、态度、关系或下一步行动发生变化。",
    "情绪放进动作、停顿、语气、回避和选择里，不由旁白替人物下结论。",
    "环境跟着人物行动出现，只保留会影响判断、关系或结果的细节。",
    "使用完整的现代中文句子，把必要的原因、条件和结果说清楚，不把判断压成逗号清单。",
    "优先写具体动作、物件和后果，少写抽象评价和创作说明。",
    "每个场景结束时发生看得见的变化：人物得到、失去、决定、误解或发现了什么。",
]
```

Do not add sensory quotas, paragraph-length quotas, payoff frequency, fixed ending ratios, imitation samples, or genre nouns.

- [ ] **Step 2: Remove the inline `is_game` craft block from `_writer_craft_section`**

Delete the two inline rules about panels, announcements, trading, appraisal, buttons, prices, and money arrival. Leave genre injection as a single call:

```python
if is_game:
    lines.extend(_web_game_writing_method_lines(chapter_number, plan or {}))
elif include_genre_method:
    methods = genre_context.get("genre_method") if isinstance(genre_context, dict) else []
    for method in methods[:3] if isinstance(methods, list) else []:
        text = compact_text(str(method), 120)
        if text:
            lines.append(text)
```

- [ ] **Step 3: Make the writer system prompt genre-neutral**

Replace the writer branch in `_model_system_prompt` with:

```python
if agent == "writer":
    return (
        "你是中文网文写手。只输出正在发生的小说正文，不解释创作规则、剧情作用或任务要求；"
        "已经通过人物行动表现的信息不要再总结一遍。"
    )
```

- [ ] **Step 4: Run the universal and existing prompt-structure tests**

Run:

```powershell
pytest tests/story_core/test_writer_prompt_method.py -k "universal_writer_craft_is_short or writer_system_prompt_is_genre_neutral or body_prompt_has_five_writer_facing_sections or body_prompt_prefers_positive_craft_guidance or body_prompt_does_not_teach" -q
```

Expected: all selected tests pass; the body prompt still has five writer-facing sections and no checklist/sample teaching.

- [ ] **Step 5: Commit the universal prompt cleanup**

```powershell
git add packages/story_core/orchestrator.py tests/story_core/test_writer_prompt_method.py
git commit -m "refactor: make writer craft genre neutral"
```

### Task 3: Centralize Web-Game Writing Methods

**Files:**
- Modify: `packages/story_core/web_game_author_craft.py`
- Modify: `packages/story_core/orchestrator.py:5684-5708`
- Modify: `packages/story_core/chapter_governance.py:317-337`
- Test: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: Write a failing test for one compact web-game genre card**

```python
def test_web_game_writer_prompt_has_one_compact_genre_method_card():
    story = StoryState(
        story_id="s-game-craft-once",
        outline="玩家进入游戏完成第一个战斗任务。",
        genre="网游",
        style="",
    )
    prompt = StoryOrchestrator()._body_prompt(
        story,
        2,
        {"event_plan": {"chapter_title": "第一次战斗", "chapter_goal": "击败同级怪物并提交任务"}},
    )

    assert prompt.count("## 网游写法") == 1
    assert "怪物面板" in prompt
    assert "任务" in prompt
    assert "背包" in prompt
    assert "隐藏优势" in prompt
```

- [ ] **Step 2: Add a writer-facing renderer to the web-game craft module**

In `web_game_author_craft.py`, add:

```python
def web_game_writer_method_lines(
    chapter_number: int,
    *,
    plan: dict[str, Any] | None = None,
    language_cards: list[Any] | None = None,
) -> list[str]:
    plan = plan if isinstance(plan, dict) else {}
    phase_hint = (
        "第一章先让主角试清一条基础规则，并把第一次优势藏住；是否领奖、修理或补给服从项目账本。"
        if chapter_number == 1
        else "围绕当前等级能完成的目标推进，不无理由跨越阶段。"
    )
    lines = [
        "## 网游写法",
        phase_hint,
        "规则通过战斗、任务、背包、价格、NPC回应和结算自然出现，不由旁白解释系统流程。",
        "面板只显示马上影响选择的事实；同类普通怪的面板不重复，精英和首领再补技能与特性。",
        "任务、等级、属性、技能、装备、消耗、掉落和货币变化都要与账本一致。",
        "玩家、NPC、怪物和组织只按各自能看到的证据反应，隐藏优势不会因一次普通收益直接暴露。",
        "交易按游戏内操作和结果写，现实兑换只在项目设定允许时出现。",
    ]
    for card in language_cards or []:
        lines.append(
            f"语言卡[{card.card_id}]：常用{'、'.join(card.preferred)}；"
            f"避开{'、'.join(card.avoid)}；例：{card.example}"
        )
    return lines
```

This renderer is genre-owned. It may use game nouns, but it must not contain book-specific names, exact balances, grey-wolf facts, or fixed chapter outcomes.

- [ ] **Step 3: Turn the orchestrator helper into a thin adapter**

Import `web_game_writer_method_lines` from `web_game_author_craft.py`, then replace `_web_game_writing_method_lines` with:

```python
def _web_game_writing_method_lines(
    chapter_number: int,
    plan: dict[str, Any] | None = None,
) -> list[str]:
    plan = plan if isinstance(plan, dict) else {}
    cards = select_game_language_cards(plan, max_cards=3)
    return web_game_writer_method_lines(
        chapter_number,
        plan=plan,
        language_cards=cards,
    )
```

Keep this adapter so current imports and focused language-card tests remain stable.

- [ ] **Step 4: Remove duplicated prose instruction from chapter governance**

Retain hard facts and continuity checks in `chapter_governance.py`. Replace the three near-identical `soft_guidance` branches with cross-genre governance only:

```python
soft_guidance = [
    "人物只能依据自己已经看到、听到、问到或试出的信息行动。",
    "资源、伤势、线索和人物关系变化必须与本章前后的账本一致。",
]
if game_context:
    soft_guidance[1] = "等级、经验、货币、背包、装备、任务和关系变化必须与本章前后的账本一致。"
elif xuanhuan_context or xianxia_context:
    soft_guidance[1] = "术法、法宝、境界、伤势、资源和因果变化必须与本章前后的账本一致。"
```

Do not repeat dialogue style, modern Chinese, exposition, scene-writing, or panel presentation here; those belong to writer craft and genre craft.

- [ ] **Step 5: Run web-game method, governance, and isolation tests**

Run:

```powershell
pytest tests/story_core/test_writer_prompt_method.py -k "web_game_method or web_game_writer_prompt_has_one_compact_genre_method_card or non_game_writer_prompts_do_not_receive_web_game_craft or panel" -q
pytest tests/story_core/test_chapter_governance.py -q
```

Expected: all selected tests pass; trade and combat language cards still load selectively; non-game prompts contain no game method card.

- [ ] **Step 6: Commit the genre-owned craft module**

```powershell
git add packages/story_core/web_game_author_craft.py packages/story_core/orchestrator.py packages/story_core/chapter_governance.py tests/story_core/test_writer_prompt_method.py
git commit -m "refactor: move web game prose methods into genre craft"
```

### Task 4: Verify Runtime Genre Isolation And Prompt Output

**Files:**
- Modify: `tests/story_core/test_novel_type_runtime_integration.py`
- Test: `tests/story_core/test_writer_prompt_method.py`
- Test: `tests/story_core/test_novel_type_runtime_integration.py`

- [ ] **Step 1: Add a runtime custom-type isolation test**

Extend the existing orchestrator import in `test_novel_type_runtime_integration.py`:

```python
from packages.story_core.orchestrator import StoryOrchestrator, _writer_seed_summary
```

Then use the `sports` custom type already created by `runtime_type_library` and assert its writer prompt contains its runtime description but no game craft:

```python
def test_runtime_non_game_type_does_not_inherit_web_game_writer_method(runtime_type_library):
    story = StoryState(
        story_id="s-runtime-sports",
        outline="替补队员争取下一场首发。",
        genre=CUSTOM_NAME,
        genre_plugin_ids=[CUSTOM_ID],
    )

    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {"event_plan": {"chapter_title": "首发名单"}},
    )

    assert CUSTOM_DESCRIPTION in prompt
    assert "网游写法" not in prompt
    assert "怪物面板" not in prompt
    assert "玩家和NPC" not in prompt
```

- [ ] **Step 2: Run the focused writer and runtime integration suites**

Run:

```powershell
pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_novel_type_runtime_integration.py -q
```

Expected: both files pass with no game terminology in non-game prompts.

- [ ] **Step 3: Inspect one game and one non-game rendered prompt**

Run:

```powershell
@'
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator

cases = [
    StoryState(story_id="preview-game", outline="完成同级任务。", genre="网游"),
    StoryState(story_id="preview-xuanhuan", outline="少年处理宗门冲突。", genre="东方玄幻"),
]
for story in cases:
    prompt = StoryOrchestrator()._body_prompt(story, 2, {"event_plan": {"chapter_title": "推进"}})
    print(f"=== {story.genre} ===")
    print(prompt)
'@ | python -
```

Expected: both prompts share the same compact universal craft; only the game prompt has `## 网游写法` and game vocabulary; the non-game prompt receives its own runtime genre content.

- [ ] **Step 4: Run prompt-template regression tests**

Run:

```powershell
pytest tests/story_core/test_prompt_templates.py tests/story_core/test_prompt_management.py tests/story_core/test_writer_prompt_method.py -q
```

Expected: all pass, confirming global templates, project overrides, prompt preview, and actual model-call assembly still use the five-section structure.

- [ ] **Step 5: Review the diff for accidental book-specific or game-specific leakage**

Run:

```powershell
git diff -- packages/story_core/orchestrator.py packages/story_core/web_game_author_craft.py packages/story_core/chapter_governance.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_novel_type_runtime_integration.py
rg -n "玩家|NPC|怪物|面板|等级|技能|装备|任务|掉落|背包|拍卖行|铜币" packages/story_core/orchestrator.py
```

Expected: remaining matches in `orchestrator.py` are conditional game fact/output adapters, not universal system or craft text. No project-specific character, amount, monster, or chapter outcome is added to the genre module.

- [ ] **Step 6: Commit the runtime isolation verification**

```powershell
git add tests/story_core/test_novel_type_runtime_integration.py
git commit -m "test: prevent genre craft leakage across novel types"
```
