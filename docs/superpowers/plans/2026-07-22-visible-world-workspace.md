# 可见世界观工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将世界背景、分类规则、地点、阵营、怪物和完整章节事实全部放到可见、可维护的世界观单页中。

**Architecture:** 保留现有文件项目与 `world_blueprint` 数据模型，以多个单一职责的客户端组件编辑各自字段。路由页面只负责装配；所有保存都复制原蓝图后替换所属字段，事实继续从故事状态只读展示。

**Tech Stack:** Next.js、React、TypeScript、Playwright、Python story_core tests

---

### Task 1: 扩展世界观前端类型

**Files:**
- Modify: `apps/web/lib/api.ts`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: 写入失败测试夹具**

在世界观页面测试项目的 `world_blueprint` 中加入：

```ts
premise: "《天启之门》连接现实与游戏经济。",
current_arc: "开服首日，异常掉落刚刚出现。",
world_rules: ["玩家开局身份相同。"],
progression_rules: ["转职必须完成前置任务。"],
quest_rules: ["任务先接取后提交。"],
economy_rules: ["新手期使用铜币。"],
reality_bridge_rules: ["游戏收益通过合法交易影响现实。"],
```

- [ ] **Step 2: 运行测试并确认页面找不到相应分区**

Run: `npx playwright test tests/story-workbench.spec.ts -g "世界观页面完整展示"`
Expected: FAIL，页面不存在“世界背景”或“游戏影响现实”编辑区域。

- [ ] **Step 3: 扩展类型**

在 `ImportedWorldBlueprint` 增加：

```ts
reality_bridge_rules?: string[];
```

- [ ] **Step 4: 运行 TypeScript 检查**

Run: `npx tsc --noEmit`
Expected: PASS

### Task 2: 实现背景与规则编辑器

**Files:**
- Create: `apps/web/components/ws/WorldBackgroundEditor.tsx`
- Create: `apps/web/components/ws/WorldRulesEditor.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: 完成背景编辑测试**

测试点击“保存世界背景”后，PUT 请求应保留怪物卡并更新：

```ts
expect(savedProject).toMatchObject({
  world_summary: "新的项目摘要",
  world_blueprint: {
    premise: "新的世界前提",
    current_arc: "新的当前局势",
    monster_profiles: [{ name: "灰狼" }],
  },
});
```

- [ ] **Step 2: 完成规则编辑测试**

测试四组文本框都可见，保存“游戏影响现实”后：

```ts
expect(savedBlueprint.reality_bridge_rules).toEqual([
  "游戏收益通过合法交易影响现实。",
]);
expect(savedBlueprint.world_rules).toEqual(["玩家开局身份相同。"]);
```

- [ ] **Step 3: 实现 `WorldBackgroundEditor`**

组件接收：

```ts
type Props = {
  projectId: string;
  worldSummary: string;
  blueprint: ImportedWorldBlueprint;
  onSaved?: () => void;
};
```

显示“项目摘要、世界前提、当前局势”三个常驻文本框，保存时调用：

```ts
updateProject(projectId, {
  world_summary: draft.summary,
  world_blueprint: {
    ...blueprint,
    premise: draft.premise,
    current_arc: draft.currentArc,
  },
}, { fallbackToMock: false });
```

- [ ] **Step 4: 实现 `WorldRulesEditor`**

用四个常驻多行文本框编辑 `world_rules`、`progression_rules`、任务与经济规则、`reality_bridge_rules`。任务与经济分别保存，不把两组值合成一个字段；每行解析成一条规则。

- [ ] **Step 5: 运行前端测试与类型检查**

Run: `npx playwright test tests/story-workbench.spec.ts -g "世界观页面完整展示"`
Expected: PASS

Run: `npx tsc --noEmit`
Expected: PASS

### Task 3: 实现地点、阵营与完整事实面板

**Files:**
- Create: `apps/web/components/ws/WorldEntitiesEditor.tsx`
- Create: `apps/web/components/ws/ConfirmedFactsPanel.tsx`
- Modify: `apps/web/lib/worldDisplay.ts`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: 写地点与阵营保存测试**

新增地点“灰狼坡”和阵营“命令者公会”后断言：

```ts
expect(savedBlueprint.locations).toEqual(
  expect.arrayContaining([expect.objectContaining({ name: "灰狼坡" })]),
);
expect(savedBlueprint.factions).toEqual(
  expect.arrayContaining([expect.objectContaining({ name: "命令者公会" })]),
);
```

- [ ] **Step 2: 写事实完整展示测试**

夹具提供 25 条项目事实和两条章节事实，断言第 25 条仍可见，并显示“项目事实”“第 1 章”分组；断言页面不存在“作者约束”标题。

- [ ] **Step 3: 实现 `WorldEntitiesEditor`**

地点和阵营各自显示名称与描述输入框，支持新增、删除和保存。更新单项时使用对象展开保留附加字段：

```ts
next[index] = { ...next[index], name, description };
```

- [ ] **Step 4: 实现事实分组函数与组件**

在 `worldDisplay.ts` 增加：

```ts
export function groupWorldFacts(facts: string[]) {
  // “第N章事实：”进入对应章节，其余进入“项目事实”。
}
```

`ConfirmedFactsPanel` 不截断输入，不提供编辑按钮，显示“由章节回写，不在此处直接修改”。

- [ ] **Step 5: 运行目标测试**

Run: `npx playwright test tests/story-workbench.spec.ts -g "世界观页面完整展示"`
Expected: PASS

### Task 4: 重组页面并验证写作兼容

**Files:**
- Modify: `apps/web/app/projects/[id]/world/page.tsx`
- Modify: `packages/story_core/writing_packet.py`
- Test: `tests/story_core/test_writing_packet.py`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: 写现实桥接规则按需读取测试**

构造涉及现实到账的章节计划，断言写作包包含相关 `reality_bridge_rules`；构造纯游戏战斗计划，断言不注入无关现实规则。

- [ ] **Step 2: 重组世界观路由**

按以下顺序渲染，不再使用旧的只读侧栏和作者约束区：

```tsx
<WorldBackgroundEditor />
<WorldRulesEditor />
<WorldEntitiesEditor />
<MonsterBestiary />
<ConfirmedFactsPanel />
```

- [ ] **Step 3: 最小化接入现实桥接规则**

在写作包世界规则候选中读取 `reality_bridge_rules`，仅当本章计划或方向包含“现实、到账、提现、收入、账单、房租”等现实连接词时加入。

- [ ] **Step 4: 跑完整回归**

Run: `python -m pytest tests/story_core -q`
Expected: 全部通过

Run: `npx tsc --noEmit`
Expected: PASS

- [ ] **Step 5: 浏览器验证**

打开 `/projects/file%3Ap-gou-webgame-restored/world`，确认六个分区全部可见；编辑世界前提并保存原值，确认保存提示成功且怪物卡、地点和规则未丢失。
