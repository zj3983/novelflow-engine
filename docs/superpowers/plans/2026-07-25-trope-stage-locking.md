# Trope Stage Locking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make novel-type trope templates automatically select a book-level trope, lock one trope per arc, schedule optional chapter beats, and reach writing and review without extra model calls.

**Architecture:** Add one focused trope runtime module that normalizes, merges, resolves, and validates templates. Persist only template IDs and an optional chapter beat in the existing outline models; opening and outline generators select from a compact candidate list, while chapter generation resolves the active ID into one compact contract. The writer and existing plot-spine reviewer consume that contract, so no new Agent or provider call is introduced.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, existing story-core prompt and orchestration pipeline.

---

## File Map

- Create `packages/story_core/trope_runtime.py`: normalize, merge, compact, resolve, and validate trope templates without depending on storage or model providers.
- Create `tests/story_core/test_trope_runtime.py`: unit coverage for ordering, deduplication, compaction, resolution, and validation.
- Modify `packages/story_core/novel_type_catalog.py`: expose compact type-specific plus generic candidates in prompt context.
- Modify `packages/story_core/project_outline.py`: persist `primary_trope_id`, `trope_id`, and optional `trope_beat`; include them in selected chapter context.
- Modify `packages/story_core/opening_directions.py`: require and validate an automatic trope choice for each generated direction.
- Modify `packages/story_core/outline_planning_generation.py`: pass trope choices and validation rules to the planner.
- Modify `packages/story_core/outline_planning.py`: validate generated book, arc, and chapter selections against the candidate set.
- Modify `packages/story_core/file_project_store.py`: carry the selected opening trope into the initial outline and preserve it through planning and save-time validation.
- Modify `packages/story_core/chapter_seed.py`: resolve the active arc selection into one `trope_contract`.
- Modify `packages/story_core/orchestrator.py`: retain that contract in director and writer prompts and attach it to the existing review context.
- Modify `packages/story_core/plot_spine_review.py`: review scheduled trope-beat coverage and expose avoidance guidance through the existing review result.
- Modify focused tests under `tests/story_core/`; no frontend or API schema changes are required because existing JSON models transport the added outline fields.

### Task 1: Build the trope runtime boundary

**Files:**
- Create: `packages/story_core/trope_runtime.py`
- Create: `tests/story_core/test_trope_runtime.py`

- [ ] **Step 1: Write failing normalization and resolution tests**

