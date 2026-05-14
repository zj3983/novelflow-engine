# Novel Autogrowth Pluginization Roadmap

This project is being moved from a web-app-first shape toward a plugin-first shape.

## Target Shape

The writing workflow should be operable from Codex/Claude-style plugin commands without requiring the browser as the main control surface.

Primary flow:

1. Plugin command or MCP tool receives the user intent.
2. `scripts/novel_agent.py` calls the writing engine or compatibility API.
3. Project state is stored as files under `.story-system/`, `.webnovel/`, and `chapters/`.
4. The web dashboard becomes an optional viewer/editor, not the source of truth.

## Current Phase

Phase 1 is now focused on making the existing API-backed system plugin-operable:

- `doctor` checks backend health and visible projects.
- `start-api` starts the FastAPI backend in the background.
- `dashboard` returns the local dashboard URL.
- `export-project` writes an API project into plugin-friendly files.
- The `novel-autogrowth` skill no longer contains machine-specific worktree paths.

Phase 2 adds the first file-backed read model:

- `packages.story_core.file_project_store.FileProjectStore` reads `.story-system/`, `.webnovel/`, and `chapters/`.
- `novel-agent file summary <project_dir>` summarizes exported projects without the API.
- `novel-agent file review <project_dir>` reads stored chapter review payloads without the API.
- `novel-agent file query <project_dir> <keyword>` searches exported settings, state, JSON chapters, and Markdown chapters.
- `novel-agent file writing-packet <project_dir>` builds a compact writing packet from exported files.

Phase 3 exposes those file-backed reads through MCP:

- `file_summary`
- `file_review`
- `file_query`
- `file_writing_packet`

Phase 4 tightens the prose boundary:

- API writing packets and file writing packets now include a `prose_renderer` contract.
- `chinese-novelist` is treated as a downstream prose renderer only.
- World simulation, continuity decisions, economy rules, and review verdicts stay in Novel Autogrowth before prose is written.
- Renderer input is limited to compact packet fields so raw project dumps and reviewer internals do not leak into chapter body text.

Phase 5 starts the file-backed write loop:

- `FileProjectStore.write_chapter` writes a new chapter JSON, Markdown body, review payload, state update, and commit record.
- `FileProjectStore.rewrite_chapter` replaces an existing chapter body while preserving surrounding chapter metadata where possible.
- `FileProjectStore.commit` records a project manifest under `.story-system/commits/` without touching Git.
- CLI and MCP expose `file write`, `file rewrite`, and `file commit`.

Phase 6 starts the API-free generation loop:

- `FileProjectStore.generate_next_chapter` restores `StoryState` from `.webnovel/state.json`.
- The existing `StoryEngine` generates the next chapter in-process, without FastAPI or SQLite.
- The resulting bundle is persisted through the same file-backed chapter, review, state, and commit path.
- CLI and MCP expose `file generate-next` / `file_generate_next`.

## Exported Project Layout

`novel-agent export-project <project_id>` writes:

```text
<output>/
  .story-system/
    MASTER_SETTING.json
    chapters/
      0001.json
    reviews/
      0001.json
    commits/
      latest_export.json
  .webnovel/
    project.json
    state.json
  chapters/
    0001-章节名.md
```

For now this is an export/read-write model with offline summary, review, query, writing packet, manual write, manual rewrite, file commit, and in-process file-backed next-chapter generation support.

## Next Phase

1. Add file-backed `init` for creating a new project directory without SQLite.
2. Move the dashboard to read the file store directly when a project directory is supplied.
3. Keep the API as compatibility and dashboard support until the file path is complete.
