# Outline And Character Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-click generation of a three-level opening outline and concrete first-arc character cards, including a visible stage antagonist and a protected long-term antagonist.

**Architecture:** A new planning generator returns one strict JSON document containing the outline and character candidates. A separate validator enforces opening-plan quality, while `FileProjectStore` performs an atomic merge into the file project. Writing packets continue to use the existing outline selector and add a new cast-based character selector so only scene-relevant, reveal-safe character data reaches the writer.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, pytest, Next.js/React, TypeScript, Playwright.

---

## File Structure

- Create `packages/story_core/character_profiles.py`: concrete character-card models, legacy normalization, non-empty merge, and prompt-safe projection.
- Create `packages/story_core/outline_planning.py`: generated planning document models and opening/continuation validation.
- Create `packages/story_core/outline_planning_generation.py`: one-shot LLM planning generator.
- Modify `packages/story_core/project_outline.py`: add stage-antagonist traces and chapter cast fields to the canonical outline.
- Modify `packages/story_core/models.py`: attach concrete profile fields to runtime `CharacterState` without removing existing portraits.
- Modify `packages/story_core/file_project_store.py`: atomic planning save, generation entrypoint, cast selection, and writing-packet integration.
- Modify `apps/api/routes/file_projects.py`: planning generation API.
- Modify `apps/web/lib/api.ts`: planning and concrete character-card types and requests.
- Modify `apps/web/app/projects/[id]/outline/page.tsx`: generate, regenerate, extend, guidance, and remaining-plan warning.
- Modify `apps/web/app/projects/[id]/characters/page.tsx`: concrete information first; abstract portrait second.
- Modify `apps/web/app/globals.css`: small layout additions for planning controls and concrete profile sections.
- Add focused unit, API, and Playwright tests beside the existing outline, file project, and workbench tests.

### Task 1: Extend The Canonical Outline Without Breaking Old Projects

**Files:**
- Modify: `packages/story_core/project_outline.py`
- Modify: `tests/story_core/test_project_outline.py`

- [ ] **Step 1: Write failing schema and selection tests**

Add tests proving arc plans accept `stage_antagonist`, `long_term_antagonist_traces`, chapter plans accept `cast`, and `select_outline_context()` returns only the active arc and target chapter with those fields.

```python
def test_outline_supports_opposition_and_chapter_cast() -> None:
    outline = normalize_project_outline({
        "arcs": [{
            "id": "opening",
            "start_chapter": 1,
            "end_chapter": 10,
            "stage_antagonist": "赵衡",
            "long_term_antagonist_traces": ["旧名册有一页被换过"],
        }],
        "chapters": [{"chapter_number": 1, "cast": ["林照", "赵衡"]}],
    })
    context = select_outline_context(outline, 1)
    assert context["active_arc"]["stage_antagonist"] == "赵衡"
    assert context["chapter"]["cast"] == ["林照", "赵衡"]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/story_core/test_project_outline.py -q`

Expected: FAIL because the strict Pydantic models reject the new fields.

- [ ] **Step 3: Add fields with backward-compatible defaults**

```python
class ArcOutline(_OutlineModel):
    # existing fields remain unchanged
    stage_antagonist: str = ""
    long_term_antagonist_traces: list[str] = Field(default_factory=list)

class ChapterPlan(_OutlineModel):
    # existing fields remain unchanged
    cast: list[str] = Field(default_factory=list)
```

Update legacy projection so missing fields normalize to empty values. Do not make manual outline saving require an antagonist or five chapters.

- [ ] **Step 4: Run outline tests and verify GREEN**

Run: `python -m pytest tests/story_core/test_project_outline.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/project_outline.py tests/story_core/test_project_outline.py
git commit -m "feat: extend outline opposition and cast fields"
```

### Task 2: Add Concrete Character Profiles And Legacy Compatibility

**Files:**
- Create: `packages/story_core/character_profiles.py`
- Modify: `packages/story_core/models.py`
- Create: `tests/story_core/test_concrete_character_profiles.py`

- [ ] **Step 1: Write failing concrete profile tests**

Cover basic identity, origin, current life, story drive, dialogue examples, relationship knowledge boundaries, old-card normalization, and preservation of non-empty user fields.

```python
def test_generated_patch_never_overwrites_non_empty_user_fields() -> None:
    existing = {"name": "林照", "identity_profile": {"age": 19, "occupation": "守祠杂役"}}
    generated = {"name": "林照", "identity_profile": {"age": 18, "occupation": "外门弟子"}}
    merged = merge_character_profile(existing, generated)
    assert merged["identity_profile"] == {"age": 19, "occupation": "守祠杂役"}
```

- [ ] **Step 2: Run the new test and verify RED**

Run: `python -m pytest tests/story_core/test_concrete_character_profiles.py -q`

