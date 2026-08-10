# Continuation Import Outline Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every continuation import produce an evidence-backed overall outline, full-book arc outline, completed core character cards, normalized world context, and a five-chapter rolling outline beginning after the imported chapter.

**Architecture:** Keep source scanning and atomic baseline creation in `continuation_project.py`. Add a focused `ContinuationOutlineBootstrapper` that runs after the baseline project exists. When foundation layers are missing it reuses `FileProjectStore.generate_outline_plan(..., mode="regenerate", persist_chapter_window=False)` and converts the returned detailed window into the independent rolling schema; when an old project already has approved overall/arcs/characters it calls a rolling-only generator and never rewrites the three-level outline. It persists phase checkpoints and marks the project ready only after a pure readiness validator passes. API calls run it in a background executor and read status from disk, so reload and retry do not lose progress.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, pytest, Next.js/React/TypeScript, existing `LLMOutlinePlanningGenerator`, `FileProjectStore`, and `RollingOutlineStore`.

---

## File Map

- Create `packages/story_core/continuation_outline_bootstrap.py`: contracts, checkpoint persistence, chapter conversion, readiness validation, orchestration.
- Modify `packages/story_core/continuation_project.py`: baseline import only; no fabricated future outline.
- Modify `packages/story_core/outline_planning_generation.py`: rolling-compatible chapter-window output.
- Modify `packages/story_core/file_project_store.py`: optionally keep generated chapter detail out of the legacy outline and preserve imported facts/manual edits.
- Modify `apps/api/routes/continuation_imports.py`: enqueue bootstrap after project creation.
- Modify `apps/api/routes/file_projects.py`: bootstrap start/status/retry endpoints.
- Modify `apps/web/components/ContinuationImportWizard.tsx`: make outline bootstrap mandatory.
- Modify `apps/web/app/projects/[id]/outline/page.tsx`: progress, artifacts, retry, legacy backfill.
- Modify `apps/web/lib/api.ts`: bootstrap API types and clients.
- Add or modify focused backend/frontend tests listed below.

### Task 1: Readiness contracts

**Files:**
- Create: `packages/story_core/continuation_outline_bootstrap.py`
- Create: `tests/story_core/test_continuation_outline_bootstrap.py`

- [ ] **Step 1: Write failing tests**

Create fixtures with current chapter 147 and test these exact results:

```python
def test_readiness_requires_future_arc_covering_next_chapter(tmp_path):
    root = seed_imported_project(tmp_path, future_arc=False, rolling=True)
    result = validate_continuation_bootstrap(root)
    assert not result.ready
    assert "import_future_arc_required" in result.errors

def test_readiness_requires_rolling_target_chapter(tmp_path):
    root = seed_imported_project(tmp_path, future_arc=True, rolling=False)
    result = validate_continuation_bootstrap(root)
    assert not result.ready
    assert "import_chapter_window_required:148" in result.errors

def test_readiness_accepts_complete_import(tmp_path):
    root = seed_imported_project(tmp_path, future_arc=True, rolling=True)
    result = validate_continuation_bootstrap(root)
    assert result.ready
    assert result.errors == []
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/story_core/test_continuation_outline_bootstrap.py -q`

Expected: collection fails because the new module does not exist.

- [ ] **Step 3: Implement the pure validator**

Expose:

```python
BootstrapPhaseId = Literal[
    "source_analysis", "outline_foundation", "character_roster",
    "world_context", "chapter_window", "readiness_check",
]
BOOTSTRAP_PHASES: tuple[BootstrapPhaseId, ...] = (...)
class BootstrapReadiness(BaseModel):
    ready: bool
    next_chapter: int
    errors: list[str] = Field(default_factory=list)
def validate_continuation_bootstrap(project_root: str | Path) -> BootstrapReadiness: ...
```

Validate concrete files, not `pipeline_stage`: overall core fields; an arc covering current chapter; a future arc covering next chapter; a real protagonist card; world premise plus rules or power-system content; rolling detail for next chapter; current chapter matching imported chapters.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/continuation_outline_bootstrap.py tests/story_core/test_continuation_outline_bootstrap.py
git commit -m "feat: validate continuation import readiness"
```

### Task 2: Separate baseline import from planning

**Files:**
- Modify: `packages/story_core/continuation_project.py:48-84`
- Modify: `packages/story_core/continuation_project.py:689-824`
- Modify: `packages/story_core/continuation_project.py:933-1076`
- Modify: `tests/story_core/test_continuation_project.py`

- [ ] **Step 1: Add failing tests**

```python
def test_import_baseline_has_no_template_future_plot(tmp_path):
    created = create_test_continuation_project(tmp_path, start_after_chapter=12)
    outline = read_json(created.root / ".webnovel/outline.json")
    project = read_json(created.root / ".webnovel/project.json")
    assert outline["chapters"] == []
    assert not [arc for arc in outline["arcs"] if arc["start_chapter"] > 12]
    assert project["pipeline_stage"] == "outline_bootstrapping"

