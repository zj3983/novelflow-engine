# Novel Autogrowth Engine

This project turns a novel outline into a continuously evolving chapter stream.

The backend keeps story state, memory compression, and chapter continuity checks in Python. The web workbench lets you trigger chapter generation and inspect the evolving story bundle from the browser.

## Local development

Create local configuration:

```bash
cp .env.example .env.local
```

API:

```bash
uvicorn apps.api.main:app --reload --port 8000
```

Web:

```bash
cd apps/web
npm install
npm run dev
```

Tests:

```bash
pytest -q
cd apps/web
npx playwright test
```

### Legacy world-context migration

File projects created before the world-context split can be inspected and
migrated without changing chapter prose:

```bash
python scripts/migrate_world_context.py data/exported-projects/<project-id> --dry-run
python scripts/migrate_world_context.py data/exported-projects/<project-id> --apply
```

The migration keeps static settings in `world_blueprint`, writes the current
state to `world_snapshot`, writes short sourced facts to `continuity_facts`,
and backs up the original JSON files under
`.story-system/world-context-backups/` before applying changes.

## Configuration

The API loads `.env` and `.env.local` without overriding real process
environment variables. Runtime settings changed in the UI are persisted under
`~/.novel-autogrowth-engine/runtime_config.json` by default.

State is persisted with SQLite through `SQLiteStoryStore`; the default database
path is `apps/api/data/stories.db`.

See `docs/configuration.md` for model, API key, database, CORS, and storage
roadmap details. See `docs/api.md` for backend endpoints and
`docs/deployment.md` for Docker/Compose deployment.

## Modular agent architecture

The chapter-generation pipeline is split into explicit modules so each agent
sees only the material it needs and every intermediate artifact is
inspectable. The orchestrator stays the public entry point
(`StoryOrchestrator` → `StoryEngine`), but the agents behind it live in
their own packages with stable runtime boundaries and Pydantic contracts.

### Module ownership

| Package | Owns | Public surface |
| --- | --- | --- |
| `packages/story_core/context/` | Canonical project reader + role-specific views | `ProjectContextReader`, `build_director_context`, `build_writer_context` |
| `packages/story_core/agents/` | Director, writer, fact-extractor, consistency agents | `DirectorAgent`, `WriterAgent`, `FactExtractor`, `FocusedConsistencyAgent`, `pipeline.run_modular_pipeline` |
| `packages/story_core/canon/` | Stable entity registry, entity preflight, `ContinuityDelta` apply | `CanonRegistry`, `CanonService.apply_delta` |
| `packages/story_core/continuity/` | Per-chapter snapshots, deterministic checks, the delta itself | `ChapterSnapshot`, `ContinuityStore`, `ContinuityDelta` |
| `packages/story_core/craft_modules/` | Selective craft-module registry + selector | `CraftModuleSelector`, `select_craft_modules` |
| `packages/story_core/persistence/` | Atomic file writes, candidate store, director store, workflow artifact store, project transaction | `ProjectTransaction` (context-manager), `WorkflowArtifactStore` |

The orchestrator's main flow now has two entry points:

* `StoryOrchestrator(use_modular_agents=False)` — legacy path used by the
  existing 4 000+ tests (`generate_next_chapter_bundle`). Kept until the
  CLI / API layer is migrated.
* `StoryOrchestrator(use_modular_agents=True)` — new
  `generate_next_chapter_via_modular_pipeline(...)` that drives the
  Director → CanonService preflight → Writer → FactExtractor pipeline
  and persists per-stage workflow artifacts to
  `.story-system/workflow/{job_id}/`. The CLI flips the flag in
  production.

### On-disk artifacts

The new agents read and write the canonical layout under
`.story-system/`:

