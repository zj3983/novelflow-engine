# Continuous Chapter Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Add a durable backend continuous-generation job that sequentially creates 2, 5, 10, or 20 new chapters, confirms only candidates that pass the ordinary confirmation gate, and stops safely at outline, quality, failure, or user boundaries.

**Architecture:** Put durable job state and the sequential runner in a dedicated API service. The runner reuses `FileProjectStore.generate_next_chapter(persist=False)` and `FileProjectStore.confirm_candidate(..., accept_quality_warnings=False)`; it does not call rewrite, expansion, force-confirm, or browser-side loops. File-project routes own per-project mutual exclusion and background submission. The writing page only starts, polls, stops, and renders the persisted job.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, `ThreadPoolExecutor`, atomic JSON files, Next.js 14, React, TypeScript, pytest, Playwright.

---

### Task 1: Add the persistent continuous-job model and store

**Files:**
- Create: `apps/api/services/continuous_generation.py`
- Create: `tests/api/test_continuous_generation_service.py`

1. Add failing tests for:
   - accepting only counts `2`, `5`, `10`, and `20`;
   - creating a job with `queued`, `start_chapter`, `current_chapter`, and an empty `completed_chapters` list;
   - atomically writing both `<job_id>.json` and `latest.json` under `.story-system/continuous-generation-jobs`;
   - loading a job after a new service instance is created;
   - setting `stop_requested` without discarding completed chapters;
   - reconciling a confirmed chapter that advanced on disk before the last job-state write;
   - changing ambiguous `running` or `confirming` recovery states to `stopped/recovery_confirmation_required` rather than rerunning them.

2. Run the focused test and confirm it fails because the service does not exist:

   ```powershell
   uv run pytest -q tests/api/test_continuous_generation_service.py
   ```

3. Implement `ContinuousGenerationJobStore` with these public methods:

   ```python
   ALLOWED_CONTINUOUS_COUNTS = frozenset({2, 5, 10, 20})

   class ContinuousGenerationJobStore:
       def __init__(self, project_root: Path) -> None: ...
       def create(self, *, project_id: str, story_id: str, count: int, start_chapter: int) -> dict[str, object]: ...
       def load(self, job_id: str | None = None) -> dict[str, object] | None: ...
       def save(self, job: dict[str, object]) -> None: ...
       def request_stop(self, job_id: str) -> dict[str, object]: ...
       def reconcile(self, job: dict[str, object], *, official_chapter: int) -> dict[str, object]: ...
   ```

4. Persist the schema fields from the approved design plus `phase` and `candidate_id`. Use phases `queued`, `checking_outline`, `generating`, `confirming`, and `between_chapters` so recovery can distinguish safe and ambiguous boundaries.

5. Write through a temporary sibling file followed by `Path.replace`; never update only the in-memory object.

6. Rerun the focused test and confirm it passes.

### Task 2: Implement the sequential runner against existing store boundaries

**Files:**
- Modify: `apps/api/services/continuous_generation.py`
- Modify: `tests/api/test_continuous_generation_service.py`

1. Add failing runner tests using a fake file-project store for:
   - generating and ordinarily confirming chapters in strict numeric order;
   - passing `persist=False` to every generation call;
   - passing `accept_quality_warnings=False` to every confirmation call;
   - never calling regeneration or expansion;
   - stopping after the current model call when `stop_requested` becomes true;
   - retaining chapters 1 and 2 when chapter 3 generation fails;
   - mapping `volume_missing` to `next_volume_required`;
   - mapping `volume_plan_ready` and `detail_partial` to `volume_detail_required`;
   - mapping ordinary confirmation failure to `candidate_confirmation_required` and preserving `candidate_id`;
   - reaching `completed` only when `completed_count == requested_count`.

2. Run the focused test to see the expected missing-runner failures.

3. Implement a runner with dependency injection so tests do not call a real model:

   ```python
   class ContinuousGenerationRunner:
       def run(
           self,
           job_id: str,
           *,
           project_store: FileProjectStore,
           job_store: ContinuousGenerationJobStore,
       ) -> dict[str, object]: ...
   ```

