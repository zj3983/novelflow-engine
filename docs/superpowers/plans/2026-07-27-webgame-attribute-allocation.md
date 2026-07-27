# Webgame Attribute Allocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make free attribute points a configured, visible and persistent webgame progression loop from level-up planning through prose and character-card synchronization.

**Architecture:** Extend the structured power-system specification with an optional `attribute_allocation` object, then keep all arithmetic and validation in a focused `attribute_allocation.py` module. The orchestrator supplies the current allocation context to planning and writing, applies only valid allocation directives to the progression ledger, and mirrors the result into the protagonist card. Post-draft memory remains evidence-only, while the current `p-gou-webgame-restored` migration supplies its concrete six-stat baseline and first allocation.

**Tech Stack:** Python 3, Pydantic story models, pytest, existing file-project migration utilities, JSON-backed runtime projects.

---

## File Map

- Create `packages/story_core/attribute_allocation.py`: normalize rule access, level parsing, idempotent point awards, allocation validation and prompt context.
- Modify `packages/story_core/power_system_spec.py`: preserve and validate the optional structured rule.
- Modify `packages/story_core/power_system_prompt.py`: include the compact rule in stage-aware prompt slices.
- Modify `packages/story_core/world_blueprint_context.py`: render the rule in the managed power-system document.
- Modify `apps/web/lib/api.ts` and `apps/web/components/ws/StructuredPowerSystem.tsx`: show the configured rule on the world page.
- Modify `packages/story_core/orchestrator.py`: award points around ledger level changes, apply allocation directives, sync the full state, and pass the decision through director/writer plans.
- Modify `packages/story_core/writing_packet.py`: include current points and allocation history only when the project enables free allocation.
- Modify `packages/story_core/writing_taskbook.py`: stop suppressing attributes when a level-up allocation must be shown.
- Modify `packages/story_core/post_draft_memory.py`: document and accept evidence-backed allocation leaves without relaxing evidence rules.
- Modify `packages/story_core/web_game_review.py`: report a hard issue when a planned level-up allocation disappears from prose or contradicts the ledger contract.
- Modify `scripts/p_gou_power_system_data.py` and `scripts/upgrade_project_power_system.py`: migrate the current book rule, baseline, first allocation and chapter-nine outline wording.
- Add or extend focused tests under `tests/story_core/` and `tests/test_upgrade_project_power_system.py`.

### Task 1: Structured Attribute Rule

**Files:**
- Create: `packages/story_core/attribute_allocation.py`
- Modify: `packages/story_core/power_system_spec.py`
- Modify: `packages/story_core/power_system_prompt.py`
- Modify: `packages/story_core/world_blueprint_context.py`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/components/ws/StructuredPowerSystem.tsx`
- Test: `tests/story_core/test_attribute_allocation.py`
- Test: `tests/story_core/test_power_systems.py`
- Test: `tests/story_core/test_world_blueprint_context.py`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing schema and normalization tests**

```python
def test_power_system_preserves_free_attribute_allocation_rule():
    spec = complete_game_power_spec()
    spec["attribute_allocation"] = {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {"力量": 5, "体质": 5, "敏捷": 5, "智力": 5, "精神": 5, "感知": 5},
        "allow_carry": True,
        "respec_rule": "仅在明确洗点机会出现时重置",
    }
    normalized = normalize_power_system_spec(spec)
    assert normalized["attribute_allocation"]["points_per_level"] == 5
    assert normalized["attribute_allocation"]["base_attributes"]["智力"] == 5
    assert power_system_prompt_slice(spec)["attribute_allocation"]["mode"] == "free"
```

- [ ] **Step 2: Run the tests and confirm the rule is currently dropped**

Run: `pytest -q tests/story_core/test_power_systems.py -k attribute_allocation`

Expected: FAIL because `attribute_allocation` is absent after normalization.

- [ ] **Step 3: Implement bounded rule normalization**

Add `attribute_allocation` to `CANONICAL_FIELDS` and normalize exactly these fields:

```python
ATTRIBUTE_ALLOCATION_FIELDS = (
    "mode", "points_per_level", "starting_level", "base_attributes", "allow_carry", "respec_rule"
)

