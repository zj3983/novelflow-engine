# Game Class Progression and Equipment Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete shared-level class advancement tree and evidence-backed equipment cards to game-webnovel world state, writing context, and the world page.

**Architecture:** Extend the existing bounded `power_system_spec` normalizer with game-only advancement tiers and per-path trees. Add a focused equipment-card domain module that normalizes, validates, merges, and projects cards, then connect it to file-project chapter persistence and writing-packet world selection. Render both structures through focused React components while preserving the existing generic world-blueprint update contract.

**Tech Stack:** Python 3.12, Pydantic-backed story models, FastAPI file-project routes, Next.js/React/TypeScript, CSS modules, pytest, Playwright.

---

### Task 1: Canonical Game Class Advancement Schema

**Files:**
- Modify: `packages/story_core/power_system_spec.py`
- Modify: `packages/story_core/power_system_prompt.py`
- Modify: `packages/story_core/world_enrichment.py`
- Test: `tests/api/test_project_world_enrichment.py`
- Test: `tests/story_core/test_writing_packet.py`

- [ ] **Step 1: Write failing normalization and validation tests**

Add fixtures with `class_advancement_tiers` at levels 10, 30, and 60 and `advancement_tree` entries on every path. Assert normalization preserves bounded option fields and game validation rejects missing, duplicate, out-of-order, or nonstandard levels.

```python
assert [item["level"] for item in validated["class_advancement_tiers"]] == [10, 30, 60]
assert validated["paths"][0]["advancement_tree"][1]["options"][0]["transfer_task"]

with pytest.raises(PowerSystemValidationError, match="game_class_advancement_tiers"):
    validate_power_system_spec(incomplete, novel_type_id="game_webnovel")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/api/test_project_world_enrichment.py -k "advancement_tier or advancement_tree"`

Expected: FAIL because the new fields are discarded or not validated.

- [ ] **Step 3: Implement bounded nested normalization**

Add canonical field constants and normalizers for tiers, advancement nodes, and options. Limit all lists and strings using the existing `_MAX_LIST` and `_MAX_STRING` safeguards.

```python
GAME_CLASS_ADVANCEMENT_LEVELS = (10, 30, 60)

def _normalize_advancement_option(value: Any) -> dict[str, Any]:
    return {
        "name": _text(_mapping_get(value, "name")),
        "requirements": _text_list(_mapping_get(value, "requirements")),
        "transfer_task": _text(_mapping_get(value, "transfer_task")),
        "ability_changes": _text_list(_mapping_get(value, "ability_changes")),
        "next_options": _text_list(_mapping_get(value, "next_options")),
    }
```

- [ ] **Step 4: Add game-only completeness validation**

Require exactly the shared levels `(10, 30, 60)` and require every base path to have one node per level with at least one named option, a transfer task, and an ability change. Leave non-game validation unchanged.

- [ ] **Step 5: Update world-enrichment and writing prompt projections**

Tell the model that all game classes share the three levels and that hidden classes are options within those nodes. Ensure `power_system_prompt_slice` retains the nearest and next class nodes without exceeding its existing budget.

- [ ] **Step 6: Run focused tests and commit**

Run:

```powershell
pytest -q tests/api/test_project_world_enrichment.py tests/story_core/test_writing_packet.py
```

Expected: PASS.

Commit: `feat: add structured game class advancement trees`

### Task 2: Equipment Card Domain Model and Merge Rules

**Files:**
- Create: `packages/story_core/equipment_cards.py`
- Modify: `packages/story_core/models.py`
- Test: `tests/story_core/test_equipment_cards.py`

- [ ] **Step 1: Write failing domain tests**

Cover bounded normalization, stable ID generation, rejection of non-equipment items, non-empty merge precedence, owner/durability updates, aliases, conflicting same-name candidates, and lore statuses.

```python
card = normalize_equipment_card({
    "name": "暮色裁决",
    "equipment_type": "武器",
    "rarity": "史诗",
    "description": "钟声响起时，持剑者已经没有退路。",
    "lore": "由旧王庭最后一位铸剑师打造。",
    "lore_status": "rumor",
})
assert card["id"] == "equipment-mu-se-cai-jue"
assert card["lore_status"] == "rumor"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/story_core/test_equipment_cards.py`

