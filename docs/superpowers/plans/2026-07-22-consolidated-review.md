# Consolidated Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将多路审稿结果合并为一份简短、可执行的综合审稿，并让自动改稿和页面统一使用它。

**Architecture:** 保留现有本地检查器作为内部事实来源，在 `simplified_review.py` 完成分类、近似去重和修改指令收敛。质量报告继续保存明细，消费端只读取综合结果。

**Tech Stack:** Python、FastAPI 数据结构、React/TypeScript、pytest、Playwright

---

### Task 1: 综合审稿器

**Files:**
- Modify: `packages/story_core/simplified_review.py`
- Test: `tests/story_core/test_simplified_review.py`

- [ ] 写失败测试，要求重复问题合并、问题和修改指令均不超过三项。
- [ ] 运行 `python -m pytest tests/story_core/test_simplified_review.py -q`，确认测试因缺少综合修改清单而失败。
- [ ] 实现规范化去重、分类优先级和 `revision_plan` 输出。
- [ ] 重跑测试并确认通过。

### Task 2: 接入质量报告与自动改稿

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_file_project_store.py`
- Test: `tests/story_core/test_orchestrator.py`

- [ ] 写失败测试，要求改稿上下文只包含综合审稿的三条指令。
- [ ] 运行目标测试并确认失败。
- [ ] 在质量报告生成后写入 `simplified_review`，改稿入口优先读取其 `revision_plan`。
- [ ] 重跑目标测试并确认通过。

### Task 3: 简化页面

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/components/ws/SimplifiedReview.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] 写失败测试，要求页面只出现一份综合审稿和最多三项修改。
- [ ] 运行 Playwright 目标测试并确认失败。
- [ ] 更新类型和组件，展示状态、分类计数和综合修改清单。
- [ ] 重跑前端测试并确认通过。

### Task 4: 回归验证

**Files:**
- Verify only

- [ ] 运行 `python -m pytest tests/story_core -q`。
- [ ] 运行相关前端测试。
- [ ] 调用当前项目章节审稿接口，确认综合报告不超过三项且内部明细仍可诊断。