```python
from packages.story_core.trope_runtime import (
    compact_trope_candidates,
    merge_trope_templates,
    resolve_trope_contract,
)


TYPE_TEMPLATE = {
    "id": "resource_gate",
    "name": "类型专用资源门槛",
    "trigger": "主角缺少关键资源",
    "beats": ["发现门槛", "支付代价", "取得入口"],
    "payoff": "得到可见的下一阶段入口",
    "avoid": ["无代价获得资源"],
}


def test_merge_prefers_type_specific_template_and_appends_generic_candidates():
    generic = [{**TYPE_TEMPLATE, "name": "通用资源门槛"}, {**TYPE_TEMPLATE, "id": "chapter_hook"}]
    merged = merge_trope_templates([[TYPE_TEMPLATE], generic])
    assert [item["id"] for item in merged] == ["resource_gate", "chapter_hook"]
    assert merged[0]["name"] == "类型专用资源门槛"


def test_resolve_returns_only_one_locked_contract_and_rejects_unknown_beat():
    contract = resolve_trope_contract([TYPE_TEMPLATE], "resource_gate", "支付代价")
    assert contract == {
        "template_id": "resource_gate",
        "name": "类型专用资源门槛",
        "trigger": "主角缺少关键资源",
        "current_beat": "支付代价",
        "payoff": "得到可见的下一阶段入口",
        "avoid": ["无代价获得资源"],
    }
    assert resolve_trope_contract([TYPE_TEMPLATE], "missing", None) == {}
    assert resolve_trope_contract([TYPE_TEMPLATE], "resource_gate", "不存在") == {}


def test_prompt_candidates_are_bounded_but_keep_all_selection_fields():
    compact = compact_trope_candidates([TYPE_TEMPLATE])
    assert compact[0].keys() == {"id", "name", "trigger", "beats", "payoff", "avoid"}
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `pytest tests/story_core/test_trope_runtime.py -q`

Expected: collection fails with `ModuleNotFoundError: packages.story_core.trope_runtime`.

- [ ] **Step 3: Implement the focused runtime module**

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from packages.story_core.agent_base import compact_list, compact_text


TROPE_FIELDS = ("id", "name", "trigger", "beats", "payoff", "avoid")


def _normalize_template(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    template_id = str(value.get("id") or "").strip()
    if not template_id:
        return None
    return {
        "id": template_id,
        "name": str(value.get("name") or "").strip(),
        "trigger": str(value.get("trigger") or "").strip(),
        "beats": [str(item).strip() for item in value.get("beats", []) if str(item).strip()],
        "payoff": str(value.get("payoff") or "").strip(),
        "avoid": [str(item).strip() for item in value.get("avoid", []) if str(item).strip()],
    }


def merge_trope_templates(groups: Iterable[Iterable[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            template = _normalize_template(raw)
            if template is None or template["id"] in seen:
                continue
            seen.add(template["id"])
            merged.append(template)
    return deepcopy(merged)


def compact_trope_candidates(templates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": compact_text(item["id"], 80),
            "name": compact_text(item["name"], 80),
            "trigger": compact_text(item["trigger"], 180),
            "beats": compact_list(item["beats"], max_items=8, item_chars=120),
            "payoff": compact_text(item["payoff"], 180),
            "avoid": compact_list(item["avoid"], max_items=6, item_chars=120),
        }
        for item in merge_trope_templates([templates])
    ]


def resolve_trope_contract(
    templates: Iterable[dict[str, Any]], template_id: str, current_beat: str | None
) -> dict[str, Any]:
    selected = next((item for item in merge_trope_templates([templates]) if item["id"] == template_id), None)
    beat = str(current_beat or "").strip()
    if selected is None or (beat and beat not in selected["beats"]):
        return {}
    return {
        "template_id": selected["id"],
        "name": selected["name"],
        "trigger": selected["trigger"],
        "current_beat": beat,
        "payoff": selected["payoff"],
        "avoid": list(selected["avoid"]),
    }
```

- [ ] **Step 4: Run the unit tests**

Run: `pytest tests/story_core/test_trope_runtime.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the runtime boundary**

```bash
git add packages/story_core/trope_runtime.py tests/story_core/test_trope_runtime.py
git commit -m "feat: add trope runtime resolver"
```

### Task 2: Persist trope selections and expose prompt candidates

**Files:**
- Modify: `packages/story_core/project_outline.py`
- Modify: `packages/story_core/novel_type_catalog.py`
- Test: `tests/story_core/test_project_outline.py`
- Test: `tests/story_core/test_novel_type_catalog.py`

- [ ] **Step 1: Add failing outline compatibility and context tests**

Add assertions that `OverallOutline` dumps `primary_trope_id`, `ArcOutline` dumps `trope_id`, and `ChapterPlan` dumps `trope_beat`. Add this context test:

```python
def test_outline_context_carries_locked_trope_and_optional_chapter_beat():
    context = select_outline_context(
        normalize_project_outline(
            {
                "overall": {"primary_trope_id": "golden_finger_first_test"},
                "arcs": [{"id": "opening", "start_chapter": 1, "end_chapter": 10, "trope_id": "resource_gate"}],
                "chapters": [{"chapter_number": 3, "trope_beat": "支付代价"}],
            }
        ),
        3,
    )
    assert context["overall"]["primary_trope_id"] == "golden_finger_first_test"
    assert context["active_arc"]["trope_id"] == "resource_gate"
    assert context["chapter"]["trope_beat"] == "支付代价"