def normalize_attribute_allocation_rule(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or str(value.get("mode") or "").strip() != "free":
        return {}
    points = value.get("points_per_level")
    starting_level = value.get("starting_level", 1)
    base = value.get("base_attributes")
    if not isinstance(points, int) or isinstance(points, bool) or not 1 <= points <= 100:
        return {}
    if not isinstance(starting_level, int) or isinstance(starting_level, bool) or starting_level < 1:
        return {}
    if not isinstance(base, Mapping) or not base:
        return {}
    base_attributes = {
        str(name).strip(): amount
        for name, amount in list(base.items())[:16]
        if str(name).strip() and isinstance(amount, int) and not isinstance(amount, bool) and 0 <= amount <= 10000
    }
    if not base_attributes:
        return {}
    return {
        "mode": "free",
        "points_per_level": points,
        "starting_level": starting_level,
        "base_attributes": base_attributes,
        "allow_carry": bool(value.get("allow_carry", True)),
        "respec_rule": _text(value.get("respec_rule")),
    }
```

Expose the same normalized object from `power_system_prompt_slice`; do not add a default to genre-wide templates.

Render an “属性分配” section in both the managed Markdown and `StructuredPowerSystem`. The UI section shows allocation mode, points per level, whether points can be retained, initial values and the wash-point rule; it does not mix these mechanics into the six attribute effect descriptions.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest -q tests/story_core/test_attribute_allocation.py tests/story_core/test_power_systems.py tests/story_core/test_world_blueprint_context.py
cd apps/web
npx playwright test tests/story-workbench.spec.ts -g "属性分配"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/attribute_allocation.py packages/story_core/power_system_spec.py packages/story_core/power_system_prompt.py packages/story_core/world_blueprint_context.py apps/web/lib/api.ts apps/web/components/ws/StructuredPowerSystem.tsx tests/story_core/test_attribute_allocation.py tests/story_core/test_power_systems.py tests/story_core/test_world_blueprint_context.py apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add structured free attribute rules"
```

### Task 2: Idempotent Ledger Awards and Allocation

**Files:**
- Modify: `packages/story_core/attribute_allocation.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_attribute_allocation.py`
- Test: `tests/story_core/test_orchestrator.py`

- [ ] **Step 1: Write failing arithmetic and synchronization tests**

```python
def test_level_two_awards_five_points_once():
    ledger = {"protagonist": {"level": "Lv.1", "attributes": SIX_FIVES}}
    award_attribute_points(ledger, rule=RULE, previous_level=1, current_level=2, chapter_number=1)
    award_attribute_points(ledger, rule=RULE, previous_level=1, current_level=2, chapter_number=1)
    assert ledger["protagonist"]["unallocated_attribute_points"] == 5
    assert ledger["protagonist"]["attribute_point_awards"] == [{"level": 2, "points": 5, "chapter": 1}]

def test_valid_allocation_is_conserved_and_recorded():
    ledger = {"protagonist": {"attributes": SIX_FIVES, "unallocated_attribute_points": 5}}
    assert apply_attribute_allocation(ledger, {"allocations": {"智力": 5}, "reason": "提高火球伤害"}, rule=RULE, chapter_number=1)
    assert ledger["protagonist"]["attributes"]["智力"] == 10
    assert ledger["protagonist"]["unallocated_attribute_points"] == 0
    assert ledger["protagonist"]["attribute_allocations"][-1]["allocations"] == {"智力": 5}
```

Also test a two-level jump awards 10, while negative, unknown-stat and six-points-from-five directives are rejected without mutation.

- [ ] **Step 2: Run tests and confirm missing behavior**

Run: `pytest -q tests/story_core/test_attribute_allocation.py tests/story_core/test_orchestrator.py -k "attribute or allocation"`

Expected: FAIL because awards and directives are not applied.

- [ ] **Step 3: Implement ledger operations and orchestrator integration**

Use one award record per reached level, so regeneration cannot pay twice. In `_apply_ledger_updates`, capture the old level before merge, remove `protagonist.attribute_allocation` from the ordinary merge payload, merge normal leaves, award newly reached levels, then validate and apply the directive. Invalid directives are ignored and recorded in generation diagnostics, not persisted as character state.

Extend `_sync_character_game_panels` so these fields mirror into `game_state.current` and `game_panel.attributes`:

```python
for field in ("attributes", "unallocated_attribute_points", "attribute_point_awards", "attribute_allocations"):
    value = protagonist.get(field)
    if value not in (None, "", [], {}):
        current[field] = deepcopy(value)
```

Do not restore the old Su Ye-only fallback attributes when a structured rule exists.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/story_core/test_attribute_allocation.py tests/story_core/test_orchestrator.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/attribute_allocation.py packages/story_core/orchestrator.py tests/story_core/test_attribute_allocation.py tests/story_core/test_orchestrator.py
git commit -m "feat: persist level-up attribute points"
```

### Task 3: Director and Writer Handoff

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/writing_packet.py`
- Modify: `packages/story_core/writing_taskbook.py`
- Test: `tests/story_core/test_director_plan_quality.py`
- Test: `tests/story_core/test_writing_packet.py`
- Test: `tests/story_core/test_writing_taskbook.py`

- [ ] **Step 1: Write failing prompt-boundary tests**

```python
def test_writing_packet_includes_enabled_attribute_context_only():
    packet = build_codex_writing_packet(free_point_story(), chapter_number=2)
    assert packet["attribute_allocation"]["available_points"] == 5
    assert packet["attribute_allocation"]["attributes"]["智力"] == 5
    assert "attribute_allocation" not in build_codex_writing_packet(non_free_story(), chapter_number=2)

def test_upgrade_plan_requires_allocate_or_carry_decision():
    plan = complete_plan_with_level_change("Lv.1", "Lv.2")
    issues = _director_plan_quality_issues(free_point_story(), plan)
    assert any("属性点" in issue for issue in issues)
```

- [ ] **Step 2: Run tests and confirm current handoff omits allocation state**

Run: `pytest -q tests/story_core/test_writing_packet.py tests/story_core/test_director_plan_quality.py tests/story_core/test_writing_taskbook.py -k attribute`

Expected: FAIL.

- [ ] **Step 3: Add the compact planning and prose contract**

Add a single compact object, not the whole power-system dump:

```json
{
  "mode": "free",
  "points_per_level": 5,
  "attributes": {"力量": 5, "体质": 5, "敏捷": 5, "智力": 5, "精神": 5, "感知": 5},
  "available_points": 5,
  "latest_allocations": [],
  "chapter_decision": {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 0}
}
```

The director contract requires `event_plan.attribute_allocation_decision` only when the current chapter plan raises the level or when points are explicitly handled. Allowed modes are `allocate` and `carry`; allocation totals must not exceed projected available points. `_compact_writer_plan_for_prompt` must preserve this decision.

Replace the first-chapter taskbook phrase that suppresses all attributes with: the initial panel may stay short, but after a visible level-up the character must see the five new points and either allocate or consciously retain them. For this book's migrated first chapter, require the actual `智力+5` confirmation instead of a full repeated stat dump.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/story_core/test_writing_packet.py tests/story_core/test_director_plan_quality.py tests/story_core/test_writing_taskbook.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/orchestrator.py packages/story_core/writing_packet.py packages/story_core/writing_taskbook.py tests/story_core/test_director_plan_quality.py tests/story_core/test_writing_packet.py tests/story_core/test_writing_taskbook.py
git commit -m "feat: require visible level-up allocation decisions"
```

### Task 4: Evidence-Only Memory and Review

**Files:**
- Modify: `packages/story_core/post_draft_memory.py`
- Modify: `packages/story_core/web_game_review.py`
- Test: `tests/story_core/test_post_draft_memory.py`
- Test: `tests/story_core/test_web_game_review_agent.py`

- [ ] **Step 1: Write failing evidence and review tests**

```python
def test_memory_accepts_literal_attribute_allocation_evidence():
    body = "夜烬把五点全部加到智力上。确认后，智力从五变成十，可用属性点归零。"
    payload = {
        "ledger_updates": {"protagonist": {"attribute_allocation": {"allocations": {"智力": 5}, "remaining": 0}}},
        "ledger_evidence": {
            "protagonist.attribute_allocation.allocations.智力": "五点全部加到智力上",
            "protagonist.attribute_allocation.remaining": "可用属性点归零",
        },
    }
    result = normalize_post_draft_memory(payload, body=body, existing_character_names={"苏叶"})
    assert result["ledger_updates"]["protagonist"]["attribute_allocation"]["allocations"] == {"智力": 5}

def test_review_rejects_level_up_that_omits_required_allocation_scene():
    issues = review_web_game_chapter(level_up_body_without_points(), event_plan_with_allocate_decision(), world_facts=[])
    assert any(issue.code == "attribute_allocation_missing" for issue in issues)
```

Add rejection tests where the evidence says `智力+5` but the payload requests `智力+6`, and where prose merely lists a final panel without showing the decision.

- [ ] **Step 2: Run tests and verify expected failures**

Run: `pytest -q tests/story_core/test_post_draft_memory.py tests/story_core/test_web_game_review_agent.py -k attribute`

Expected: FAIL.

- [ ] **Step 3: Add aliases and the narrow review rule**

Add ledger aliases for `attributes`, `unallocated_attribute_points` and `attribute_allocation`. Keep exact numeric evidence checks. The reviewer should activate only when the event plan carries an allocation decision; it must not demand full panels in unrelated chapters.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/story_core/test_post_draft_memory.py tests/story_core/test_web_game_review_agent.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/post_draft_memory.py packages/story_core/web_game_review.py tests/story_core/test_post_draft_memory.py tests/story_core/test_web_game_review_agent.py
git commit -m "feat: verify prose-backed attribute allocations"
```

### Task 5: Migrate the Current Book

**Files:**
- Modify: `scripts/p_gou_power_system_data.py`
- Modify: `scripts/upgrade_project_power_system.py`
- Modify: `tests/test_upgrade_project_power_system.py`
- Runtime update: `data/exported-projects/p-gou-webgame-restored/.webnovel/project.json`
- Runtime update: `data/exported-projects/p-gou-webgame-restored/.webnovel/state.json`
- Runtime update: `data/exported-projects/p-gou-webgame-restored/.webnovel/outline.json`
- Runtime update: `data/exported-projects/p-gou-webgame-restored/chapters/0001-裂纹狼心.md`
- Runtime update: `data/exported-projects/p-gou-webgame-restored/大纲/第1卷-详细大纲.md`

- [ ] **Step 1: Write a failing migration test on a copied fixture**

```python
def test_upgrade_adds_attribute_rule_and_first_allocation(tmp_path):
    root = copy_project_fixture(tmp_path)
    run_upgrade(root)
    project = read_json(root / ".webnovel" / "project.json")
    state = read_json(root / ".webnovel" / "state.json")
    rule = project["world_blueprint"]["power_system_spec"]["attribute_allocation"]
    lead = next(card for card in state["characters"] if card["role"] == "protagonist")
    assert rule["points_per_level"] == 5
    assert lead["game_state"]["current"]["attributes"]["智力"] == 10
    assert lead["game_state"]["current"]["unallocated_attribute_points"] == 0
    assert "五点全部加到智力" in (root / "chapters" / "0001-裂纹狼心.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the migration test and confirm failure**

Run: `pytest -q tests/test_upgrade_project_power_system.py -k attribute`

Expected: FAIL because the existing migration has no allocation data.

- [ ] **Step 3: Extend the existing transactional migration**

Configure this book with six base stats at 5, 5 points per level, carry enabled and explicit respec-only reset. Patch the first chapter immediately after the Lv.2 message with a short in-world allocation action: 夜烬以意念展开角色面板，结合当前火球术路线，把五点全部加到智力，确认智力 5 -> 10，并看到可用属性点归零。虚拟现实界面不得出现光标。

Update state and both character mirrors with the same final values and one chapter-one allocation record. Change chapter nine from “first intelligence allocation / skill points into intelligence” to a later build-efficiency verification that keeps skill points and attribute points distinct.

- [ ] **Step 4: Run migration twice and verify idempotence**

Run:

```powershell
pytest -q tests/test_upgrade_project_power_system.py
python scripts/upgrade_project_power_system.py D:/xiaoshuofish-flow-test/data/exported-projects/p-gou-webgame-restored
python scripts/upgrade_project_power_system.py D:/xiaoshuofish-flow-test/data/exported-projects/p-gou-webgame-restored --check
```

Expected: tests PASS; first command migrates; `--check` reports no pending change.

- [ ] **Step 5: Commit tracked migration code**

```powershell
git add scripts/p_gou_power_system_data.py scripts/upgrade_project_power_system.py tests/test_upgrade_project_power_system.py
git commit -m "fix: migrate first webgame attribute allocation"
```

### Task 6: Regression and Real-Project Verification

**Files:**
- No new production files.

- [ ] **Step 1: Run focused suites**

Run:

```powershell
pytest -q tests/story_core/test_attribute_allocation.py tests/story_core/test_power_systems.py tests/story_core/test_orchestrator.py tests/story_core/test_writing_packet.py tests/story_core/test_director_plan_quality.py tests/story_core/test_writing_taskbook.py tests/story_core/test_post_draft_memory.py tests/story_core/test_web_game_review_agent.py tests/test_upgrade_project_power_system.py
```

Expected: PASS.

- [ ] **Step 2: Run full backend regression**

Run: `pytest -q tests/story_core tests/api`

Expected: all tests pass with only documented skips.

- [ ] **Step 3: Inspect the real writing packet and chapter**

Run:

```powershell
python scripts/novel_agent.py writing-packet file:p-gou-webgame-restored --chapter-number 1
rg -n "获得5点自由属性|五点全部加到智力|智力.*10|可用属性点.*0" data/exported-projects/p-gou-webgame-restored/chapters data/exported-projects/p-gou-webgame-restored/.webnovel
rg -n "技能点全投智力|第一次.*智力加点" data/exported-projects/p-gou-webgame-restored/.webnovel/outline.json data/exported-projects/p-gou-webgame-restored/大纲
```

Expected: writing packet contains the enabled rule and current allocation; chapter/state contain the same result; obsolete chapter-nine wording has no matches.

- [ ] **Step 4: Check repository cleanliness and diff quality**

Run: `git diff --check; git status --short`

Expected: no whitespace errors and no unintended tracked files.
