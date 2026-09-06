# Reliable World Build Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make modular worldbuilding recoverable, conflict-safe, and truthful: every module must produce useful content, a restarted server must not leave jobs stuck, and the UI must show the real task state.

**Architecture:** Keep one asynchronous world-build job per project. Store a durable job record, reconcile unfinished records on startup/read, and allow only the job endpoint to perform modular enrichment. Preserve author-edited fields with a project revision check. Build each module from explicit author facts plus completed module outputs, not from generic defaults added by the merge layer.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest; Next.js/React, TypeScript.

---

## Constraints

- Do not change formal chapter text, outline text, character cards, or user-authored world fields.
- Do not silently re-run an interrupted model call after a server restart. Mark it as interrupted and let the user retry.
- Keep `world_build_artifacts` as an auditable record of completed module outputs.
- The legacy `POST /enrich-world` path must not be allowed to race the job path.

## Files and Responsibilities

- Modify `packages/story_core/world_enrichment.py`: module output contracts and module-specific prompt context.
- Modify `apps/api/routes/file_projects.py`: durable job lifecycle, stale-job reconciliation, mutation exclusion, user-facing failures.
- Modify `apps/web/lib/api.ts`: current-job API client and typed response fields.
- Modify `apps/web/app/projects/[id]/world/page.tsx`: restore active task state after reload and show retryable status.
- Modify `tests/api/test_project_world_enrichment.py`: module contract and prompt-context tests.
- Modify `tests/api/test_story_routes.py`: durable job, stale recovery, conflict, and endpoint tests.
- Create or modify the nearest existing frontend test location only if this repository already has a React test runner; otherwise cover frontend behavior with a typed API test and manual browser acceptance steps.

---

### Task 1: Make incomplete module output fail before it reaches the project

**Files:**
- Modify: `packages/story_core/world_enrichment.py:91-180, 1949-1958`
- Test: `tests/api/test_project_world_enrichment.py`

- [ ] **Step 1: Add failing tests for missing required fields.**

  Add a parametrized test that calls `_module_world_payload` with a `WorldBuildModule` whose required fields are `("world_rules", "locations")`, then assert that a payload containing only `world_rules` raises `WorldEnrichmentError("world_build_module_incomplete:core_rules:locations")`.

  Add tests for the real contracts:
  - `core_rules`: must return `world_rules`, `locations`, and `factions`; power-system genres must also return `power_system_spec`.
  - `society_and_livelihood`: must return `world_systems` and `living_world`.
  - `story_engine`: must return `opening_arc`, `volume_plan`, and `longform_framework`.
  - `game_ecology`: must return `npc_system`, `quest_network`, `server_runtime`, and `map_ecology`.

- [ ] **Step 2: Run the focused tests and confirm they fail.**

  Run:
  ```powershell
  pytest tests/api/test_project_world_enrichment.py -k "world_build and incomplete" -q
  ```
  Expected: failure because `WorldBuildModule` has no required-field contract.

- [ ] **Step 3: Add an explicit `required_fields` tuple to `WorldBuildModule`.**

  Extend the dataclass:
  ```python
  @dataclass(frozen=True)
  class WorldBuildModule:
      module_id: str
      title: str
      fields: tuple[str, ...]
      required_fields: tuple[str, ...]
      instructions: str
      max_tokens: int
  ```
  Populate the contracts listed in Step 1 in `world_build_modules`. Keep optional fields in `fields`; only `required_fields` decides whether completion is allowed.

- [ ] **Step 4: Validate required fields in `_module_world_payload`.**

  After constructing `payload`, reject each absent or blank required field:
  ```python
  missing = [
      field for field in module.required_fields
      if field not in payload or _is_blank_world_value(payload[field])
  ]
  if missing:
      raise WorldEnrichmentError(
          f"world_build_module_incomplete:{module.module_id}:{','.join(missing)}"
      )
  ```
  Do not accept merge defaults as module output.

- [ ] **Step 5: Run tests and commit.**

  Run:
  ```powershell
  pytest tests/api/test_project_world_enrichment.py -k "world_build" -q
  ```
  Expected: all selected tests pass.

  Commit:
  ```powershell
  git add packages/story_core/world_enrichment.py tests/api/test_project_world_enrichment.py
  git commit -m "fix: require complete world build module outputs"
  ```

### Task 2: Stop merge defaults from contaminating later module prompts

**Files:**
- Modify: `packages/story_core/world_enrichment.py:1915-2071`
- Test: `tests/api/test_project_world_enrichment.py`

- [ ] **Step 1: Write a failing prompt-context test.**

  Build a blank non-game project and use a fake gateway that captures each `ModelRequest.prompt`. Make the core module return only its valid owned fields. Assert the later `society_and_livelihood` prompt contains the core output but does **not** contain fallback text created by `_merge_enrichment`, such as default `opening_arc`, `volume_plan`, `living_world`, or `world_systems` values.

