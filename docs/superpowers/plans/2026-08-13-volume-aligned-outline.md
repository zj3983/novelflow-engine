# Volume-Aligned Outline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every non-final volume at least 50 chapters, place a concrete story node at most every 15 chapters, generate chapter outlines for a complete volume before prose writing starts, and show the exact blocked next step in the workbench.

**Architecture:** Add a pure volume-domain module as the single source of truth for boundaries, nodes, batches, and workflow state. Keep volume planning separate from chapter-detail generation: the outline generator produces a complete volume plan, then a coordinator generates 15-chapter detail batches into resumable checkpoints and publishes them atomically as one complete volume. Backend status endpoints and both outline/write pages consume the same derived workflow state.

**Tech Stack:** Python 3.11, Pydantic 2, FastAPI, pytest, Next.js 14, React 18, TypeScript, Playwright.

---

## File Structure

- Create `packages/story_core/volume_outline.py`: pure volume validation, active/next-volume lookup, 15-chapter node coverage, detail batches, and workflow-state derivation.
- Create `packages/story_core/volume_detail_checkpoints.py`: project-local resumable batch manifest and atomic payload storage.
- Create `packages/story_core/volume_outline_migration.py`: deterministic legacy-volume consolidation without changing chapter bodies or continuity state.
- Create `scripts/migrate_volume_outlines.py`: dry-run/apply migration for every file project.
- Modify `packages/story_core/project_outline.py`: persist final-volume marker and concrete story nodes.
- Modify `packages/story_core/outline_planning.py`: use volume-domain validation in generated-plan validation.
- Modify `packages/story_core/outline_planning_generation.py`: generate complete volume foundations and explicit 15-chapter detail batches.
- Modify `packages/story_core/file_project_store.py`: coordinate full-volume generation, expose workflow state, enforce the prose gate, and apply migration.
- Modify `packages/story_core/elastic_outline.py`: delegate legacy window status to full-volume missing-detail calculation.
- Modify `apps/api/routes/file_projects.py`: expose volume workflow, design-next-volume, and generate/continue-volume-detail endpoints.
- Modify `apps/web/lib/api.ts`: add volume models and API clients.
- Modify `apps/web/app/projects/[id]/outline/page.tsx`: render volume state, nodes, progress, and the correct single action.
- Modify `apps/web/app/projects/[id]/write/page.tsx`: render the current volume and redirect with a precise reason.
- Add focused pytest and Playwright coverage listed below.

### Task 1: Define the volume domain model

**Files:**
- Create: `packages/story_core/volume_outline.py`
- Modify: `packages/story_core/project_outline.py`
- Test: `tests/story_core/test_volume_outline.py`
- Test: `tests/story_core/test_project_outline.py`

- [ ] **Step 1: Write failing model and pure-domain tests**

```python
def test_non_final_volume_must_have_at_least_fifty_chapters():
    arc = arc_payload(start_chapter=1, end_chapter=49, is_final_arc=False)
    with pytest.raises(ValueError, match="volume_too_short:opening"):
        validate_volume_structure([arc], core_ending_chapter=120)


def test_final_volume_may_be_shorter_than_fifty_chapters():
    arc = arc_payload(start_chapter=101, end_chapter=120, is_final_arc=True)
    validate_volume_structure([arc], core_ending_chapter=120)


def test_story_nodes_cover_volume_without_more_than_fifteen_chapter_gap():
    arc = arc_payload(
        start_chapter=1,
        end_chapter=60,
        story_nodes=[node(1, 15), node(16, 30), node(31, 45), node(46, 60)],
    )
    assert validate_volume_structure([arc], core_ending_chapter=60)[0]["id"] == "opening"
```

- [ ] **Step 2: Run tests and verify the missing types/functions fail**

Run: `python -m pytest tests/story_core/test_volume_outline.py tests/story_core/test_project_outline.py -q`

Expected: FAIL because `StoryNode`, `validate_volume_structure`, and the new arc fields do not exist.

- [ ] **Step 3: Add the persisted types and pure helpers**

