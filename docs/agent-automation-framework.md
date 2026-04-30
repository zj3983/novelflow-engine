# Agent Automation Framework

## Goal

Provide a stable automation spine for Novel Autogrowth Engine so Codex can generate, review, revise, and persist the same story state through CLI/API contracts instead of screen state or manual copy-paste.

## Layers

```text
User intent
-> Codex conversation
-> novel-autogrowth skill
-> scripts/novel_agent.py
-> FastAPI story/project endpoints
-> Story Core generation, review, revision
-> frontend workbench display
```

The default reviewer is the built-in Codex/self reviewer exposed by the API. It uses the saved chapter bundle, quality report, genre guardrails, world facts, continuity ledger, and revision prompt to decide whether to approve or revise.

```text
automation-jobs
-> generate chapter
-> local agent review
-> revise latest chapter when needed
-> persist refreshed bundle/ledger
```

OpenClaw remains an optional external reviewer through JSON packages, but it is no longer the default path:

```text
review-package
-> openclaw-review-request/v1
-> OpenClaw reviewer
-> openclaw-review-result/v1
-> apply-review-result
-> agent-revise API
```

## Current CLI Surface

Fetch project context:

```powershell
python scripts\novel_agent.py context <project_id> --recent-chapters 3 --include-body
```

Read world state:

```powershell
python scripts\novel_agent.py world get <project_id>
```

Patch world state:

```powershell
python scripts\novel_agent.py world patch <project_id> --world-summary "..." --current-focus "..." --author-constraint "..."
```

Export OpenClaw review package:

```powershell
python scripts\novel_agent.py review-package <project_id> --chapter-number 1 --include-body
```

Apply OpenClaw review result:

```powershell
python scripts\novel_agent.py apply-review-result <project_id> --chapter-number 1 --result-file review-result.json --include-body
```

Run OpenClaw directly as reviewer:

```powershell
python scripts\novel_agent.py openclaw-review <project_id> --chapter-number 1 --include-body --apply
```

Run bounded automation with the built-in reviewer:

```powershell
python scripts\novel_agent.py auto <project_id> --intent "..." --max-revisions 1 --include-body
```

## Automation Rules

- Codex should fetch context before changing worldbuilding or judging chapter quality.
- World changes go through `world patch`; chapter prose changes go through `revise` or `apply-review-result`.
- Historical chapters are not mutated directly; rollback or branch first.
- Built-in review is the default automated path and should be used for normal generation.
- OpenClaw output is advisory until applied through `apply-review-result`.
- `openclaw-review --apply` and `auto --review-provider openclaw` are optional external-review paths only.
- `auto` is bounded by `--max-revisions` so it cannot revise forever.

## Next Build Steps

1. Add frontend controls for showing built-in review findings and applied revision instructions.
2. Persist review results in the backend instead of only returning the applied response.
3. Add genre-specific reviewer packs after the automation framework remains stable.
4. Keep OpenClaw export/import as an optional compatibility path.
