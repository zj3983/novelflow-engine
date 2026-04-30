# Codex Plugin Architecture

Novel Autogrowth should be operated as a Codex plugin, not only as a web app.
The web dashboard is the visual workstation; the plugin is the control layer that lets Codex inspect, review, revise, and steer the project from conversation.

## Target Shape

```text
User conversation
  -> lightweight Codex controller plugin
  -> MCP tools
  -> FastAPI backend
  -> story_core agents and persistent store
  -> web dashboard reflects the updated state
```

This mirrors command-oriented webnovel tools such as `webnovel-writer`: the user can ask for writing operations in natural language, while the plugin maps those requests to stable project commands.

The engine itself should remain an independent application. The plugin is a remote control, not a copy of the whole project.

## Responsibilities

### Codex Plugin

- Understand user intent from conversation.
- Fetch current project context before giving writing advice.
- Review chapters with an editor mindset.
- Convert taste feedback into concrete world rules or author constraints.
- Call generation, review, revise, rollback, and world patch commands.
- Summarize results back to the user.

### Backend

- Own project state, stories, chapters, world bible, character dossiers, and memory.
- Run generation and revision through configured model runtime.
- Persist all accepted changes.
- Expose safe APIs for plugin and dashboard.

### Web Dashboard

- Show current world, chapter history, simulation state, and review reports.
- Let the user trigger common operations manually.
- Avoid becoming the only way to operate the writing system.

## Plugin Tools

The preferred installed controller plugin lives outside the repository:

```text
C:\Users\Administrator\.codex\plugins\novel-autogrowth
```

It exposes a stdio MCP server at:

```text
C:\Users\Administrator\.codex\plugins\novel-autogrowth\mcp\server.py
```

This lightweight server talks to the engine through HTTP only. It does not import repository code, so it can survive project refactors as long as the public API remains stable.

The repository also keeps a development copy at:

```text
plugins/novel-autogrowth/mcp/novel_autogrowth_mcp.py
```

Tool set:

```text
doctor
get_context
get_world
get_writing_packet
review_chapter
revise_chapter
submit_manual_draft
submit_segment_draft
patch_world
continue_generation
dashboard
```

The MCP tools are thin wrappers over backend HTTP APIs. This keeps one source of truth while giving Codex typed operations instead of fragile shell parsing.

## CLI Fallback

The CLI remains available when MCP is not installed or the plugin server cannot start:

```powershell
python scripts\novel_agent.py context <project_id> --recent-chapters 3 --include-body
python scripts\novel_agent.py review <project_id> --chapter-number 1 --include-body
python scripts\novel_agent.py writing-packet <project_id> --chapter-number 1
python scripts\novel_agent.py manual-draft <project_id> --chapter-number 1 --body-file .\chapter_exports\manual_ch1.txt --include-body
python scripts\novel_agent.py manual-segment-draft <project_id> --chapter-number 1 --segment-index 3 --body-file .\chapter_exports\segment_3.txt --include-body
python scripts\novel_agent.py revise <project_id> --chapter-number 1 --instruction "..." --include-body
python scripts\novel_agent.py world patch <project_id> --author-constraint "..."
python scripts\novel_agent.py auto <project_id> --intent "continue one chapter" --review-provider local --max-revisions 1 --include-body
```

## Conversation Flow

```text
"看下现在状态"
  -> get_context
  -> summarize latest chapter, world gaps, next safe action

"你亲自审第一章"
  -> get_context + review_chapter
  -> Codex adds editorial judgment
  -> return must-fix / optional / revision plan

"按你的意见改"
  -> revise_chapter with the concrete revision plan
  -> review_chapter again

"你来写正文 / 重写第一章"
  -> get_writing_packet
  -> Codex writes the prose directly
  -> submit_manual_draft
  -> review_chapter again

"局部改这一段"
  -> get_context + review_chapter
  -> Codex rewrites only the requested segment
  -> submit_segment_draft
  -> review_chapter again

"继续生成"
  -> continue_generation
  -> get_context
  -> report chapter result and remaining risks
```

## Current Plugin Files

User-level controller plugin:

- `C:\Users\Administrator\.codex\plugins\novel-autogrowth\.codex-plugin\plugin.json`
- `C:\Users\Administrator\.codex\plugins\novel-autogrowth\.mcp.json`
- `C:\Users\Administrator\.codex\plugins\novel-autogrowth\mcp\server.py`
- `C:\Users\Administrator\.codex\plugins\novel-autogrowth\skills\novel-autogrowth\SKILL.md`

Repository development copy:

- `plugins/novel-autogrowth/.codex-plugin/plugin.json`
- `plugins/novel-autogrowth/.mcp.json`
- `plugins/novel-autogrowth/mcp/novel_autogrowth_mcp.py`
- `plugins/novel-autogrowth/skills/novel-autogrowth/SKILL.md`
- `.agents/plugins/marketplace.json`

## Next Milestones

1. Confirm the Codex host loads `[mcp_servers.novel-autogrowth]` after an app restart.
2. Add database/model/runtime details to the `doctor` response.
3. Add a `review --codex-package` mode that emits a compact editor packet for high-quality conversational review.
4. Add richer segment IDs so local rewrites can target named scenes, not only zero-based paragraphs.
5. Add installation docs for using the controller plugin on another machine.
