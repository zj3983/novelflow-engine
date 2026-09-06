# 网游提示词冲突清理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清除网游模板内部冲突和旧书硬编码，使每本书以自身事实与细纲为准。

**Architecture:** 不增加新 Agent。修改现有导演、写手和兼容写作包三个边界，并用提示词快照测试锁住模块职责。

**Tech Stack:** Python 3.11、Pydantic、pytest。

---

### Task 1: 固定导演优先级

**Files:**
- Modify: `packages/story_core/agents/director/prompt.py`
- Test: `tests/story_core/test_modular_director_agent.py`

- [ ] 增加失败测试，要求导演提示词声明事实和细纲优先于题材模板。
- [ ] 修改规则说明，禁止模板覆盖细纲，只允许在未确定处补充机制边界。
- [ ] 运行导演测试。

### Task 2: 精简写手通用规则与角色投影

**Files:**
- Modify: `packages/story_core/agents/writer/prompt.py`
- Test: `tests/story_core/test_modular_writer_agent.py`

- [ ] 增加失败测试，覆盖主动首次验证能力和后台角色字段泄漏。
- [ ] 将首次能力规则改为服从角色认知与细纲动作。
- [ ] 只投影当前可写状态，不序列化整块角色档案。
- [ ] 运行写手测试。

### Task 3: 清除旧写作包的旧书硬编码

**Files:**
- Modify: `packages/story_core/writing_packet.py`
- Test: `tests/story_core/test_writing_packet.py`

- [ ] 增加失败测试，使用全新网游设定并断言不出现旧人物、职业、怪物和材料。
- [ ] 将默认首章场景、硬锁和标题示例改为中性网游结构。
- [ ] 保留从项目状态抽取的具体游戏 ID、职业、背包和货币。
- [ ] 运行写作包测试。

### Task 4: 集成验证

**Files:**
- Test: `tests/story_core/test_modular_pipeline_e2e.py`
- Test: `tests/story_core/test_genre_prompt_isolation.py`

- [ ] 运行模块化流程和题材隔离测试。
- [ ] 读取当前测试项目最新导演与写手上下文，确认旧规则不再出现。
- [ ] 重启后端并验证提示词审计接口。
