# Elastic Longform Outline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing three-level outline so a novel can finish cleanly around chapter 150, expand toward chapter 500 when selected, and maintain only a rolling 30-chapter detailed window.

**Architecture:** Keep `project-outline/v1` and add optional elastic fields that normalize to safe defaults for old outlines. Put window calculations and project-state validation in a focused `elastic_outline.py` module, keep persistence transactional in `FileProjectStore`, and project only compact current-story context into writing packets. The outline page exposes explicit strategy controls and per-arc continue/close routes; the author remains the only source of strategy changes.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, pytest, Next.js 14, React, TypeScript, Playwright.

---

### Task 1: Add the elastic outline data contract

**Files:**
- Modify: `packages/story_core/project_outline.py`
- Test: `tests/story_core/test_project_outline.py`

- [ ] **Step 1: Write failing model and compatibility tests**

Add these tests to `tests/story_core/test_project_outline.py`:

```python
def test_elastic_outline_fields_round_trip() -> None:
    normalized = normalize_project_outline(
        {
            "overall": {
                "story": "夜烬从新手村走向主城。",
                "core_ending_chapter": 150,
                "extension_ceiling_chapter": 500,
                "current_strategy": "observe",
                "ending_contract": "现实线和游戏线都完成核心结局。",
            },
            "arcs": [
                {
                    "id": "opening",
                    "start_chapter": 1,
                    "end_chapter": 30,
                    "game_line_payoff": "进入主城并建立稳定材料渠道。",
                    "reality_line_payoff": "到账足够支付眼前急账的收入。",
                    "extension_gate": {
                        "continue_route": "进入主城并开放公会竞争。",
                        "close_route": "回收新手村线索并转入校验者结局。",
                    },
                }
            ],
        }
    )

    assert normalized["overall"]["core_ending_chapter"] == 150
    assert normalized["overall"]["extension_ceiling_chapter"] == 500
    assert normalized["overall"]["current_strategy"] == "observe"
    assert normalized["arcs"][0]["extension_gate"]["continue_route"]


def test_old_outline_defaults_to_non_expanding_observe_mode() -> None:
    normalized = normalize_project_outline(
        {
            "arcs": [
                {"id": "opening", "start_chapter": 1, "end_chapter": 30}
            ],
            "chapters": [{"chapter_number": 1}],
        }
    )

    assert normalized["overall"]["core_ending_chapter"] == 30
    assert normalized["overall"]["extension_ceiling_chapter"] == 30
    assert normalized["overall"]["current_strategy"] == "observe"
    assert normalized["arcs"][0]["extension_gate"] == {
        "continue_route": "",
        "close_route": "",
    }


def test_extension_ceiling_cannot_precede_core_ending() -> None:
    with pytest.raises(ValueError, match="extension_ceiling_before_core_ending"):
        normalize_project_outline(
            {
                "overall": {
                    "core_ending_chapter": 150,
                    "extension_ceiling_chapter": 120,
                }
            }
        )


def test_expandable_outline_requires_both_routes_for_core_arcs() -> None:
    with pytest.raises(ValueError, match="missing_arc_extension_route:opening"):
        normalize_project_outline(
            {
                "overall": {
                    "core_ending_chapter": 150,
                    "extension_ceiling_chapter": 500,
                },
                "arcs": [
                    {
                        "id": "opening",
                        "start_chapter": 1,
                        "end_chapter": 30,
                        "game_line_payoff": "进入主城。",
                        "reality_line_payoff": "解决急账。",
                        "extension_gate": {"continue_route": "继续", "close_route": ""},
                    }
                ],
            }
        )


def test_expandable_outline_requires_dual_line_payoffs_for_core_arcs() -> None:
    with pytest.raises(ValueError, match="missing_arc_dual_line_payoff:opening"):
        normalize_project_outline(
            {
                "overall": {
                    "core_ending_chapter": 150,
                    "extension_ceiling_chapter": 500,
                },
                "arcs": [
                    {
                        "id": "opening",
                        "start_chapter": 1,
                        "end_chapter": 30,
                        "extension_gate": {
                            "continue_route": "进入下一阶段。",
                            "close_route": "进入结局。",
                        },
                    }
                ],
            }
        )
```

- [ ] **Step 2: Run the tests and confirm the new fields are rejected**

Run:

```powershell
pytest -q tests/story_core/test_project_outline.py -x
```

Expected: FAIL with `extra_forbidden` for `core_ending_chapter` or `extension_gate`.

- [ ] **Step 3: Add typed fields and deterministic old-outline defaults**

In `packages/story_core/project_outline.py`, add these declarations:

