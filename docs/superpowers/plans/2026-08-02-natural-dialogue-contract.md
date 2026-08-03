# Natural Dialogue Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让通用写手获得简短、可复用的对话场景约束，减少提纲式短句和说明式台词，同时不增加模型调用或对话 Agent。

**Architecture:** `dialogue_context.py` 只整理本场谈话需要的关系、诉求、情绪、未说出口的信息和预期变化；`common_writer.py` 把它作为场景材料交给写手，并只保留三条通用对话原则。`writing_taskbook.py` 不再注入固定问答结构和改写范例，`prose_style_review.py` 只报告问题类型与修改方向。

**Tech Stack:** Python 3.11、pytest、现有 Story Core 写作流水线

---

### Task 1: 将对话上下文改成场景契约

**Files:**
- Modify: `packages/story_core/dialogue_context.py`
- Modify: `tests/story_core/test_dialogue_context.py`

- [ ] **Step 1: 写出场景契约测试**

用正常 UTF-8 中文重写测试，要求输出包含 `conversation_reason`、`participants`、`relationships`、`tone_boundary`、`unsaid_pressure` 和 `expected_change`。参与者只保留姓名、当场诉求与情绪，不把动作压缩进台词指令。

```python
def test_dialogue_context_builds_scene_contract_without_scripted_lines():
    context = build_dialogue_context(
        {"cards": [{"identity": {"name": "林修"}}, {"identity": {"name": "沈墨璃"}}]},
        {
            "event_plan": {"chapter_satisfaction": {"emotion_target": "两人决定是否继续引出寒毒"}},
            "character_moves": {
                "林修": [{"goal": "劝沈墨璃停手", "emotion": "担心", "action": "按住她的手腕"}],
                "沈墨璃": [{"goal": "确认寒毒位置", "emotion": "着急", "action": "继续运转灵力"}],
            },
        },
    )
    assert context["conversation_reason"] == "两人决定是否继续引出寒毒"
    assert context["participants"] == [
        {"name": "林修", "want": "劝沈墨璃停手", "emotion": "担心"},
        {"name": "沈墨璃", "want": "确认寒毒位置", "emotion": "着急"},
    ]
    assert "speaker_intents" not in context
    assert "action" not in str(context["participants"])
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_dialogue_context.py -q`

Expected: FAIL，旧结构仍返回 `speaker_intents`，且没有新的场景契约字段。

- [ ] **Step 3: 实现场景契约**

保留现有角色动作归属去重逻辑，但改为生成 `participants`。用章节情绪目标作为谈话缘由与预期变化；关系卡生成语气边界；从计划已有的 `hidden_fact`、`unsaid_pressure` 或 `memory_constraints.unresolved_threads` 中提取未说出口的信息，没有来源时留空，不自行编造。

```python
return {
    "conversation_reason": emotional_target,
    "participants": participants,
    "relationships": relationships[:6],
    "tone_boundary": "按人物关系和当前场合决定语气；没有亲近依据时，不突然开玩笑或接梗。",
    "unsaid_pressure": unsaid_pressure,
    "expected_change": emotional_target,
}
```

- [ ] **Step 4: 运行测试并确认通过**

Run: `python -m pytest tests/story_core/test_dialogue_context.py -q`

Expected: PASS。

### Task 2: 缩短通用写手的对话规则

**Files:**
- Modify: `packages/story_core/genre_stages/common_writer.py`
- Modify: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: 添加提示词边界测试**

在写手提示词测试中断言只出现三条原则，并且不再出现旧的逐段任务、固定情绪清单和“本场对话目的”压缩格式。

```python
assert "先回应对方刚说的内容" in prompt
assert "关系和场合决定说话方式" in prompt
assert "允许解释、犹豫、回避和日常过渡" in prompt
assert "整场对话发生变化即可" in prompt
assert "每段对话都让人知道一个条件" not in prompt
assert "本场对话目的：" not in prompt
assert "不用两个字装冷静" not in prompt
```

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `python -m pytest tests/story_core/test_writer_prompt_method.py -q`

Expected: FAIL，提示词仍包含旧的对话规则与压缩格式。

- [ ] **Step 3: 修改通用写法方法卡**

把 `_generic_writing_method_lines()` 中两条旧规则替换成三条通用原则，不限定题材、不要求每句承担信息任务。

```python
"对话先回应对方刚说的内容，再说自己真正关心的事，不要让人物各说各的。",
"人物关系和场合决定说话方式；允许解释、犹豫、回避和日常过渡，不必句句推进剧情。",
"整场对话发生信息、态度、关系或行动变化即可，不要把每句台词写成结论或口令。",
```

- [ ] **Step 4: 修改出场人物区块**

`_writer_character_section()` 改读新的场景契约，分别展示谈话缘由、关系尺度、参与者诉求与未说出口的信息，不拼接 `goal + emotion + action`。