Expected: collection fails because `character_profiles.py` does not exist.

- [ ] **Step 3: Implement focused profile models**

Create models with these exact responsibilities:

```python
class IdentityProfile(BaseModel):
    aliases: list[str] = Field(default_factory=list)
    gender: str = ""
    age: int | None = None
    birthplace: str = ""
    origin: str = ""
    current_identity: str = ""
    occupation: str = ""
    affiliation: str = ""

class BackgroundProfile(BaseModel):
    family: str = ""
    upbringing: str = ""
    education_or_training: str = ""
    formative_events: list[str] = Field(default_factory=list)
    arrival_reason: str = ""

class CurrentLifeProfile(BaseModel):
    residence: str = ""
    livelihood: str = ""
    economic_state: str = ""
    resources_and_ability: str = ""
    authority_scope: str = ""
    immediate_problem: str = ""

class StoryDriveProfile(BaseModel):
    long_term_goal: str = ""
    immediate_goal: str = ""
    motivation: str = ""
    failure_stakes: str = ""
    hidden_matters: list[str] = Field(default_factory=list)
    main_conflict_reason: str = ""
```

Add `character_tier`, `first_appearance`, the four nested profiles, `dialogue_examples`, and `relationship_notes` to `CharacterState`. Keep all current portrait/performance fields intact.

Implement `normalize_character_profile()`, `merge_character_profile()`, and `project_character_for_writer()`. The writer projection must omit `hidden_matters` unless explicitly listed in an allowed reveal set.

- [ ] **Step 4: Run profile and existing portrait tests**

Run: `python -m pytest tests/story_core/test_concrete_character_profiles.py tests/story_core/test_character_portraits.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/character_profiles.py packages/story_core/models.py tests/story_core/test_concrete_character_profiles.py
git commit -m "feat: add concrete character profiles"
```

### Task 3: Validate A Generated Opening Plan

**Files:**
- Create: `packages/story_core/outline_planning.py`
- Create: `tests/story_core/test_outline_planning.py`

- [ ] **Step 1: Write failing plan-validation tests**

Test one valid plan and explicit failures for missing protagonist, missing stage antagonist, missing long-term antagonist, chapter gaps, fewer than five opening chapters, and a chapter cast name with no card.

```python
def test_opening_plan_rejects_cast_without_character_card(valid_payload) -> None:
    valid_payload["outline"]["chapters"][0]["cast"].append("无卡人物")
    with pytest.raises(ValueError, match="missing_character_card:无卡人物"):
        validate_generated_opening_plan(valid_payload)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/story_core/test_outline_planning.py -q`

Expected: collection fails because the module does not exist.

- [ ] **Step 3: Implement strict generation-only validation**

Define `PlanningCharacterCard`, `GeneratedOutlinePlan`, and `validate_generated_opening_plan()`. Initial generation must require:

- all five total-outline fields;
- one arc beginning at chapter 1;
- chapters 1 through 5 without gaps;
- one protagonist card;
- one `stage_antagonist` card matching the arc field;
- one `long_term_antagonist` card;
- four to six cards in total for the opening stage, so the initial cast stays useful without becoming a full cast database;
- every chapter `cast` name present in the generated cards.

