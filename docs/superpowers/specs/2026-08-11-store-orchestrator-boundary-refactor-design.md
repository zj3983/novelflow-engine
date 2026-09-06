# FileProjectStore / StoryOrchestrator Boundary Refactor

## Goal

Reduce duplicated chapter-history and modular-pipeline assembly logic while preserving every existing public API, persisted JSON shape, generation result, and recovery behavior.

## Scope

The refactor covers the current continuation/rolling-outline delta plus the directly related legacy code in:

- `packages/story_core/file_project_store.py`
- `packages/story_core/orchestrator.py`
- `packages/story_core/continuation_outline_bootstrap.py`

It may add small internal modules under `packages/story_core/`, but callers must continue using `FileProjectStore` and `StoryOrchestrator` as before.

## Non-goals

- No API route or frontend contract changes.
- No changes to `.webnovel` or `.story-system` schemas.
- No redesign of prompts, generation stages, quality gates, or retry policy.
- No broad cleanup of unrelated methods in the two large classes.
- No deletion of compatibility behavior without a characterization test.

## Design

### 1. Centralize chapter-history mutation

Add an internal `chapter_history.py` module containing pure functions for:

- replacing one record by `chapter_number`;
- preserving deterministic order and retention limits;
- applying a chapter summary and timeline entry to a story-state mapping;
- deriving the timeline impact from `next_focus`, then falling back to the summary.

`FileProjectStore` and the modular bundle adapter in `StoryOrchestrator` will call the same functions. This removes the current parallel list comprehensions and prevents the two paths from producing different history ordering or duplicate chapter rows.

### 2. Isolate modular bundle adaptation

Move the pure conversion of modular-agent output into an internal `modular_bundle_adapter.py` module. It will build:

- scene cards and scene-result summaries;
- the canonical chapter summary;
- updated chapter history;
- the legacy `ChapterBundle` compatibility payload.

`StoryOrchestrator` remains responsible for running agents, progress events, and persistence boundaries. The adapter receives data and returns data; it performs no model calls or filesystem writes.

### 3. Keep store normalization focused

Retain project-specific fallback extraction in `FileProjectStore`, because it depends on legacy candidate shapes. Replace only the generic history-array mutation with `chapter_history.py`. The existing `_chapter_summary_payload` behavior remains unchanged and continues to reject placeholders such as `continue`.

### 4. Simplify bootstrap checkpoint transitions

Introduce one internal helper that loads the continuation analysis, computes the fingerprint, loads the checkpoint, and persists the initial `running` state. Both `prepare()` and `run()` use it.

Phase transition helpers remain responsible for immediate checkpoint persistence. Failure handling must leave no phase in an ambiguous in-memory-only state.

The CLI payload compatibility normalizer remains in place for this refactor; although it fills structural scene fields, changing that recovery policy would alter behavior and belongs in a separate review.

## Compatibility invariants

- Regenerating chapter N replaces, rather than duplicates, chapter N in `chapter_summaries` and `timeline`.
- History remains ordered by chapter number and respects the existing retention limit.
- `next_focus` remains the preferred timeline impact; summary is the fallback.
- Modular and legacy generation produce the same chapter-history shape.
- Candidate confirmation, rollback, and regeneration do not read future-chapter state.
- Checkpoint files are written before background work starts and after every phase transition.

## Testing strategy

1. Add characterization tests for history replacement, ordering, limits, and fallback impact.
2. Add an equivalence test showing modular bundle adaptation and store confirmation use the same history rules.
3. Run each new test before implementation and confirm the expected failure.
4. Run focused continuation, modular-pipeline, candidate-confirmation, regeneration, and rolling-outline tests.
5. Run the complete Python suite and the web production build because the current delta also changes API and workbench code.

## Rollout

Apply the refactor in small steps:

1. Add and adopt `chapter_history.py`.
2. Extract modular bundle adaptation without changing orchestration order.
3. Deduplicate bootstrap checkpoint preparation.
4. Review the final diff for reduced line count and unchanged external contracts.

Each step must leave the focused test set green before the next begins.