def test_import_cannot_disable_outline_bootstrap():
    with pytest.raises(ValueError):
        ContinuationSettings(
            start_after_chapter=12,
            generate_outline=False,
            outline_chapters=0,
        )
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/story_core/test_continuation_project.py -q`

Expected: old `_continuation_outline()` still creates future templates.

- [ ] **Step 3: Implement**

Keep wire compatibility but require planning:

```python
generate_outline: Literal[True] = True
outline_chapters: int = Field(default=5, ge=5, le=10)
```

Replace `_continuation_outline()` with an evidence-only historical baseline. It may record imported history, but must contain no future arc or chapter rows. Set `pipeline_stage="outline_bootstrapping"`. Do not call a model inside project creation or validation.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/story_core/test_continuation_project.py tests/story_core/test_continuation_sessions.py -q`

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/continuation_project.py tests/story_core/test_continuation_project.py
git commit -m "refactor: separate import baseline from planning"
```

### Task 3: Generate rolling-compatible chapter detail

**Files:**
- Modify: `packages/story_core/outline_planning_generation.py:166-176`
- Modify: `packages/story_core/outline_planning_generation.py:750-804`
- Modify: `packages/story_core/continuation_outline_bootstrap.py`
- Modify: `tests/story_core/test_continuation_outline_bootstrap.py`
- Modify: `tests/story_core/test_outline_planning_generation.py`

- [ ] **Step 1: Add failing conversion tests**

Assert that generated chapters 148 and 149 convert to valid rolling rows, and that blank gain/cost, fewer than two scenes, unknown cast, or wrong chapter number fails before disk writes.

```python
batch = rolling_batch_from_generated_window(
    chapters=[detailed_chapter(148), detailed_chapter(149)],
    character_cards=[character_card("林修", "protagonist")],
    volume_range=(148, 160),
)
assert [row["chapter_number"] for row in batch] == [148, 149]
validate_rolling_batch(
    batch,
    expected_chapter_numbers=[148, 149],
    volume_range=(148, 160),
)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/story_core/test_continuation_outline_bootstrap.py tests/story_core/test_outline_planning_generation.py -q`

- [ ] **Step 3: Extend only the generation-phase model**

```python
class GeneratedDetailedChapter(ChapterPlan):
    core_conflict: str = Field(min_length=1)
    gain: str = Field(min_length=1)
    cost: str = Field(min_length=1)
    foreshadowing: list[str] = Field(default_factory=list)
    state_delta_summary: str = Field(min_length=1)
    scene_chain: list[ChapterScenePlan] = Field(min_length=2, max_length=4)
```

Use it in `GeneratedChapterWindow`. Update only the chapter-window prompt. Before merging into `ProjectOutline`, project rows back through `ChapterPlan.model_validate()` so generation-only keys never enter the three-level outline schema.

- [ ] **Step 4: Implement deterministic conversion**

Map `goal → chapter_goal`, `core_conflict`, real cast cards, `scene_chain → scenes`, `gain`, `cost`, `foreshadowing`, `ending_hook → hook`, and `state_delta_summary → state_delta`. Validate the whole batch with `validate_rolling_batch()`.

In `continuation_outline_bootstrap.py`, define a narrow batch interface for projects that already have approved foundation layers:

```python
class RollingWindowGenerator(Protocol):
    def generate(
        self,
        *,
        context: dict[str, Any],
        chapter_numbers: list[int],
        volume_range: tuple[int, int],
    ) -> list[dict[str, Any]]: ...

class LLMRollingWindowGenerator:
    def generate(self, *, context, chapter_numbers, volume_range): ...
```

The production implementation makes one planner-stage JSON call for the complete window, validates the returned batch, and has no filesystem access. Its context contains only the approved active arc, three recent summaries, relevant character cards, compact world rules, open foreshadowing, and exact requested chapter numbers.

- [ ] **Step 5: Verify GREEN and commit**

Run the Task 3 test command, then:

```powershell
git add packages/story_core/outline_planning_generation.py packages/story_core/continuation_outline_bootstrap.py tests/story_core/test_continuation_outline_bootstrap.py tests/story_core/test_outline_planning_generation.py
git commit -m "feat: generate rolling-compatible chapter windows"
```

### Task 4: Resumable bootstrap orchestrator

**Files:**
- Modify: `packages/story_core/continuation_outline_bootstrap.py`
- Modify: `packages/story_core/file_project_store.py:5640-6168`
- Modify: `tests/story_core/test_continuation_outline_bootstrap.py`

- [ ] **Step 1: Add failing orchestration tests**

Test: full baseline reaches ready; retry skips completed phases; changed input invalidates the changed phase and later phases; manual overall/character/rolling fields remain unchanged; invalid chapter batch writes nothing. Add a legacy fixture whose overall/arcs/characters are already valid and assert the planning generator is not called while the rolling-only generator is called for chapters 148–152.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/story_core/test_continuation_outline_bootstrap.py -q`