```
.story-system/
├── director/NNNN.json          # Director artifact per chapter
├── continuity/
│   ├── snapshots/NNNN.json     # Per-chapter regeneration base state
│   └── stale.json              # Markers for chapters downstream of a regen
├── canon/registry.json         # Stable-id entity registry
├── workflow/<job_id>/          # One JSON per stage per run
│   ├── director.json
│   ├── writer.json
│   └── fact-extractor.json
├── craft-modules/              # Selective craft modules
├── characters/                 # Per-character card JSON
├── entities/                   # Per-entity card JSON
├── chapters/NNNN.json          # Chapter metadata
├── reviews/NNNN.json           # Per-chapter review JSON
└── commits/                    # Confirm-commit log
```

The legacy `.webnovel/` shape (`outline.json`, `state.json`, `project.json`)
is still read by the file-project store during the migration window; the
two layouts co-exist.

### Migrating a legacy project

Real projects on disk still ship data under `.webnovel/`. Bring one up to
the modular layout with:

```bash
python -m scripts.migrate_modular_story_state --project /path/to/project
# or
python -m scripts.migrate_modular_story_state --all --projects-file projects.txt
# preview only:
python -m scripts.migrate_modular_story_state --project /path/to/project --dry-run
```

The script:

* Creates a timestamped backup under
  `.story-system/.migrate-backup-<stamp>/` before writing.
* Fills in the canonical directories (`director/`,
  `continuity/snapshots/`, `canon/`, `workflow/`, `craft-modules/`,
  `characters/`, `entities/`) and a stub `MASTER_SETTING.json` if the
  project only has `.webnovel/`.
* Seeds a `canon/registry.json` from the legacy `state.json#characters`
  list (the `game_id` becomes an alias).
* Builds a per-chapter `ChapterSnapshot` from the legacy
  `chapter_summaries` so a regeneration has a base state.
* Builds a per-chapter director stub from the outline so the workbench
  has a row to render even before the next chapter is generated.
* Stamps `.story-system/state.json` with `modular_state_migrated_at`
  and `modular_migration_schema` for idempotency.
* Prints counts for migrated chapters, seeded entities, created
  snapshots, and director artifacts. Warnings (e.g. duplicate character
  display names) are surfaced so the user can resolve them in the
  workbench — the script never silently picks between two confirmed
  identities.

The script is idempotent: re-running it on a project that already has the
canonical artifacts is a no-op for `canon/registry.json`,
`director/`, and `continuity/snapshots/`, and a refresh of the
`state.json` migration marker.

### Regenerating an earlier chapter

When a user rewrites chapter N, the candidate confirmation marks
chapters N+1, N+2, … as stale so the workbench can warn before
regenerating them:

```
.story-system/continuity/stale.json
{"chapters": [3, 4, 5, ...], "trigger_chapter": 2}
```

The downstream chapter *files* stay on disk; only the marker changes.
The next regeneration reads the snapshot at
`.story-system/continuity/snapshots/(N-1).json` as the base state
instead of inferring from later chapter prose.

### Inspecting a failed stage

If a chapter run aborts mid-pipeline, the workbench's per-stage row
shows the failure and the orchestrator rolls the on-disk state back to
the pre-run snapshot. To inspect the per-stage artifacts directly:

```bash
ls .story-system/workflow/<job_id>/
cat .story-system/workflow/<job_id>/director.json   # status, error, output_summary
cat .story-system/workflow/<job_id>/writer.json
cat .story-system/workflow/<job_id>/fact-extractor.json
```

The `error` field on each record names the failure reason; the
`output_summary` is a one-line digest so a terminal `cat` is enough to
see what the stage produced before the abort.

### Smoke generation

To exercise the modular pipeline end-to-end without a live model
endpoint, drive the orchestrator with stub director / writer runtimes:

```bash
python -m scripts.smoke_modular_pipeline --copy .codex-run/<project> .codex-run/_smoke_target
```

The script copies the project, runs
`generate_next_chapter_via_modular_pipeline` against the copy, and
prints the per-stage workflow artifacts the workbench would render.
It exits non-zero if any stage's artifact is missing on disk.

### Production pipeline smoke (Round 7 acceptance)

`scripts/smoke_production_pipeline.py` drives the production
modular pipeline end-to-end against a disposable copy of a real
project and asserts the four acceptance criteria the Round 7
plan pinned:

```bash
python -m scripts.smoke_production_pipeline \
    data/exported-projects/p-gou-webgame-restored
```