```

Also assert that an outline without the three fields normalizes them to `None`.

- [ ] **Step 2: Add a failing prompt-context candidate test**

```python
def test_novel_type_prompt_context_includes_type_then_generic_trope_candidates():
    context = novel_type_prompt_context(runtime_novel_type("game_webnovel"))
    ids = [item["id"] for item in context["genre_trope_templates"]]
    assert "first_advantage_verification" in ids
    assert "low_status_reversal" in ids
    assert len(ids) == len(set(ids))
```

- [ ] **Step 3: Run focused tests and verify the new assertions fail**

Run: `pytest tests/story_core/test_project_outline.py tests/story_core/test_novel_type_catalog.py -q`

Expected: failures for missing fields and missing `genre_trope_templates`.

- [ ] **Step 4: Add optional persisted fields and selected-context keys**

In `project_outline.py`, add:

```python
class OverallOutline(_OutlineModel):
    primary_trope_id: str | None = None


class ArcOutline(_OutlineModel):
    trope_id: str | None = None


class ChapterPlan(_OutlineModel):
    trope_beat: str | None = None
```

Add `primary_trope_id` and `trope_id` to the corresponding key tuples in `select_outline_context`. Keep `schema_version` at `project-outline/v1` because all fields are optional and old documents remain valid.

- [ ] **Step 5: Add compact type plus generic templates to prompt context**

In `novel_type_catalog.py`, resolve `generic_webnovel`, put the requested record first, merge with the generic record second, and add:

```python
type_templates = list(getattr(record, "trope_templates", ()) or ())
generic = runtime_novel_type("generic_webnovel")
generic_templates = list(getattr(generic, "trope_templates", ()) or ()) if generic else []
context["genre_trope_templates"] = compact_trope_candidates(
    merge_trope_templates([type_templates, generic_templates])
)
```

Include this list in the existing 6,000-character trimming loop. Trim candidate lists only by removing trailing generic candidates, never by removing fields from the selected template shape.

- [ ] **Step 6: Run focused tests**

Run: `pytest tests/story_core/test_project_outline.py tests/story_core/test_novel_type_catalog.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit model and catalog support**

```bash
git add packages/story_core/project_outline.py packages/story_core/novel_type_catalog.py tests/story_core/test_project_outline.py tests/story_core/test_novel_type_catalog.py
git commit -m "feat: persist trope selections in outlines"
```

### Task 3: Make opening directions select and carry the primary trope

**Files:**
- Modify: `packages/story_core/opening_directions.py`
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_opening_directions.py`

- [ ] **Step 1: Update the direction fixture and write failing validation tests**

Update the test helper `direction()` to include `"primary_trope_id": "low_status_reversal"`. Add tests proving unknown IDs fail, selection persists the ID, and an empty candidate set accepts `None`:

```python
def test_generator_rejects_direction_trope_outside_prompt_candidates():
    payload = direction_set()
    payload["directions"][0]["primary_trope_id"] = "not-a-template"
    generator = generator_returning(payload, novel_type="urban")
    with pytest.raises(ValueError, match="opening_direction_generation_failed"):
        generator.generate(OpeningBrief(novel_type_id="urban", idea="落魄鉴定师翻身"))


def test_select_direction_copies_primary_trope_to_overall_outline(tmp_path):
    store = make_opening_store(tmp_path)
    store.generate_opening_directions(StaticDirectionGenerator())
    store.select_opening_direction("direction-1")
    assert store.project_outline()["overall"]["primary_trope_id"] == "low_status_reversal"
