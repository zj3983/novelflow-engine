# 2026-10-31 本地源码同步

从远端 `main@9aa67dc2` 建立独立分支，按路径白名单导入本地当前应用源码、核心模块、测试及两个评估脚本。没有把整个本地快照历史推送到主线。

内容包括写作工作台、文风传递、候选稿审查与精修、语义复核、长度策略、CLI provider 结果处理、收尾规划和对应测试。所有实现均为本地已有改动；本次主要负责整理与验证。源码中已有 #46/#48 的工作不代表这两个 Issue 的全部实验验收通过。#46 的最小主线修复单列 Draft PR #53。

同步白名单不包含真实小说、候选稿数据、运行配置、认证信息、构建缓存、一次性视频材料或其他项目内容。既有私人审计记录保留在原工作区。新增源码中的常见密钥/私钥格式扫描无匹配；这仅是所扫描模式的结果。

## 当前验证

- 完整 Python：`pytest -q`，5872 passed、8 skipped、2 warnings，680.05 秒。
- 核心 Python：`pytest tests/story_core -q`，5000 passed、8 skipped、2 warnings，468.33 秒。
- 两个警告为 Starlette/httpx 弃用提示及测试替身 `ChunkedErrorBody` 无 `close` 的 unraisable warning，未改第三方依赖来消除提示。
- Web：`npm ci`、`npm run build` 通过。CSS autoprefixer 提示 `end` 的兼容性；未将其当作构建失败。
- 浏览器：下列八个 spec 合计 152 passed、18 failed，4.7 分钟。不是全部 Web 测试通过。
- `git diff --cached --check` 通过。

```text
tests/foreshadowing-workbench.spec.ts
tests/author-tools.spec.ts
tests/longform-phase2.spec.ts
tests/navigation-convergence.spec.ts
tests/review-annotations.spec.ts
tests/writing-preferences.spec.ts
tests/world-state-layout.spec.ts
tests/story-workbench.spec.ts
```

浏览器失败记录包含旧导航/设置控件定位、卷纲准备状态文案、目录阅读位置、细纲及关系页操作，以及候选稿审查/精修请求和面板定位。部分期望仍引用已调整的界面文字；候选稿请求来源和页面行为差异仍需逐项检查，不能将 18 项都归为测试问题或时序抖动。

本次没有修改产品代码或放宽测试以把同步分支标成通过。完整日志、失败 trace 和错误页面快照保留在隔离工作区/本地交付记录，不随源码公开真实项目材料。

## 交付边界

此分支是供审查的本地源码同步，保持 Draft，不自动合并。合并前须处理浏览器失败并完成必要复审。回滚使用本分支对应提交，不对原小说、项目数据或原工作区执行重置。
