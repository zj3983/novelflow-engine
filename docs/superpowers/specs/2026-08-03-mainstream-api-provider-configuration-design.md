# 主流 API 供应商配置重构设计

日期：2026-08-03

## 目标

把当前 `codexcli` 与单一 `openai` 槽位重构为“供应商账户 + 写作阶段绑定”。每个供应商独立保存密钥、地址和模型，剧情规划与正文写作可以分别选择供应商。正文后的状态提取继续保留，但不再暴露单独的“记忆回写模型”配置。

本次重构解决以下问题：

- DeepSeek、Kimi、通义等配置共用一个槽位，切换后名称、地址、模型和密钥容易串用。
- 页面显示“OpenAI 兼容 API”，无法直接看出实际调用的供应商。
- `memory` 作为独立模型配置增加理解和维护成本，但其工作本质属于结构化规划与状态提取。
- Claude、Gemini 不能可靠地假装成 OpenAI 兼容接口，需要原生协议适配。

## 范围

首批内置供应商：

- OpenAI
- DeepSeek
- Moonshot / Kimi
- 阿里云百炼 / 通义千问
- 智谱 GLM
- 火山方舟 / 豆包
- MiniMax
- 硅基流动
- OpenRouter
- xAI
- Anthropic / Claude
- Google Gemini
- Ollama
- Codex CLI
- 自定义 OpenAI 兼容 API

供应商目录采用数据驱动设计。新增一个兼容供应商时，只增加预设数据；只有出现新协议时才增加调用适配器。

本次不实现供应商账号云同步、用量计费统计、自动购买额度和模型价格实时抓取。

## 核心模型

### 供应商目录

代码内维护不可写的供应商预设，包含：

- `id`：稳定标识，例如 `deepseek`、`anthropic`。
- `name`：页面名称。
- `protocol`：`openai_compatible`、`anthropic`、`gemini`、`codex_cli`。
- `default_base_url`：默认 API 地址。
- `default_models`：建议模型列表，区分规划与写作用途。
- `base_url_editable`：是否允许修改地址。
- `requires_api_key`：是否需要密钥。
- `help_text`：简短配置说明。

模型预设只用于创建和选择，不强制覆盖用户手工填写的模型名称。

### 供应商账户

运行时配置保存为供应商账户映射。每个账户独立包含：

- `api_key`
- `base_url`
- `models`
- `custom_models`
- `codex_command`（仅 Codex CLI）

API 密钥继续使用 Windows DPAPI 加密落盘。读取接口默认返回掩码；用户主动点击显示时，使用现有密钥揭示接口。任何日志、连接测试错误和写作调用记录都不得包含明文密钥。

### 阶段绑定

只保留两个用户可配置阶段：

- `planner`：剧情规划、大纲、世界观补全、章节规划、结构化审稿输入、正文后的状态与连续性提取。
- `writer`：正文生成、扩写、压缩、改稿。

每个阶段保存：

- `provider_id`
- `model`

两个阶段可以选择不同供应商。删除公开配置中的 `memory` 阶段；旧代码请求 `memory` 时在兼容期内解析为 `planner`，迁移完成后内部调用直接改用 `planner`。

## 调用架构

新增统一模型网关，输入为供应商协议、地址、密钥、模型、消息、JSON 模式和超时，输出统一的文本结果与标准错误。

网关包含四个适配器：

1. `OpenAICompatibleAdapter`：处理 OpenAI、DeepSeek、Kimi、通义、GLM、豆包、MiniMax、硅基流动、OpenRouter、xAI、Ollama和自定义兼容接口。
2. `AnthropicAdapter`：将统一消息转换为 Anthropic Messages API，并处理 system、max tokens 和 JSON 输出约束。
3. `GeminiAdapter`：将统一消息转换为 Gemini generateContent API，并处理 system instruction、generation config 和 JSON MIME 类型。
4. `CodexCLIAdapter`：保留现有 Codex CLI 调用方式。

章节流程不再直接判断具体供应商，只按阶段解析绑定，再交给统一网关。连接测试也调用同一个适配器，避免“测试能通、正文调用却走另一套代码”。

## 页面设计

配置页分为三个未嵌套区域：

### 写作阶段

