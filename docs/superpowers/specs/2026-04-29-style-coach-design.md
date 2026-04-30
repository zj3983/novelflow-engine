# Style Coach Design

## 背景

当前系统已经能完成网游小说的基础闭环：导入/创建项目、生成世界设定、推演世界事件、生成章节、审稿、改稿、回写章节记忆与角色状态。最近测试说明，系统在“发生什么”上逐步稳定，但在“怎么写得像网文作者”上仍不稳定。

核心问题不是规则不足，而是模型缺少可执行的写法范式。继续堆“不要 AI 味”“不要解释规则”这类禁令，只能减少局部错误，不能稳定教会模型如何把推演事件表演成小说。

本设计新增一个轻量的写作教练层，让生成流程从“规则约束”升级为“写法范式 + 分场景表演 + 事实锁定 + 审稿改稿”。

## 目标

1. 让模型在写作前先获得题材写法范式，而不是只拿到禁写规则。
2. 把 `world_events` 和 `scene_cards` 翻译成能直接写正文的表演卡。
3. 降低解释腔、机械短段、说明书式网游规则。
4. 防止润色或改稿时改乱账本、职业、装备、任务、NPC 信息边界。
5. 保持第一版实现轻量，不引入复杂样本库或训练流程。

## 非目标

1. 不做真正模型训练或微调。
2. 不做大型小说语料库抓取。
3. 不一次性支持所有题材的深度范式，第一阶段只强化网游升级流。
4. 不替代世界推演系统，Style Coach 只决定“怎么写”，不决定“世界实际发生什么”。

## 推荐方案

采用“轻量写作教练插件”方案。

新增 `packages/story_core/style_coach.py`，提供结构化的写作范式和场景表演建议。它不调用模型，先以可测试的规则和模板实现。后续如果需要，可以扩展为可配置 playbook 或样章学习模块。

### 生成链路

```mermaid
flowchart LR
  A["world_events 世界推演"] --> B["chapter_seed 剧情种子"]
  B --> C["style_coach 写作教练"]
  C --> D["performance_cards 表演卡"]
  D --> E["writer 分段写作"]
  E --> F["fact_guard 事实账本校验"]
  F --> G["style_critic 文风审稿"]
  G --> H["style_rewriter 自动改稿"]
  H --> I["最终章节"]
  I --> J["角色面板 / 世界记忆 / 章节摘要回写"]
```

## 模块设计

### 1. Style Coach

文件：`packages/story_core/style_coach.py`

职责：

- 根据题材、章节号、章节阶段、世界事件，生成写作策略。
- 给 Writer 明确“如何表演”，而不是只给“不能写什么”。
- 输出结构化 `StyleGuidance`，供初稿和改稿共用。

示例输出：

```json
{
  "genre": "web_game_leveling",
  "voice": "直白、紧凑、生活化，有爽点但不喊爽点",
  "chapter_pattern": "现实压力 -> 游戏入口 -> 异常伏笔 -> 小额验证 -> 弱线索钩子",
  "show_rules": [
    "交易规则通过界面、手续费、到账和旁人脚本记录表现",
    "金手指先异常再验证，不直接解释成百科",
    "公会压力只给资源点目击或批次记录，不正面对抗"
  ],
  "avoid_rules": [
    "不要用意味着、风险也是、很清楚、很直接解释逻辑",
    "不要连续使用孤立短段切卡片",
    "不要让润色新增消费、装备或任务结果"
  ]
}
```

第一阶段只内置一个 playbook：`web_game_leveling_opening`。

### 2. Performance Cards

现有 `scene_cards` 偏“事件检查表”，需要升级成“表演卡”。表演卡不改变推演事实，只补充写作方式。

建议数据结构：

```json
{
  "scene_id": "c1-market-listing",
  "source_event": "market_weak_trace",
  "purpose": "让主角第一次变现，同时留下弱线索",
  "must_show": ["数量", "单价", "手续费", "到账", "批次弱线索"],
  "write_as": ["界面操作", "手指停顿", "成交提示音", "旁人脚本记录"],
  "avoid": ["解释市场规则", "直接说风险", "暴露坐标", "新增消费"],
  "fact_locks": ["毒腺38枚寄售", "单价4铜", "手续费5%", "余额1银44铜"]
}
```