```

- [ ] **Step 2: Run the opening tests and verify failure**

Run: `pytest tests/story_core/test_opening_directions.py -q`

Expected: model validation fails because `primary_trope_id` is currently forbidden, and the selected outline lacks the field.

- [ ] **Step 3: Require a valid choice whenever candidates exist**

Add `primary_trope_id: str | None = Field(default=None, max_length=100)` to `OpeningDirection`, include it in the trim validator without converting `None`, and update the system prompt to require exactly:

```text
id, title, hook, protagonist_goal, main_conflict, growth_path, opening_promise, primary_trope_id
```

After `OpeningDirectionSet.model_validate(parsed)`, validate every direction ID against `prompt_context["genre_trope_templates"]`. When candidates exist, `None`, blank, and unknown IDs raise `ValueError("unknown_primary_trope_id:<id>")`; when candidates are empty, only `None` is accepted. The system instruction must say to choose one listed ID, or return `null` only when the list is empty.

- [ ] **Step 4: Carry the selected ID through storage and planning input**

In `select_opening_direction`, write:

```python
"primary_trope_id": selected.primary_trope_id,
```

inside `overall`. Extend `_planning_opening_direction` and `PlanningOpeningDirection` to include `primary_trope_id`, defaulting to the saved overall value when no selected direction exists. This lets both the opening-first and direct-outline flows use one planner input shape.

- [ ] **Step 5: Run opening and storage regression tests**

Run: `pytest tests/story_core/test_opening_directions.py tests/api/test_file_project_creation_routes.py -q`

Expected: all tests pass; fake API fixtures have the new required field.

- [ ] **Step 6: Commit opening selection**

```bash
git add packages/story_core/opening_directions.py packages/story_core/outline_planning_generation.py packages/story_core/file_project_store.py tests/story_core/test_opening_directions.py tests/api/test_file_project_creation_routes.py
git commit -m "feat: select primary trope with opening direction"
```

### Task 4: Validate book, arc, and chapter trope choices in outline generation

**Files:**
- Modify: `packages/story_core/outline_planning.py`
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing semantic-validation tests**

Create a small candidate fixture with `resource_gate` and beats `发现门槛`, `支付代价`, `取得入口`. Add cases for:

```python
@pytest.mark.parametrize(
    "mutate,error",
    [
        (lambda plan: plan["outline"]["overall"].update(primary_trope_id="missing"), "unknown_primary_trope_id"),
        (lambda plan: plan["outline"]["arcs"][0].update(trope_id="missing"), "unknown_arc_trope_id"),
        (lambda plan: plan["outline"]["chapters"][0].update(trope_beat="不存在"), "invalid_chapter_trope_beat"),
    ],
)
def test_generated_outline_rejects_invalid_trope_selection(mutate, error):
    payload = valid_generated_plan_with_tropes()
    mutate(payload)
    with pytest.raises(ValueError, match=error):
        validate_generated_opening_plan(
            payload,
            expected_chapter_numbers=list(range(1, 31)),
            trope_templates=TROPE_TEMPLATES,
        )
```

Also test that `trope_beat=None` is legal and that a no-template novel type accepts all three fields as `None`.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py -q`

Expected: failures because validators do not accept `trope_templates` and do not inspect trope fields.

- [ ] **Step 3: Add one reusable generated-plan validator**

In `outline_planning.py`, add:

```python
def validate_generated_trope_selection(
    plan: GeneratedOutlinePlan,
    trope_templates: list[dict[str, Any]],
) -> None:
    templates = {item["id"]: item for item in merge_trope_templates([trope_templates])}
    if not templates:
        if plan.outline.overall.primary_trope_id is not None:
            raise ValueError("unexpected_primary_trope_id")
        if any(arc.trope_id is not None for arc in plan.outline.arcs):
            raise ValueError("unexpected_arc_trope_id")
        if any(chapter.trope_beat is not None for chapter in plan.outline.chapters):
            raise ValueError("unexpected_chapter_trope_beat")
        return
    primary = str(plan.outline.overall.primary_trope_id or "")
    if primary not in templates:
        raise ValueError(f"unknown_primary_trope_id:{primary}")
    for arc in plan.outline.arcs:
        if str(arc.trope_id or "") not in templates:
            raise ValueError(f"unknown_arc_trope_id:{arc.id}:{arc.trope_id or ''}")
    for chapter in plan.outline.chapters:
        if not chapter.trope_beat:
            continue
        arc = next((item for item in plan.outline.arcs if item.start_chapter <= chapter.chapter_number <= item.end_chapter), None)
        template = templates.get(str(arc.trope_id or "")) if arc else None
        if template is None or chapter.trope_beat not in template["beats"]:
            raise ValueError(f"invalid_chapter_trope_beat:{chapter.chapter_number}")
```

