# Store / Orchestrator Boundary Refactor Implementation Plan

> **For Codex:** Execute this plan task by task with `superpowers:executing-plans`. Preserve the current dirty worktree and do not commit or push.

**Goal:** Remove duplicated chapter-history mutation and modular-pipeline adaptation logic while preserving public APIs, persisted JSON shapes, generation behavior, and recovery semantics.

**Architecture:** Introduce two small pure modules: one owns chapter-number keyed history replacement/update, and one converts modular-agent output into the existing `ChapterBundle`. `FileProjectStore` keeps its storage-specific text normalization, `StoryOrchestrator` keeps orchestration only, and `ContinuationOutlineBootstrapper` shares checkpoint initialization through one private helper.

**Tech Stack:** Python 3.11+, Pydantic, pytest, existing Story Core models and agents.

---

### Task 1: Characterize and extract chapter-history operations

**Files:**
- Create: `tests/story_core/test_chapter_history.py`
- Create: `packages/story_core/chapter_history.py`

1. Add failing tests for replacement of a mapping and legacy `Chapter N:` string, deterministic chapter ordering, history limits, duplicate replacement, and `next_focus` timeline impact fallback.
2. Run `uv run pytest -q tests/story_core/test_chapter_history.py` and confirm failure is the missing module/API.
3. Implement `replace_chapter_record(...)` and `apply_chapter_history(...)` as pure functions. Preserve the existing equality, ordering, trimming, and mapping shapes.
4. Rerun the focused test and confirm it passes.

### Task 2: Route FileProjectStore history writes through the shared helper

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_file_project_store.py`
- Test: `tests/story_core/test_candidate_confirmation_transaction.py`
- Test: `tests/story_core/test_regenerate_no_future_read.py`

1. Run the three focused suites as a characterization baseline.
2. Import `replace_chapter_record`, replace all `_replace_by_chapter_number` calls, and remove the duplicated private method.
3. Rerun the same suites and the new chapter-history tests.
4. Confirm no serialized fields, retention limits, or future-read behavior changed.

### Task 3: Extract modular bundle adaptation from StoryOrchestrator

**Files:**
- Create: `tests/story_core/test_modular_bundle_adapter.py`
- Create: `packages/story_core/modular_bundle_adapter.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_modular_main_flow.py`

1. Add a focused adapter test that supplies a minimal modular result and asserts the legacy `ChapterBundle`, chapter summary, scene results, next outline, and story-history shapes.
2. Run the new test and confirm the expected missing module/API failure.
3. Move only deterministic conversion code into `adapt_modular_bundle_to_legacy(...)`; keep agent calls, retry/fallback policy, and filesystem work in the orchestrator.
4. Reuse `apply_chapter_history(...)` when advancing the returned story state.
5. Make `_generate_next_chapter_bundle_via_modular_agents(...)` call the pipeline and delegate conversion to the adapter.
6. Run the adapter and modular-main-flow suites.

### Task 4: Deduplicate continuation-bootstrap checkpoint initialization

**Files:**
- Modify: `packages/story_core/continuation_outline_bootstrap.py`
- Test: `tests/story_core/test_continuation_outline_bootstrap.py`

1. Run the focused bootstrap suite as a characterization baseline.
2. Extract one private helper that reads continuation analysis, computes the fingerprint, loads the matching checkpoint, and persists the initial `running` state.
3. Use it from both `prepare()` and `run()` without changing phase transitions or persistence timing.
4. Rerun the focused bootstrap suite.

### Task 5: Review and verify the complete delta

**Files:**
- Review all files changed by Tasks 1–4.

1. Run focused regression tests:
   `uv run pytest -q tests/story_core/test_chapter_history.py tests/story_core/test_modular_bundle_adapter.py tests/story_core/test_file_project_store.py tests/story_core/test_modular_main_flow.py tests/story_core/test_candidate_confirmation_transaction.py tests/story_core/test_regenerate_no_future_read.py tests/story_core/test_continuation_outline_bootstrap.py tests/story_core/test_rolling_outline_integration.py`
2. Run the full Python suite: `uv run pytest -q`.
3. Run the web production build from `apps/web` with `C:\Program Files\nodejs\npm.cmd run build`.
4. Run `git diff --check` and inspect `git diff --stat` plus the final diff for accidental unrelated edits.
5. Report exact verification results and remaining risks. Do not create a commit or push unless separately requested.