- [ ] **Step 3: Persist checkpoints**

Write atomically to `.story-system/continuation-bootstrap/checkpoint.json`:

```json
{
  "schema_version": "continuation-bootstrap/v1",
  "input_fingerprint": "sha256",
  "status": "running",
  "phases": [
    {"id": "source_analysis", "status": "completed", "artifact": {}, "error": ""}
  ]
}
```

Fingerprint confirmed analysis, genre, continuation point, source fingerprint, and guidance. Reuse completed phases only when their input fingerprint matches.

- [ ] **Step 4: Implement `ContinuationOutlineBootstrapper.run()`**

It must:

1. Require confirmed continuation analysis.
2. Inspect readiness before calling a model and mark already-valid layers as adopted checkpoints.
3. When foundation or roster is missing, call `FileProjectStore.generate_outline_plan(planning_generator, mode="regenerate", persist_chapter_window=False)` and reuse its `outline_foundation`, `character_roster`, and `chapter_window` callbacks.
4. Add the optional `persist_chapter_window` parameter to `generate_outline_plan()` and `save_generated_outline_plan()`; default it to `True` so existing new-book behavior is unchanged. With `False`, validate and return generated chapter detail but persist only overall/arcs/characters plus committed historical chapter rows.
5. When only chapter detail is missing, call an injected rolling-only generator with the approved current arc, recent summaries, character cards, world context, and requested numbers. Do not call the full planning generator.
6. Normalize confirmed world claims without a second model call.
7. Convert and atomically write exactly five future rows with `RollingOutlineStore.apply_rolling_batch()`.
8. Run readiness validation.
9. Set `pipeline_stage="world_ready"` only on success.

Do not overwrite committed history or rows marked manual.

- [ ] **Step 5: Verify GREEN**

Run:

`python -m pytest tests/story_core/test_continuation_outline_bootstrap.py tests/story_core/test_file_project_store.py tests/story_core/test_rolling_outline_integration.py -q`

- [ ] **Step 6: Commit**

```powershell
git add packages/story_core/continuation_outline_bootstrap.py packages/story_core/file_project_store.py tests/story_core/test_continuation_outline_bootstrap.py
git commit -m "feat: bootstrap imported project writing foundations"
```

### Task 5: Background API, status, and retry

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `apps/api/routes/continuation_imports.py:46-103`
- Modify: `apps/api/routes/continuation_imports.py:655-735`
- Modify: `tests/api/test_continuation_import_routes.py`
- Modify: `tests/api/test_outline_rolling_routes.py`

- [ ] **Step 1: Add failing API tests**

Verify:

- project creation returns `bootstrap_status` and `next_path` containing `bootstrap=1`;
- status survives clearing route-process memory because it comes from disk;
- retry queues only the first failed phase;
- duplicate starts do not duplicate model calls;
- `generate_outline=false` returns 422;
- body generation remains 409 until bootstrap readiness succeeds.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/api/test_continuation_import_routes.py tests/api/test_outline_rolling_routes.py -q`

- [ ] **Step 3: Implement endpoints**

Add a dedicated single-worker executor and:

- `POST /file-projects/{project_id}/continuation-bootstrap` → 202
- `GET /file-projects/{project_id}/continuation-bootstrap` → persisted status

After atomic baseline creation, enqueue bootstrap and return immediately. Map unconfirmed/running to 409, invalid imported data to 422, invalid model output to 502, unavailable runtime to 503.

- [ ] **Step 4: Verify GREEN and commit**

Run the Task 5 command, then:

```powershell
git add apps/api/routes/file_projects.py apps/api/routes/continuation_imports.py tests/api/test_continuation_import_routes.py tests/api/test_outline_rolling_routes.py
git commit -m "feat: expose continuation bootstrap jobs"
```

### Task 6: Frontend progress and mandatory planning

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/components/ContinuationImportWizard.tsx`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify or add tests under the repository's existing frontend test convention.

- [ ] **Step 1: Add failing UI tests**

Verify: optional-outline checkbox is absent; request always sends `generate_outline:true` and `outline_chapters:5`; `?bootstrap=1` shows all six phases; failed phase shows error and retry; legacy import shows “补齐导入资料”; writing action is unavailable before ready.

- [ ] **Step 2: Add API types**