```python
lines.append(f"谈话缘由：{conversation_reason}")
lines.append(f"关系尺度：{tone_boundary}")
lines.append(f"{name}此刻想要：{want}")
lines.append(f"{name}当前情绪：{emotion}")
lines.append(f"没有说出口：{unsaid_pressure}")
lines.append(f"谈完后的变化：{expected_change}")
```

- [ ] **Step 5: 运行写手提示词测试**

Run: `python -m pytest tests/story_core/test_writer_prompt_method.py -q`

Expected: PASS。

### Task 3: 删除任务书中的固定对话模板

**Files:**
- Modify: `packages/story_core/writing_taskbook.py`
- Modify: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: 添加任务书隔离测试**

断言最终写手提示词不再包含固定三轮问答、固定改写范例和“每章至少一轮连续问答”。

```python
assert "一人问/催/提醒" not in prompt
assert "每章至少有一轮连续问答" not in prompt
assert "先试，不深入" not in prompt
assert "柜台不认" not in prompt
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_writer_prompt_method.py -q`

Expected: FAIL，任务书仍注入固定结构或例句。

- [ ] **Step 3: 精简通用任务书**

删除 `GENERIC_CRAFT_TEMPLATES` 中固定对话轮次和改写范例；将通用 `dialogue` 规则压缩为不重复写手主提示词的检查项。

```python
"人物先听懂上一句再作答；只有关系和情境允许时，才使用玩笑、调侃或省略说法。",
"台词不能替作者讲规则、设定、流程或审稿结论。",
```

网游专属术语只保留在 `GAME_CRAFT_TEMPLATES`，但同样删除固定台词范例和强制三轮问答。

- [ ] **Step 4: 运行提示词与题材隔离测试**

Run: `python -m pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_genre_prompt_isolation.py -q`

Expected: PASS。

### Task 4: 将审稿改成问题类型和修改方向

**Files:**
- Modify: `packages/story_core/prose_style_review.py`
- Modify: `tests/story_core/test_modern_chinese_dialogue.py`

- [ ] **Step 1: 添加审稿输出测试**

保留电报句与连续省略对象的检测，同时断言修改计划不再携带固定改写句。

```python
report = review_prose_style("“窗坏、瓦落、门锁坏，先报我，不许自己乱拆。”")
plan_text = "\n".join(report["revision_plan"])
assert "清单式短句" in plan_text
assert "要是窗子、屋瓦或者门锁" not in plan_text
assert "我就在坡口打两只看看" not in plan_text
```

并保留紧急对白允许短句的测试：`“快走！”“我留下断后。”` 不应被判为电报式对话。

- [ ] **Step 2: 运行测试并确认失败**

Run: `python -m pytest tests/story_core/test_modern_chinese_dialogue.py -q`

Expected: FAIL，当前修改计划仍包含固定范例。

- [ ] **Step 3: 精简审稿修改方向**

删除 `revision_plan` 中的固定改写示例，只保留三类方向：补足被省略的对象与关系、让回答承接上一句、把系统流程改成角色可见的动作和后果。保留现有正则检测，不新增模型调用。

```python
plan=(
    "补足连续状态对白里被省略的对象，并让后一句回应前一句的判断或决定。"
    if any("连续省略对象" in item for item in modern_dialogue)
    else "把清单式短句改成符合人物关系和场合的完整口语；补足必要对象、原因或选择，但保留紧急场景中自然的短句。"
)
```

- [ ] **Step 4: 运行审稿测试**

Run: `python -m pytest tests/story_core/test_modern_chinese_dialogue.py -q`

Expected: PASS。

### Task 5: 验证完整写作链路

**Files:**
- Verify only: `packages/story_core/orchestrator.py`
- Verify only: `packages/story_core/pipeline/context_stage.py`
- Verify only: `packages/story_core/genre_stages/game_webnovel/writer.py`

- [ ] **Step 1: 运行对话与提示词相关测试**

Run: `python -m pytest tests/story_core/test_dialogue_context.py tests/story_core/test_modern_chinese_dialogue.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_genre_prompt_isolation.py tests/story_core/test_genre_stage_profiles.py -q`

Expected: PASS。

- [ ] **Step 2: 运行 Story Core 回归测试**

Run: `python -m pytest tests/story_core -q`

Expected: PASS；若存在与本改动无关的既有失败，记录测试名和错误，不修改无关模块。

- [ ] **Step 3: 检查提示词残留**

Run: `rg -n "每段对话都让人知道|每章至少有一轮连续问答|本场对话目的：|先试，不深入|柜台不认" packages/story_core tests/story_core`

Expected: 生产代码无残留；测试中只允许出现在否定断言里。

- [ ] **Step 4: 检查改动范围**

Run: `git diff --check && git diff -- packages/story_core/dialogue_context.py packages/story_core/genre_stages/common_writer.py packages/story_core/writing_taskbook.py packages/story_core/prose_style_review.py tests/story_core/test_dialogue_context.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_modern_chinese_dialogue.py`

Expected: 无空白错误；改动只涉及自然对话契约与对应测试。
