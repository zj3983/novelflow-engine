# 模块化正文提示词优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将正文生成提示词压缩为职责清楚的五块材料，避免风格规则、人物资料和 Skill 内容重复注入。

**Architecture:** 保留现有 `prompt_modules.py` 模块目录和项目状态存储；在 `orchestrator.py` 增加统一的正文提示词装配边界，由事实摘要、人物摘要、本章方向和单一写法模块组成。默认题材/风格方法可被对应 Skill 替换，改稿阶段额外读取审稿与原正文。

**Tech Stack:** Python 3、Pydantic、pytest、Next.js 提示词预览页

---

### Task 1: 固定五块提示词合同

**Files:**
- Modify: `tests/story_core/test_writer_prompt_method.py`
- Modify: `tests/story_core/test_prompt_modules.py`

- [ ] **Step 1: 写失败测试**

新增测试，要求正文提示词依次出现：`输出要求`、`本章方向`、`本章事实`、`出场人物`、`正文写法`；不出现原始计划键名、完整人物库或重复的通用风格段。

```python
def test_body_prompt_has_five_writer_facing_sections_without_duplicate_style_rules():
    story = StoryState(story_id="s-five", outline="外门守炉", genre="xianxia", style="白描")
    prompt = StoryOrchestrator()._body_prompt(story, 1, {"event_plan": {"chapter_title": "守炉"}})
    headings = ["## 输出要求", "## 本章方向", "## 本章事实", "## 出场人物", "## 正文写法"]
    assert all(heading in prompt for heading in headings)
    assert [prompt.index(heading) for heading in headings] == sorted(prompt.index(heading) for heading in headings)
    assert prompt.count("第三人称有限视角") == 1
    assert "event_plan" not in prompt
    assert "character_moves" not in prompt
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_prompt_modules.py -q`

Expected: 新增五块结构测试失败，现有测试保持可运行。

- [ ] **Step 3: 增加 Skill 替换测试**

验证启用风格 Skill 后默认 `style_context` 不再重复注入；题材 Skill 只替换题材方法，不删除本章事实。

```python
def test_replaceable_slots_keep_facts_and_replace_only_default_methods():
    assert replaceable_slots() == {"genre": "genre_context", "style": "style_context"}
    assert "core_context" not in replaceable_slots().values()
    assert "character_context" not in replaceable_slots().values()
```

- [ ] **Step 4: 提交测试合同**

```powershell
git add tests/story_core/test_writer_prompt_method.py tests/story_core/test_prompt_modules.py
git commit -m "test: define modular writer prompt contract"
```

### Task 2: 实现紧凑正文装配

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/writing_taskbook.py`
- Test: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: 增加单一正文写法模块**

在 `orchestrator.py` 中生成一份正向方法说明，只保留限知视角、实时事件、连续动作、自然对话、有效心理环境和现代中文语序。不要加入全面禁词或“每句台词必须配动作”的规则。

```python
def _writer_craft_section() -> list[str]:
    return [
        "## 正文写法",
        "使用第三人称有限视角，一场戏跟随一个观察人物。",
        "从正在发生的事情写起，让人物面对具体问题并作出选择。",
        "动作连续写清原因和结果，不把完整动作切成名词式短句。",
        "对话符合人物关系和当时目的，有正常的接话、解释和情绪变化。",
        "心理和环境只在影响选择、关系或现场状态时出现。",
        "长短句随内容自然变化，保持现代中文语序。",
        "规则和设定通过人物行动、反馈与后果显露。",
    ]
```

- [ ] **Step 2: 将任务书缩为本章方向**

调整紧凑任务书输出，使其只提供章节目标、场面变化、读者要看到的结果和结尾承接，不重复通用白描、对话和反 AI 规则。

- [ ] **Step 3: 组装五块提示词**

让 `_body_prompt()` 按固定顺序组装：

```python
sections = [
    _writer_output_section(chapter_number, plan),
    _writer_direction_section(plan),
    _writer_fact_section(chapter_seed, plot_contract),
    _writer_character_section(character_context, dialogue_context),
    _writer_craft_section(),
]
```

题材方法和 Skill 摘要放进对应章节，不再作为独立 JSON 尾段重复注入。首次写作不读取 `review_context` 和 `source_body`。

- [ ] **Step 4: 运行聚焦测试**

Run: `pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_writing_taskbook.py tests/story_core/test_prompt_modules.py -q`

Expected: 全部通过。

- [ ] **Step 5: 提交正文装配改动**

```powershell
git add packages/story_core/orchestrator.py packages/story_core/writing_taskbook.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_prompt_modules.py
git commit -m "refactor: simplify modular writer prompt"
```

### Task 3: 对齐改稿和提示词面板

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_writer_prompt_method.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: 写改稿阶段失败测试**

要求改稿提示词复用五块正文结构，并只额外增加 `修改目标` 和隐藏的 `原正文`；审稿字段不能混入正文写法模块。

- [ ] **Step 2: 实现改稿装配**

复用正文装配函数，在末尾加入压缩后的修改清单和原正文。保留事实优先级：项目事实高于 Skill，审稿只指出要改的地方。

- [ ] **Step 3: 更新面板模块说明**

让提示词预览页的数据明确标出五块用途；面板仍展示完整实际提示词，但不新增页面或卡片。

- [ ] **Step 4: 运行聚焦测试**

Run: `pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_file_project_store.py -q`

Expected: 全部通过。

- [ ] **Step 5: 提交改稿和预览改动**

```powershell
git add packages/story_core/orchestrator.py packages/story_core/file_project_store.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_file_project_store.py
git commit -m "refactor: align revision and prompt preview modules"
```

### Task 4: 验证修仙与网游项目

**Files:**
- Test: `tests/story_core/test_writer_prompt_method.py`
- Test: `tests/story_core/test_genre_plugins.py`
- Test: `tests/api/test_story_routes.py`

- [ ] **Step 1: 运行正文提示词相关测试**

Run: `pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_prompt_modules.py tests/story_core/test_writing_taskbook.py tests/story_core/test_genre_plugins.py tests/api/test_story_routes.py -q`

Expected: 全部通过。

- [ ] **Step 2: 检查修仙项目提示词**

请求 `p-xianxia-incense-test-2` 第一章提示词预览，确认包含守炉剧情事实和本章人物，不包含网游面板、背包、掉落规则，也不重复通用风格说明。

- [ ] **Step 3: 检查网游项目提示词**

请求现有网游项目第一章提示词预览，确认题材方法仍包含任务、经验、装备等表面规则，五块正文结构保持一致。

- [ ] **Step 4: 运行完整 Python 测试和前端构建**

Run: `pytest -q`

Run: `npm run build`（工作目录：`apps/web`）

Expected: Python 测试全部通过，Next.js 构建成功。

- [ ] **Step 5: 只提交本任务相关剩余文件**

```powershell
git status --short
git add packages/story_core/orchestrator.py packages/story_core/writing_taskbook.py packages/story_core/file_project_store.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_prompt_modules.py tests/story_core/test_file_project_store.py
git commit -m "test: verify modular writer prompts"
```
