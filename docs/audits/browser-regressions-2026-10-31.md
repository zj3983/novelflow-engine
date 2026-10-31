# 18 项浏览器失败：原因与最小修复

基线为 PR #54 的 `790bac60`。先在相同的隔离工作区、3167 端口与两 worker 条件下重跑原 18 项：18 failed、0 flaky，保留 JSON 报告。没有先修改产品实现来适配测试。

## 根因分组

| 项数 | 用例 | 已核实原因 | 最小修复 |
| ---: | --- | --- | --- |
| 4 | author-tools 的模块、关系、模板与作品资料 | 模拟响应 CORS 写死允许 `127.0.0.1:3100`，当前页面来自 `127.0.0.1:3167`。trace 中请求来源与 `route.fulfill` 响应头不匹配，页面显示工作区无法连接；同 SHA 的远端默认端口测试通过 | 模拟响应来源跟随现有 Playwright base URL/port 设置 |
| 3 | navigation-convergence | 当前项目导航已分组，`/config` 名为“配置”，章节页标题和侧栏入口也已调整；兼容入口 fixture 仍只拦截已停用的 product/write 请求 | 核验当前入口名称、href 与 aria-current；拦截该合成项目实际使用的读取端点 |
| 3 | 下一卷、部分细纲、卷纲读取失败 | 页面提示已调整，测试仍匹配旧文字，原有禁止生成行为仍在 | 更新提示断言，保留按钮禁用、目标链接与生成请求数断言 |
| 2 | 窄屏目录、延迟章节读取 | 窄屏目录已是横向条，测试仍要求纵向溢出；章节标题也已简化。延迟加载前后正文正常 | 检查横向溢出、180px 高度上限和当前标题；保留页面滚动、旧正文保留及加载次数断言 |
| 1 | 三层大纲编辑与重新规划 | 后半段仍使用旧收束提示、章节分组标题及重新生成按钮名称；新增完结核对组件缺少模拟读取响应 | 跟随当前页面结构补齐断言与合成响应，保留总纲/阶段/章节保存载荷和生成步骤检查 |
| 1 | 人物关系与项目设置 | 项目设置位于默认折叠的“项目”导航组中，角色查询只匹配可见元素 | 先展开项目组，再核验链接和保存关系 |
| 4 | 候选稿上下文审稿、两种 AI 味检查状态、候选精修 | fixture 把待审候选放在已有正式正文的第 1 章，而当前规则明确默认打开正式正文。上下文审查/精修因此正确使用正式正文来源；候选面板也不会持续显示 | 候选场景改为尚无正文的第 2 章，先断言候选面板，再检查确切章节号和 candidate ID；正式正文场景保留第 1 章 |

候选精修用例分别检查两种真实前提：第 1 章有已提交版本可回看；第 2 章没有已提交版本，不显示错误的历史正文。两种情况都检查已确认的第 1 章保持原样。

同类的两项候选稿标注测试原先也可能误测正式正文，已采用相同的第 2 章夹具并明确断言候选面板，保留原文定位和正文不变检查。

修复集中于三个现有 spec。产品代码、业务审稿规则、确认门禁与 CI workflow 保持原状；本次没有调用真实模型或写入小说项目。

## 验证记录

- 原 18 项在修改前单独重跑：18 failed、0 flaky。
- 修复后重跑与上轮相同的八个 spec：170 passed、0 failed、0 skipped、0 flaky，164.34 秒。没有删除用例；原 18 项与最终结果按文件和标题逐项匹配，18/18 通过。
- `npx tsc --noEmit` 通过，`git diff --check` 通过。
- 仅测试与文档变化，本轮没有重跑 Python；两个 PR 原提交的完整 Python CI 结果见下方。推送后由现有 CI 检查新提交。

复现完整浏览器检查：

```powershell
$env:PLAYWRIGHT_PORT='3167'; $env:CI='1'
npx playwright test tests/foreshadowing-workbench.spec.ts tests/author-tools.spec.ts tests/longform-phase2.spec.ts tests/navigation-convergence.spec.ts tests/review-annotations.spec.ts tests/writing-preferences.spec.ts tests/world-state-layout.spec.ts tests/story-workbench.spec.ts --workers=2 --reporter=json
```

以上在 `apps/web` 执行。原始失败日志与分轮 JSON 留在本地 `.codex-run/github-sync-20261031/`；`browser18-resolution.json` 保存原 18 项到最终结果的匹配记录。本机运行材料不加入源码。

## CI 核对

- PR #53，`bd21e5f5`，run `41194894922`：Python、Web 均 completed/success。
- PR #54 原提交 `790bac60`，run `41195389680`：Python completed/success，Web completed/failure；构建通过，浏览器为 18 passed、3 failed，失败均属于上表导航组。远端原 workflow 只运行四个 spec，和本地八 spec 的 170 项覆盖不同。

修复提交到 PR #54，保持 Draft；新提交的最终 CI 状态见该 PR 的检查记录，不自动合并。
