# 小说生成 Agent 模块化设计

## 1. 目标

将当前集中在 `orchestrator.py` 中的章节生成职责拆成可独立理解、测试和替换的模块。

本次设计要求：

- 导演 Agent 与写作 Agent 分别主动读取各自需要的项目资料。
- 两个 Agent 共用文件读取能力，但获得不同范围的上下文。
- 写作 Agent 可以在 Codex CLI、其他 CLI 和普通 API 之间切换，不改变业务流程。
- 新人物、装备、功法、技能、怪物、任务和地点在正文前完成必要建档。
- 正文生成后只产生候选事实变更；检查通过并确认后才更新正式状态。
- 重写章节必须从目标章之前的快照重新开始，不能沿用旧版本产生的后续状态。
- 工作台能够显示每一步读取了什么、为什么读取以及产出了什么。

## 2. 非目标

- 不在写作 Agent 内实现审稿、存储、状态更新和大纲修改。
- 不为人物、装备、功法分别建立一套 Agent；它们由统一的设定管理模块处理。
- 不让模型任意扫描整个项目作为默认读取方式。
- 不把所有写作技巧、题材规则和角色卡一次性注入正文提示词。
- 不在 JSON 和 Markdown 中维护两份可独立编辑的正文。

## 3. 核心产物

系统中的内容分为四类，所有权必须清楚。

| 类型 | 示例 | 负责模块 | 是否可由下游覆盖 |
| --- | --- | --- | --- |
| 长期规划 | 总纲、卷纲、章节细纲 | 大纲模块 | 否 |
| 正式设定 | 世界规则、角色卡、装备卡、功法卡 | CanonService | 否 |
| 动态状态 | 等级、位置、关系、物品归属、伏笔状态 | ContinuityStore | 只能通过确认后的状态变更更新 |
| 章节表达 | 导演计划、正文、审稿报告 | 对应 Agent | 不得反向修改上级事实 |

事实优先级如下：

1. 用户人工明确修改。
2. 已确认世界设定和实体档案。
3. 总纲、卷纲与章节细纲。
4. 目标章之前的连续性状态。
5. 导演计划。
6. 写作 Agent 的临时表达。

下级产物与上级事实冲突时必须停止，不能自行选择一个版本继续。

## 4. 模块结构

建议逐步整理为以下目录：

```text
packages/story_core/
  agents/
    director/
      agent.py
      contract.py
      prompt.py
    writer/
      agent.py
      contract.py
      prompt.py
      runtime.py
    consistency/
      agent.py
      contract.py
    fact_extractor/
      agent.py
      contract.py
  context/
    project_reader.py
    director_context.py
    writer_context.py
    trace.py
  canon/
    service.py
    contracts.py
    registry.py
    schemas/
      character.py
      item.py
      ability.py
      location.py
      faction.py
      quest.py
  continuity/
    store.py
    snapshot.py
    delta.py
  runtimes/
    base.py
    cli.py
    api.py
  genres/
    game_webnovel/
    xuanhuan/
  orchestration/
    chapter_pipeline.py
    rewrite_pipeline.py
```

`orchestrator.py` 最终只负责阶段顺序、失败传播和事务提交，不再组装正文提示词。

## 5. 共享项目读取层

`ProjectContextReader` 是确定性代码，不是模型 Agent。它负责：

- 按稳定路径读取项目文件。
- 根据实体 ID、章节号和资料类型进行精确查询。
- 缓存同一次任务中的重复读取。
- 为每次读取记录文件、版本、范围和读取原因。
- 返回结构化数据，不返回无法追踪来源的大段拼接文本。

导演和写手共用读取器，但使用不同视图。

### 5.1 导演视图

导演读取：

- 当前阶段的总纲摘要。
- 当前卷大纲。
- 本章细纲。
- 上一章摘要和章末状态。
- 与本章相关的未回收伏笔。
- 主要人物简版状态。
- 本章涉及的世界规则。
- 当前成长、节奏和压力状态。

导演不读取完整写作技巧、完整文风样本、对话 Skill 和无关角色卡。

### 5.2 写手视图

写手读取：

- 已通过规划检查的导演产物。
- 本章细纲。
- 上一章结尾及必要正文片段。
- 本章出场人物的完整角色卡和关系边界。
- 本章引用地点、物品、能力和任务的正式档案。
- 目标章之前的连续性状态。
- 当前题材模块。
- 本章确实需要的一个或少量写作技巧模块。

写手不读取整部详细大纲、其他卷细纲、无关角色卡和无关世界规则。

## 6. 导演 Agent

导演 Agent 的输入只包含：

```json
{
  "project_root": "D:/novels/example-project",
  "chapter_number": 4,
  "operation": "generate",
  "user_instruction": ""
}
```