Call it from both generated-plan validators when `trope_templates` is supplied. Keep manual `normalize_project_outline()` permissive so deleted templates do not make old projects unreadable.

- [ ] **Step 4: Update planner instructions and validation calls**

In `outline_planning_generation.py`, compute the candidate list from `prompt_context["genre_trope_templates"]`, add rules that every arc locks one valid ID and only milestone chapters carry a valid beat, and add this explicit system guidance:

```text
Choose one primary_trope_id for the book and one trope_id per arc from genre_trope_templates.
Use trope_beat only on milestone chapters; it must exactly equal one beat of that arc template.
Do not put trope_beat on every chapter and do not change an arc trope inside the arc.
```

Pass the same candidate list into `validate_generated_opening_plan` and `validate_generated_continuation_plan`.

- [ ] **Step 5: Enforce the same rules at store save time**

In `save_generated_outline_plan`, resolve candidates from `_planning_brief().novel_type_id` and pass them into the same validators. This prevents custom or fake generators from bypassing semantic validation. For `extend`, require the generated overall primary ID to match the existing primary ID and preserve committed arcs and chapter beats through the existing merge functions.

- [ ] **Step 6: Run planner and store tests**

Run: `pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py -q`

Expected: all tests pass, including direct initial generation without a selected opening direction.

- [ ] **Step 7: Commit outline scheduling**

```bash
git add packages/story_core/outline_planning.py packages/story_core/outline_planning_generation.py packages/story_core/file_project_store.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py
git commit -m "feat: lock tropes in generated outline stages"
```

### Task 5: Resolve the active trope into chapter writing prompts

**Files:**
- Modify: `packages/story_core/chapter_seed.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_chapter_seed.py`
- Test: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: Write failing chapter-seed tests**

Build a `StoryState` with `genre_plugin_ids=["game_webnovel"]` and this selected outline context:

```python
story.outline_context = {
    "overall": {"primary_trope_id": "first_advantage_verification"},
    "active_arc": {"id": "opening", "trope_id": "first_advantage_verification"},
    "chapter": {"chapter_number": 2, "trope_beat": "用一次小风险验证优势"},
}
seed = build_chapter_seed(story, 2)
assert seed["trope_contract"]["template_id"] == "first_advantage_verification"
assert seed["trope_contract"]["current_beat"] == "用一次小风险验证优势"
assert len([seed["trope_contract"]["template_id"]]) == 1
```

Add cases where the ID is missing or the beat is invalid and assert `trope_contract` is absent rather than generation crashing.

- [ ] **Step 2: Write failing compaction and non-game writer tests**

Assert `_compact_chapter_seed_for_prompt(seed)` retains `trope_contract`, `_writer_seed_summary(seed)["当前阶段套路"]` contains only the compact contract, and a non-game writer prompt includes the selected contract while excluding unrelated candidate IDs.

- [ ] **Step 3: Run the focused tests and verify failure**

Run: `pytest tests/story_core/test_chapter_seed.py tests/story_core/test_writer_prompt_method.py -q`

Expected: failures for missing `trope_contract` and missing non-game prompt content.

- [ ] **Step 4: Resolve one contract in `build_chapter_seed`**

Merge templates from selected plugins in type-specific-first order, read `trope_id` from `story.outline_context.active_arc` and `trope_beat` from `story.outline_context.chapter`, then call `resolve_trope_contract`. Add the key only when resolution succeeds:

```python
trope_contract = resolve_trope_contract(templates, trope_id, trope_beat)
seed = { ...existing fields... }
if trope_contract:
    seed["trope_contract"] = trope_contract
return seed
```

Do not read from `simulation_blueprint["trope_templates"]` after compaction; use the shared runtime helper so prompt and runtime validation have identical semantics.

- [ ] **Step 5: Keep only the selected contract in director and writer prompts**

Add `trope_contract` to `_compact_chapter_seed_for_prompt.keep_keys` and include it under `当前阶段套路` in `_writer_seed_summary`. In `_body_prompt`, build the compact seed for every genre. Preserve the existing game-specific class-name replacement, but for non-game stories pass a summary containing only `trope_contract` plus existing outline anchors needed by `_writer_fact_section`.

The writer instruction for a non-empty beat must say “本章产生可观察推进”; for an empty beat it must say “只保持阶段承诺，不强行完成整套节点，也不得自行换套路”.

- [ ] **Step 6: Run chapter seed and writer tests**

Run: `pytest tests/story_core/test_chapter_seed.py tests/story_core/test_writer_prompt_method.py -q`

Expected: all tests pass and unrelated trope IDs do not appear in writer prompts.

- [ ] **Step 7: Commit runtime prompt integration**

```bash
git add packages/story_core/chapter_seed.py packages/story_core/orchestrator.py tests/story_core/test_chapter_seed.py tests/story_core/test_writer_prompt_method.py
git commit -m "feat: inject locked trope into chapter writing"
```

### Task 6: Feed the trope contract into existing review and verify no extra calls

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/plot_spine_review.py`
- Test: `tests/story_core/test_plot_spine_review.py`
- Test: `tests/story_core/test_orchestrator.py`

- [ ] **Step 1: Write failing plot-spine trope tests**

```python
def test_plot_spine_reviews_scheduled_trope_beat():
    plan = {
        "trope_contract": {
            "template_id": "resource_gate",
            "current_beat": "主角支付灵石和一次人情，换到秘境入口",
            "payoff": "取得秘境资格",
            "avoid": ["无代价获得资源"],
        }
    }
    failed = review_plot_spine_completion("主角来到山门，闲谈片刻。", plan)
    assert not failed["pass"]
    assert any("套路节点" in item for item in failed["issues"])

    passed = review_plot_spine_completion(
        "主角交出二十灵石，又欠执事一次人情，终于拿到秘境资格。",
        plan,
    )
    assert passed["diagnostics"]["trope_beat_covered"] is True


def test_plot_spine_does_not_force_a_beat_when_current_beat_is_empty():
    review = review_plot_spine_completion(
        "主角承接上一章结果继续调查。",
        {"trope_contract": {"template_id": "resource_gate", "current_beat": "", "avoid": ["无代价获得资源"]}},
    )
    assert not any("套路节点" in item for item in review["issues"])
