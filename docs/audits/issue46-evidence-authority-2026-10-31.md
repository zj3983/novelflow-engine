# Issue #46：Canon 证据权威性最小修复

基线：`origin/main` 的 `9aa67dc2`。本次从主线单独提取修复，不依赖本地写作工作区的其他改动。

## 复现与原因

现有快照会展示调用方传入的上下文事实，但一致性审查把这些条目的索引与来源也加入权威证据集合。错误的 Writer/Director 摘要因此可以触发硬阻断。另有两处已复现问题：有效来源 ID 可以掩盖不存在的显式引文；模型返回的 `blocking=false` 会因证据匹配被升级。

修复在快照投影处区分 `authority=confirmed/context`，保留调用方原始来源为 `context_origin`，上下文继续可见但不进入阻断证据集合。已确认快照中的旧事实即使来源字符串为 `writer_context`，仍保留权威性。显式引文须自身匹配快照证据，警告保持警告。程序硬门禁及 Writer 策略不变，v1 快照仅增加字段，不迁移持久化数据。

## 当前验证

15 个合成场景各以原始、反转上下文顺序运行，共 30 个决策；另外覆盖旧来源兼容。相同 fixture 在修复前后重新执行，JUnit 记录来源、快照版本、章界及决策。

| 指标 | 主线 | 修复后 |
| --- | ---: | ---: |
| 合成决策正确 | 16/30 | 30/30 |
| 非权威证据误阻断 | 12/20 | 0/20 |
| 未来证据触发阻断 | 0 | 0 |

测试还断言快照不包含未来事实、审查不修改传入快照。这里的两种顺序是同一组场景的扰动测试，不能计作 30 个独立人工 gold 样本。

- 原有快照与一致性基线：28 passed。
- 新 fixture 修复前：14 failed、17 passed；修复后：31 passed。
- Canon、事实审查和质量门禁扩展回归：170 passed。
- `git diff --check` 通过。

复现：

```powershell
uv run --frozen pytest -q tests/story_core/test_canon_evidence_authority.py tests/story_core/test_canon_review_snapshot.py tests/story_core/test_modular_consistency_agent.py -o junit_family=legacy --junitxml=after.xml
uv run --frozen python scripts/summarize_canon_evidence_audit.py before.xml after.xml --output metrics.json
```

`before.xml` 需在原主线源码上运行同一版 fixture 取得。指标脚本仅比较确定性 fixture，不调用模型。

## 剩余验收与回滚

本次未调用真实 provider、未读取或修改真实小说、未修改运行配置。合成决策指标不是关键事实引用准确率，不能宣称真实准确率达到 98%。10 月 30 日新增的五类冲突识别、80 例独立人工 gold、分类/升级模型对照及真实用量延迟尚未完成，Issue 保持开放。

Draft PR 不自动合并。回滚只需撤回本 PR 的源码、fixture、指标脚本及本文档，不回滚项目、Canon 或小说数据。