```python
OutlineStrategy = Literal["observe", "expand", "close"]


class ExtensionGate(_OutlineModel):
    continue_route: str = ""
    close_route: str = ""


class OverallOutline(_OutlineModel):
    story: str = ""
    protagonist_goal: str = ""
    main_conflict: str = ""
    growth_path: str = ""
    ending_direction: str = ""
    core_ending_chapter: int = Field(default=1, ge=1, strict=True)
    extension_ceiling_chapter: int = Field(default=1, ge=1, strict=True)
    current_strategy: OutlineStrategy = "observe"
    ending_contract: str = ""
```

Add this field to `ArcOutline`:

```python
game_line_payoff: str = ""
reality_line_payoff: str = ""
extension_gate: ExtensionGate = Field(default_factory=ExtensionGate)
```

Add these checks to the `ProjectOutline` model validator:

```python
if self.overall.extension_ceiling_chapter < self.overall.core_ending_chapter:
    raise ValueError("extension_ceiling_before_core_ending")
if self.overall.extension_ceiling_chapter > self.overall.core_ending_chapter:
    for arc in self.arcs:
        if arc.end_chapter > self.overall.core_ending_chapter:
            continue
        if not arc.game_line_payoff.strip() or not arc.reality_line_payoff.strip():
            raise ValueError(f"missing_arc_dual_line_payoff:{arc.id}")
        if not arc.extension_gate.continue_route.strip() or not arc.extension_gate.close_route.strip():
            raise ValueError(f"missing_arc_extension_route:{arc.id}")
```

Before `ProjectOutline.model_validate` in `normalize_project_outline`, deep-copy dict payloads and inject old-outline defaults from the highest arc end or chapter number:

```python
def _with_elastic_defaults(payload: Any) -> Any:
    if payload is None or not isinstance(payload, dict):
        return payload
    prepared = deepcopy(payload)
    overall = prepared.setdefault("overall", {})
    arcs = prepared.get("arcs") if isinstance(prepared.get("arcs"), list) else []
    chapters = prepared.get("chapters") if isinstance(prepared.get("chapters"), list) else []
    planned_ends = [
        item.get("end_chapter")
        for item in arcs
        if isinstance(item, dict) and isinstance(item.get("end_chapter"), int) and not isinstance(item.get("end_chapter"), bool)
    ]
    planned_chapters = [
        item.get("chapter_number")
        for item in chapters
        if isinstance(item, dict) and isinstance(item.get("chapter_number"), int) and not isinstance(item.get("chapter_number"), bool)
    ]
    legacy_end = max([*planned_ends, *planned_chapters, 1])
    overall.setdefault("core_ending_chapter", legacy_end)
    overall.setdefault("extension_ceiling_chapter", overall["core_ending_chapter"])
    overall.setdefault("current_strategy", "observe")
    overall.setdefault("ending_contract", overall.get("ending_direction", ""))
    return prepared
```

Import `deepcopy` from `copy`, and call `ProjectOutline.model_validate(_with_elastic_defaults(payload))`.

- [ ] **Step 4: Update exact-field assertions for the expanded v1 schema**

Update `test_models_expose_the_canonical_outline_fields` and legacy expected dictionaries so the exact field sets include:

```python
{
    "core_ending_chapter",
    "extension_ceiling_chapter",
    "current_strategy",
    "ending_contract",
}
```

and every arc includes:

```python
"game_line_payoff": "",
"reality_line_payoff": "",
"extension_gate": {"continue_route": "", "close_route": ""}
```

- [ ] **Step 5: Run model regression tests**

Run:

```powershell
pytest -q tests/story_core/test_project_outline.py tests/story_core/test_outline_planning.py -x
```

Expected: PASS.

- [ ] **Step 6: Commit the contract**

```powershell
git add packages/story_core/project_outline.py tests/story_core/test_project_outline.py tests/story_core/test_outline_planning.py
git commit -m "feat: add elastic outline contract"
```

### Task 2: Add rolling-window and project-state validation

**Files:**
- Create: `packages/story_core/elastic_outline.py`
- Modify: `packages/story_core/file_project_store.py:2517-2528`
- Test: `tests/story_core/test_elastic_outline.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing helper tests**

Create `tests/story_core/test_elastic_outline.py`:

```python
from __future__ import annotations

import pytest

from packages.story_core.elastic_outline import (
    outline_window_status,
    validate_outline_for_project,
)


def _outline(*, strategy: str = "observe", last_chapter: int = 30) -> dict:
    return {
        "overall": {
            "core_ending_chapter": 150,
            "extension_ceiling_chapter": 500,
            "current_strategy": strategy,
            "ending_contract": "两条线完整收束。",
        },
        "arcs": [
            {
                "id": "opening",
                "start_chapter": 1,
                "end_chapter": 30,
                "extension_gate": {
                    "continue_route": "进入主城。",
                    "close_route": "转入校验者结局。",
                },
            }
        ],
        "chapters": [{"chapter_number": number} for number in range(1, last_chapter + 1)],
    }


