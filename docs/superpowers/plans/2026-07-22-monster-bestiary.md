# Monster Bestiary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在世界观页面维护怪物图鉴，并把本章相关怪物卡提供给写手。

**Architecture:** 怪物卡保存在项目世界蓝图中，前端通过现有项目更新接口保存。文件项目构建 StoryState 时注入怪物卡，写手提示词按本章文本匹配怪物名称。

**Tech Stack:** Python、FastAPI 现有项目接口、Next.js、React、TypeScript、pytest、Playwright

---

### Task 1: 数据与写作上下文

**Files:**
- Modify: `packages/story_core/models.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_writer_prompt_method.py`

- [ ] 添加失败测试，要求写手只读取本章点名的怪物卡。
- [ ] 注入怪物卡并实现相关卡片筛选。
- [ ] 运行目标测试。

### Task 2: 怪物图鉴页面

**Files:**
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/components/ws/MonsterBestiary.tsx`
- Modify: `apps/web/app/projects/[id]/world/page.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] 添加失败测试，覆盖显示、编辑和新增。
- [ ] 实现怪物卡组件并通过现有 `updateProject` 保存。
- [ ] 运行 TypeScript 和 Playwright 测试。

### Task 3: 当前项目数据与回归

**Files:**
- Modify: current project `.webnovel/project.json`

- [ ] 写入灰狼怪物卡。
- [ ] 验证页面接口和写手提示词。
- [ ] 运行完整核心测试。