```python
# packages/story_core/project_outline.py
class StoryNode(_OutlineModel):
    start_chapter: int = Field(ge=1, strict=True)
    end_chapter: int = Field(ge=1, strict=True)
    objective: str = ""
    pressure: str = ""
    turn: str = ""
    payoff: str = ""
    next_effect: str = ""


class ArcOutline(_OutlineModel):
    # existing fields remain
    is_final_arc: bool = False
    story_nodes: list[StoryNode] = Field(default_factory=list)
```

```python
# packages/story_core/volume_outline.py
MIN_VOLUME_CHAPTERS = 50
STORY_NODE_INTERVAL = 15
DETAIL_BATCH_SIZE = 15
VolumeWorkflowStatus = Literal[
    "volume_missing", "volume_plan_ready", "detail_partial",
    "ready_to_write", "volume_complete", "book_complete",
]

def volume_detail_batches(start: int, end: int) -> list[list[int]]:
    numbers = list(range(start, end + 1))
    return [numbers[index:index + DETAIL_BATCH_SIZE] for index in range(0, len(numbers), DETAIL_BATCH_SIZE)]
```

Implement `validate_volume_structure`, `find_volume_for_chapter`, `find_next_volume`, and `derive_volume_workflow` without file I/O. Require continuous non-overlapping arcs, exact node coverage, non-empty node content, one final volume at the end, and a final volume ending at `core_ending_chapter`.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/story_core/test_volume_outline.py tests/story_core/test_project_outline.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the domain layer**

```powershell
git add packages/story_core/volume_outline.py packages/story_core/project_outline.py tests/story_core/test_volume_outline.py tests/story_core/test_project_outline.py
git commit -m "feat: define volume outline rules"
```

### Task 2: Enforce the same volume rules in generation and saving

**Files:**
- Modify: `packages/story_core/outline_planning.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing parity tests**

```python
@pytest.mark.parametrize("layer", ["generated", "saved"])
def test_non_final_short_volume_is_rejected_by_both_layers(layer, prepared_plan, store):
    prepared_plan.outline.arcs[0].end_chapter = 30
    prepared_plan.outline.arcs[0].is_final_arc = False
    with pytest.raises(ValueError, match="volume_too_short"):
        validate_or_save(layer, prepared_plan, store)


def test_generated_final_short_volume_is_allowed(prepared_plan):
    prepared_plan.outline.arcs[-1].is_final_arc = True
    prepared_plan.outline.arcs[-1].start_chapter = 101
    prepared_plan.outline.arcs[-1].end_chapter = 120
    validate_generated_opening_plan(prepared_plan, expected_chapter_numbers=[])
```

- [ ] **Step 2: Run the parity tests and verify they fail at the missing rule**

Run: `python -m pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py -k "volume_too_short or final_short_volume" -q`

Expected: FAIL because both paths currently accept short arcs.

- [ ] **Step 3: Call one validator from both layers**

In `validate_generated_opening_plan` and `validate_generated_continuation_plan`, call:

```python
validate_volume_structure(
    plan.outline.arcs,
    core_ending_chapter=plan.outline.overall.core_ending_chapter,
)
```

In `FileProjectStore.save_generated_outline_plan`, call the same function after committed-outline preservation and before `_atomic_write_jsons`. Do not duplicate the minimum-length calculation in the store.

- [ ] **Step 4: Run generation/store suites**

Run: `python -m pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py -q`

Expected: PASS.

- [ ] **Step 5: Commit validation parity**

```powershell
git add packages/story_core/outline_planning.py packages/story_core/file_project_store.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py
git commit -m "feat: enforce complete volume boundaries"
```

### Task 3: Replace the ten-chapter window with full-volume batch planning

**Files:**
- Modify: `packages/story_core/elastic_outline.py`
- Modify: `packages/story_core/outline_rolling.py`
- Test: `tests/story_core/test_elastic_outline.py`
- Test: `tests/story_core/test_rolling_outline_planner.py`

- [ ] **Step 1: Write failing full-volume selection tests**

```python
def test_missing_detail_targets_the_whole_active_volume():
    status = outline_window_status(
        outline_with_volume(153, 212, detailed=range(153, 163)),
        current_chapter=152,
    )
    assert status["target_volume_range"] == [153, 212]
    assert status["next_chapter_numbers"] == list(range(163, 213))
    assert status["detail_batches"][0] == list(range(163, 178))