def test_window_status_warns_with_ten_or_fewer_planned_chapters() -> None:
    status = outline_window_status(_outline(last_chapter=30), current_chapter=20)
    assert status == {
        "last_planned_chapter": 30,
        "remaining_detailed_chapters": 10,
        "target_last_chapter": 50,
        "needs_extension": True,
        "next_chapter_numbers": list(range(31, 51)),
    }


def test_full_window_does_not_request_more_chapters() -> None:
    status = outline_window_status(_outline(last_chapter=40), current_chapter=10)
    assert status["remaining_detailed_chapters"] == 30
    assert status["needs_extension"] is False
    assert status["next_chapter_numbers"] == []


def test_core_ending_cannot_precede_committed_chapter() -> None:
    with pytest.raises(ValueError, match="core_ending_before_current_chapter"):
        validate_outline_for_project(
            {
                "overall": {
                    "core_ending_chapter": 20,
                    "extension_ceiling_chapter": 20,
                }
            },
            current_chapter=21,
        )
```

- [ ] **Step 2: Run the helper tests and verify the module is absent**

Run:

```powershell
pytest -q tests/story_core/test_elastic_outline.py -x
```

Expected: FAIL with `ModuleNotFoundError: packages.story_core.elastic_outline`.

- [ ] **Step 3: Implement the focused policy module**

Create `packages/story_core/elastic_outline.py`:

```python
from __future__ import annotations

from typing import Any

from packages.story_core.project_outline import normalize_project_outline


DETAIL_WINDOW = 30
EXTENSION_WARNING = 10


def outline_window_status(outline: dict[str, Any], *, current_chapter: int) -> dict[str, Any]:
    normalized = normalize_project_outline(outline)
    last_planned = max(
        [int(item["chapter_number"]) for item in normalized["chapters"]] or [current_chapter]
    )
    remaining = max(0, last_planned - current_chapter)
    target_last = current_chapter + DETAIL_WINDOW
    needs_extension = remaining <= EXTENSION_WARNING
    next_numbers = list(range(last_planned + 1, target_last + 1)) if needs_extension and last_planned < target_last else []
    return {
        "last_planned_chapter": last_planned,
        "remaining_detailed_chapters": remaining,
        "target_last_chapter": target_last,
        "needs_extension": bool(next_numbers),
        "next_chapter_numbers": next_numbers,
    }


def validate_outline_for_project(outline: dict[str, Any], *, current_chapter: int) -> dict[str, Any]:
    normalized = normalize_project_outline(outline)
    if normalized["overall"]["core_ending_chapter"] < current_chapter:
        raise ValueError("core_ending_before_current_chapter")
    if normalized["overall"]["current_strategy"] == "close":
        target = current_chapter + 1
        active = next(
            (
                arc
                for arc in normalized["arcs"]
                if arc["start_chapter"] <= target <= arc["end_chapter"]
            ),
            None,
        )
        if active is None or not active["extension_gate"]["close_route"].strip():
            raise ValueError("close_route_required_for_active_arc")
    return normalized
```

- [ ] **Step 4: Enforce current-chapter safety at the storage boundary**

In `FileProjectStore.update_project_outline`, replace the direct normalization call with:

```python
state = self._read_json(self.webnovel_dir / "state.json", {})
current_chapter = int(state.get("current_chapter") or 0)
normalized = validate_outline_for_project(outline_payload, current_chapter=current_chapter)
```

Import `validate_outline_for_project` from `packages.story_core.elastic_outline`.

Add this case beside the existing outline transaction tests in `tests/story_core/test_file_project_store.py`:

```python
def test_update_outline_rejects_core_ending_before_current_chapter(tmp_path) -> None:
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root, state={"current_chapter": 21})
    before = store.project_outline()
    invalid = deepcopy(before)
    invalid["overall"]["core_ending_chapter"] = 20
    invalid["overall"]["extension_ceiling_chapter"] = 20

    with pytest.raises(ValueError, match="core_ending_before_current_chapter"):
        store.update_project_outline(invalid)

    assert store.project_outline() == before
```

Add `from copy import deepcopy` beside the imports at the top of the test file. Reuse `_make_minimal_file_project`; do not introduce a second project layout.

- [ ] **Step 5: Run helper and store tests**

Run:

```powershell
pytest -q tests/story_core/test_elastic_outline.py tests/story_core/test_file_project_store.py -k "outline" -x
```

Expected: PASS.

- [ ] **Step 6: Commit policy and validation**

```powershell
git add packages/story_core/elastic_outline.py packages/story_core/file_project_store.py tests/story_core/test_elastic_outline.py tests/story_core/test_file_project_store.py
git commit -m "feat: enforce elastic outline policy"
```

### Task 3: Generate a 30-chapter rolling window without rewriting history

**Files:**
- Modify: `packages/story_core/outline_planning.py`
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/file_project_store.py:2620-2730`
- Test: `tests/story_core/test_outline_planning.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing initial, extension, and history-preservation tests**

Add tests with these assertions:

```python
def test_initial_plan_requires_thirty_detailed_chapters(valid_plan_payload: dict) -> None:
    valid_plan_payload["outline"]["chapters"] = [
        {**valid_plan_payload["outline"]["chapters"][0], "chapter_number": number}
        for number in range(1, 31)
    ]
    plan = validate_generated_opening_plan(valid_plan_payload)
    assert [item.chapter_number for item in plan.outline.chapters] == list(range(1, 31))