4. For each iteration, perform exactly this sequence:
   - reload and reconcile the durable job;
   - stop if requested;
   - compute `next_chapter = int(project_store.summary()["current_chapter"]) + 1`;
   - call `volume_workflow_status(next_chapter)` and continue only for `detail_complete`;
   - persist phase `generating`;
   - call `generate_next_chapter(persist=False)`;
   - extract and persist the returned `candidate.candidate_id`;
   - persist phase `confirming`;
   - call `confirm_candidate(candidate_id, accept_quality_warnings=False)`;
   - append the confirmed chapter once, update counts, clear `candidate_id`, and persist phase `between_chapters`.

5. Catch precise boundary errors before the general exception handler. A quality-gate `ValueError` from confirmation becomes a recoverable stop; generation, filesystem, and unexpected errors become `failed` with readable `error` text.

6. Rerun the service tests.

### Task 3: Expose continuous-generation APIs and enforce one active writer per book

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Create: `tests/api/test_continuous_generation_routes.py`
- Test: `tests/api/test_file_project_routes.py`

1. Add failing route tests for:
   - `POST /file-projects/{project_id}/continuous-generation-jobs` with `{ "count": 5 }`;
   - rejecting `count=3` with 422;
   - returning 409 if a normal generation, rewrite, expansion, or continuous job is already active for the same project;
   - making the normal generation endpoint return 409 while continuous generation is active;
   - `GET .../current` loading persisted state after in-memory maps are cleared;
   - `GET .../{job_id}` rejecting a job owned by another project;
   - `POST .../{job_id}/stop` changing `running` to `stopping` and being idempotent for terminal jobs;
   - resubmitting only a safely recoverable `queued` or `between_chapters` job;
   - returning an ambiguous recovered job as stopped without submitting work.

2. Run:

   ```powershell
   uv run pytest -q tests/api/test_continuous_generation_routes.py
   ```

3. Add a strict request model:

   ```python
   class FileProjectContinuousGenerationRequest(BaseModel):
       model_config = ConfigDict(extra="forbid", strict=True)
       count: Literal[2, 5, 10, 20] = 5
   ```

4. Add one single-worker `_continuous_generation_executor`, an active-job map keyed by canonical story ID, and a lock. Add shared helpers that check both the existing `_active_file_generation_jobs` and the new continuous map before either kind of task is created.

5. Add the four approved endpoints. API responses must include all persisted progress fields, `phase`, `candidate_id`, and a stable `schema_version: continuous-generation-job/v1`.

6. On first read, load `latest.json`, reconcile against `store.summary().current_chapter`, then:
   - submit if the phase is safely resumable and no worker is registered;
   - leave terminal jobs unchanged;
   - return `stopped/recovery_confirmation_required` for ambiguous work.

7. Ensure the runner's `finally` block clears only its own active-job registration. It must not clear or overwrite an unrelated newer job.

8. Run route and existing generation-job regression tests:

   ```powershell
   uv run pytest -q tests/api/test_continuous_generation_routes.py tests/api/test_file_project_routes.py tests/api/test_story_routes.py -k "generation_job or candidate or volume"
   ```

### Task 4: Add typed web API calls

**Files:**
- Modify: `apps/web/lib/api.ts`
- Test: `apps/web/tests/story-workbench.spec.ts`

1. Define:

   ```typescript
   export type ContinuousGenerationStatus =
     | "queued" | "running" | "stopping" | "completed" | "stopped" | "failed";

   export type ContinuousGenerationJobResponse = {
     schema_version: "continuous-generation-job/v1";
     job_id: string;
     project_id: string;
     status: ContinuousGenerationStatus;
     phase: string;
     requested_count: number;
     completed_count: number;
     start_chapter: number;
     current_chapter: number;
     completed_chapters: number[];
     candidate_id: string;
     stop_requested: boolean;
     progress: string;
     stop_reason: string;
     error: string;
     created_at: string;
     updated_at: string;
   };
   ```