def test_detail_batches_never_cross_volume_boundary():
    assert plan_volume_detail_batches((153, 212), existing=range(153, 208)) == [list(range(208, 213))]
```

- [ ] **Step 2: Run tests and verify current 10/5-chapter behavior fails**

Run: `python -m pytest tests/story_core/test_elastic_outline.py tests/story_core/test_rolling_outline_planner.py -q`

Expected: FAIL because `DETAIL_WINDOW = 10` and rolling `window=5` truncate the target.

- [ ] **Step 3: Delegate range and batch calculation to `volume_outline.py`**

Return these stable fields from `outline_window_status`:

```python
{
    "target_volume_id": arc["id"],
    "target_volume_range": [arc["start_chapter"], arc["end_chapter"]],
    "missing_chapter_numbers": missing,
    "detail_batches": volume_detail_batches_for_missing(arc, planned_numbers),
    "detail_status": "complete" if not missing else "partial" if planned_numbers_in_arc else "missing",
}
```

Keep old response keys during this task as compatibility aliases, but derive them from the full-volume result. Remove use of `DETAIL_WINDOW` and do not introduce another fixed future-window constant.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/story_core/test_elastic_outline.py tests/story_core/test_rolling_outline_planner.py -q`

Expected: PASS.

- [ ] **Step 5: Commit full-volume selection**

```powershell
git add packages/story_core/elastic_outline.py packages/story_core/outline_rolling.py tests/story_core/test_elastic_outline.py tests/story_core/test_rolling_outline_planner.py
git commit -m "feat: plan chapter detail by complete volume"
```

### Task 4: Add resumable 15-chapter volume-detail checkpoints

**Files:**
- Create: `packages/story_core/volume_detail_checkpoints.py`
- Test: `tests/story_core/test_volume_detail_checkpoints.py`

- [ ] **Step 1: Write failing checkpoint tests**

```python
def test_checkpoint_manifest_contains_one_entry_per_volume_batch(tmp_path):
    store = VolumeDetailCheckpointStore(tmp_path)
    manifest = store.prepare(volume_id="v3", batches=[[153, 167], [168, 182], [183, 197], [198, 212]])
    assert [item["id"] for item in manifest["batches"]] == [
        "0153-0167", "0168-0182", "0183-0197", "0198-0212",
    ]


def test_completed_batches_survive_retry_and_failed_batch_is_resumable(tmp_path):
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(volume_id="v3", batches=[[153, 167], [168, 182]])
    store.complete("0153-0167", {"chapters": chapter_rows(153, 167)})
    store.fail("0168-0182", "timeout")
    assert list(store.completed_payloads()) == ["0153-0167"]
    assert store.next_incomplete_batch()["id"] == "0168-0182"
```

- [ ] **Step 2: Run tests and verify the store is missing**

Run: `python -m pytest tests/story_core/test_volume_detail_checkpoints.py -q`

Expected: FAIL with import error.

- [ ] **Step 3: Implement atomic manifest/payload storage**

Use schema `volume-detail-checkpoints/v1`, path `.story-system/volume-detail/<volume-id>/`, and statuses `waiting`, `running`, `completed`, `failed`. Fingerprint `volume_id`, range, node data, existing outline version, and user guidance. A fingerprint change invalidates all batches; a retry with the same fingerprint retains completed payloads.

- [ ] **Step 4: Run checkpoint tests**

Run: `python -m pytest tests/story_core/test_volume_detail_checkpoints.py -q`

Expected: PASS.

- [ ] **Step 5: Commit checkpoint storage**

```powershell
git add packages/story_core/volume_detail_checkpoints.py tests/story_core/test_volume_detail_checkpoints.py
git commit -m "feat: checkpoint volume detail batches"
```

### Task 5: Generate one complete volume through 15-chapter batches

**Files:**
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing coordinator tests**