def test_extend_prompt_requests_only_missing_window_chapters(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=20,
        existing_chapters=list(range(1, 31)),
    )
    generator_fixture.generate(brief, mode="extend")
    assert generator_fixture.prompt_context["target_chapter_numbers"] == list(range(31, 51))


def test_regenerate_preserves_committed_chapter_outline(file_store, generated_plan) -> None:
    before = file_store.project_outline()["chapters"][0]
    file_store.save_generated_outline_plan(generated_plan, mode="regenerate")
    after = file_store.project_outline()["chapters"][0]
    assert after == before


def test_regenerate_requests_thirty_future_chapters(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=20,
        existing_chapters=list(range(1, 31)),
    )
    generator_fixture.generate(brief, mode="regenerate")
    assert generator_fixture.prompt_context["target_chapter_numbers"] == list(range(21, 51))
```

Place the validation test beside `valid_payload` in `tests/story_core/test_outline_planning.py`. Extend the `RecordingRuntime` used by `test_generator_requests_one_compact_structured_plan` in `tests/story_core/test_outline_planning_generation.py` so it records the decoded `prompt_context`. Build the persistence case from the same `_write_json` project fixture used by `test_extend_generated_plan_requires_and_appends_next_five_chapters` in `tests/story_core/test_file_project_store.py`; rename that test to describe the rolling window.

- [ ] **Step 2: Run focused tests and verify five-chapter assumptions fail**

Run:

```powershell
pytest -q tests/story_core/test_outline_planning.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py -k "outline or planning" -x
```

Expected: FAIL on `opening_chapters_must_be_1_to_5` or `extension_chapters_must_be_next_five`.

- [ ] **Step 3: Make generated-plan validation accept an explicit target sequence**

Change the validator signature in `outline_planning.py`:

```python
def validate_generated_opening_plan(
    payload: Any,
    *,
    expected_chapter_numbers: list[int] | None = None,
) -> GeneratedOutlinePlan:
    plan = GeneratedOutlinePlan.model_validate(payload)
    expected = expected_chapter_numbers or list(range(1, 31))
    chapter_numbers = [chapter.chapter_number for chapter in plan.outline.chapters]
    if chapter_numbers != expected:
        raise ValueError("generated_chapters_do_not_match_target_window")
    # Keep the existing overall, character-tier, antagonist, cast, and profile checks.
    return plan
```

Do not remove any existing character or antagonist validation.

- [ ] **Step 4: Calculate target chapters in the planner prompt**

In `LLMOutlinePlanningGenerator.generate`, compute:

```python
window = outline_window_status(
    validated.existing_outline,
    current_chapter=validated.current_chapter,
)
if mode == "initial":
    if validated.current_chapter != 0:
        raise ValueError("initial_outline_requires_unstarted_project")
    target_chapter_numbers = list(range(1, 31))
elif mode == "regenerate":
    target_chapter_numbers = list(
        range(validated.current_chapter + 1, validated.current_chapter + 31)
    )
else:
    target_chapter_numbers = window["next_chapter_numbers"]
    if not target_chapter_numbers:
        raise ValueError("outline_window_already_full")
```

This distinction is intentional: `regenerate` always rebuilds the next 30 uncommitted chapter plans even when the existing window is full, while `extend` only fills missing chapter numbers up to `current_chapter + 30`. Neither mode may target a chapter at or below `current_chapter`.

Add `target_chapter_numbers` and `current_strategy` to `prompt_context`. Replace the fixed five-chapter system instruction with:

```python
"chapter_number values must exactly equal prompt_context.target_chapter_numbers in order. "
"For initial/regenerate, provide the complete core arcs through core_ending_chapter, but only those detailed chapters. "
"For extend, continue from committed facts and the active arc; obey current_strategy. "
"Every core arc must state a concrete game_line_payoff and reality_line_payoff. "
"observe follows the core route, expand uses only the next continue_route, and close uses the active close_route."
```

Pass `expected_chapter_numbers=target_chapter_numbers` to validation for every mode.

- [ ] **Step 5: Merge generated future chapters while preserving committed chapters**

Replace `_extend_outline`'s fixed `last + 1` through `last + 5` check with the exact sequence from `outline_window_status(current, current_chapter=state_current_chapter)`. Reject a generated extension unless its chapter numbers exactly equal `next_chapter_numbers`; return `outline_window_already_full` when that list is empty.

Add this helper in `FileProjectStore` and use it for `regenerate` before persistence:

```python
def _preserve_committed_outline(
    self,
    current: dict[str, Any],
    generated: dict[str, Any],
    *,
    current_chapter: int,
) -> dict[str, Any]:
    current = normalize_project_outline(current)
    generated = normalize_project_outline(generated)
    committed = {
        item["chapter_number"]: item
        for item in current["chapters"]
        if item["chapter_number"] <= current_chapter
    }
    future = {
        item["chapter_number"]: item
        for item in generated["chapters"]
        if item["chapter_number"] > current_chapter
    }
    return normalize_project_outline(
        {
            "overall": generated["overall"],
            "arcs": generated["arcs"],
            "chapters": [*committed.values(), *future.values()],
        }
    )
