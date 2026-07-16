# 按供应商拆分真实写作阶段配置

## 目标

配置页只展示实际参与章节生成的模型阶段，模型名称只有一个生效来源。删除不会参与生成的角色 Agent 配置，以及 Codex CLI 隐藏模型覆盖造成的显示误导。

真实写作链固定为：

1. 剧情规划：生成章节意图、人物行动、事件计划和记忆约束。
2. 正文写作：生成正文，并在需要时扩写、风格适配或改稿。
3. 记忆回写：从最终正文提取事实、人物变化、未决线索和账本更新。

## 配置结构

运行时配置按供应商保存，各供应商只包含真实阶段：

```json
{
  "provider": "codexcli",
  "providers": {
    "codexcli": {
      "command": "codex",
      "stages": {
        "planner": { "model": "gpt-5.6-sol" },
        "writer": { "model": "gpt-5.6-sol" },
        "memory": { "model": "gpt-5.6-terra" }
      }
    },
    "openai": {
      "api_key": "",
      "base_url": "",
      "stages": {
        "planner": { "model": "" },
        "writer": { "model": "" },
        "memory": { "model": "" }
      }
    }
  },
  "temperature": 0.7,
  "new_character_policy": "Director review"
}
```

`planner`、`writer`、`memory` 是内部稳定标识；页面分别显示“剧情规划”“正文写作”“记忆回写”。不再暴露 `character_model`、`director_model`、`writer_model`、`memory_model` 和 `global_model` 这组重复字段。

## 生效规则

- Codex CLI 每次调用直接使用当前阶段的 `model`，不再读取 `NOVEL_CODEX_MODEL`，也不再由 `NOVEL_CODEX_USE_PAYLOAD_MODEL` 决定是否采用配置。
- OpenAI 兼容 API 使用当前供应商的连接信息和当前阶段模型。
- 三个阶段允许使用不同模型；CLI 默认规划和正文使用 `gpt-5.6-sol`，记忆使用 `gpt-5.6-terra`。
- 测试连接必须测试选中供应商和对应阶段的真实配置，提示中显示供应商、阶段和模型。
- 项目和章节状态不再复制全局模型配置，只记录运行结果和所用模型快照。

## 状态记录

删除虚假的“四 Agent 一起成功”记录。每个阶段在实际请求完成后单独记录：

- `source`: `llm` 或 `fallback`
- `model`: 实际传给供应商的模型
- `provider`: `codexcli` 或 `openai`
- `last_run_chapter`
- `fallback_reason`

没有执行的阶段不能标记为成功。旧页面中的“角色 Agent”状态删除，人物行动仍由剧情规划阶段生成。

## 旧配置迁移

读取旧 `runtime_config.json` 时执行一次兼容迁移：

- 当前供应商沿用旧 `global.provider`。
- `director_model` 迁移到 `planner.model`。
- `writer_model` 迁移到 `writer.model`。
- `memory_model` 迁移到 `memory.model`。
- 旧值为 `qwen3.6-plus` 且供应商为 Codex CLI 时，迁移为当前各阶段的 5.6 默认值，避免旧的无效展示值重新生效。
- `character_model` 和 `global_model` 不写入新结构。
- 保存新结构后不再输出旧字段；迁移保持幂等。

已有小说中的旧 `agent_settings` 只作为兼容输入，不再决定运行时模型。读取时可保留，后续保存状态时移除无效模型副本，不能影响章节内容、角色卡和连续性数据。

## 页面设计

配置页顶部选择供应商。下面只显示当前供应商需要的连接字段，再显示三个真实阶段的模型控件。每个阶段有独立“测试”按钮和最近一次测试结果。

- Codex CLI 模式使用下拉框，选项来自当前 CLI 模型目录，只展示 `gpt-5.5` 和 `gpt-5.6-*`。
- 低于 GPT-5.5 的模型不进入下拉框。
- 已保存但不在当前可选目录中的模型作为“当前配置”保留，避免页面载入时静默覆盖。
- OpenAI 兼容 API 模式继续使用文本输入，允许不同供应商的自定义模型名。

页面不再出现“全局默认模型”“角色代理模型”等字段。说明文字只解释该阶段负责什么，不展示内部兼容字段或环境变量。

## API 与兼容性

- `GET /runtime-settings` 只返回新结构。
- `PUT /runtime-settings` 只接受新结构，拒绝未知旧字段，避免旧前端把无效配置写回来。
- `/runtime-strategy` 保留非模型策略字段；旧模型字段从响应和请求中移除。
- 章节生成、开书、大纲生成和连接测试统一通过一个阶段配置解析器取供应商与模型。

## 错误处理

- 当前阶段模型为空时阻止保存，并指出具体阶段。
- Codex CLI 命令为空时使用 `codex`。
- OpenAI 模式缺少地址或密钥时，测试和生成返回明确错误，不静默切换供应商。
- 迁移文件损坏时保留原文件并使用默认配置，同时记录可见错误，不覆盖损坏数据。

## 验证

- 单元测试覆盖旧配置迁移、迁移幂等、三个阶段解析和未知字段拒绝。
- Codex CLI 提供器测试确认三个阶段分别把配置模型传给 `codex exec --model`，且环境变量不再覆盖。
- 编排器测试确认只记录实际执行阶段，失败阶段不会把其他阶段标为成功。
- API 测试确认响应中不存在五个旧模型字段。
- 前端测试确认供应商切换、三个阶段字段、保存、测试连接和错误提示。
- CLI 模型目录测试确认只返回 GPT-5.5 及以上选项，并在页面渲染为下拉框。
- 全量 Python 测试、前端构建和相关 Playwright 测试通过后完成。
