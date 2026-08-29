---
name: novel-autogrowth
description: Use when 用户要操作 Novel Autogrowth Engine，包括查看项目、生成或重写章节、审稿、修改设定、检查写作包或打开本地工作台。
---

# Novel Autogrowth

把本地项目数据视为事实来源。先取当前项目的上下文，再执行生成、改稿或设定修改；不要凭聊天记忆补写项目事实。

## 入口

- 项目根目录：`D:\xiaoshuofish-flow-test`
- API：`http://127.0.0.1:8000`
- 工作台：`http://localhost:3000`
- CLI：`python D:\xiaoshuofish-flow-test\scripts\novel_agent.py`

优先使用插件 MCP；不可用时使用 CLI，最后才直接调用 API。

## 工作原则

1. 写作、续写、改稿前先读取写作包，确认目标章节和历史快照。
2. 只读取当前项目已启用的题材模块、风格模块和 Skill；未启用的内容不得进入提示词。
3. 大纲负责本章目标和边界，导演负责具体场景链，写手只把场景链写成正文，审稿只指出必须修的问题。
4. 世界观、角色卡、关系、伏笔和连续性账本各管各的数据，不把同一事实复制成多条作者约束。
5. 历史章节重写必须使用该章开始前的快照，不能使用后续章节形成的等级、关系、财富或记忆。
6. 用户对某本书的反馈先落到该项目或对应题材模块，不自动写入通用 Skill。

## 生成与改稿

- 生成前检查写作包里实际读取了哪些模块，并确认题材没有串入。
- 导演产物必须是可执行的连续场景，不用总结代替剧情。
- 写手依据动作、反应、对话和场景变化落笔，不复述规则、面板含义或后台因果。
- 对话按角色关系、情绪和当下目的说完整；角色卡没有要求寡言时，不默认压成短句。
- 审稿优先处理连续性硬伤、剧情不成立、人物失真和明显不自然的中文；一次只给少量可执行修改。
- 默认最多自动改一轮。仍不合格时保留报告和候选稿，不反复覆盖正文。

## 常用 CLI

```powershell
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py context <project_id> --recent-chapters 3 --include-body
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py writing-packet <project_id> --chapter-number 1
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py review <project_id> --chapter-number 1 --include-body
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py revise <project_id> --chapter-number 1 --instruction "..." --include-body
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py world get <project_id>
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py world patch <project_id> --author-constraint "..."
python D:\xiaoshuofish-flow-test\scripts\novel_agent.py auto <project_id> --intent "continue one chapter" --review-provider local --max-revisions 1 --include-body
```

## 防护

- 未经用户明确要求，不覆盖历史章节。
- 模糊的口味反馈不能直接变成全局硬规则，应先改成具体、可验证的项目要求。
- 题材常识只来自当前题材模块；通用写作层不保存网游、玄幻或其他单一题材规则。
- 写作流程展示的是各阶段读取项和产物，不用易失的运行日志代替。
