---
name: novel-autogrowth
description: Use when 用户要让 Codex 操作 Novel Autogrowth Engine：查看项目状态、获取写作包、手写或重写章节、审稿、修补世界观、继续生成，或打开/测试本地工作台。
---

# Novel Autogrowth 插件

这个 skill 用来操作本地 Novel Autogrowth Engine。后端和文件项目是事实来源；Codex 先用 MCP 工具，MCP 不可用时再走 CLI。

## 项目位置

默认仓库根目录：

```powershell
D:\xiaoshuofish-flow-test
```

CLI 入口：

```powershell
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py
```

MCP 服务：

```powershell
python D:\xiaoshuofish-flow-test\plugins\novel-autogrowth\mcp\novel_autogrowth_mcp.py
```

默认 API：

```text
http://127.0.0.1:8000
```

默认工作台：

```text
http://localhost:3000
```

## 意图路由

- “看下现在状态 / 项目状态”：获取 context，概括当前故事、最新章节、世界漏洞和下一步安全动作。
- “审核第 N 章 / 单独审核”：运行 `review_chapter`，按严重程度先列问题。
- “按你的意见改 / 自动改稿”：带明确修订指令运行 `revise_chapter`。
- “你来写正文 / 重写第一章 / AI 味太重”：先取 `get_writing_packet`，Codex 手写正文，再用 `submit_manual_draft` 提交。
- “改这一段 / 局部改稿 / 第 N 段不对”：只重写指定段落或场景，再用 `submit_segment_draft` 提交。
- “继续生成”：运行有边界的生成-审稿-修订流程。
- “世界不真实 / 规则不对 / NPC 不合理”：先取 world，把反馈转成具体世界规则或作者约束，再 patch world。
- “打开工作台 / 测试页面”：用浏览器打开 `http://localhost:3000`。

## 优先工具

优先使用 MCP：

- `doctor`：检查 API 健康和可见项目。
- `get_context`：查看项目上下文、最近章节、世界漏洞和建议动作。
- `get_world`：查看世界设定、规则书、角色档案和当前故事元数据。
- `get_writing_packet`：在 Codex 手写正文前获取紧凑写作包。
- `review_chapter`：用本地/自审器审核单章。
- `revise_chapter`：按明确编辑指令修订单章。
- `submit_manual_draft`：提交 Codex 手写的完整章节。
- `submit_segment_draft`：替换某个从 0 开始编号的章节段落。
- `patch_world`：修补世界观约束、当前焦点或角色档案。
- `continue_generation`：生成下一章并返回本地/自审结果。
- `dashboard`：返回本地工作台 URL。

CLI 兜底：

```powershell
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py context <project_id> --recent-chapters 3 --include-body
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py review <project_id> --chapter-number 1 --include-body
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py writing-packet <project_id> --chapter-number 1
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py manual-draft <project_id> --chapter-number 1 --body-file .\chapter_exports\manual_ch1.txt --instruction "Codex manual rewrite" --include-body
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py manual-segment-draft <project_id> --chapter-number 1 --segment-index 3 --body-file .\chapter_exports\segment_3.txt --instruction "Local paragraph rewrite" --include-body
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py revise <project_id> --chapter-number 1 --instruction "..." --include-body
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py world patch <project_id> --author-constraint "..."
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py auto <project_id> --intent "continue one chapter" --review-provider local --max-revisions 1 --include-body
```

## 核心流程

1. 创作、审稿或建议前，先获取项目 context。
2. 如果用户指出世界、类型、连续性问题，先转成具体规则或约束，再继续生成。
3. 已知有风险时，继续生成前先审最新章节。
4. 修订必须带明确指令；修完后再审一次。
5. 自动化默认有边界，`--max-revisions 1`，除非用户明确要求更多轮。
6. OpenClaw 只作为兼容路径；正常路径是本地/Codex/自审。

## 审稿规则

审稿时先给可执行问题：

- 连续性硬伤：职业、装备、货币、背包、NPC 知识、时间线、上一章钩子。
- 网游类型规则：新手村逻辑、职业选择、玩家命名、市场行为、公会行为。
- 网文结构：钩子、目标、阻碍、行动、反馈、成本、章末悬念。
- 世界可信度：制度、经济、NPC 动机、玩家生态、信息流。
- 修订方案：能直接传给 `revise_chapter` 或手写正文使用的具体指令。

## 手写正文规则

用户让 Codex 直接写或改正文时：

- 先取 `get_writing_packet`，不要凭记忆写。
- 把世界状态、角色面板、背包、装备、货币、NPC 权限、上一章钩子当硬约束。
- 结构问题严重时优先完整手写；只有单段/单场景问题时用段落替换。
- `submit_manual_draft` 或 `submit_segment_draft` 后，立刻跑 `review_chapter`。
- 不要无限自动改稿；需要多轮时先问用户。

## 防护栏

- 不要直接改历史章节，除非用户明确要求替换那一章。
- 最新章节还有 must-fix 连续性硬伤时，不要继续生成。
- 不要把模糊口味反馈直接写进 world；先转成具体规则或作者约束。
- 默认本地/自审，不把 OpenClaw 当常规路径。
