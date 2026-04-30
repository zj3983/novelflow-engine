---
name: novel-autogrowth
description: Use when the user wants Codex to operate the Novel Autogrowth Engine as a plugin: inspect projects, get writing packets, write/rewrite chapters manually, review chapters, patch worldbuilding, continue generation, or open/test the local dashboard.
---

# Novel Autogrowth Plugin

This skill turns the repository into a Codex-operable webnovel writing plugin.
The backend remains the source of truth. Codex should use MCP tools first, then fall back to the CLI if the MCP server is unavailable.

## Project

Default repository root:

```powershell
D:\xiaoshuofish\.worktrees\novel-autogrowth-engine
```

CLI entry:

```powershell
python D:\xiaoshuofish\.worktrees\novel-autogrowth-engine\scripts\novel_agent.py
```

MCP server:

```powershell
python D:\xiaoshuofish\.worktrees\novel-autogrowth-engine\plugins\novel-autogrowth\mcp\novel_autogrowth_mcp.py
```

Default API:

```text
http://127.0.0.1:8000
```

Default dashboard:

```text
http://localhost:3000
```

## Intent Routing

- "看下现在状态" / "项目状态" -> fetch context and summarize current story, latest chapter, world gaps, and next safe action.
- "审核第 N 章" / "单独审核" -> run `review_chapter` for the requested chapter and return findings first.
- "按你的意见改" / "自动改稿" -> run `revise_chapter` with explicit revision instructions.
- "你来写正文" / "重写第一章" / "AI味太重" -> fetch `get_writing_packet`, write prose in Codex, then submit with `submit_manual_draft`.
- "改这一段" / "局部改稿" / "第 N 段不对" -> rewrite only the requested segment, then submit with `submit_segment_draft`.
- "继续生成" -> run bounded automation with the local/self reviewer.
- "世界不真实" / "规则不对" / "NPC 不合理" -> fetch world, translate feedback into concrete constraints, patch world/rulebook before generating.
- "打开工作台" / "测试页面" -> use the browser plugin against `http://localhost:3000`.

## Commands

Preferred MCP tools:

- `doctor`: check API health and visible projects.
- `get_context`: inspect active project, recent chapters, world gaps, and next actions.
- `get_world`: inspect world bible, rulebook, character profiles, and active story metadata.
- `get_writing_packet`: fetch the compact writing packet before Codex writes prose directly.
- `review_chapter`: review one chapter through the local/self reviewer.
- `revise_chapter`: revise one chapter with explicit editorial instructions.
- `submit_manual_draft`: submit a Codex-written full chapter and receive the updated review payload.
- `submit_segment_draft`: replace one zero-based chapter segment with a Codex-written local rewrite.
- `patch_world`: patch concrete worldbuilding constraints, current focus, or profiles.
- `continue_generation`: generate the next chapter and fetch its local/self review.
- `dashboard`: return the local dashboard URL.

CLI fallback commands:

Fetch context before creative advice:

```powershell
python D:\xiaoshuofish\.worktrees\novel-autogrowth-engine\scripts\novel_agent.py context <project_id> --recent-chapters 3 --include-body
```

Review one chapter:

```powershell
python D:\xiaoshuofish\.worktrees\novel-autogrowth-engine\scripts\novel_agent.py review <project_id> --chapter-number 1 --include-body
```

Fetch the Codex writing packet:

```powershell
python D:\xiaoshuofish\.worktrees\novel-autogrowth-engine\scripts\novel_agent.py writing-packet <project_id> --chapter-number 1
```

Submit a Codex/manual full chapter:

```powershell
python D:\xiaoshuofish\.worktrees\novel-autogrowth-engine\scripts\novel_agent.py manual-draft <project_id> --chapter-number 1 --body-file .\chapter_exports\manual_ch1.txt --instruction "Codex manual rewrite" --include-body
```

Submit one rewritten segment:

```powershell
python D:\xiaoshuofish\.worktrees\novel-autogrowth-engine\scripts\novel_agent.py manual-segment-draft <project_id> --chapter-number 1 --segment-index 3 --body-file .\chapter_exports\segment_3.txt --instruction "Local paragraph rewrite" --include-body
```

Patch worldbuilding:

```powershell
python D:\xiaoshuofish\.worktrees\novel-autogrowth-engine\scripts\novel_agent.py world patch <project_id> --author-constraint "..."
```

Run generate-review-revise automation:

```powershell
python D:\xiaoshuofish\.worktrees\novel-autogrowth-engine\scripts\novel_agent.py auto <project_id> --intent "continue one chapter" --review-provider local --max-revisions 1 --include-body
```

## Review Policy

When reviewing, Codex should act like a webnovel editor and report:

- Must-fix continuity bugs: profession, equipment, currency, inventory, NPC knowledge, timeline, previous chapter hooks.
- Genre rule fit: online-game conventions, beginner village logic, class choice, player names, market behavior, guild behavior.
- Webnovel structure: hook, goal, obstacle, action, payoff, cost, cliffhanger.
- World believability: institutions, economy, NPC incentives, player ecosystem, information flow.
- Revision plan: concrete instructions that can be passed to `revise_chapter` or used by Codex manual writing.

Findings must be actionable and ordered by severity.

## Manual Writing Policy

When the user asks Codex to write or rewrite prose directly:

- Fetch `get_writing_packet` first; do not write from memory alone.
- Treat world state, role panel, inventory, equipment, currency, NPC permissions, and previous hooks as hard constraints.
- Prefer full manual writing when model prose has structural problems; prefer segment rewrite when only one paragraph/scene is wrong.
- After `submit_manual_draft` or `submit_segment_draft`, immediately run `review_chapter` and report remaining must-fix issues.
- Keep generation/revision bounded; do not keep auto-rewriting loops going without user confirmation.

## Guardrails

- Do not mutate old chapters directly unless the user explicitly asks to replace that chapter.
- Do not continue generation when the latest chapter has unresolved must-fix continuity bugs.
- Do not patch vague taste feedback directly; convert it into concrete world rules or author constraints.
- Keep automation bounded with `--max-revisions 1` unless the user explicitly asks for more.
- The local/self reviewer is the default. OpenClaw is compatibility only, not the normal path.