This validator is not called by manual `PUT /outline`, so authors can keep partial drafts.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m pytest tests/story_core/test_outline_planning.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/outline_planning.py tests/story_core/test_outline_planning.py
git commit -m "feat: validate generated opening plans"
```

### Task 4: Generate The Plan In One LLM Call

**Files:**
- Create: `packages/story_core/outline_planning_generation.py`
- Create: `tests/story_core/test_outline_planning_generation.py`

- [ ] **Step 1: Write failing generator contract tests**

Use an injected `post_json` stub. Assert the request contains only the selected opening direction, genre metadata, existing user-confirmed fields, mode, and one-time guidance. Assert the parsed response passes `GeneratedOutlinePlan` validation.

```python
def test_generator_requests_one_structured_plan(fake_runtime, valid_response) -> None:
    calls = []
    generator = LLMOutlinePlanningGenerator(post_json=lambda *args, **kwargs: calls.append(args[2]) or valid_response)
    result = generator.generate(brief, mode="initial", guidance="反派不要脸谱化")
    assert len(calls) == 1
    assert result.outline.chapters[0].chapter_number == 1
    assert "反派不要脸谱化" in calls[0]["messages"][1]["content"]
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests/story_core/test_outline_planning_generation.py -q`

Expected: collection fails because the generator does not exist.

- [ ] **Step 3: Implement the generator**

Follow the runtime resolution pattern in `opening_directions.py`. Use a Chinese system instruction and JSON-only response format. Support `initial`, `regenerate`, and `extend` modes. Initial/regenerate output uses chapters 1-5; extend receives compact current outline and actual state, and returns only the next contiguous chapter batch plus any new character cards.

Do not include full chapter bodies, full prompt-module catalogs, or all existing character cards.

- [ ] **Step 4: Run generator tests and verify GREEN**

Run: `python -m pytest tests/story_core/test_outline_planning_generation.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/outline_planning_generation.py tests/story_core/test_outline_planning_generation.py
git commit -m "feat: generate outline and cast in one call"
```

### Task 5: Save Outline And Character Cards Atomically

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing atomic-save tests**

Test successful initial generation, regeneration preserving user-edited fields, extension appending contiguous chapters, and rollback when one replacement write fails.

```python
def test_save_generated_plan_updates_outline_project_and_state_together(file_store, generated_plan) -> None:
    file_store.save_generated_outline_plan(generated_plan, mode="initial")
    assert file_store.project_outline()["chapters"][0]["chapter_number"] == 1
    assert file_store.project()["character_profiles"][0]["identity_profile"]["age"] == 19
    assert file_store.state()["characters"][0]["name"] == "林照"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/story_core/test_file_project_store.py -q`

Expected: FAIL because `save_generated_outline_plan()` is missing.

- [ ] **Step 3: Implement planning persistence**

Add `generate_outline_plan(self, generator, *, mode: str, guidance: str = "")` and `save_generated_outline_plan(self, plan, *, mode: str)`. The first method builds the compact planning brief and delegates once to the generator. The second validates the result, merges it, and returns the saved outline and selected character cards.

Use `_replace_json_transaction()` for `.webnovel/outline.json`, `.webnovel/project.json`, and `.webnovel/state.json`. Merge cards by canonical name with `merge_character_profile()`. Preserve non-empty author fields. Set `pipeline_stage` to `world_ready` only after all files validate. Keep a timestamped generated-plan snapshot under `.story-system/plans/` for rollback and diagnosis.

- [ ] **Step 4: Run store tests and verify GREEN**

Run: `python -m pytest tests/story_core/test_file_project_store.py tests/story_core/test_outline_planning.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/file_project_store.py tests/story_core/test_file_project_store.py
git commit -m "feat: persist generated plans atomically"
```

### Task 6: Expose Planning Generation Through The File API

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `tests/api/test_file_project_creation_routes.py`

- [ ] **Step 1: Write failing API tests**

Cover `initial`, `regenerate`, and `extend`, trimmed one-time guidance, invalid mode, generator failure, and unchanged files after failure.

```python
def test_generate_file_project_plan_returns_outline_and_characters(client, monkeypatch) -> None:
    response = client.post(
        "/file-projects/file:p-test/outline/generate",
        json={"mode": "initial", "guidance": "阶段对手要有现实利益"},
    )
    assert response.status_code == 200
    assert response.json()["outline"]["chapters"][0]["chapter_number"] == 1
    assert any(card["character_tier"] == "stage_antagonist" for card in response.json()["characters"])
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `python -m pytest tests/api/test_file_project_creation_routes.py -q`

Expected: endpoint returns 404.

- [ ] **Step 3: Add one request model and one endpoint**

```python
class OutlinePlanGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["initial", "regenerate", "extend"] = "initial"
    guidance: str = Field(default="", max_length=1000)
```

Add `POST /file-projects/{project_id}/outline/generate`. Map model/runtime failures to stable 400 details and missing projects to 404.

- [ ] **Step 4: Run API tests and verify GREEN**

Run: `python -m pytest tests/api/test_file_project_creation_routes.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/routes/file_projects.py tests/api/test_file_project_creation_routes.py
git commit -m "feat: add file outline generation API"
```

### Task 7: Send Only Planned Cast Cards To The Writer

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `tests/story_core/test_file_project_store.py`
- Modify: `tests/story_core/test_webnovel_character_cards.py`

- [ ] **Step 1: Write failing context-selection tests**

Create a chapter plan whose cast is `林照` and `赵衡`, plus unrelated cards. Assert the writing packet contains only those cards, always includes the protagonist, omits long-term hidden matters, and keeps permitted public traces.

```python
def test_writing_packet_uses_chapter_cast_and_hides_long_term_secrets(store) -> None:
    packet = store.writing_packet(1)
    assert [card["name"] for card in packet["character_cards"]] == ["林照", "赵衡"]
    assert "幕后身份" not in json.dumps(packet["character_cards"], ensure_ascii=False)
    assert packet["outline_context"]["active_arc"]["long_term_antagonist_traces"]
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/story_core/test_file_project_store.py tests/story_core/test_webnovel_character_cards.py -q`

Expected: FAIL because the current packet sends the full character list.

- [ ] **Step 3: Add cast-based selection**