- [ ] **Step 2: Run the focused test and confirm it fails.**

  Run:
  ```powershell
  pytest tests/api/test_project_world_enrichment.py -k "world_build and prompt_context" -q
  ```
  Expected: failure because `_merge_enrichment` populates defaults before the next prompt is built.

- [ ] **Step 3: Introduce a context-only world projection.**

  Add a helper near `_build_world_module_prompt`:
  ```python
  def _world_build_context_project(
      source_project: NovelProject,
      completed_outputs: Mapping[str, Any],
  ) -> NovelProject:
      context = source_project.model_copy(deep=True)
      context.world_blueprint = {
          **deepcopy(source_project.world_blueprint or {}),
          **deepcopy(completed_outputs),
      }
      return context
  ```
  `completed_outputs` must contain only validated raw fields returned by completed modules. It must never include fields invented by `_merge_enrichment`.

- [ ] **Step 4: Use separate context and persistence flows.**

  In `_call_world_build_modules`:
  - Keep `completed_outputs: dict[str, Any]` for subsequent module prompts.
  - Pass `_world_build_context_project(project, completed_outputs)` to `_build_world_module_prompt`.
  - Continue using `_merge_enrichment` only to build the final `working` project after a module validates.
  - Add the raw payload to `completed_outputs` only after it passes Task 1 validation.

- [ ] **Step 5: Run tests and commit.**

  Run:
  ```powershell
  pytest tests/api/test_project_world_enrichment.py -k "world_build" -q
  ```
  Expected: all selected tests pass; captured prompts contain only author data and completed-module data.

  Commit:
  ```powershell
  git add packages/story_core/world_enrichment.py tests/api/test_project_world_enrichment.py
  git commit -m "fix: isolate modular world build prompt context"
  ```

### Task 3: Make the background job recoverable and prevent concurrent writers

**Files:**
- Modify: `apps/api/routes/file_projects.py:298-466, 2110-2181`
- Test: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing lifecycle tests.**

  Add tests with a temporary file project for these cases:
  - A persisted `queued` or `running` job loaded after a simulated process restart is returned as `interrupted`, with progress `服务已重启，请重新开始补全`, and is removed from the active-job map.
  - `POST /world-build-jobs` can start a new job after that interrupted record.
  - Calling legacy `POST /enrich-world` while a queued/running job exists returns HTTP 409 with `world_build_in_progress`.
  - Starting a job while the legacy endpoint is marked active also returns HTTP 409.

- [ ] **Step 2: Run tests and confirm they fail.**

  Run:
  ```powershell
  pytest tests/api/test_story_routes.py -k "world_build and (restart or conflict)" -q
  ```
  Expected: failure because persisted jobs are currently returned unchanged and the legacy endpoint has no conflict guard.

- [ ] **Step 3: Add stale-job reconciliation.**

  Add `_reconcile_world_build_job(store, job)` beside `_load_world_build_job`:
  ```python
  def _reconcile_world_build_job(store: FileProjectStore, job: dict[str, object]) -> dict[str, object]:
      if str(job.get("status")) not in {"queued", "running"}:
          return job
      recovered = {
          **job,
          "status": "interrupted",
          "progress": "服务已重启，请重新开始补全",
          "active_module_status": "interrupted",
          "updated_at": _now_iso(),
      }
      _persist_world_build_job({**recovered, "_project_root": str(store.root)})
      return recovered
  ```
  Call it whenever `current` or a specific job is loaded from disk. Do not submit another model call automatically.

- [ ] **Step 4: Make the job path the single writer.**

  Add one helper that detects an active world-build job for a project. Use it in both routes:
  - `POST /world-build-jobs`: return the in-memory active job only when it is actually queued/running.
  - `POST /enrich-world`: return `HTTPException(409, detail="world_build_in_progress")` when a job is active.

  Then deprecate the synchronous implementation without breaking callers: make `POST /enrich-world` create/return the same job response as `POST /world-build-jobs`, and update its response annotation/documentation accordingly. It must not call `enrich_project_world` directly anymore.

- [ ] **Step 5: Add revision protection for partial persistence.**

  At job creation, store a `project_revision` derived from the project metadata already used by `FileProjectStore` (or add a monotonic revision field if none exists). Before `_persist_partial_world_build_artifact` and before final `update_project`, compare the stored revision with the current project revision. If it changed because the author saved world data:
  - mark the job `conflicted`;
  - preserve completed artifacts in the job record only;
  - do not overwrite `world_blueprint`;
  - show progress `世界观已被手动修改，请重新开始补全`.

  Do not infer a revision from timestamps if the store already has a canonical update/version mechanism.

- [ ] **Step 6: Translate background failures before returning them.**

  Replace direct `error = str(exc)` display with two fields:
  ```python
  error_code = _world_build_error_code(exc)
  error = _world_build_user_message(error_code)
  ```
  Persist a truncated technical detail only in the server job JSON/log and never expose provider URLs, request bodies, or credential-shaped strings to the browser response.