Expected: collection error because `equipment_cards` does not exist.

- [ ] **Step 3: Implement the focused domain module**

Export:

```python
normalize_equipment_card(value, *, chapter_number=None) -> dict[str, Any]
normalize_equipment_cards(value) -> list[dict[str, Any]]
merge_equipment_cards(existing, updates) -> EquipmentMergeResult
equipment_cards_for_context(cards, *, names=(), owners=(), limit=12) -> list[dict[str, Any]]
```

Treat only weapon, armor, accessory, and explicitly equippable special-item types as equipment. Preserve `confirmed`, `rumor`, and `unknown`; never upgrade lore to confirmed without confirmed evidence. Empty update fields do not erase stored facts.

- [ ] **Step 4: Add a typed `EquipmentCard` model**

Add a Pydantic model with default-empty collections and bounded chapter integers. Keep the serialized world-blueprint shape as JSON-compatible dictionaries.

- [ ] **Step 5: Run tests and commit**

Run: `pytest -q tests/story_core/test_equipment_cards.py`

Expected: PASS.

Commit: `feat: add evidence-backed equipment card model`

### Task 3: Chapter Extraction, Persistence, and Writing Context

**Files:**
- Modify: `packages/story_core/post_draft_memory.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/world_context_selection.py`
- Modify: `packages/story_core/writing_packet.py`
- Test: `tests/story_core/test_post_draft_memory.py`
- Test: `tests/story_core/test_file_project_store.py`
- Test: `tests/story_core/test_writing_packet.py`

- [ ] **Step 1: Write failing extraction and persistence tests**

Extend the post-draft extraction contract with `equipment_updates`. Verify an explicit named weapon with body evidence is accepted, materials and currency are rejected, and two chapters update one card instead of creating duplicates.

```python
assert memory["equipment_updates"][0]["name"] == "暮色裁决"
assert memory["equipment_updates"][0]["first_appearance_chapter"] == 8
assert state["world_blueprint"]["equipment_cards"][0]["current_owner"] == "夜烬"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest -q tests/story_core/test_post_draft_memory.py -k equipment
pytest -q tests/story_core/test_file_project_store.py -k equipment_card
```

Expected: FAIL because extraction and world persistence do not expose equipment cards.

- [ ] **Step 3: Extend the extraction prompt and evidence filter**

Request equipment updates only when the final prose supplies a literal name and equipment evidence. Include description/lore only when the prose supplies the statement, and set lore to `rumor` when introduced as legend, rumor, or uncertain narration.

- [ ] **Step 4: Merge cards during chapter synchronization**

After accepted post-draft memory is applied, merge updates into both project world blueprint and state world context through the existing project transaction. Append workflow warnings for rejected or conflicting candidates without blocking chapter persistence.

- [ ] **Step 5: Project relevant equipment into writing packets**

Select cards referenced by scene characters, current owners, current equipment, chapter plan text, or recent facts. Fall back to a bounded set of active cards. Include only the nearest completed and next class advancement nodes for the protagonist's level.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
pytest -q tests/story_core/test_post_draft_memory.py tests/story_core/test_file_project_store.py tests/story_core/test_writing_packet.py
```

Expected: PASS.

Commit: `feat: track chapter equipment cards in writing context`

### Task 4: API Types and Editable Equipment Catalog

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/components/ws/EquipmentCatalog.tsx`
- Create: `apps/web/components/ws/EquipmentCatalog.module.css`
- Modify: `apps/web/app/projects/[id]/world/page.tsx`
- Test: `tests/api/test_file_project_creation_routes.py`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing API and UI tests**

