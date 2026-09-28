# 四页浏览器验收补充

2026-09-28，Codex 完整重启并继承直接指向 D 盘的 CODEX_HOME 后，浏览器权限错误不再复现。本记录补充此前的离线验收；不把重启后的成功反推为已经证明底层根因。

## 环境与操作边界

- PR #45 的独立工作区；基于 `d268ae03d83963656a3033ce0b525413b6eca59b` 修复。
- Codex 内置浏览器，实际访问 `http://127.0.0.1:3530/workspace`；通过页面点击访问 FastAPI 8531。
- `apps.api.longform_synthetic:app`，注入模型，专用数据目录 `D:\CodexData\longform-acceptance-20260928`。
- 本轮浏览器新建作品 `file:p-79d0a26b7acc476a82b971b714ec69ac`（浏览器闭环验收0928）；从零生成并逐章确认 3 章。
- 原 60 章合成作品只用于目录、阅读和跨卷历史查看。此前 60 章实际 HTTP 验收见 [离线记录](acceptance-2026-09-28.md)，本次不声称重新从零生成 60 章。
- 无真实模型调用、真实小说写入、自动确认服务或安全检查绕过。

## 实际页面流程

| 操作 | 结果 |
| --- | --- |
| 新建书名、类型、想法、90 万字 / 3000 字目标、作者要求 | 创建成功；目标默认值与作者要求可见 |
| 准备方向、选择方向、准备和生成规划、完善本卷、生成新增章节安排 | 完成首卷 1–50 章规划，未完成时不能采纳 |
| 采纳规划、准备第一章 | 候选生成和审查完成，等待人工确认 |
| 第一章手工修改，保存前刷新 | 编辑文字完整恢复，确认不可用 |
| 保存新稿、查看保留旧稿 | 旧稿不含新增句子，新稿保留修改；新稿未经检查不能确认 |
| 重新检查、确认并继续 | 第一章保存成功，第二章仅生成候选，没有自动确认 |
| 第二章 AI 改稿并重新检查 | 新正文与旧稿均保留，检查完成后恢复确认 |
| 390px 窄屏双击“只确认本章”，再刷新 | 仍为已确认第 2 章，没有重复确认或自动生成第 3 章 |
| 第三章注入 writer:3 一次失败 | 正式正文仍为 2 章，页面提供重试生成 |
| 重试后注入 consistency:3 一次失败 | 保留第三章候选，确认禁用；刷新后正文完全一致 |
| 显式重新检查后确认 | 正式章节变为 3 章，无永久运行状态 |
| 人物搜索、四个故事分类、修改后续设定 | 可操作；后续打算保存，已确认 3 章保留 |
| 六十章目录折叠 | 正文 scrollTop 从 848 到 848，没有移动阅读位置 |

四页分别在 1487×1058 和 390×844 检查。实际 `scrollWidth` 为 1472 / 375，均未横向溢出。逐页检查未出现 artifact、revision、stale、validation_failed、provenance、preflight、raw JSON、provider protocol 或类型 ID。截图是实际页面，不是重新生成的设计稿。

独立 `/prototype/longform` 另验证硬冲突禁用确认、AI 改稿检查失败后的重试，以及“本章已保存，下一章尚未开始”的刷新恢复和继续；查看了卷末进入下一卷规划的界面。**这部分是纯模拟交互，不替代真实服务的跨卷和失败回归。**

## 验收发现并修复

1. **慢请求导致永远显示生成中。** 固定间隔轮询会在上次读取尚未完成时启动新读取、更新请求序号，丢弃所有较慢结果。后台轮询现在等待在途请求结束；主动导航仍可以使旧结果失效。新增可控异步读取回归。
2. **规划枚举泄露。** 后端字段投影曾把未知字段标为“内容”，展示 ready、custom、protagonist、core 等。现在仅投影具备用户标签的字段，内部状态和未知标量保留在存储中；保存可见字段不会删除它们。另将系统初始化的“小说类型：ID”精确映射为类型名称。前端没有新增内部枚举解释规则。

## 回归

```powershell
# 仓库根目录
uv run pytest tests/story_core/test_candidate_editing.py tests/story_core/test_longform_lifecycle.py tests/story_core/test_longform_plan.py tests/api/test_creation_product_routes.py -q
# apps/web
node --test tests/live-adapter-polling.test.cjs
npm run test:e2e -- tests/longform-prototype.spec.ts --workers=2
npm exec -- tsc --noEmit
$env:NEXT_DIST_DIR='.next-acceptance-build'
npm run build
```

- Core/API 专项：28 passed，1 个既有 Starlette/httpx 弃用告警；产品接口子集单独运行 14 passed。
- 慢请求 / 旧导航响应回归：1 passed。
- 类型检查、构建通过。
- 原型页面专项：14 passed（49.0s）。初次使用旧按钮文案及未填写 AI 修改要求的脚本失败；更新为当前用户操作后全套通过，保留冲突、跨卷、双击、刷新、来源变更与确认断言。
- 四页真实 API 浏览器操作为上表逐步验收，和纯模拟原型专项分别记录。远端 CI 结果以 PR 最终 HEAD 检查为准。

## 截图与测量

| 页面 | 桌面 | 窄屏 |
| --- | --- | --- |
| 作品 | [截图](evidence/browser-2026-09-28/books-desktop.jpg) | [截图](evidence/browser-2026-09-28/books-mobile.jpg) |
| 全书规划 | [截图](evidence/browser-2026-09-28/planning-desktop.jpg) | [截图](evidence/browser-2026-09-28/planning-mobile.jpg) |
| 写作 | [截图](evidence/browser-2026-09-28/writing-desktop.jpg) | [截图](evidence/browser-2026-09-28/writing-mobile.jpg) |
| 故事设定 | [截图](evidence/browser-2026-09-28/story-desktop.jpg) | [截图](evidence/browser-2026-09-28/story-mobile.jpg) |

[窄屏测量](evidence/browser-2026-09-28/mobile-checks.json)、[桌面测量](evidence/browser-2026-09-28/desktop-checks.json)、[目录位置](evidence/browser-2026-09-28/directory-scroll.json)。同目录还有开书、候选、改稿和失败状态截图。

## 范围与限制

当前可启动和操作；保持 Draft，等待独立复审。首卷完整规划目前需依次准备、生成、完善本卷并生成新增安排；本次没有另造自动调度器。未映射为用户字段的内部内容不提供通用编辑入口。历史正文仍只读。

真实模型文本质量、连续性与速度尚未验收，依赖安全独立处理。浏览器内没有重新走 50→51 的完整真实服务生成操作；该跨卷服务链依据此前 60 章 HTTP 验收，本轮截图和原型不替代它。外观与操作证据供用户和独立复审确认，不自行宣称产品 ACCEPT。