- [ ] **Step 7: Run route tests and commit.**

  Run:
  ```powershell
  pytest tests/api/test_story_routes.py -k "world_build or enrich_world" -q
  ```
  Expected: all selected tests pass, including restart and conflict cases.

  Commit:
  ```powershell
  git add apps/api/routes/file_projects.py tests/api/test_story_routes.py
  git commit -m "fix: recover and serialize world build jobs"
  ```

### Task 4: Restore task visibility after refresh and make failure actionable

**Files:**
- Modify: `apps/web/lib/api.ts:4522-4538`
- Modify: `apps/web/app/projects/[id]/world/page.tsx:1-120`
- Test: nearest established frontend test location, if available

- [ ] **Step 1: Add a current-job client function.**

  Add:
  ```typescript
  export async function fetchCurrentWorldBuildJob(projectId: string): Promise<WorldBuildJobResponse | null> {
    try {
      return await tryFetchJson(`${fileProjectPath(projectId)}/world-build-jobs/current`);
    } catch (error) {
      if (error instanceof Error && error.message.includes("404")) return null;
      throw error;
    }
  }
  ```
  Match the repository's existing HTTP-error helper rather than string-matching if it provides a typed status code.

- [ ] **Step 2: Restore and poll the task in a `useEffect`.**

  On page mount, request the current job. If it is queued/running, place it in `worldBuildJob` and poll it every 900 ms. Use a cancellation flag or `AbortController` in the cleanup function so route changes never update an unmounted component.

- [ ] **Step 3: Reuse one polling function for button and restoration.**

  Extract `watchWorldBuildJob(initialJob)` so both the button click and page-load recovery use the same terminal handling:
  - `completed`: refresh project data and show `世界观构建完成`.
  - `interrupted`: show a visible `重新开始补全` button.
  - `conflicted`: show a visible `保留手动修改，重新补全` button.
  - `failed`: show the translated message and `重试` button.

- [ ] **Step 4: Keep raw artifacts readable but not as the primary status.**

  Retain `world_build_artifacts`, but render each artifact as a titled section with its Chinese field labels. Put raw JSON behind an optional `查看原始输出` disclosure. Do not display module ids such as `core_rules` to readers.

- [ ] **Step 5: Verify type-check and browser behavior.**

  Run:
  ```powershell
  Set-Location apps/web
  npx tsc --noEmit
  ```
  Expected: no TypeScript errors.

  Manual acceptance:
  1. Start world build, refresh the page during module two, and verify the correct module/progress returns.
  2. Restart the API during a running build, refresh, and verify the task says interrupted rather than loading forever.
  3. Edit a world-rule field during a build, then verify the job reports conflict and the edit remains unchanged.
  4. Cause a model failure and verify the page shows a Chinese retryable message, not a Python exception.

  Commit:
  ```powershell
  git add apps/web/lib/api.ts "apps/web/app/projects/[id]/world/page.tsx"
  git commit -m "fix: restore visible world build job progress"
  ```

### Task 5: Full regression and handoff

**Files:**
- No production-file changes expected
- Test: `tests/api/test_project_world_enrichment.py`
- Test: `tests/api/test_story_routes.py`

- [ ] **Step 1: Run the complete worldbuilding regression suite.**

  Run:
  ```powershell
  pytest tests/api/test_project_world_enrichment.py tests/api/test_project_world_systems.py tests/api/test_story_routes.py -q
  ```
  Expected: all tests pass. If Windows temp-directory cleanup emits a non-failing path-length warning after pytest reports success, record it as test-environment noise; do not suppress a genuine test failure.

- [ ] **Step 2: Run static checks.**

  Run:
  ```powershell
  python -m compileall -q packages/story_core/world_enrichment.py apps/api/routes/file_projects.py
  Set-Location apps/web
  npx tsc --noEmit
  Set-Location ../..
  git diff --check
  ```
  Expected: all commands exit with code 0. CRLF notices are acceptable only if `git diff --check` itself succeeds.

- [ ] **Step 3: Do an end-to-end manual acceptance run.**

  Create one blank normal project and one blank game-webnovel project. For each:
  1. Start AI worldbuilding from the world page.
  2. Verify every required module appears only after its required fields exist.
  3. Refresh during execution and verify progress returns.
  4. Confirm the final world page contains completed artifacts and does not expose raw internal errors.
  5. Generate the first chapter and verify its writing context reads project world data rather than the artifacts' raw JSON.

- [ ] **Step 4: Commit the integration result.**

  ```powershell
  git add apps/api/routes/file_projects.py apps/web/lib/api.ts "apps/web/app/projects/[id]/world/page.tsx" packages/story_core/world_enrichment.py tests/api/test_project_world_enrichment.py tests/api/test_story_routes.py
  git commit -m "fix: harden modular worldbuilding workflow"
  ```

## Coverage Check

- Restart-stuck jobs: Task 3.
- Concurrent old/new worldbuilding writers and manual-save overwrite: Task 3.
- Module falsely marked complete: Task 1.
- Defaults polluting later model calls: Task 2.
- Refresh losing the actual task state and raw error display: Task 4.
- API, model, frontend and regression verification: Task 5.