```

Read `current_chapter` from `state.json` before merging. Keep `_replace_json_transaction` unchanged so a failed generation never writes a partial outline.

- [ ] **Step 6: Run planning and persistence tests**

Run:

```powershell
pytest -q tests/story_core/test_outline_planning.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py -k "outline or planning" -x
```

Expected: PASS.

- [ ] **Step 7: Commit rolling generation**

```powershell
git add packages/story_core/outline_planning.py packages/story_core/outline_planning_generation.py packages/story_core/file_project_store.py tests/story_core/test_outline_planning.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py
git commit -m "feat: roll thirty chapter outline window"
```

### Task 4: Keep writing packets compact and strategy-safe

**Files:**
- Modify: `packages/story_core/project_outline.py`
- Modify: `packages/story_core/file_project_store.py:3690-3840`
- Test: `tests/story_core/test_project_outline.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write a failing context-projection test**

Add:

```python
def test_writing_context_omits_future_routes_and_outline_bulk() -> None:
    outline = normalize_project_outline(
        {
            "overall": {
                "story": "核心故事",
                "core_ending_chapter": 150,
                "extension_ceiling_chapter": 500,
                "current_strategy": "observe",
                "ending_contract": "两条线完整收束。",
            },
            "arcs": [
                {
                    "id": "opening",
                    "start_chapter": 1,
                    "end_chapter": 30,
                    "extension_gate": {
                        "continue_route": "跨服战争",
                        "close_route": "进入最终冲突",
                    },
                }
            ],
            "chapters": [{"chapter_number": 2, "goal": "完成前置任务"}],
        }
    )

    context = select_outline_context(outline, 2)

    assert context["overall"]["ending_contract"] == "两条线完整收束。"
    assert context["overall"]["current_strategy"] == "observe"
    assert "core_ending_chapter" not in context["overall"]
    assert "extension_gate" not in context["active_arc"]
    assert "arcs" not in context
    assert "chapters" not in context
```

- [ ] **Step 2: Run the context tests and verify future route leakage**

Run:

```powershell
pytest -q tests/story_core/test_project_outline.py tests/story_core/test_file_project_store.py -k "outline_context or writing_context or selected_outline" -x
```

Expected: FAIL because normalized `overall` and `active_arc` currently pass every field through.

- [ ] **Step 3: Project only current writing information**

In `select_outline_context`, construct explicit projections:

```python
overall_context = {
    key: normalized["overall"][key]
    for key in (
        "story",
        "protagonist_goal",
        "main_conflict",
        "growth_path",
        "ending_direction",
        "current_strategy",
        "ending_contract",
    )
}
active_arc_context = (
    {
        key: active_arc[key]
        for key in (
            "id",
            "title",
            "start_chapter",
            "end_chapter",
            "goal",
            "obstacle",
            "payoff",
            "game_line_payoff",
            "reality_line_payoff",
            "end_state",
            "stage_antagonist",
            "long_term_antagonist_traces",
        )
    }
    if active_arc is not None
    else None
)
```

Return these projections with the selected chapter. Do not include `extension_gate`, all arcs, all chapters, or the numeric ceiling in writing context.

- [ ] **Step 4: Assert the file-project writing packet uses the compact projection**

Extend the existing writing-packet test in `tests/story_core/test_file_project_store.py` to assert:

```python
assert packet["outline_context"]["overall"]["ending_contract"]
assert "extension_gate" not in packet["outline_context"]["active_arc"]
assert "chapters" not in packet["outline_context"]
```

- [ ] **Step 5: Run packet regression tests**

Run:

```powershell
pytest -q tests/story_core/test_project_outline.py tests/story_core/test_file_project_store.py tests/story_core/test_writing_packet.py tests/api/test_story_routes.py -k "outline or packet or writing" -x
```

Expected: PASS.

- [ ] **Step 6: Commit compact projection**

```powershell
git add packages/story_core/project_outline.py packages/story_core/file_project_store.py tests/story_core/test_project_outline.py tests/story_core/test_file_project_store.py
git commit -m "feat: scope longform outline writing context"
```

### Task 5: Expose elastic strategy and expansion gates in the outline page

