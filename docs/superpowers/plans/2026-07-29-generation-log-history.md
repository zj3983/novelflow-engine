# Generation Log History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让文件项目可以查看历史生成任务，并让自动改稿在修复审稿问题时遵守原稿与项目篇幅上限。

**Architecture:** 后端从现有持久化任务目录生成轻量历史列表，前端按任务编号加载完整流程。改稿阶段单独计算篇幅硬上限，把它同时送入提示词、模型输出预算和流程日志，现有安全选择器继续负责最终拒绝越界候选。

**Tech Stack:** FastAPI、Python、Next.js/React、TypeScript、pytest、Playwright

---

### Task 1: 文件项目生成任务历史接口

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Test: `tests/api/test_story_routes.py`

- [x] **Step 1: 写失败测试**

新增测试，手工写入两个 `fgj-*.json`、一个 `latest.json` 和一个损坏 JSON，调用 `GET /file-projects/{project_id}/generation-jobs?limit=30`，断言仅返回两个有效任务并按 `updated_at` 倒序排列；再覆盖空目录返回空列表。

- [x] **Step 2: 运行接口测试并确认失败**

Run: `pytest tests/api/test_story_routes.py -k "generation_job_history" -q`
Expected: FAIL，接口当前仅支持 POST。

- [x] **Step 3: 实现历史列表接口**

在 `file_projects.py` 增加列表响应转换和 GET 路由。用 `_store_for(project_id)` 定位目录，只匹配 `fgj-*.json`，逐个容错解析，按 `updated_at` 倒序后截取 `limit`；响应项包含 `job_id`、`story_id`、`chapter_number`、`status`、`progress`、`error`、`created_at`、`updated_at`。

- [x] **Step 4: 运行接口测试**

Run: `pytest tests/api/test_story_routes.py -k "generation_job_history or current_generation_job or generation_log_survives" -q`
Expected: PASS。

### Task 2: 日志页历史任务选择

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/log/page.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [x] **Step 1: 写失败的页面测试**

拦截历史列表与两个单任务接口，打开日志页，断言默认展示最新任务；点击旧任务后展示旧任务步骤；运行中的最新任务仍会轮询，旧任务不会轮询。

- [x] **Step 2: 运行页面测试并确认失败**

Run: `npm --prefix apps/web run test:e2e -- --grep "生成日志历史"`
Expected: FAIL，页面没有历史列表和切换入口。

- [x] **Step 3: 增加 API 类型与请求方法**

在 `api.ts` 增加 `GenerationJobSummary`、`GenerationJobHistoryResponse` 和 `fetchGenerationJobHistory(projectId, limit)`，仅对文件项目调用 GET 历史接口。

- [x] **Step 4: 实现日志页状态与界面**

页面首次加载历史列表，默认选择第一项，再通过 `fetchGenerationJob` 读取完整步骤。用紧凑列表展示时间、章节与状态；仅当所选任务是当前运行任务时每 2 秒刷新，并在失败时展示该任务错误。

- [x] **Step 5: 运行页面测试**

Run: `npm --prefix apps/web run test:e2e -- --grep "生成日志历史"`
Expected: PASS。

### Task 3: 自动改稿篇幅硬上限

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_orchestrator.py`

- [x] **Step 1: 写失败测试**

覆盖三种原稿长度：3000 字得到 4200、5000 字得到 5000、6000 字得到 5500；断言改稿提示词明确写入硬上限与“替换、合并、删除”，并断言改稿调用的 `max_tokens` 小于原来的固定 7000。

- [x] **Step 2: 运行改稿测试并确认失败**

Run: `pytest tests/story_core/test_orchestrator.py -k "revision_char_ceiling or revision_prompt" -q`
Expected: FAIL，当前提示词只使用计划目标且调用固定 `max_tokens=7000`。

- [x] **Step 3: 实现上限计算与动态预算**

新增 `_revision_char_ceiling(body)`，返回 `min(MAX_CHAPTER_CHARS, max(MIN_CHAPTER_CHARS, _chapter_char_count(body)))`。提示词写明具体硬上限和局部改写方式；改稿调用预算使用 `min(6200, ceiling + 500)`。

- [x] **Step 4: 将安全报告字数写入流程产物**

在“审稿改稿完成”的 outputs 中加入 `original_chars` 和 `candidate_chars`，直接取 `revision_safety_report` 已有字段。

- [x] **Step 5: 运行改稿与安全测试**

Run: `pytest tests/story_core/test_orchestrator.py tests/story_core/test_revision_safety.py -q`
Expected: PASS。

### Task 4: 联合验证

**Files:**
- Verify only

- [x] **Step 1: 运行后端相关测试**

Run: `pytest tests/api/test_story_routes.py tests/story_core/test_orchestrator.py tests/story_core/test_revision_safety.py -q`
Expected: PASS。

- [x] **Step 2: 运行前端类型检查和目标页面测试**

Run: `apps/web/node_modules/.bin/tsc.cmd --noEmit`
Expected: PASS。

Run: `npm --prefix apps/web run test:e2e -- --grep "生成日志历史"`
Expected: PASS。

- [x] **Step 3: 检查改动范围**

Run: `git diff --check`
Expected: 无输出，退出码 0。
