# 长程 HTTP 复验：2026-09-30

本次在 PR #45 源码 HEAD `748fe6dff02da56139b8d1f31e515365e86397c6` 上重新执行 60 章离线流程，覆盖阶段二完成后的规划与写作链路。执行使用专用 FastAPI 离线入口、进程内固定模型回答和全新隔离目录，没有调用真实模型、外部服务或已有小说数据。

## 环境与结果

- 隔离数据根目录：`D:\CodexData\longform-stage4-20260930-e5f2ad6188f44dc09ae0d709bdffb108`
- 合成作品：`file:p-fa9b9eff699643ff94f8d95b5dca7cc4`，初始确认章节数为 0。
- 从建书、方向选择、两卷规划准备与采纳开始，逐章生成、检查并人工确认到第 60 章；实际经过第 50 → 51 章。
- 第 3 章手工改稿、重新检查后确认；第 4 章 AI 改稿、重新检查后确认。
- 第 17 章首次生成失败，显式重试后成功；第 18 章检查失败时确认被拒绝，候选正文保留，重新检查后成功确认。
- 每章旧确认令牌重放均被拒绝。结束时逐章回读 60 章正文，SHA-256 全部与确认时一致。
- 事件日志共 75 条；完整记录见 [60 章 HTTP 事件](evidence/http-60-chapters-2026-09-30.jsonl)。

服务使用 `NOVELFLOW_LONGFORM_SYNTHETIC=1` 保护入口，覆写文件项目、运行配置、能力缓存、数据库、小说类型和提示模板路径到隔离目录；合成服务拒绝外网连接与外部命令，未启用 Uvicorn workers/reload。该结果证明当前 HTTP 与存储链的流程、恢复和正文保护；不代表真实模型的文本质量或连续性。

复验命令：

```powershell
uv run python scripts/verify_longform_offline.py --url http://127.0.0.1:8532 --chapters 60 --output '<隔离目录>/http-60-evidence.jsonl'
```