实现方式：

- 保留现有 `scene_cards` 字段。
- 新增 `performance_cards` 字段，或在 `scene_cards` 内新增 `write_as`、`avoid`、`fact_locks`。
- 第一阶段推荐直接扩展 `scene_cards`，减少模型和 API 改动面。

### 3. Fact Guard

文件：`packages/story_core/fact_guard.py`

职责：

- 在改稿前后比较硬事实。
- 防止 Writer 或 Rewriter 擅自新增消费、改余额、改职业、改装备、改任务进度。

第一阶段支持这些事实锁：

- 主角游戏 ID
- 游戏职业
- 等级与经验
- 货币余额
- 背包/任务材料
- 装备与耐久
- NPC 信息边界
- 交易行可见信息

示例结果：

```json
{
  "pass": false,
  "issues": [
    "改稿新增未授权消费：劣质蓝水、回城符、一百零二铜",
    "最终余额从 1银44铜 变成 42铜"
  ],
  "action": "reject_revision"
}
```

处理策略：

- 初稿生成后：只报告，不自动拒绝。
- 自动改稿后：若事实锁失败，拒绝改稿结果，保留上一版正文。
- 页面手动改稿：返回明确错误，让用户决定是否接受。

### 4. Style Critic

现有 `prose_style_review.py` 已经开始检测套话、元语言、对白问题和机械切段。下一步把它升级成更明确的文风审稿器。

建议指标：

```json
{
  "scene_density": 8,
  "exposition_ratio": 6,
  "mechanical_texture": 5,
  "dialogue_texture": 8,
  "genre_flavor": 7,
  "fact_consistency": 8
}
```

第一阶段只做轻量规则：

- `mechanical_texture`：机械短段、报告式判断。
- `exposition_ratio`：解释词密度，例如“意味着、因此、规则、模型、数据、风险、不能、需要”。
- `scene_density`：正文是否有足够动作、界面反馈、对白、环境细节。
- `genre_flavor`：网游文必要表面是否存在，例如面板、任务、掉落、交易、玩家生态、NPC 服务。

### 5. Style Rewriter

改稿器不再只拿 issues，而是同时拿：

- `StyleGuidance`
- `performance_cards`
- `fact_locks`
- `writing_review`

硬约束：

- 不新增事件。
- 不新增消费。
- 不改余额。
- 不改职业。
- 不改任务结果。
- 不改 NPC 已知范围。

允许改：

- 合并机械短段。
- 把解释句改成动作或界面反馈。
- 把规则说明改成角色操作。
- 把心理判断改成微动作。
- 把对白改得更口语。

## 数据流

### 初稿生成

1. Orchestrator 获得 `world_events` 和 `scene_cards`。
2. 调用 `build_style_guidance(story, chapter_number, world_events, scene_cards)`。
3. 调用 `build_performance_cards(scene_cards, style_guidance)`。
4. Writer prompt 注入：
   - 世界事实
   - 推演事件
   - 表演卡
   - 写作教练范式
   - 事实锁
5. Writer 生成正文。
6. `Fact Guard` 和 `Style Critic` 审核。

### 自动改稿

1. Critic 生成问题清单。
2. Rewriter 接收正文、问题清单、表演卡、事实锁。
3. Rewriter 输出修订正文。
4. Fact Guard 比较修订前后。
5. 若 Fact Guard 失败，拒绝修订，返回失败原因。
6. 若通过，刷新章节摘要、角色面板、质量报告。

## Prompt 注入方式

Writer prompt 增加三个区块。

### 写作教练

```text
写作教练：
- 本章不是解释规则，而是表演规则。
- 每个规则至少落到动作、界面、对白、物品、声音、旁人反应之一。
- 不要连续使用孤立短段制造“AI 卡片感”。
```

### 表演卡

```text
场景：交易行寄售
目的：第一次变现并留下弱线索。
必须表面化：数量、单价、手续费、到账、批次号。
写法：界面操作、成交提示音、主角停顿、旁人脚本记录。
禁止：解释市场规则、暴露坐标、直接说风险、额外购买道具。
```

### 事实锁

