# Issue #48：普通生成 delta 语义复核最小修复

日期：2026-11-01。基线：`e4b49ed86469780c6871d5971cbb58144e41460f`。关联 [Issue #48](https://github.com/zj3983/novelflow-engine/issues/48)。本 PR 只处理已经复现的普通生成审核顺序缺口，保持 Draft，不自动合并或关闭 issue。

## 失败原因与修复

原流程在 Writer 结束后先审正文，再由 FactExtractor 产生 delta。确定性提取器能把“林照没有获得铜钱”“打算获得铜钱”“梦见获得铜钱”提成库存 +1，把“没有到达码头”提成到达；引句完整存在于正文，所以确认时的引句门禁不能拒绝这些变化。上游正文审核没有看到提案；若其未报错，候选可以被标为 checked 并错误写入 Canon。

```text
原流程：Writer（包括最终润色）→ 正文 Review → FactExtractor → 候选 → 确认
新流程：Writer（包括最终润色）→ FactExtractor → 正文/Canon/delta 共用一次 Review → 候选 → 确认
```

完整模块流程延后 Writer 内原有正文 Review，提取后复用已经用于候选编辑/修复的 `review_candidate_semantics`。没有新增审核模型调用、重试、状态系统、否定词黑名单或新的提取器。独立 `run_writer` 默认仍按原契约审正文。已有语义协议同时保留 Canon findings 和每项 delta 判定。

- supported 且无其他硬错误：沿用原来的人工确认与事务提交。
- unsupported / uncertain：沿用 `candidate.semantic_*` blocking findings，候选及正文保留，不能接受质量警告强行确认。
- 审核不可用、缺 decisions、错 review/change ID、重复项或畸形 issues：保存 `candidate.semantic_unverified` 硬阻断，语义结果为 unavailable；适配器将 consistency_checked 设为 false，已有候选绑定会标 unchecked。确认与直接 persist 都拒绝，正文不丢失。
- 无状态变化：沿用已有协议的正文审核 fallback。
- 模型能力预检 BLOCKED/SPLIT：继续传播 `ModelPreflightBlockedError`，不保存候选或完成态 Writer/FactExtractor 工作流产物。由于 Review 必须看到 delta，提取现在发生在该 Review 预检之前；默认提取器是确定性、本地、无模型调用的。旧测试“预检失败前从不提取”的顺序断言相应更新，候选/正式状态不落库的断言保留。

语义判定摘要随模块 bundle 进入已有 `quality_report.candidate_semantic_review`，可查看本次 review_id、判定项与状态。未改真实项目、候选、配置、历史快照或 Web 源码。

## 回归设计和结果

`tests/story_core/test_generated_candidate_semantics.py` 使用实际模块流水线、FactExtractor、适配器、候选存储、来源绑定、确认事务及 Canon 落盘。仅 Director/Writer/Review 模型响应使用固定 runtime；没有复制提取/提交业务逻辑，也没有调用真实 provider。

26 个新增检查：

- 否定/打算/梦境库存、否定到达四个已复现负例，以及 uncertain；每例分别检验正常确认与接受质量警告，合计 10 项。
- 缺 decisions、重复项、错 review_id、错 change_id、畸形 issues、模型不可用；分别检查两种确认参数，合计 12 项。另断言直接 persist 也不能绕过，并逐字保留正文。
- 实际获得、实际到达两个正例，可正常确认并写入正确 Canon；审核仅调用一次，提示词包含真实提取的拟变更。
- BLOCKED/SPLIT 两个预检负例，不产生候选或正式章节。

所有拒绝路径都检查：候选仍 pending、正文可读、没有正式章节、current_chapter 仍为 0、Canon 库存/位置不变、没有新连续性快照、原有合成项目 JSON 字节不变。

同一份新增回归放到未修复基线执行：**24 failed / 2 passed，4.30 秒**。20 项在预期拒绝处报 `DID NOT RAISE`；两个正例已能提交但审核提示词没有 delta，另两个不可用检查缺失语义结果；两个原有预检传播行为通过。

首轮定向修复回归：79 passed，24.71 秒。完整 Python 初跑：**5919 passed、8 skipped、1 failed，690.78 秒**；唯一失败是 `test_automatic_prose_revision.py` 对旧“Review 先于提取”的顺序断言及其替换旧审核函数的 mock。只更新该用例，使其通过真实审核入口验证最终润色正文→提取→审核的顺序。生产代码未因此调整。修正后六组相关回归：**96 passed，18.63 秒**，包含全部 26 项新增回归和该自动润色顺序检查。没有在本机重新跑第二遍完整 Python；远端 CI 的完整结果单独记录，不把定向通过冒充一次全量通过。

初跑的 32 个 warning 包括 JUnit xunit2 与既有 `record_property` 不兼容的 30 个提示，以及既有 Starlette/httpx 弃用提示和 cover-provider 测试替身的临时文件析构提示，未修改这些无关代码。未在本机运行 Web build/browser；本次没有 Web 改动。原工作区已有 161 个受保护源码文件哈希复核无变化。

复现命令：

```powershell
$env:PYTHONUTF8='1'
D:\xiaoshuofish-flow-test\.venv\Scripts\python.exe -m pytest -q tests/story_core/test_generated_candidate_semantics.py tests/story_core/test_modular_pipeline_e2e.py tests/story_core/test_candidate_semantics.py tests/story_core/test_modular_bundle_adapter.py tests/story_core/test_modular_main_flow.py
D:\xiaoshuofish-flow-test\.venv\Scripts\python.exe -m pytest -q tests/story_core/test_automatic_prose_revision.py tests/story_core/test_generated_candidate_semantics.py tests/story_core/test_modular_pipeline_e2e.py tests/story_core/test_candidate_semantics.py tests/story_core/test_modular_bundle_adapter.py tests/story_core/test_modular_main_flow.py
D:\xiaoshuofish-flow-test\.venv\Scripts\python.exe -m pytest -q
```

这证明真实程序边界能执行受支持/不受支持/未核验响应的处理，不证明模型在真实小说上的语义准确率已经达到 95%。#48 的独立标注与模型质量验收仍待完成，不能因本次门禁修复关闭 issue。

## 回滚

撤回本 PR 三个生产文件和相关测试/本文档即可恢复原调用顺序。没有数据迁移或新持久化格式；回滚不触碰小说、Canon、历史项目或模型配置。回滚会重新开放这次已证实的审核覆盖缺口。
