# Webgame Monster Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让网游正文在怪物首次正式交战时展示简洁怪物面板，并避免同类怪物反复刷屏。

**Architecture:** 写作任务书提供展示规则，网游审稿器检查漏写，拆书模块移除错误禁令。底层不新增怪物数据库，数值沿用项目世界设定和章节计划。

**Tech Stack:** Python、pytest

---

### Task 1: 写作输入

**Files:**
- Modify: `packages/story_core/writing_taskbook.py`
- Test: `tests/story_core/test_writing_taskbook.py`

- [ ] 添加失败测试，要求网游任务书包含首次普通怪和精英首领的面板规则。
- [ ] 实现规则并确认测试通过。

### Task 2: 网游审稿

**Files:**
- Modify: `packages/story_core/web_game_review.py`
- Test: `tests/story_core/test_web_game_review_agent.py`

- [ ] 添加失败测试，覆盖第一章战斗漏面板和已有简洁面板两种情况。
- [ ] 实现检查并确认测试通过。

### Task 3: 拆书兼容与回归

**Files:**
- Modify: `packages/story_core/book_dissection.py`
- Test: `tests/story_core/test_book_dissection.py`

- [ ] 添加失败测试，要求怪物面板不再被归类为禁用表达。
- [ ] 删除旧禁令并运行 `python -m pytest tests/story_core -q`。

