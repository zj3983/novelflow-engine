# 第一章整章正文质感升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 强化网游第一章整章正文生成和写作包，让正文更白描、对话更自然、反馈更具体，并避免提前变现和谜语式表达。

**Architecture:** 复用现有整章 `_body_prompt`、写作任务书和写作包，不新增分段流程。新增共享的第一章整章契约数据，由 orchestrator prompt、writing_taskbook、writing_packet 同步消费。

**Tech Stack:** Python 3.11、pytest、FastAPI 项目内 `packages.story_core` 模块。

---

### Task 1: 写失败测试锁定整章第一章契约

**Files:**
- Modify: `tests/story_core/test_writer_prompt_method.py`
- Modify: `tests/story_core/test_writing_packet.py`

- [ ] **Step 1: Add prompt expectations**

在 `tests/story_core/test_writer_prompt_method.py` 增加测试：

```python
def test_web_game_first_chapter_whole_body_prompt_has_plain_four_beat_contract():
    story = StoryState(story_id="s-whole-ch1", outline="网游开服，千倍爆率。", genre="网游", style="番茄升级流")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "灰狼坡"}})

    assert "整章四拍" in prompt
    assert "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子" in prompt
    assert "本次不用分段生成" in prompt
    assert "白描" in prompt
    assert "自然对话" in prompt
    assert "不要用华丽词语、夸张比喻或谜语式暗示" in prompt
    assert "台词不能替作者讲规则" in prompt
    assert prompt.index("整章四拍") < prompt.index("硬性质量闸门")
```

- [ ] **Step 2: Add writing packet expectations**

在 `tests/story_core/test_writing_packet.py` 的 `test_first_chapter_packet_contains_manual_drafting_contract` 中增加：

```python
    assert packet["whole_chapter_contract"]["mode"] == "whole_body_only"
    assert "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子" in packet["whole_chapter_contract"]["beat_map"]
    assert any("白描" in item for item in packet["whole_chapter_contract"]["style"])
    assert any("自然对话" in item for item in packet["whole_chapter_contract"]["dialogue"])
    assert any("谜语式" in item for item in packet["whole_chapter_contract"]["avoid"])
```

- [ ] **Step 3: Run failing tests**

Run: `pytest tests/story_core/test_writer_prompt_method.py::test_web_game_first_chapter_whole_body_prompt_has_plain_four_beat_contract tests/story_core/test_writing_packet.py::test_first_chapter_packet_contains_manual_drafting_contract -q`

Expected: FAIL because `whole_chapter_contract` and the prompt text do not exist yet.

### Task 2: Implement shared first-chapter whole-body contract

**Files:**
- Modify: `packages/story_core/writing_taskbook.py`
- Modify: `packages/story_core/writing_packet.py`
- Modify: `packages/story_core/orchestrator.py`

- [ ] **Step 1: Add contract builder**

In `packages/story_core/writing_taskbook.py`, add:

```python
def first_chapter_whole_body_contract(*, game_genre: bool) -> dict[str, Any]:
    if not game_genre:
        return {}
    return {
        "mode": "whole_body_only",
        "beat_map": "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子",
        "beats": [
            "现实压力：用余额、房租、旧设备、身体反应或生活细节说明为什么现在必须登录。",
            "登录建号：写清游戏ID、职业选择、Lv.1短面板、初始武器或技能，以及开服现场质感。",
            "低级验证：用一场小规模战斗或测试写出血蓝、耐久、背包、掉落、任务进度和普通玩家更慢的对比。",
            "下一步钩子：材料先不卖，章末落到任务、装备、技能、地图或NPC服务门槛。",
        ],
        "style": [
            "整体接近白描：句子清楚，动作具体，少修辞，少比喻。",
            "不要用华丽词语、夸张比喻或谜语式暗示制造气氛。",
            "读者要一眼知道角色在做什么、怕什么、想试什么、下一步去哪里。",
        ],
        "dialogue": [
            "自然对话：人物说话要短、顺、接地气。",
            "台词不能替作者讲规则、讲设定或讲审稿结论。",
            "对话要推进价格、任务、信任、误会、信息或行动。",
        ],
        "avoid": [
            "不用分段生成；按整章连续正文自然写出四拍。",
            "不要提前完成变现、成交、到账、手续费扣款、公共频道扩散、论坛爆帖、公会追查或市场玩家盯盘。",
            "不要写边界、推演、审稿、场景卡、模型、算法、变量、规则被撬开、这意味着、这说明。",
            "不要写谜语式短句或故意绕弯的悬疑腔。",
        ],
    }
```

- [ ] **Step 2: Expose contract in writing packet**

In `packages/story_core/writing_packet.py`, import the helper and add:

```python
"whole_chapter_contract": first_chapter_whole_body_contract(game_genre=game_genre) if target_chapter == 1 else {},
```

- [ ] **Step 3: Inject contract into whole-body prompt**

In `packages/story_core/orchestrator.py`, import the helper and append a prompt line before `"硬性质量闸门"` inside `_chapter_prompt_method_block`:

```python
whole_body_contract = first_chapter_whole_body_contract(game_genre=_story_game_context_for_prompt(plan)) if chapter_number == 1 else {}
```

If direct story access is not available in the helper block, infer game context from `plan`, `taskbook`, and `director_card`, then append:

```python
if whole_body_contract:
    lines.extend([
        "第一章整章写法契约：本次不用分段生成，按整章连续正文自然完成。",
        f"整章四拍：{whole_body_contract['beat_map']}",
        f"四拍要求：{_plain_prompt_json(whole_body_contract['beats'])}",
        f"白描与自然对话：{_plain_prompt_json([*whole_body_contract['style'], *whole_body_contract['dialogue']])}",
        f"整章禁区：{_plain_prompt_json(whole_body_contract['avoid'])}",
    ])
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/story_core/test_writer_prompt_method.py::test_web_game_first_chapter_whole_body_prompt_has_plain_four_beat_contract tests/story_core/test_writing_packet.py::test_first_chapter_packet_contains_manual_drafting_contract -q`

Expected: PASS.

### Task 3: Verify no regressions in adjacent prompt/packet tests

**Files:**
- No further file changes expected.

- [ ] **Step 1: Run adjacent tests**

Run: `pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_writing_packet.py tests/story_core/test_writing_taskbook.py -q`

Expected: PASS.

- [ ] **Step 2: Review git diff**

Run: `git diff -- packages/story_core/orchestrator.py packages/story_core/writing_packet.py packages/story_core/writing_taskbook.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_writing_packet.py docs/superpowers/plans/2026-05-14-first-chapter-whole-body-prose.md`

Expected: Diff only contains first-chapter whole-body prompt/packet changes and tests.