Verify the project response exposes normalized equipment cards, PUT rejects nameless/typeless cards, and the world page filters cards by type, rarity, and owner. Verify editing description, lore status, owner, durability, and status persists through `updateProject`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pytest -q tests/api/test_file_project_creation_routes.py -k equipment_card
cd apps/web; npx playwright test tests/story-workbench.spec.ts --grep "装备图鉴"
```

Expected: FAIL because no equipment catalog is rendered or validated.

- [ ] **Step 3: Normalize equipment cards at the file-project update boundary**

When `world_blueprint.equipment_cards` is supplied, normalize and validate the list before merging it into project data. Return a stable `invalid_equipment_cards` error for malformed records.

- [ ] **Step 4: Add TypeScript types and catalog component**

Define `ImportedEquipmentCard` and add `equipment_cards?: ImportedEquipmentCard[]` to `ImportedWorldBlueprint`. Render compact cards with semantic controls: select menus for filters/status, inputs for facts, and a textarea for description/lore. Do not render empty lore regions.

- [ ] **Step 5: Add responsive styles and integrate only for game projects**

Use a two-column catalog above 900px and one column below. Keep card radius at 8px or less, avoid nested cards, and enforce `min-width: 0` and `overflow-wrap: anywhere`.

- [ ] **Step 6: Verify and commit**

Run the focused API and Playwright commands from Step 2.

Expected: PASS.

Commit: `feat: add editable game equipment catalog`

### Task 5: Render the Complete Class Tree

**Files:**
- Modify: `apps/web/components/ws/StructuredPowerSystem.tsx`
- Modify: `apps/web/components/ws/StructuredPowerSystem.module.css`
- Modify: `apps/web/lib/api.ts`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing class-tree UI tests**

Update the fixture to include shared tiers and per-path trees. Assert all three level headings, transfer tasks, requirements, ability changes, and next options are visible. Assert malformed or incomplete game trees show “力量体系需要补全”.

- [ ] **Step 2: Run test and verify RED**

Run: `cd apps/web; npx playwright test tests/story-workbench.spec.ts --grep "职业转职树"`

Expected: FAIL because the current UI only renders string branches.

- [ ] **Step 3: Extend types and structured completeness checks**

Add types for advancement tiers, nodes, and options. For game projects, require levels exactly `10, 30, 60` and one valid node at each level on every path. Keep xianxia and generic completeness behavior unchanged.

- [ ] **Step 4: Render shared tiers and path options**

Render one “职业转职树” section with vertical level nodes and compact path option groups. Retain legacy branch strings only as a fallback when the structured draft is incomplete; do not present fallback strings as a complete system.

- [ ] **Step 5: Verify desktop and mobile behavior**

Run:

```powershell
cd apps/web
npx playwright test tests/story-workbench.spec.ts --grep "职业转职树|装备图鉴|360px"
```

Expected: PASS with no horizontal overflow at 360px.

- [ ] **Step 6: Commit**

Commit: `feat: render game class advancement tree`

### Task 6: Regression and Live Verification

**Files:**
- Modify only if a regression is found in files already listed above.

- [ ] **Step 1: Run backend regression suites**

```powershell
pytest -q tests/story_core/test_equipment_cards.py tests/story_core/test_post_draft_memory.py tests/story_core/test_file_project_store.py tests/story_core/test_writing_packet.py tests/api/test_project_world_enrichment.py tests/api/test_file_project_creation_routes.py
```

- [ ] **Step 2: Run frontend regression suites**

```powershell
cd apps/web
npx playwright test tests/story-workbench.spec.ts --grep "力量体系|职业转职树|装备图鉴|世界观"
```

- [ ] **Step 3: Verify the live game project**

Open `http://127.0.0.1:3000/projects/file%3Ap-gou-webgame-restored/world`. Confirm the page either displays the complete tree/catalog or clearly marks legacy data for enrichment. Run world enrichment once if the project still has legacy data, then confirm cards and class nodes persist after reload.

- [ ] **Step 4: Inspect writing context**

Fetch a writing packet for the next chapter and verify it includes the next relevant transfer node and only relevant equipment cards, without expanding the full catalog into every prompt.

- [ ] **Step 5: Final diff and status review**

Run:

```powershell
git diff --check
git status --short
```

Confirm only task-related lines are staged or committed and pre-existing unrelated working-tree changes remain intact.