```

- [ ] **Step 2: Run the review tests and verify failure**

Run: `pytest tests/story_core/test_plot_spine_review.py -q`

Expected: the reviewer ignores `trope_contract`, so the missing beat is not reported.

- [ ] **Step 3: Extend the existing plot-spine review conservatively**

Read `simulation_plan["trope_contract"]`. When `current_beat` is non-empty, reuse `_coverage()` with threshold `0.25`; on failure append one `套路节点未兑现` issue and one revision instruction containing the expected beat and payoff. Always expose `avoid` under `diagnostics["trope_avoid"]` so revision prompts receive the exact template guidance. Do not infer an `avoid` violation from isolated keywords; that would create false positives. The writer and revision prompt already receive the exact avoid rules, while review only fails on observable scheduled-beat absence.

- [ ] **Step 4: Attach the contract to the existing simulation and revision path**

Immediately after `chapter_seed = build_chapter_seed(...)` in the main generation path, copy a resolved contract into:

```python
simulation_plan["trope_contract"] = chapter_seed["trope_contract"]
```

when present. This makes the current `review_plot_spine_completion(body, simulation_plan)` call inspect it and ensures the existing review result and revision checklist carry the issue. Repeat the same attachment in regeneration paths that build their own chapter seed.

- [ ] **Step 5: Assert provider call counts do not increase**

Extend an existing orchestrator fake-provider test to capture call count before and after enabling `outline_context` with a valid trope. Assert the count is equal and the director/writer payload contains one selected contract. No new reviewer provider call may be introduced.

- [ ] **Step 6: Run review and orchestrator tests**

Run: `pytest tests/story_core/test_plot_spine_review.py tests/story_core/test_orchestrator.py -q`

Expected: all tests pass; scheduled beats are reviewed and empty beats do not create failures.

- [ ] **Step 7: Commit review integration**

```bash
git add packages/story_core/orchestrator.py packages/story_core/plot_spine_review.py tests/story_core/test_plot_spine_review.py tests/story_core/test_orchestrator.py
git commit -m "feat: review scheduled trope beats"
```

### Task 7: Run compatibility and end-to-end regression coverage

**Files:**
- Modify: `tests/api/test_file_project_creation_routes.py`
- Modify: `tests/story_core/test_novel_type_runtime_integration.py`
- Modify: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Add an end-to-end runtime integration test**

The test should create or load a project with a real novel type, generate three opening directions, select one, save an initial generated outline with one locked arc and one milestone beat, construct the next `StoryState`, and assert:

```python
assert saved["outline"]["overall"]["primary_trope_id"] == selected_trope_id
assert saved["outline"]["arcs"][0]["trope_id"] == selected_trope_id
assert seed["trope_contract"]["template_id"] == selected_trope_id
assert seed["trope_contract"]["current_beat"] == scheduled_beat
assert unrelated_template_id not in json.dumps(_writer_seed_summary(seed), ensure_ascii=False)
```

- [ ] **Step 2: Add compatibility cases**

Cover these exact cases:

- A legacy `outline.json` with none of the new fields still loads and generates a chapter seed.
- A custom type with `trope_templates=[]` generates prompt context with an empty candidate list and accepts `None` selections.
- A saved old outline whose template ID was deleted loads; `build_chapter_seed` omits the contract instead of raising.
- Initial direct outline generation and opening-first outline generation use the same candidate IDs.
- Extend mode preserves committed chapter beats and the locked arc trope.

- [ ] **Step 3: Run focused integration tests**

Run: `pytest tests/story_core/test_novel_type_runtime_integration.py tests/story_core/test_file_project_store.py tests/api/test_file_project_creation_routes.py -q`

Expected: all tests pass.

- [ ] **Step 4: Run the complete backend suite**

Run: `pytest tests/story_core tests/api -q`

Expected: all tests pass with no unexpected provider/network calls.

- [ ] **Step 5: Check formatting and repository diff**

Run: `git diff --check`

Expected: no whitespace errors.

Run: `git status --short`

Expected: only intentional trope-stage-locking changes remain. If execution started from the current dirty worktree, do not stage unrelated pre-existing files; execute this plan in a dedicated clean worktree from commit `bf81600` instead.

- [ ] **Step 6: Commit final fixture or regression adjustments**

```bash
git add tests/api/test_file_project_creation_routes.py tests/story_core/test_novel_type_runtime_integration.py tests/story_core/test_file_project_store.py
git commit -m "test: cover trope stage locking workflow"
```

## Completion Check

Before merging, verify all of the following from test evidence and prompt captures:

- Opening generation chooses only a listed `primary_trope_id`.
- Direct outline generation also chooses a primary trope.
- Every generated arc has one valid locked `trope_id`.
- Only milestone chapters carry `trope_beat`, and every beat belongs to that arc's template.
- The writer sees one resolved contract for all genres, never the complete candidate library.
- A scheduled beat reaches the existing plot-spine review and revision path.
- Empty beats do not force repetitive chapter structures.
- Deleted IDs and old projects degrade without crashing.
- No Agent, runtime setting, or provider call was added.