```python
def test_generate_volume_detail_calls_model_once_per_fifteen_chapter_batch(store, recording_generator):
    result = store.generate_volume_detail(recording_generator, volume_id="v3")
    assert recording_generator.chapter_batches == [
        list(range(153, 168)), list(range(168, 183)),
        list(range(183, 198)), list(range(198, 213)),
    ]
    assert result["detail_status"] == "complete"


def test_failed_second_batch_keeps_first_and_retry_starts_at_second(store, fail_once_generator):
    with pytest.raises(ValueError, match="volume_detail_generation_failed:0168-0182"):
        store.generate_volume_detail(fail_once_generator, volume_id="v3")
    store.generate_volume_detail(fail_once_generator, volume_id="v3")
    assert fail_once_generator.calls.count(tuple(range(153, 168))) == 1
```

- [ ] **Step 2: Run tests and verify coordinator methods are missing**

Run: `python -m pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py -k "volume_detail" -q`

Expected: FAIL because no complete-volume coordinator exists.

- [ ] **Step 3: Extract an explicit chapter-batch generator**

Add this public method to `LLMOutlinePlanningGenerator` and move the current inner `chapter_window` prompt/validation into it:

```python
def generate_chapter_batch(
    self,
    brief: OutlinePlanningBrief,
    *,
    volume: dict[str, Any],
    chapter_numbers: list[int],
    previous_batches: list[dict[str, Any]],
    guidance: str = "",
) -> GeneratedChapterWindow:
    ...
```

The prompt must include the full volume goal and all `story_nodes`, the current batch node, previous batch endings, committed facts, and the required volume ending. It must not ask the model to redesign the volume.

- [ ] **Step 4: Implement `FileProjectStore.generate_volume_detail`**

For each incomplete checkpoint batch, call `generate_chapter_batch`, validate exact chapter numbers and continuity, and complete that checkpoint. After every batch is complete, merge all payloads in chapter order and write them through `RollingOutlineStore.apply_rolling_batch` in one final publish step. Return:

```python
{
    "schema_version": "volume-detail-generation/v1",
    "volume_id": volume_id,
    "volume_range": [start, end],
    "detail_status": "complete",
    "completed_chapters": total,
    "total_chapters": total,
    "batches": checkpoint_statuses,
}
```

- [ ] **Step 5: Run generation/store suites**

Run: `python -m pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py tests/story_core/test_outline_rolling_store.py -q`

Expected: PASS.

- [ ] **Step 6: Commit complete-volume generation**

```powershell
git add packages/story_core/outline_planning_generation.py packages/story_core/file_project_store.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py
git commit -m "feat: generate complete volume detail"
```

### Task 6: Design the next volume before detail generation

**Files:**
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing next-volume workflow tests**

```python
def test_completed_volume_without_successor_requires_volume_design(store):
    status = store.volume_workflow_status(target_chapter=61)
    assert status["status"] == "volume_missing"
    assert status["next_action"] == "design_next_volume"


def test_design_next_volume_creates_plan_but_not_chapter_detail(store, generator):
    result = store.design_next_volume(generator)
    assert result["status"] == "volume_plan_ready"
    assert result["volume_range"] == [61, 120]
    assert RollingOutlineStore(store.root).read_chapter(61) is None
```

- [ ] **Step 2: Run tests and verify the explicit state/action is absent**

Run: `python -m pytest tests/story_core/test_file_project_store.py tests/story_core/test_outline_planning_generation.py -k "design_next_volume or volume_missing" -q`

Expected: FAIL.

- [ ] **Step 3: Add a volume-only generator method**

```python
def generate_next_volume(
    self,
    brief: OutlinePlanningBrief,
    *,
    previous_volume: ArcOutline,
    guidance: str = "",
) -> ArcOutline:
    ...
```

Require `start_chapter == previous_volume.end_chapter + 1`, at least 50 chapters unless `is_final_arc`, complete node coverage, a resolved volume conflict, and a `next_arc_entry` unless final. The model receives total outline, committed facts, unresolved foreshadowing, character states, and the prior volume end state.

- [ ] **Step 4: Save only the new volume plan**