```text
事实锁：
- 夜烬职业：元素法师学徒。
- 毒腺：48枚总获得，10枚任务预留，38枚寄售。
- 单价：4铜。
- 手续费：5%。
- 最终余额：1银44铜。
- 任务材料：灰狼毒腺10/10，已预留，未提交。
```

## API 与 UI 影响

第一阶段可以不新增外部 API。

后端内部新增：

- `style_guidance` 写入 `ChapterBundle.chapter_seed` 或 `simulation_plan`。
- `performance_cards` 写入 `ChapterBundle.scene_cards` 扩展字段。
- `fact_guard` 结果写入 `quality_report.writing_review.world_state_review` 或新增 `quality_report.fact_guard`。

前端可选增强：

- 章节详情显示“写作教练建议”。
- 审稿面板显示“AI 味来源”。
- 改稿失败时显示“事实锁失败原因”。

第一阶段 UI 不作为阻塞项。

## 测试策略

### 单元测试

- `test_style_coach.py`
  - 网游第一章返回正确 opening pattern。
  - 交易事件生成交易行表演建议。
  - 公会压力保持弱线索。

- `test_fact_guard.py`
  - 检测余额被改乱。
  - 检测任务材料被改乱。
  - 检测新增未授权消费。
  - 检测职业被改乱。

- `test_prose_style_review.py`
  - 机械短段失败。
  - 解释腔失败。
  - 生活化场景通过。

### 集成测试

- 第一章生成后必须包含：
  - 现实压力
  - 游戏 ID
  - 职业选择
  - 角色面板
  - 小额验证
  - 一个 NPC 服务节点
  - 交易行弱线索
  - 章节钩子

- 自动改稿后必须：
  - 文风评分不下降。
  - 事实锁不变。
  - 质量报告刷新。

## 实施顺序

### Phase 1: Style Coach 基础版

1. 新增 `style_coach.py`。
2. 定义 `StyleGuidance` 和 `PerformanceCard`。
3. 内置 `web_game_leveling_opening` playbook。
4. 将 guidance 注入 Writer 和 Revision prompt。
5. 添加单元测试。

### Phase 2: Fact Guard

1. 新增 `fact_guard.py`。
2. 从正文和 bundle 中抽取事实锁。
3. 对比改稿前后硬事实。
4. 自动改稿失败时拒绝保存。
5. 添加账本、职业、装备、任务测试。

### Phase 3: Style Critic 升级

1. 扩展 `prose_style_review.py`。
2. 增加解释腔、场景密度、机械短段指标。
3. 把文风问题转成具体 revision plan。
4. 添加测试。

### Phase 4: 改稿闭环

1. Rewriter prompt 注入 StyleGuidance、PerformanceCard、FactLocks。
2. 改稿后先跑 Fact Guard，再跑 Style Critic。
3. 若事实锁失败，保留原文并返回错误。
4. 若文风仍失败，允许最多一次二次改稿。

## 风险与取舍

### 风险 1: 规则再次变多

缓解：

- Style Coach 输出写法范式，不输出长篇禁令。
- Prompt 中只保留当前章节相关表演卡。

### 风险 2: Fact Guard 误判

缓解：

- 第一阶段只锁确定性事实。
- 不锁模糊表达，例如“风险变大”。

### 风险 3: 改稿变保守

缓解：

- 事实锁只保护账本和身份，不限制句式、段落、对白、环境。

### 风险 4: 题材泛化不足

缓解：

- Style Coach 设计为 playbook 注册机制。
- 网游先落地，后续玄幻、都市、诡异、末世分别加 playbook。

## 成功标准

1. 第一章不再依赖大量“不要”规则，也能生成自然的网游开篇。
2. 自动改稿不会新增消费、改余额、改职业或改任务。
3. 机械短段比例显著下降。
4. 交易行、NPC、面板、掉落等规则主要通过场景表现。
5. 审稿报告能指出“哪一段像说明书”，而不是只给泛泛结论。

## 下一步

如果本设计确认，下一步进入实施计划：

1. 先实现 Phase 1 `style_coach.py`。
2. 再实现 Phase 2 `fact_guard.py`。
3. 最后接入自动改稿闭环。