The script:

1. Copies the source project to a temporary disposable
   directory so the source is never written to.
2. Hashes the source directory before and after the run —
   the smoke fails if the source hash changes.
3. Drives Director → Writer → FocusedConsistency → FactExtractor
   end-to-end.
4. Asserts the four acceptance criteria:
   * director reads only the current book's outline / previous
     chapter / foreshadowing / character state;
   * director artifact has ≥ 2 causal scene beats;
   * writer prompt contains the 4200-5500 target range and
     the 3800-6000 hard range;
   * writer context preserves the protagonist's equipment,
     level, inventory, and quests.
5. Runs the candidate through `_save_candidate_from_bundle` so
   the candidate's `quality_report.ok` is checked against the
   same length gate the confirmation flow will run.

The smoke is the one-line acceptance check for the Round 7
plan; the rest of the plan's acceptance lives in
`tests/story_core/test_modular_*` and the production test
suite (`pytest -q`).

### Rolling-outline fill smoke (Round 8 acceptance)

The Round 8 plan added a rolling chapter-outline fill: when
the user clicks "生成下一章" and the target chapter has no
outline, the system must generate a 5-chapter window of
outlines before the body generation starts. The fill lives
in a separate file (`.story-system/outline-generation/rolling_outline.json`)
so the legacy `ProjectOutline` schema is not disturbed.

The same smoke script exposes a `--mode rolling-fill` that
exercises the fill on a disposable copy of the project:

```bash
python -m scripts.smoke_production_pipeline --mode rolling-fill \
    data/exported-projects/p-gou-webgame-restored
```

The smoke asserts the Round 8 plan's acceptance criteria:

1. The first call produces `kind="filled"` with a 5-chapter
   window starting at the target chapter (the smoke uses
   `state.current_chapter + 1` so the test mirrors the
   production code path).
2. A second call is a no-op (`kind="present"`, empty
   `chapter_numbers`) — repeated invocations don't churn
   the disk.
3. A chapter the smoke marks with `source="manual"` keeps
   its user-edited title across a subsequent fill (the
   "已存在或人工修改的细纲不会被覆盖" rule).
4. The source project's hash is byte-identical before and
   after the run — the smoke never writes to the source.

The rolling-fill smoke is the one-line acceptance check
for the Round 8 plan; the unit tests in
`tests/story_core/test_outline_rolling*.py` and
`tests/story_core/test_rolling_outline_*.py` cover the
planner / store / validation layers in isolation.

### Rolling-outline flow (Round 8)

```
  生成下一章 click
        │
        ▼
  generate_next_chapter(target_chapter)
        │
        ▼
  ensure_rolling_outline(target_chapter)
        │
        ├─ plan_rolling_window → gap = missing chapter numbers
        │
        ├─ generator(n)        → fill 5 chapters (window=5)
        │   stub today; real LLM swap later
        │
        ├─ RollingOutlineStore.apply_rolling_batch
        │   ├─ validate_rolling_batch (whole batch or none)
        │   ├─ skip chapters already on disk (legacy + rolling)
        │   ├─ backup previous rolling_outline.json
        │   └─ atomic write + fill log
        │
        └─ return RollingOutlineStatus(kind=filled|present)
        │
        ▼
  body generation reads target chapter's outline
        │
        ▼
  on success: writing_packet + candidate
```

Idempotency rules:

* The store reads BOTH `.webnovel/outline.json` (legacy)
  and `.story-system/outline-generation/rolling_outline.json`
  (rolling) so chapters in either file count as "filled".
* Chapters with `source="manual"` are skipped on every
  fill — a user-edited chapter is never overwritten.
* A failed validation (bad payload, wrong chapter number,
  out-of-volume) aborts the whole batch; the on-disk
  outline is byte-identical to the pre-call state.

The `regenerate_chapter` path does NOT call
`ensure_rolling_outline` — old-chapter rewrites use only
the chapter's existing outline and the chapters leading
UP to it, so a re-write of chapter 30 never reads the
rolling outline for chapter 50.