Implement `FileProjectStore.design_next_volume` using optimistic outline version checking. It appends one non-overlapping arc and writes no rolling chapter rows. If a successor already exists, return `volume_plan_ready` without another model call.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/story_core/test_file_project_store.py tests/story_core/test_outline_planning_generation.py -k "next_volume or volume_missing" -q`

Expected: PASS.

- [ ] **Step 6: Commit next-volume planning**

```powershell
git add packages/story_core/outline_planning_generation.py packages/story_core/file_project_store.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py
git commit -m "feat: require next volume design before detail"
```

### Task 7: Expose workflow APIs and enforce precise prose blocking

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/api/test_file_project_routes.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing route and gate tests**

```python
def test_workflow_endpoint_reports_design_next_volume(client, project_id):
    response = client.get(f"/file-projects/{project_id}/outline/volume-workflow?target_chapter=61")
    assert response.json()["status"] == "volume_missing"
    assert response.json()["next_action"] == "design_next_volume"


@pytest.mark.parametrize("status,error", [
    ("volume_missing", "next_volume_required:61"),
    ("volume_plan_ready", "volume_detail_required:v2"),
    ("detail_partial", "volume_detail_incomplete:v2"),
])
def test_generate_next_chapter_uses_precise_volume_error(store, status, error):
    configure_workflow(store, status)
    with pytest.raises(ValueError, match=f"^{error}$"):
        store.generate_next_chapter()
```

- [ ] **Step 2: Run route/gate tests and verify current generic error fails**

Run: `python -m pytest tests/api/test_file_project_routes.py tests/story_core/test_file_project_store.py -k "volume_workflow or precise_volume_error" -q`

Expected: FAIL; current code emits `chapter_outline_required:<n>`.

- [ ] **Step 3: Add three explicit endpoints**

```text
GET  /file-projects/{project_id}/outline/volume-workflow?target_chapter=N
POST /file-projects/{project_id}/outline/volumes/next
POST /file-projects/{project_id}/outline/volumes/{volume_id}/detail
```

The detail endpoint resumes checkpoints and returns HTTP 202 only if it is moved to the existing background-job executor; otherwise it returns the completed/failed status envelope synchronously with the existing 420-second frontend timeout. Do not invoke either write endpoint from chapter generation.

- [ ] **Step 4: Replace the generic prose gate**

In `generate_next_chapter`, derive workflow status before `rolling_fill_status` and raise the exact state-specific error. Permit prose only for `ready_to_write` or for a chapter that already has confirmed/manual detail inside the active volume.

- [ ] **Step 5: Run API and store tests**

Run: `python -m pytest tests/api/test_file_project_routes.py tests/story_core/test_file_project_store.py -q`

Expected: PASS.

- [ ] **Step 6: Commit workflow API and gate**

```powershell
git add apps/api/routes/file_projects.py packages/story_core/file_project_store.py tests/api/test_file_project_routes.py tests/story_core/test_file_project_store.py
git commit -m "feat: expose volume writing workflow"
```

### Task 8: Migrate every existing project without changing prose or facts

**Files:**
- Create: `packages/story_core/volume_outline_migration.py`
- Create: `scripts/migrate_volume_outlines.py`
- Test: `tests/story_core/test_volume_outline_migration.py`

- [ ] **Step 1: Write failing migration tests**

```python
def test_migration_consolidates_short_overlapping_arcs_and_preserves_chapters(tmp_path):
    root = legacy_project_with_short_arcs(tmp_path)
    before_bodies = chapter_file_hashes(root)
    before_state = read_json(root / ".webnovel/state.json")
    report = migrate_project_volume_outline(root, apply=True)
    outline = read_json(root / ".webnovel/outline.json")
    assert all(volume_length(arc) >= 50 or arc["is_final_arc"] for arc in outline["arcs"])
    assert chapter_file_hashes(root) == before_bodies
    assert read_json(root / ".webnovel/state.json") == before_state
    assert report["overlap_count_after"] == 0