**Files:**
- Modify: `apps/web/lib/api.ts:930-990`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify: `apps/web/app/globals.css:230-330,1650-1670`
- Test: `apps/web/tests/story-workbench.spec.ts:716-866`

- [ ] **Step 1: Extend the browser fixture with elastic fields and write failing assertions**

Add these fields to the outline fixture:

```typescript
overall: {
  ...outline.overall,
  core_ending_chapter: 150,
  extension_ceiling_chapter: 500,
  current_strategy: "observe",
  ending_contract: "现实线和游戏线都完成核心结局。",
},
arcs: [{
  ...outline.arcs[0],
  game_line_payoff: "进入内门并获得新功法。",
  reality_line_payoff: "解决住处和眼前收入问题。",
  extension_gate: {
    continue_route: "进入内门并扩大旧案。",
    close_route: "回收旧名册并转入最终审判。",
  },
}],
```

Then assert:

```typescript
await expect(page.getByLabel("核心完结章数")).toHaveValue("150");
await expect(page.getByLabel("最大扩展章数")).toHaveValue("500");
await expect(page.getByRole("radio", { name: "观察中" })).toBeChecked();
await page.getByRole("radio", { name: "收束" }).check();
await page.getByRole("tab", { name: "阶段大纲" }).click();
await expect(page.getByLabel("游戏线阶段结果")).toHaveValue("进入内门并获得新功法。");
await expect(page.getByLabel("现实线阶段结果")).toHaveValue("解决住处和眼前收入问题。");
await expect(page.getByLabel("继续路线")).toHaveValue("进入内门并扩大旧案。");
await expect(page.getByLabel("收束路线")).toHaveValue("回收旧名册并转入最终审判。");
```

Change the fixture story to `current_chapter: 20` with detailed chapters through 30 and assert the page says `章节计划还剩 10 章，请补充下一批。`.

- [ ] **Step 2: Run the browser test and verify controls are missing**

From `apps/web`, run:

```powershell
npx playwright test tests/story-workbench.spec.ts --grep "file project outline edits" --workers=1
```

Expected: FAIL because the strategy, ceiling, gate controls, and ten-chapter warning are absent.

- [ ] **Step 3: Add TypeScript contracts**

In `apps/web/lib/api.ts`, add:

```typescript
export type OutlineStrategy = "observe" | "expand" | "close";

export type OutlineExtensionGate = {
  continue_route: string;
  close_route: string;
};
```

Extend `ProjectOutlineOverall` with:

```typescript
core_ending_chapter: number;
extension_ceiling_chapter: number;
current_strategy: OutlineStrategy;
ending_contract: string;
```

Extend `ProjectOutlineArc` with:

```typescript
game_line_payoff: string;
reality_line_payoff: string;
extension_gate: OutlineExtensionGate;
```

- [ ] **Step 4: Render the compact longform strategy controls**

In the overall tab, add two numeric inputs, one textarea for `ending_contract`, and a radio group:

```tsx
<div className="ws-outline-strategy" role="radiogroup" aria-label="长篇策略">
  {([
    ["observe", "观察中"],
    ["expand", "扩展"],
    ["close", "收束"],
  ] as const).map(([value, label]) => (
    <label key={value}>
      <input
        type="radio"
        name="outline-strategy"
        value={value}
        checked={draft.overall.current_strategy === value}
        onChange={() => setDraft({
          ...draft,
          overall: { ...draft.overall, current_strategy: value },
        })}
      />
      <span>{label}</span>
    </label>
  ))}
</div>
```

Use `type="number"`, `min={story?.current_chapter || 1}`, and clear labels `核心完结章数` and `最大扩展章数`.

Derive the arc containing `(story?.current_chapter ?? 0) + 1`. Disable the `收束` radio when that arc is missing or its `close_route.trim()` is empty, and show `请先填写当前阶段的收束路线。` beside the strategy group. Add a Playwright case that clears `收束路线`, returns to `总纲`, and asserts the `收束` radio is disabled; this makes the page enforce the same rule as the API instead of waiting for save failure.

In every arc card add `游戏线阶段结果` and `现实线阶段结果` textareas bound directly to `arc.game_line_payoff` and `arc.reality_line_payoff`. Add `继续路线` and `收束路线` textareas that update `arc.extension_gate` without replacing either sibling value.

- [ ] **Step 5: Replace the two-chapter warning with rolling-window status**

Calculate:

```typescript
const remainingChapters = Math.max(0, lastPlannedChapter - (story?.current_chapter ?? 0));
if (remainingChapters <= 10) {
  items.push(`章节计划还剩 ${remainingChapters} 章，请补充下一批。`);
}
```

Also warn locally when the extension ceiling is below the core ending, or when `close` is selected and the active arc has no close route. Keep the API as the authoritative validator.

- [ ] **Step 6: Add restrained responsive styling**

Add CSS for `.ws-outline-strategy` as a compact segmented radio group and keep it inside the existing outline grid. At widths below the existing mobile breakpoint, stack the segments and numeric fields; do not add a new floating card or nested card.

