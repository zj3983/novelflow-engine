# 可见世界观工作台设计

## 目标

把项目已有的世界背景、世界规则、地点、阵营、怪物和已确认事实集中展示在世界观页面。所有长期设定都可见，能编辑的内容可以直接编辑，不再依赖隐藏字段或旧设定文件。

## 页面结构

世界观页面采用单页纵向分区，不使用标签页、折叠面板或只读侧栏：

1. 世界背景
2. 世界规则
3. 地点
4. 阵营
5. 怪物图鉴
6. 已确认事实

作者要求不再显示在世界观页面，继续由项目设置或提示词页面管理。

## 数据归属

### 世界背景

- 项目摘要：`project.world_summary`
- 世界前提：`world_blueprint.premise`
- 当前局势：`world_blueprint.current_arc`
- 三项分别显示和编辑，保存时保留其他 `world_blueprint` 字段。

### 世界规则

- 基础规则：`world_blueprint.world_rules`
- 成长与战斗：`world_blueprint.progression_rules`
- 任务与经济：合并展示、分别保存 `quest_rules` 和 `economy_rules`
- 游戏影响现实：新增 `world_blueprint.reality_bridge_rules`
- 每组规则按一行一条编辑，不与作者约束、章节事实混存。

### 地点与阵营

- 地点：`world_blueprint.locations`
- 阵营：`world_blueprint.factions`
- 支持新增、编辑和删除。
- 兼容已有 `{name, description}` 及附加字段，编辑时不删除未展示字段。

### 怪物图鉴

- 沿用 `world_blueprint.monster_profiles`。
- 保持独立卡片及现有增删改能力。

### 已确认事实

- 来源为 `story.world_facts`，完整显示，不再限制为前 20 条。
- 事实按可识别的“第 N 章事实”来源分组；无法识别来源的归入“项目事实”。
- 本期只读，避免用户修改事实后与章节状态、历史快照失去同步。
- 页面明确显示“由章节回写，不在此处直接修改”。

## 保存与兼容

- 所有可编辑区域使用现有 `updateProject` 接口。
- 更新 `world_blueprint` 时始终复制现有对象，只替换当前区域负责的字段。
- 保存成功后刷新工作区数据，并在当前区域显示成功或错误状态。
- 不迁移、不删除旧字段；已有项目打开后立即可见。

## 写作上下文

- 本次不扩大写作提示词长度。
- 写作阶段仍按任务相关性提取世界资料。
- 新增的 `reality_bridge_rules` 进入世界规则候选池，但只在章节涉及现实与游戏连接时提取。
- 页面展示完整数据，提示词只读取相关数据，两者职责分开。

## 组件边界

- `WorldBackgroundEditor`：背景三字段。
- `WorldRulesEditor`：四组规则。
- `WorldEntitiesEditor`：地点与阵营。
- `MonsterBestiary`：保留现有实现。
- `ConfirmedFactsPanel`：事实分组与完整展示。
- 世界观路由只负责排列组件和传递项目数据。

## 验证

- 单元/组件测试覆盖各区域读取、编辑和保存。
- 验证保存一个区域不会清除其他 `world_blueprint` 字段。
- 验证全部事实可见且按章节分组。
- 验证作者约束不再出现在世界观页面。
- 运行后端测试、前端 TypeScript 检查，并在本地工作台实际完成一次编辑保存。