def test_migration_is_idempotent(tmp_path):
    root = legacy_project_with_short_arcs(tmp_path)
    migrate_project_volume_outline(root, apply=True)
    first = file_hash(root / ".webnovel/outline.json")
    migrate_project_volume_outline(root, apply=True)
    assert file_hash(root / ".webnovel/outline.json") == first
```

- [ ] **Step 2: Run tests and verify migration module is missing**

Run: `python -m pytest tests/story_core/test_volume_outline_migration.py -q`

Expected: FAIL with import error.

- [ ] **Step 3: Implement deterministic consolidation**

Group adjacent legacy arcs into the smallest story-preserving volumes of at least 50 chapters. Use chapter summaries and existing arc boundaries only to select among nearby legal endpoints; never alter chapter Markdown, state, character cards, facts, or foreshadowing files. Merge text fields by ordered deduplication, create 15-chapter node ranges from existing chapter summaries, mark only the last arc as final, and write through the file-project atomic update mechanism.

The CLI must support:

```text
python scripts/migrate_volume_outlines.py --root data/exported-projects --dry-run
python scripts/migrate_volume_outlines.py --root data/exported-projects --apply
python scripts/migrate_volume_outlines.py --project p-da2c16a6ee9440d6ad52cb402ead88a0 --apply
```

Dry-run prints project ID, old/new volume ranges, blockers, and files that would change. Apply creates a timestamped backup under `data/migration-backups/volume-outline/` before writing.

- [ ] **Step 4: Run migration tests and a dry-run over local projects**

Run: `python -m pytest tests/story_core/test_volume_outline_migration.py -q`

Run: `python scripts/migrate_volume_outlines.py --root data/exported-projects --dry-run`

Expected: tests PASS; dry-run exits 0 and changes no project files.

- [ ] **Step 5: Commit migration tooling**

```powershell
git add packages/story_core/volume_outline_migration.py scripts/migrate_volume_outlines.py tests/story_core/test_volume_outline_migration.py
git commit -m "feat: migrate legacy books to complete volumes"
```

### Task 9: Show the exact next action on outline and writing pages

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify: `apps/web/app/projects/[id]/write/page.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing Playwright tests for every workflow state**

```typescript
test("finished volume asks the user to design the next volume", async ({ page }) => {
  await mockVolumeWorkflow(page, { status: "volume_missing", next_action: "design_next_volume" });
  await page.goto(projectWriteUrl(60));
  await expect(page.getByText("本卷已完成，请先设计下一卷")).toBeVisible();
  await expect(page.getByRole("button", { name: "设计下一卷" })).toBeVisible();
  await expect(page.getByRole("button", { name: "生成下一章" })).toBeHidden();
});

test("partial detail shows real volume progress", async ({ page }) => {
  await mockVolumeWorkflow(page, {
    status: "detail_partial", volume_range: [61, 120],
    completed_chapters: 30, total_chapters: 60,
    next_action: "continue_volume_detail",
  });
  await page.goto(projectOutlineUrl("chapters", 61));
  await expect(page.getByText("第 61-120 章，已完成 30/60 章")).toBeVisible();
  await expect(page.getByRole("button", { name: "继续生成本卷细纲" })).toBeVisible();
});
```

- [ ] **Step 2: Run Playwright and verify labels/actions are absent**

Run: `pnpm --dir apps/web test:e2e -- story-workbench.spec.ts`

Expected: FAIL on the new visible text and buttons.

- [ ] **Step 3: Add typed workflow clients**

```typescript
export type VolumeWorkflowStatus =
  | "volume_missing" | "volume_plan_ready" | "detail_partial"
  | "ready_to_write" | "volume_complete" | "book_complete";

export type VolumeWorkflowResponse = {
  status: VolumeWorkflowStatus;
  next_action: "design_next_volume" | "generate_volume_detail" |
    "continue_volume_detail" | "generate_chapter" | "view_ending";
  volume_id?: string;
  volume_title?: string;
  volume_range?: [number, number];
  completed_chapters: number;
  total_chapters: number;
  failed_batch?: [number, number] | null;
};
```

Add `fetchVolumeWorkflow`, `designNextVolume`, and `generateVolumeDetail` in `apps/web/lib/api.ts`.

- [ ] **Step 4: Render one primary action per state**