Add a private selector that reads `selected_outline["chapter"]["cast"]`, includes the protagonist, resolves cards by name/game ID, and calls `project_character_for_writer()`. Replace the full `characters` assignment in the writing packet with this selected list. Do not change stored cards.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/story_core/test_file_project_store.py tests/story_core/test_webnovel_character_cards.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/file_project_store.py tests/story_core/test_file_project_store.py tests/story_core/test_webnovel_character_cards.py
git commit -m "feat: scope writing packets to planned cast"
```

### Task 8: Add Outline Generation Controls To The Workbench

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing Playwright tests**

Mock the generation endpoint and verify:

- an empty outline shows “生成大纲”;
- an existing outline shows “重新生成” and “补充后续章节”;
- guidance is sent once and not persisted into the returned outline;
- successful generation refreshes all three tabs;
- two remaining planned chapters show a visible reminder;
- API failure leaves the current fields unchanged.

- [ ] **Step 2: Run the focused browser test and verify RED**

Run: `npm --prefix apps/web run test:e2e -- --grep "outline generation"`

Expected: FAIL because the controls and API function do not exist.

- [ ] **Step 3: Add API types and functions**

Extend `ProjectOutlineArc` and `ProjectChapterOutline`, then add:

```typescript
export type OutlineGenerationMode = "initial" | "regenerate" | "extend";

export async function generateProjectOutline(
  projectId: string,
  mode: OutlineGenerationMode,
  guidance = "",
): Promise<GeneratedOutlinePlanResponse> {
  return await tryFetchJson(`${fileProjectPath(projectId)}/outline/generate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ mode, guidance }),
  }, 180000) as GeneratedOutlinePlanResponse;
}
```

- [ ] **Step 4: Implement the page controls**

Use one guidance textarea shared by the three explicit commands. Disable controls while a request is active. Replace the local draft only after a successful response. Keep manual editing and “保存大纲” unchanged.

- [ ] **Step 5: Run Playwright and build**

Run:

```powershell
npm --prefix apps/web run test:e2e -- --grep "outline generation"
npm --prefix apps/web run build
```

Expected: focused test and build pass.

- [ ] **Step 6: Commit**

```powershell
git add apps/web/lib/api.ts apps/web/app/projects/[id]/outline/page.tsx apps/web/app/globals.css apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add outline generation controls"
```

### Task 9: Make Character Cards Concrete In The UI

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/characters/page.tsx`
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing character-card UI tests**

Verify a card visibly shows age, origin, occupation, upbringing, current livelihood, immediate goal, stakes, relationships, and dialogue examples. Verify editing sends those concrete fields, while old projects with only portrait fields remain readable.

- [ ] **Step 2: Run the focused browser test and verify RED**

Run: `npm --prefix apps/web run test:e2e -- --grep "concrete character card"`

Expected: FAIL because the page does not render the concrete fields.

- [ ] **Step 3: Extend frontend character types**

Mirror the Python nested models in `StoryCharacter`. Keep every new property optional so old API payloads remain valid.

- [ ] **Step 4: Reorder and expand the character page**

Render sections in this order: basic identity, origin, current life, goals/conflict, relationships, dialogue examples, dynamic state, advanced portrait. Change save to send the concrete nested fields plus an edited portrait, instead of sending only `personality_portrait`.

- [ ] **Step 5: Run focused Playwright and build**

Run:

```powershell
npm --prefix apps/web run test:e2e -- --grep "concrete character card"
npm --prefix apps/web run build
```

Expected: focused test and build pass.

- [ ] **Step 6: Commit**

```powershell
git add apps/web/lib/api.ts apps/web/app/projects/[id]/characters/page.tsx apps/web/app/globals.css apps/web/tests/story-workbench.spec.ts
git commit -m "feat: show concrete character cards"
```

### Task 10: End-To-End Regression Verification

**Files:**
- Modify only if a test exposes a defect in files already listed above.

- [ ] **Step 1: Run the complete backend suite**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run the complete web suite**

Run:

```powershell
npm --prefix apps/web run test:e2e
npm --prefix apps/web run build
```

Expected: all Playwright tests pass and the production build exits 0.

- [ ] **Step 3: Verify the existing migrated novel remains readable**

Run a read-only script against `data/exported-projects/p-xianxia-incense-test-2` and assert:

- title remains `我替宗门看守断香炉`;
- chapter 1 body hash is unchanged;
- old character cards render through normalization;
- manual outline remains editable before AI regeneration.

- [ ] **Step 4: Inspect the final diff**

Run:

```powershell
git status --short
git diff --check
git diff --stat HEAD~9..HEAD
```

Confirm unrelated pre-existing genre changes and migration-tool files were not staged by these tasks.

If verification exposes a defect, return to the task that owns the affected behavior, add a failing regression test there, and repeat that task's RED-GREEN-commit cycle before rerunning this section.