Define `ContinuationBootstrapPhase` and `ContinuationBootstrapStatus`, plus `fetchContinuationBootstrap(projectId)` and `startContinuationBootstrap(projectId)`.

- [ ] **Step 3: Update UI**

Replace the old switch/number field with “导入后自动生成5章细纲”. Poll only while queued/running. Render persisted phase artifacts in `details`. A legacy project requires an explicit backfill click; page load must not silently call a model.

- [ ] **Step 4: Verify**

Run:

```powershell
cd apps/web
npx tsc --noEmit
```

Also run the frontend test script defined in `apps/web/package.json`, when present.

- [ ] **Step 5: Commit**

```powershell
git add apps/web/lib/api.ts apps/web/components/ContinuationImportWizard.tsx 'apps/web/app/projects/[id]/outline/page.tsx'
git commit -m "feat: show continuation bootstrap progress"
```

### Task 7: Safe legacy-project backfill

**Files:**
- Modify: `packages/story_core/continuation_outline_bootstrap.py`
- Create: `scripts/backfill_continuation_outline.py`
- Create: `tests/scripts/test_backfill_continuation_outline.py`

- [ ] **Step 1: Add failing tests with the current-book shape**

Fixture: complete manual overall, 17 arcs through chapter 300, 147 committed chapters, no rolling file. Dry-run must report only `chapter_window` and `readiness_check` missing. Apply must leave `.webnovel/outline.json` byte-identical and add rolling chapters 148–152.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/scripts/test_backfill_continuation_outline.py -q`

- [ ] **Step 3: Implement dry-run-first script**

Commands:

```powershell
python scripts/backfill_continuation_outline.py <project-root> --dry-run
python scripts/backfill_continuation_outline.py <project-root> --apply
```

Dry-run prints current chapter, present layers, missing phases, next window, and proposed files. Apply creates a timestamped backup under `.story-system/backups/continuation-bootstrap/`, runs only missing phases, and rejects non-continuation projects.

- [ ] **Step 4: Verify GREEN and commit**

```powershell
python -m pytest tests/scripts/test_backfill_continuation_outline.py tests/story_core/test_continuation_outline_bootstrap.py -q
git add packages/story_core/continuation_outline_bootstrap.py scripts/backfill_continuation_outline.py tests/scripts/test_backfill_continuation_outline.py
git commit -m "feat: backfill imported project outline layers"
```

### Task 8: Full and real-project acceptance

- [ ] **Step 1: Run focused backend suites**

```powershell
python -m pytest tests/story_core/test_continuation_analysis.py tests/story_core/test_continuation_import.py tests/story_core/test_continuation_project.py tests/story_core/test_continuation_outline_bootstrap.py tests/api/test_continuation_import_routes.py tests/api/test_outline_rolling_routes.py -q
```

- [ ] **Step 2: Run complete verification**

```powershell
python -m pytest -q
cd apps/web
npx tsc --noEmit
cd ../..
git diff --check
```

Expected: all tests pass; existing skips and line-ending warnings are allowed, whitespace errors are not.

- [ ] **Step 3: Dry-run the current project**

```powershell
python scripts/backfill_continuation_outline.py "D:\\xiaoshuofish-flow-test\\data\\exported-projects\\p-da2c16a6ee9440d6ad52cb402ead88a0" --dry-run
```

Expected: current chapter 147; overall present; 17 arcs; future arc starts at 148; missing `chapter_window` and `readiness_check`; proposed rolling window 148–152; no file changed.

- [ ] **Step 4: Apply through the UI**

Click “补齐导入资料”. Wait for ready. Confirm outlines 148–152 appear and chapter 148正文 still does not exist.

- [ ] **Step 5: Verify the body gate**

Before backfill, chapter 148 generation returns 409 `chapter_outline_required:148`. After backfill it may create a job. Stop or discard the candidate before confirmation so acceptance does not modify the novel正文.

- [ ] **Step 6: Record evidence**

The implementation handoff must include exact pytest counts, TypeScript result, preserved outline hash, bootstrap phase statuses, and rolling chapter numbers.

## Acceptance Checklist

- [ ] Import cannot disable outline initialization.
- [ ] Baseline creation performs no model call and fabricates no future plot.
- [ ] Imported history and future plans are distinct.
- [ ] Overall and arcs cover the planned book.
- [ ] Only the next five chapters get detailed rolling outlines.
- [ ] Past正文 and facts remain unchanged.
- [ ] Manual outline, character, and rolling edits remain unchanged.
- [ ] Progress and artifacts survive reload.
- [ ] Retry resumes from the first failed phase.
- [ ] Project is not write-ready before readiness passes.
- [ ] Missing detail still blocks正文 generation with HTTP 409.
- [ ] 《万界维修工：从家电到仙器》 keeps 147正文 chapters and gains only outlines 148–152.