On the outline page, replace “补充后续章节” and fixed remaining-window messages with volume title/range, node cards, batch progress, and one state-derived button. On the write page, fetch workflow for `nextChapterNumber`; show current volume name/range at the top and redirect to `outline?tab=arcs&chapter=N&reason=volume_missing` or `outline?tab=chapters&chapter=N&reason=volume_detail_required` before attempting body generation.

- [ ] **Step 5: Run frontend tests and production build**

Run: `pnpm --dir apps/web test:e2e -- story-workbench.spec.ts`

Run: `pnpm --dir apps/web build`

Expected: Playwright PASS and Next.js build exits 0.

- [ ] **Step 6: Commit workbench workflow UI**

```powershell
git add apps/web/lib/api.ts apps/web/app/projects/[id]/outline/page.tsx apps/web/app/projects/[id]/write/page.tsx apps/web/tests/story-workbench.spec.ts
git commit -m "feat: guide users through volume workflow"
```

### Task 10: Apply migration and run end-to-end acceptance

**Files:**
- Modify only through migration: `data/exported-projects/*/.webnovel/outline.json`
- Test: `tests/story_core/test_volume_outline_acceptance.py`

- [ ] **Step 1: Add a full workflow acceptance test**

```python
def test_volume_lifecycle_from_missing_plan_to_first_prose(tmp_path, fake_models):
    store = completed_first_volume_project(tmp_path)
    assert store.volume_workflow_status(61)["status"] == "volume_missing"
    volume = store.design_next_volume(fake_models.outline)
    assert volume["status"] == "volume_plan_ready"
    detail = store.generate_volume_detail(fake_models.outline, volume_id=volume["volume_id"])
    assert detail["detail_status"] == "complete"
    assert store.volume_workflow_status(61)["status"] == "ready_to_write"
    candidate = store.generate_next_chapter(engine=fake_models.writer, persist=False)
    assert candidate["chapter_number"] == 61
```

- [ ] **Step 2: Run the acceptance test**

Run: `python -m pytest tests/story_core/test_volume_outline_acceptance.py -q`

Expected: PASS.

- [ ] **Step 3: Run full backend and frontend verification before touching project data**

Run: `python -m pytest -q`

Run: `pnpm --dir apps/web build`

Expected: all pytest tests pass; frontend build exits 0.

- [ ] **Step 4: Dry-run, inspect, then apply all-project migration**

Run: `python scripts/migrate_volume_outlines.py --root data/exported-projects --dry-run > .run/volume-outline-dry-run.txt`

Inspect: every listed non-final volume is at least 50 chapters, ranges do not overlap, and no chapter/state file is listed under changed files.

Run: `python scripts/migrate_volume_outlines.py --root data/exported-projects --apply`

Expected: one backup per changed project and exit code 0.

- [ ] **Step 5: Verify the target long-running project through API and browser**

Run backend and frontend, then verify project `file:p-da2c16a6ee9440d6ad52cb402ead88a0`:

- Volumes are story-preserving and every non-final volume is at least 50 chapters.
- The volume containing chapter 153 displays all its 15-chapter nodes.
- Missing detail displays the complete volume range.
- Completing one batch shows real partial progress.
- Completing all batches enables chapter 153 prose generation.
- Finishing a volume presents “设计下一卷” before any further prose action.

- [ ] **Step 6: Commit migrated outlines and acceptance coverage separately**

```powershell
git add tests/story_core/test_volume_outline_acceptance.py
git commit -m "test: cover complete volume lifecycle"
git add data/exported-projects/*/.webnovel/outline.json
git commit -m "data: migrate projects to complete volumes"
```

## Final Verification

- [ ] Run `python -m pytest -q` and confirm no failures.
- [ ] Run `pnpm --dir apps/web build` and confirm exit code 0.
- [ ] Run the focused Playwright workbench tests and confirm all volume states render correctly.
- [ ] Run migration dry-run a second time and confirm it reports zero pending changes.
- [ ] Confirm `git diff --check` is clean.
- [ ] Confirm unrelated dirty files from before this feature remain untouched and unstaged.

