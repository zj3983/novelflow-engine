# 长篇工作区离线验收记录

2026-09-28，恢复此前暂停的验收。仅使用新建合成项目与注入模型，没有调用真实 provider 或修改真实小说。

## 执行环境

- Draft PR #45；集成工作区 `codex/longform-workbench-product`。
- `uv sync --extra dev --frozen`，Python 3.12.12，仓库锁定依赖。
- 实际 HTTP 服务：`apps.api.longform_synthetic:app`，`http://127.0.0.1:8531`。
- Web 开发地址：`http://127.0.0.1:3530/workspace`。
- 独立数据目录：`D:\CodexData\longform-acceptance-20260928`，不用于正式小说。

## 已确认的结果

- `npm run build`（独立 NEXT_DIST_DIR）通过，包括类型检查；CSS 有一条 `end` 兼容性提醒。
- 首轮完整 Python：5564 passed、8 skipped、5 failed、2 warnings。失败为既有断言未同步新产品契约；保留首次失败记录，不视为首次通过。
- 更新按钮定位与新增建议字段的断言后，产品接口专项 13 passed。
- 新增候选修改、旧检查拒绝、确认后下一章启动失败及显式重试、作者要求变化使规划采纳失效的 4 项 Core 回归通过。
- 扩展专项 `test_opening_build.py`、`test_opening_prose.py`、`test_opening_directions.py`、旧项目开书恢复、产品接口与新增候选/继续服务回归：101 passed、1 warning。
- `npm exec -- tsc --noEmit` 独立类型检查通过。
- 修复后的完整 `uv run pytest -q --tb=short`：**5574 passed、8 skipped、2 warnings**，用时 800.89 秒。警告分别为 Starlette 的 httpx 弃用提醒和封面测试替身临时文件关闭告警。

专项命令：

```powershell
uv run pytest tests/story_core/test_opening_build.py tests/story_core/test_opening_prose.py tests/story_core/test_opening_directions.py tests/story_core/test_file_project_store.py::test_opening_brief_recovers_for_legacy_blank_project tests/api/test_creation_product_routes.py tests/story_core/test_candidate_editing.py tests/story_core/test_longform_lifecycle.py -q
```

## 验收中修复

四页读取在每章重复构造和校验完整规划，并重复准备模型调用日志读取器。50 章规划时实际 HTTP 读取曾为 38 秒。现在在一次受锁保护的读取中选定修订、读取各部分；不跨请求保留缓存，写入仍由原动作服务重新校验。

在相同合成数据副本上的 cProfile 对照，优化规划快照与日志读取后，单次投影由 17.7 秒降到 3.4 秒（分析器开销包含在内，不作为生产性能承诺）。新增产品投影等价测试比较内容、动作令牌和无写入性质。

同步开书目标字段断言；并将旧的“模型调用持有项目锁”回归改为验证锁外调用期间可修改输入，而旧模型结果在提交前因来源漂移被拒绝。没有放松来源检查。

## 长程 HTTP 流程

可复用脚本 `scripts/verify_longform_offline.py` 只接受带专用离线响应标记的服务器。从创建书籍开始，准备方向和正式规划，逐章生成、审查、确认；包含手工与 AI 改稿、旧确认令牌拒绝、重复确认拒绝、确认并继续、50→51 跨卷及正文哈希核对。

```powershell
$env:NOVELFLOW_LONGFORM_SYNTHETIC='1'
$env:NOVELFLOW_LONGFORM_SYNTHETIC_ROOT='<全新独立目录>'
$env:NOVELFLOW_LONGFORM_SYNTHETIC_FAIL_ONCE='writer:17,consistency:18'
uv run python -m uvicorn apps.api.longform_synthetic:app --host 127.0.0.1 --port 8531
# 另一终端，在仓库根目录：
uv run python scripts/verify_longform_offline.py --chapters 60 --output '<独立目录>/evidence.jsonl'
```

**本次通过：60 章生成、检查、逐章调用人工确认 API，跨过 50→51，60 章正文哈希全部一致。** [逐步事件记录](evidence/http-60-chapters-2026-09-28.jsonl)。

从空项目 `file:p-d4f25222caa24d2d9425fcc426a2dcf6` 创建开始，没有预填章节。验收期间修复读取性能、调整验收脚本的规划动作顺序后，在同一项目继续；这不是一次不间断运行。第 3 章手工改稿后旧确认令牌被拒绝，重审后确认；第 4 章 AI 修改并重审；第 7 章确认后继续准备第 8 章。第 17 章写作失败后显式重试；第 18 章检查失败保留原文、拒绝确认，重新检查同一正文后通过。

另在已确认 43 章、下一任务 `running` 时停止离线服务。使用同一数据目录重启后仍为 43 章，读取工作区的模型调用增量为 0，任务可重试；随后显式继续。第二卷完整规划范围为 51–100，但正文仅生成和确认到 60。最终无运行中任务、无待确认候选、无未释放的规划运行。

本记录证明实际 HTTP 服务和存储链的离线流程与保护行为；不等于浏览器操作通过，也不证明 60 章真实模型文本质量。

## 浏览器阻塞（当天早先记录，后已恢复）

本轮实际打开本地 `/workspace` 时，再次遇到 `saved browser permissions could not be verified`。此前公共网站成功不代表本地工作台访问已恢复。没有绕过安全检查或使用替代浏览器通道。本轮没有四页实拍截图、桌面/窄屏视觉验收成绩，也没有将 API 通过当作页面验收通过。

真实模型连续性、文本质量、输出速度与依赖安全不属于本次离线验收。

当天完整重启后已完成四页浏览器操作、桌面与窄屏检查，并修复验收发现的问题。见 [浏览器验收补充](browser-acceptance-2026-09-28.md)；上文保留首次阻塞的事实，不再代表当前状态。
