# Development & Generation Pipeline Notes

This document preserves the implementation-oriented material that previously lived on the project homepage. The README is intentionally optimized for first-time users; detailed migration, regeneration, workflow artifact, smoke-test, and rolling-outline notes live here.

> These notes describe a fast-moving codebase. Treat `main`, tests, and the current implementation as the source of truth when details diverge.

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
| `packages/story_core/character_agent.py` | Bounded character-intent proposals and rule fallback | `CharacterAgent`, `RuleBasedCharacterProposalProvider` |
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
  production modular flow:

  ```text
  OutlineExecutionContract
      → bounded relevant cast
      → Character Intent
      → Director
      → Canon Preflight
      → Writer
      → Consistency / Review
      → FactExtractor
  ```

  The CLI flips the flag in production. The execution contract is built from
  the target chapter outline and preserves the core conflict, gain, cost,
  state delta, planned hook, opening carry, payoff contract and
  `must_not_write` constraints. Director staging must satisfy that contract;
  it is not allowed to replace the contract with a new chapter plan.

  Character Intent is a bounded candidate-pressure pass: it answers what a
  selected character may want, try, avoid or withhold in the current chapter.
  It is not a second plot planner and it is not canon. A character may
  investigate, protect, test a relationship, resist, hesitate, stay silent,
  fail or do nothing when the current stimulus is weak. The Director may
  adopt, defer, collide or reject those pressures. Only the Director's final
  scene-level intents are sent to Writer; raw Character proposals never go
  directly to Writer.

  Character Intent failure is advisory. If the model provider and its rule
  fallback both fail, the stage yields no proposals and Director continues
  from the existing bounded context. Per-stage workflow artifacts are
  persisted to `.story-system/workflow/{job_id}/`.

### OutlineExecutionContract and chapter boundaries

`OutlineExecutionContract` is the program-built bridge between the rolling
outline and Director/Writer. It carries the chapter's `core_conflict`,
`gain`, `cost`, `state_delta`, `planned_hook`, `opening_carry`,
`payoff_contract`, and `must_not_write` values (plus the related turn and
mid-feedback fields). These are execution constraints, not optional prompt
decoration: the Director may stage how the contract becomes a scene, but the
Director → Writer handoff must not compress the contract until its required
gain, cost, state transition, and hook disappear.

`planned_hook` belongs to the chapter contract. Writer may express it in
different prose, but must preserve its substance. The candidate pipeline
checks the end of the body deterministically; a missing hook produces
`chapter.hook_not_landed`, a blocking finding rather than an advisory style
note.

### Chapter-bounded Canon Review Snapshot

Factual review uses `canon-review-snapshot/v1`, a read-only view of the
confirmed state available before the target chapter. For a historical rewrite
the builder prefers the previous chapter's continuity snapshot or saved
`updated_story`; it does not blindly read the live registry, where later
chapters may already have introduced facts. If a bounded base is unavailable,
the historical review does not silently treat current live state as evidence.

Model-backed factual findings must be grounded in Canon evidence before they
can be treated as blocking contradictions. Expression-oriented findings such
as style, dialogue, exposition, or an unavailable advisory review remain
visible to the workbench but do not become factual Canon merely because a
model mentioned them.

### Previous-chapter handoff

The modular context keeps two different handoff values:

* `previous_chapter_summary` answers what happened in the previous chapter.
* `previous_chapter_tail` is the actual prose ending from which the next
  chapter should continue.

Director and Writer receive the actual tail when constructing the opening
handoff, rather than relying on a summary to recreate the last position,
gesture, or unfinished sentence.

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
│   ├── character-intent.json   # Bounded CharacterAgent proposals
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
  ensure_rolling_outline(target_chapter, window=5)
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