2. Add `startContinuousGeneration`, `fetchCurrentContinuousGeneration`, `fetchContinuousGenerationJob`, and `stopContinuousGeneration`. Keep their timeout short because model generation runs in the backend, not inside the HTTP request.

3. Add a Playwright request-mocking test first so path, request body, and response shape are fixed before wiring the page.

4. Run the focused Playwright test and confirm the API expectation passes.

### Task 5: Add the continuous-generation controls and persisted progress UI

**Files:**
- Modify: `apps/web/app/projects/[id]/write/page.tsx`
- Modify: `apps/web/app/globals.css` only if existing workbench controls cannot express the layout
- Test: `apps/web/tests/story-workbench.spec.ts`

1. Add failing Playwright scenarios for:
   - the selector offering 2, 5, 10, and 20 with 5 selected by default;
   - starting a five-chapter backend job with one click;
   - polling the current job after page reload;
   - showing `已完成 2/5，正在生成第 153 章`;
   - disabling generate-next, rewrite, expansion, and another continuous start while active;
   - requesting stop and showing `当前章节完成后停止`;
   - linking `next_volume_required` and `volume_detail_required` to the correct outline tab and chapter;
   - linking `candidate_confirmation_required` to the pending candidate chapter;
   - refreshing chapters and opening the last completed chapter after completion.

2. Run the new focused scenarios and confirm they fail before implementation.

3. Add page state for selected count, current continuous job, loading/error, and polling timer. Poll only while status is `queued`, `running`, or `stopping`; cancel timers on unmount.

4. Render the controls in the existing chapter toolbar or immediately below it. Use the existing button, badge, and card styles. The selector remains visible for every confirmed chapter, not only when content is short.

5. Do not create a browser generation loop. The page sends one start request and then only reads status.

6. Make all existing write actions consult one `generationBusy` value that includes both normal and continuous jobs.

7. Run the focused Playwright scenarios.

### Task 6: Verify recovery, candidate preservation, and no automatic rewrites

**Files:**
- Modify only if tests expose a defect in the files above
- Test: `tests/api/test_continuous_generation_service.py`
- Test: `tests/api/test_continuous_generation_routes.py`
- Test: `tests/story_core/test_candidate_confirmation_transaction.py`
- Test: `apps/web/tests/story-workbench.spec.ts`

1. Add an acceptance test that requests five chapters, confirms two, encounters missing detail on the third target, and asserts:
   - the first two official chapter files exist;
   - `completed_chapters` contains exactly those two chapters;
   - the job is `stopped/volume_detail_required`;
   - no rewrite or expansion method was called.

2. Add a crash-recovery test for each durable boundary:
   - safe `queued` resumes;
   - safe `between_chapters` resumes from the next official chapter;
   - official chapter advanced but job count lagged is reconciled once;
   - `generating` and `confirming` stop for human inspection;
   - a pending candidate remains available after confirmation is blocked.

3. Run focused Python verification:

   ```powershell
   uv run pytest -q tests/api/test_continuous_generation_service.py tests/api/test_continuous_generation_routes.py tests/api/test_file_project_routes.py tests/story_core/test_candidate_confirmation_transaction.py
   ```

4. Run focused browser verification:

   ```powershell
   Set-Location apps/web
   pnpm exec playwright test tests/story-workbench.spec.ts --grep "连续生成"
   ```

5. Run the full regression gates:

   ```powershell
   Set-Location D:\xiaoshuofish-flow-test
   uv run pytest -q
   Set-Location apps/web
   pnpm run build
   ```

6. Start the backend and frontend, use a disposable file project with complete volume detail, and run two chapters end to end. Verify the job JSON, official chapter files, candidate statuses, page progress, stop button, and reload recovery. Do not use the user's production novel for destructive testing.

7. Run `git diff --check`, inspect only the intended files, and report exact test results and any remaining model-provider risk. Do not stage unrelated dirty-worktree files.