导演自己通过导演视图读取资料，输出结构化章节计划：

```json
{
  "chapter_number": 4,
  "chapter_goal": "确认灰石裂缝的异常来源",
  "opening_state": "承接上一章返回灰烬村",
  "scenes": [
    {
      "location_id": "location-guard-office",
      "participant_ids": ["character-su-ye", "character-guard-captain"],
      "goal": "提交调查结果",
      "conflict": "证据不足",
      "result": "获得一次补查机会"
    }
  ],
  "required_facts": ["protagonist.level=2"],
  "must_not_happen": ["守备队长知道混沌之种"],
  "ending_hook": "裂缝深处再次震动",
  "required_entity_ids": ["character-su-ye", "character-guard-captain"],
  "proposed_entities": [],
  "referenced_rule_ids": ["rule-zone-level-gap"]
}
```

导演只提出缺失实体需求，不直接生成完整角色卡或物品卡。

## 7. 设定管理模块

统一的 `CanonService` 管理所有可持续存在的实体：

- 人物和身份别名。
- 人物关系。
- 装备、道具和材料。
- 功法、技能和能力。
- 怪物、任务、地点和势力。

每个实体必须有稳定 `entity_id`。例如苏叶与夜烬属于同一人物：

```json
{
  "entity_id": "character-su-ye",
  "entity_type": "character",
  "real_name": "苏叶",
  "aliases": ["夜烬"],
  "identities": ["现实身份", "游戏身份"]
}
```

实体生命周期：

```text
proposed -> approved -> active -> retired
```

- `proposed`：导演提出但尚未确认。
- `approved`：写前检查完成，可以进入正文。
- `active`：已在确认正文中正式出现。
- `retired`：死亡、销毁、失效或退出剧情。

CanonService 本身负责查询、校验、版本和持久化，不直接自由创作。缺失实体需要补卡时，由它调用统一的 `EntityDesigner`：

1. `EntityDesigner` 根据实体类型选择固定结构模板。
2. 模型只填写导演计划和现有设定能够支持的字段。
3. CanonService 校验实体 ID、别名、力量体系、来源和重复记录。
4. 校验通过后保存为 `approved`，失败时退回导演或等待人工修改。

`EntityDesigner` 是 CanonService 的可替换生成器，不为人物、装备和功法分别增加常驻 Agent。

### 7.1 写前建档

会影响后续一致性的实体必须在正文前建档。

人物基础卡包含身份、来历、当前目标、关系、知识边界、行为方式和说话边界。

装备、功法和技能基础卡包含类型、等级、来源、使用条件、效果、限制、代价、唯一性和初始归属。

无名路人、普通环境物件、不会再次出现的杂物和公共模板中的普通怪物无需单独建卡。

### 7.2 写后更新

正文后只更新首次出现章节、当前位置、归属、数量、进度、关系变化、已知信息和存续状态，不重写基础定义。

## 8. 写作 Agent

写作 Agent 的公开接口：

```python
result = WriterAgent(runtime).run(
    WriterRequest(
        project_root=project_root,
        chapter_number=chapter_number,
        operation="rewrite",
        user_instruction="加快升级节奏",
        director_artifact=".story-system/director/0004.json",
    )
)
```

写作 Agent 负责：

1. 读取并校验导演产物。
2. 根据实体和规则引用装配写手视图。
3. 选择当前题材模块和必要技巧模块。
4. 调用指定 CLI 或 API 生成正文。
5. 返回 Markdown 正文和生成追踪信息。

写作 Agent 不负责审稿、修改角色卡、更新世界观、提交状态、保存项目和决定章节是否通过。

CLI 与 API 共用同一个写作 Agent。`runtime.py` 只负责请求传输和模型响应归一化，不能改变业务上下文。

### 8.1 写作技巧与 Skill 模块

写作技巧、题材规则和用户 Skill 不属于 WriterAgent 内部代码。它们通过统一模块清单注册：

```json
{
  "module_id": "craft-natural-dialogue",
  "purpose": "dialogue",
  "activation": ["chapter_has_dialogue"],
  "requires": ["character_context", "relationship_context"],
  "conflicts": ["craft-telegraphic-dialogue"],
  "scope": "project",
  "max_chars": 1800,
  "enabled": true
}
```

- 每个模块可以单独安装、启用、禁用和卸载。
- 未启用模块不得进入写手上下文。
- WriterAgent 根据导演场景和模块触发条件选择模块。
- 同一职责默认最多选择一个模块；冲突模块不能同时加载。
- 题材模块只能由小说类型选择，不能进入其他题材项目。
- 工作台必须显示实际注入的模块 ID 和字符数，不能只显示“Skill 已加载”。