显示两行：剧情规划、正文写作。每行选择供应商和模型，并显示当前连接状态。页面明确说明正文状态提取跟随剧情规划配置。

### 供应商账户

显示内置供应商列表。每个供应商显示是否已配置、协议和当前地址。选中后编辑该供应商自己的密钥、地址和自定义模型。提供单个“测试连接”按钮。

未配置的供应商仍可查看预设，但不能被阶段绑定保存为有效配置。Codex CLI 不显示 API 密钥字段。自定义兼容接口要求填写名称、地址和至少一个模型。

### 封面图片

保持现有独立配置，不与文本模型供应商混合。本次仅适配新的通用密钥组件，不改变图片生成协议。

## 数据迁移

加载旧配置时执行一次幂等迁移：

1. `codexcli` 配置迁移到 `providers.codexcli`。
2. 旧 `openai` 槽位根据 `base_url` 识别供应商。`api.deepseek.com` 迁移到 DeepSeek；百炼、Moonshot、OpenRouter 等已知域名迁移到对应供应商；无法识别时迁移到自定义 OpenAI 兼容账户。
3. 旧全局 `provider` 同时绑定到 `planner` 和 `writer`。
4. 旧 `planner`、`writer` 模型分别写入阶段绑定。
5. 旧 `memory` 模型不再成为独立绑定；如果规划模型为空，才用旧 `memory` 模型补充规划模型，否则保留规划模型。
6. 迁移写入新结构前保留原配置备份；再次加载新结构不得重复迁移或覆盖用户修改。

当前已保存的 DeepSeek 密钥必须原样迁移并继续保持 DPAPI 加密。

## 错误处理

统一错误分类：

- `missing_api_key`
- `invalid_base_url`
- `unsupported_protocol`
- `authentication_failed`
- `model_not_found`
- `rate_limited`
- `request_timed_out`
- `provider_unavailable`
- `invalid_provider_response`

页面显示中文解释和供应商、阶段、模型，但不显示密钥或完整响应正文。生成任务记录实际使用的供应商、协议和模型，便于排查配置串用。

如果规划和写作分别使用不同供应商，一个阶段失败时不得静默回退到另一个阶段的供应商。只有显式配置的回退策略才允许跨供应商重试；本次默认不启用自动回退。

## 兼容与清理

- 保留旧配置读取器一个迁移周期，写入只使用新格式。
- 删除页面和公开 API 中的 `memory` 模型字段。
- 正文状态提取改用 `planner` 阶段绑定。
- 删除无调用方的旧 `MemoryAgent` 实现及对应过期测试，但保留 `post_draft_memory`、状态标准化和账本回写逻辑。
- 现有项目内的历史 `agent_runtime.memory` 仅作为运行记录兼容读取，不再决定模型配置。

## 测试策略

后端单元测试覆盖：

- 供应商预设完整性和稳定 ID。
- 每种协议的请求转换与响应解析。
- 两阶段分别选择不同供应商。
- `memory` 内部请求解析到 `planner`。
- 密钥加密、掩码、揭示和日志脱敏。
- 旧 DeepSeek、Kimi、Codex CLI、自定义地址的迁移。
- 迁移幂等性和未知供应商地址处理。
- 连接测试与正式调用共用适配器。

API 测试覆盖读取、保存、单供应商连接测试、非法绑定、缺失密钥和原生协议错误映射。

前端测试覆盖供应商独立编辑、阶段分别绑定、模型预设与自定义模型、密钥显示隐藏、保存后重载、未配置供应商阻止保存，以及页面不再出现“记忆回写模型”。

最后执行运行时配置单元测试、API 路由测试、配置页 Playwright 测试、前端类型检查和生产构建。

## 验收标准

- DeepSeek 与 Kimi 的密钥、地址和模型互不覆盖。
- 剧情规划和正文写作可以选择不同供应商。
- Claude 与 Gemini 使用原生协议完成连接测试和模型调用。
- 页面能明确看到每个阶段实际使用的供应商和模型。
- 配置页不再显示独立的记忆回写模型。
- 正文后的摘要、人物、伏笔和账本更新仍正常产生。
- 旧 DeepSeek 配置无需重新输入密钥即可继续使用。
- 配置和生成日志中不出现明文 API 密钥。