- [ ] **Step 7: Run frontend verification**

From `apps/web`, run:

```powershell
npm run build
npx tsc --noEmit
npx playwright test tests/story-workbench.spec.ts --grep "file project outline edits" --workers=1
```

Expected: production build and typecheck PASS; focused Playwright PASS.

- [ ] **Step 8: Commit the workbench controls**

```powershell
git add apps/web/lib/api.ts apps/web/app/projects/[id]/outline/page.tsx apps/web/app/globals.css apps/web/tests/story-workbench.spec.ts
git commit -m "feat: manage elastic outline strategy"
```

### Task 6: Migrate 苟在网游里成神 and run full regression

**Files:**
- Modify through API: `data/exported-projects/p-gou-webgame-restored/.webnovel/outline.json`
- Modify: `docs/superpowers/specs/2026-07-19-elastic-longform-outline-design.md`
- Test: `tests/story_core/test_elastic_outline.py`
- Test: `tests/api/test_file_project_creation_routes.py`

- [ ] **Step 1: Add an API round-trip test for old and elastic outlines**

In `tests/api/test_file_project_creation_routes.py`, create a file project, PUT an old outline with no elastic fields, GET it, and assert normalized defaults. Then PUT an elastic outline and assert `current_strategy`, both ceilings, and both routes persist after a second GET and in `.webnovel/outline.json`.

The elastic payload must use:

```python
{
    "overall": {
        "story": "长篇测试",
        "core_ending_chapter": 150,
        "extension_ceiling_chapter": 500,
        "current_strategy": "observe",
        "ending_contract": "核心结局完整。",
    },
    "arcs": [
        {
            "id": "opening",
            "start_chapter": 1,
            "end_chapter": 30,
            "game_line_payoff": "进入下一地图。",
            "reality_line_payoff": "获得第一笔稳定收入。",
            "extension_gate": {
                "continue_route": "进入下一地图。",
                "close_route": "进入最终冲突。",
            },
        }
    ],
    "chapters": [{"chapter_number": number} for number in range(1, 31)],
}
```

- [ ] **Step 2: Run API and elastic tests**

Run:

```powershell
pytest -q tests/story_core/test_elastic_outline.py tests/story_core/test_project_outline.py tests/api/test_file_project_creation_routes.py -x
```

Expected: PASS.

- [ ] **Step 3: Back up the current project outline before migration**

Run:

```powershell
$projectRoot = 'D:\xiaoshuofish-flow-test\data\exported-projects\p-gou-webgame-restored'
$backupDir = Join-Path $projectRoot '.story-system\backups'
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot '.webnovel\outline.json') -Destination (Join-Path $backupDir 'outline-before-elastic.json')
```

Verify the backup parses before changing the live outline:

```powershell
Get-Content -Raw -Encoding UTF8 (Join-Path $backupDir 'outline-before-elastic.json') | ConvertFrom-Json | Out-Null
```

- [ ] **Step 4: Migrate the project through the outline API**

Use Node's UTF-8 JSON handling to GET the current outline, preserve its first 30 chapter plans, and PUT five core arcs through chapter 150. Set:

```javascript
outline.overall.core_ending_chapter = 150;
outline.overall.extension_ceiling_chapter = 500;
outline.overall.current_strategy = "observe";
outline.overall.ending_contract = "苏叶在现实中摆脱生存危机，在游戏中查清混沌之种和校验者主线；两条线都完成核心冲突。";
outline.arcs = [
  {
    id: "ash-village",
    title: "灰烬村开局",
    start_chapter: 1,
    end_chapter: 30,
    goal: "解决现实急账，建立材料和交易渠道，进入主城。",
    obstacle: "新手资源有限，异常收益必须经过任务、交易和现实到账。",
    payoff: "现实有短期缓冲，游戏进入主城。",
    game_line_payoff: "夜烬建立材料和交易渠道并进入主城。",
    reality_line_payoff: "苏叶用第一笔收入解决眼前急账。",
    end_state: "夜烬带着异常记录进入主城。",
    stage_antagonist: "白河仓库背后的市场中介",
    long_term_antagonist_traces: ["旧账出现早期校验记录"],
    extension_gate: {
      continue_route: "展开主城职业、商路和公会竞争。",
      close_route: "直接追查旧账来源并进入校验者主线。",
    },
  },
  {
    id: "main-city",
    title: "主城立足",
    start_chapter: 31,
    end_chapter: 60,
    goal: "完成第一次转职，把掉落优势转成职业优势。",
    obstacle: "公会控制任务、地图和材料渠道。",
    payoff: "现实收入稳定，主角拥有独立职业路线。",
    game_line_payoff: "夜烬完成第一次转职并拥有独立职业路线。",
    reality_line_payoff: "苏叶获得可持续的现实收入。",
    end_state: "夜烬不再依赖新手村渠道。",
    stage_antagonist: "主城资源公会负责人",
    long_term_antagonist_traces: ["校验记录指向更高权限"],
    extension_gate: {
      continue_route: "开放更大的公会竞争和区域地图。",
      close_route: "击败资源负责人并取得校验者坐标。",
    },
  },
  {
    id: "guild-conflict",
    title: "公会冲突",
    start_chapter: 61,
    end_chapter: 90,
    goal: "在幕后建立队伍和交易网络，打破单一公会封锁。",
    obstacle: "主角需要借势，却不能公开异常来源。",
    payoff: "第一个阶段敌人败退，主角形成自己的网络。",
    game_line_payoff: "夜烬拥有独立队伍、商路和地图入口。",
    reality_line_payoff: "苏叶获得不依附单一中介的变现渠道。",
    end_state: "夜烬拥有独立队伍、商路和地图入口。",
    stage_antagonist: "试图垄断异常材料的公会高层",
    long_term_antagonist_traces: ["游戏异常开始映射现实设备"],
    extension_gate: {
      continue_route: "开放跨服、公会战争和更大交易网络。",
      close_route: "用现有网络追到现实设备来源。",
    },
  },
  {
    id: "reality-change",
    title: "现实异变",
    start_chapter: 91,
    end_chapter: 120,
    goal: "确认游戏能力影响现实的边界，并保护现实身份。",
    obstacle: "现实变化有限且有代价，敌人掌握设备和资金优势。",
    payoff: "主角获得第一种可验证的现实能力。",
    game_line_payoff: "夜烬查明游戏异常映射现实的第一条规则。",
    reality_line_payoff: "苏叶获得第一种可验证且有代价的现实能力。",
    end_state: "现实线和游戏线正式合流。",
    stage_antagonist: "掌握异常设备的现实利益方",
    long_term_antagonist_traces: ["第一位校验者仍可能存活"],
    extension_gate: {
      continue_route: "扩大现实能力体系和全球服务器变化。",
      close_route: "锁定第一位校验者并进入最终调查。",
    },
  },
  {
    id: "validator-truth",
    title: "校验者真相",
    start_chapter: 121,
    end_chapter: 150,
    goal: "找到第一位校验者，解决混沌之种的核心来源。",
    obstacle: "核心敌人能同时影响游戏规则和现实渠道。",
    payoff: "现实和游戏两条线完成核心结局。",
    game_line_payoff: "夜烬解决混沌之种和校验者的核心冲突。",
    reality_line_payoff: "苏叶保住现实身份、生活和选择权。",
    end_state: "苏叶保住身份和选择权，混沌之种得到阶段性结论。",
    stage_antagonist: "截断校验链的核心利益方",
    long_term_antagonist_traces: ["全球服务器仍有同类节点"],
    extension_gate: {
      continue_route: "进入全球服务器和更高层校验网络。",
      close_route: "关闭外层节点并完成全书结局。",
    },
  },
];
```

The migration command must assert `outline.chapters.length === 30` before PUT and must stop if the API returns a non-2xx status. Do not regenerate chapter details during migration.

- [ ] **Step 5: Verify the live project after migration**

Check through the API and the UTF-8 file:

```powershell
node -e "fetch('http://127.0.0.1:8000/file-projects/file%3Ap-gou-webgame-restored/outline').then(r=>r.json()).then(o=>console.log(JSON.stringify({core:o.overall.core_ending_chapter,ceiling:o.overall.extension_ceiling_chapter,strategy:o.overall.current_strategy,arcs:o.arcs.length,chapters:o.chapters.length},null,2)))"
```

Expected:

```json
{"core":150,"ceiling":500,"strategy":"observe","arcs":5,"chapters":30}
```

Also assert the first 30 chapter titles are unchanged from the backup and the file contains no literal `?` runs or mojibake markers.

- [ ] **Step 6: Run full backend and frontend verification**

Run:

```powershell
pytest -q tests/story_core tests/api -x
```

From `apps/web`, run:

```powershell
npm run build
npx tsc --noEmit
npx playwright test tests/story-workbench.spec.ts --grep "file project outline edits" --workers=1
```

Expected: backend suite, production build, typecheck, and focused browser test PASS. Report any pre-existing full-workbench failures separately; do not count them as elastic-outline passes.

- [ ] **Step 7: Record shipped behavior and commit**

Update `docs/superpowers/specs/2026-07-19-elastic-longform-outline-design.md` only if the final field names or error codes changed during implementation. Then commit tests and any doc correction:

```powershell
git add docs/superpowers/specs/2026-07-19-elastic-longform-outline-design.md tests/api/test_file_project_creation_routes.py tests/story_core/test_elastic_outline.py
git commit -m "test: verify elastic outline migration"
```

The final report must include the exact test counts, the live project's five arc names, the retained detailed chapter range, and the backup path.