## 9. 写后检查与事实提交

正文生成后的顺序固定为：

1. 确定性检查器检查经验、等级、伤害、余额、库存、时间和任务进度。
2. 事实一致性 Agent 检查正文与正式事实之间的明确矛盾。
3. 事实提取器从正文提取候选状态变化。
4. CanonService 校验候选变更的实体 ID、来源和合法状态转换。
5. 所有阻塞检查通过后生成候选版本；仅在项目明确开启 `auto_confirm` 时自动原子提交，否则等待用户确认。

事实一致性 Agent 不评价文风、节奏、爽点和普通措辞。写作质量建议可以展示，但不能阻止保存。

事实提取器不得直接写入正式状态。候选变更示例：

```json
{
  "chapter_number": 4,
  "base_snapshot": "chapter-0003-confirmed",
  "changes": [
    {
      "entity_id": "item-cracked-wolf-heart",
      "field": "owner_id",
      "before": null,
      "after": "character-su-ye",
      "evidence": "正文第18段"
    }
  ],
  "unregistered_entities": []
}
```

正文出现未登记的重要实体时，任务进入待处理状态。系统可以补卡后重新检查，或删除该实体并重写正文，但不能静默登记为正式事实。

## 10. 重写语义

重写第 N 章必须：

1. 加载第 N-1 章确认后的快照。
2. 作废旧第 N 章及其后章节产生的派生状态。
3. 重新运行导演计划和实体需求检查。
4. 重新生成正文并执行写后检查。
5. 确认后创建新的第 N 章版本。

下游章节默认标记为 `stale`，不能继续使用旧状态生成新章节。系统不得把旧版章节产生的人物、装备、关系和伏笔残留到新版时间线中。

## 11. 正文与元数据存储

正文唯一来源为：

```text
chapters/0004-章节标题.md
```

章节 JSON 不再保存可独立修改的正文副本，只保存：

- Markdown 路径和内容哈希。
- 导演产物引用。
- 上下文读取追踪。
- 审查报告。
- 候选与已提交状态变更。
- 章节版本和基础快照。

正式提交必须采用同一事务：正文、章节元数据、连续性状态和实体状态要么全部成功，要么全部回滚。

## 12. 可观察性

每个 Agent 和模块都输出统一追踪事件：

```json
{
  "stage": "writer.context",
  "status": "done",
  "reads": [
    {
      "source": "characters/character-su-ye.json",
      "reason": "导演计划声明为本章出场人物",
      "version": "sha256:abc123"
    }
  ],
  "ignored": ["其他卷大纲", "未出场人物卡"],
  "output": ".story-system/writer/0004-context.json"
}
```

工作台展示的是持久化流程记录，不依赖刷新即消失的控制台日志。

## 13. 错误处理

- 导演计划与大纲冲突：退回导演阶段。
- 导演引用不存在的正式实体：进入写前建档阶段。
- 写手上下文缺失必要事实：停止正文调用并显示缺失来源。
- 正文数值不闭合：阻止提交，返回确定性错误。
- 正文与正式事实冲突：阻止提交，返回证据和冲突来源。
- 只有风格建议：允许保存，将建议作为非阻塞报告展示。
- CLI 或 API 调用失败：保留已完成产物并允许从失败阶段重试。

## 14. 测试要求

至少覆盖：

- 导演和写手获得不同上下文视图。
- 写手只读取导演引用的角色、地点和规则。
- 苏叶与夜烬不会生成两张角色卡。
- 新人物和新装备在正文前进入 `approved`。
- 未登记重要实体不会被事实提取器静默入库。
- API 与 CLI 使用同一份 WriterRequest 和 WriterResult 契约。
- 重写章节恢复正确快照并使下游章节失效。
- Markdown 是正文唯一来源，JSON 哈希能检测外部修改。
- 任一提交步骤失败时正文和状态都能回滚。
- 页面刷新后仍能查看各阶段读取记录和产物。

## 15. 迁移顺序

为控制风险，按以下顺序改造：

1. 建立 Agent 请求、响应和上下文追踪契约。
2. 抽取共享 `ProjectContextReader`，保持现有生成结果不变。
3. 将现有正文提示词和模型调用迁入新的 WriterAgent。
4. 将导演调用迁入新的 DirectorAgent。
5. 建立 CanonService 和实体 ID，先兼容现有角色卡与物品记录。
6. 引入候选状态变更和原子提交。
7. 实现基于确认快照的重写回滚。
8. 将正文切换为 Markdown 唯一来源。
9. 删除旧 `writer_agent.py` 和 `orchestrator.py` 中已经迁出的兼容实现。

迁移期间每一步都必须保持现有 API 可用，避免一次性重写整个流程。
