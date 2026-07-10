# Structured Character Portrait Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, editable personality portraits to every character card and inject only a scene-relevant character slice into chapter-writing prompts.

**Architecture:** Extend `CharacterState` with typed portrait models, generate missing fields through a new rule-only portrait module, and persist edits through file-project character endpoints. Keep the full portrait in project state while the orchestrator selects only planned characters and compiles a compact scene-performance slice. The characters page edits the canonical card and never calls a language model.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, pytest, Next.js App Router, React, TypeScript.

---

### Task 1: Typed portrait model and deterministic defaults

**Files:**
- Create: `packages/story_core/character_portraits.py`
- Modify: `packages/story_core/models.py`
- Test: `tests/story_core/test_character_portraits.py`

- [ ] **Step 1: Write the failing model/default tests**

```python
from packages.story_core.character_portraits import complete_character_portrait
from packages.story_core.models import CharacterState, PersonalityPortrait


def test_protagonist_portrait_has_behavioral_detail_without_llm():
    character = CharacterState(name="苏叶", role="主角", game_id="夜烬")
    completed = complete_character_portrait(character, genre="网游", story_function="隐藏优势成长线")
    portrait = completed.personality_portrait
    assert portrait.temperament.core_traits
    assert portrait.psychology.desire
    assert portrait.behavior.pressure_mode
    assert portrait.emotion.triggers
    assert portrait.voice.lying_style
    assert portrait.growth.invariants
    assert portrait.writing_limits


def test_portrait_completion_preserves_user_fields():
    character = CharacterState(
        name="洛婶",
        role="药剂师",
        personality_portrait=PersonalityPortrait.model_validate(
            {"temperament": {"core_traits": ["嘴硬心软"]}}
        ),
    )
    completed = complete_character_portrait(character, genre="网游")
    assert completed.personality_portrait.temperament.core_traits == ["嘴硬心软"]
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `pytest tests/story_core/test_character_portraits.py -q`

Expected: collection fails because `character_portraits` and `PersonalityPortrait` do not exist.

- [ ] **Step 3: Add typed portrait sections**

Add Pydantic models in `models.py`: `TemperamentPortrait`, `PsychologyPortrait`, `BehaviorPortrait`, `EmotionPortrait`, `SocialPortrait`, `CharacterVoicePortrait`, `GrowthPortrait`, and `PersonalityPortrait`. Add:

```python
personality_portrait: PersonalityPortrait = Field(default_factory=PersonalityPortrait)
```

to `CharacterState`.

- [ ] **Step 4: Implement rule-only completion**

Create `complete_character_portrait(character, genre, story_function="")` in `character_portraits.py`. Select templates by protagonist, recurring supporting character, and service NPC. Merge recursively so non-empty user values always win. Do not import or call any model provider.

- [ ] **Step 5: Run the focused test**

Run: `pytest tests/story_core/test_character_portraits.py -q`

Expected: all portrait tests pass.

### Task 2: Persist complete cards and protect existing data

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing persistence tests**

```python
def test_complete_character_portraits_adds_missing_fields_without_overwrite(file_project_store):
    before = file_project_store.state()["characters"][0]
    before["personality_portrait"] = {"temperament": {"core_traits": ["用户自定义"]}}
    file_project_store.update_character(before["name"], before)
    result = file_project_store.complete_character_portrait(before["name"])
    assert result["personality_portrait"]["temperament"]["core_traits"] == ["用户自定义"]
    assert result["personality_portrait"]["behavior"]["pressure_mode"]


def test_update_character_rejects_unknown_name(file_project_store):
    with pytest.raises(KeyError, match="character_not_found"):
        file_project_store.update_character("不存在的人", {"core_motivation": "x"})
```

- [ ] **Step 2: Confirm the tests fail**

Run: `pytest tests/story_core/test_file_project_store.py -k "character_portrait or update_character" -q`

Expected: methods are missing.

- [ ] **Step 3: Add store methods**

Implement `update_character(name, patch)` and `complete_character_portrait(name)` on `FileProjectStore`. Read the raw state, locate the canonical character by name or game ID, validate through `CharacterState`, preserve immutable identity fields unless explicitly supplied, and write `.webnovel/state.json` atomically through the existing `_write_json` helper.

- [ ] **Step 4: Complete cards during state assembly without forced migration**

When `state()` builds protagonist and proposed cards, expose a completed in-memory portrait. Only `update_character` or `complete_character_portrait` persists it, so old projects remain readable without automatic file churn.

- [ ] **Step 5: Run store tests**

Run: `pytest tests/story_core/test_file_project_store.py -q`

Expected: all file-project tests pass.

### Task 3: Compile a scene-relevant character slice

**Files:**
- Modify: `packages/story_core/character_portraits.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_webnovel_character_cards.py`

- [ ] **Step 1: Write failing extraction tests**

```python
def test_character_context_contains_scene_slice_not_full_portrait():
    context = _character_context_for_prompt(
        story,
        {
            "character_moves": [{"name": "夜烬"}, {"name": "洛婶"}],
            "scene_cards": [{"location": "药剂铺", "name": "洛婶"}],
        },
    )
    assert [card["identity"]["name"] for card in context["cards"]] == ["苏叶", "洛婶"]
    assert context["cards"][0]["scene_portrait"]["pressure_behavior"]
    assert context["cards"][0]["scene_portrait"]["voice"]
    assert "personality_portrait" not in context["cards"][0]
```

- [ ] **Step 2: Confirm extraction test fails**

Run: `pytest tests/story_core/test_webnovel_character_cards.py -q`

Expected: `scene_portrait` is absent.

- [ ] **Step 3: Add `build_scene_portrait_slice`**

Return only current drive, current emotion, pressure behavior, conflict reaction, relevant social stance, voice, visible mannerisms, and writing limits. Cap list counts and text lengths so each character remains within 300 to 500 Chinese characters.

- [ ] **Step 4: Wire the slice into `_character_context_for_prompt`**

Keep `_planned_character_names` as the selection gate. Add `scene_portrait` to selected cards and update `_character_context_summary_for_prompt` to carry the slice instead of reducing the card to only motivation, speech, and risk.

- [ ] **Step 5: Run prompt and character tests**

Run: `pytest tests/story_core/test_webnovel_character_cards.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_file_project_store.py -q`

Expected: selected-character tests pass and prompt tests confirm the full character library is absent.

### Task 4: Character read, edit, and template-completion API

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `apps/web/lib/api.ts`
- Test: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing route tests**

```python
def test_file_project_character_can_be_edited(client):
    response = client.put(
        "/file-projects/file:p-gou-webgame-restored/characters/苏叶",
        json={"personality_portrait": {"temperament": {"core_traits": ["谨慎但不退缩"]}}},
    )
    assert response.status_code == 200
    assert response.json()["personality_portrait"]["temperament"]["core_traits"] == ["谨慎但不退缩"]


def test_file_project_character_template_completion_is_local(client, monkeypatch):
    response = client.post("/file-projects/file:p-gou-webgame-restored/characters/苏叶/complete-portrait")
    assert response.status_code == 200
    assert response.json()["personality_portrait"]["growth"]["invariants"]
```

- [ ] **Step 2: Confirm route tests fail with 404**

Run: `pytest tests/api/test_story_routes.py -k "character_can_be_edited or template_completion" -q`

Expected: both endpoints return 404.

- [ ] **Step 3: Add API request model and routes**

Add `CharacterUpdateRequest` with optional editable card fields. Add:

```text
GET  /file-projects/{project_id}/characters
PUT  /file-projects/{project_id}/characters/{character_name}
POST /file-projects/{project_id}/characters/{character_name}/complete-portrait
```

Return 404 for unknown characters and 422 for invalid structures.

- [ ] **Step 4: Add typed web API functions**

Extend `StoryResponse.characters` with `personality_portrait` and `performance_profile`. Add `updateFileProjectCharacter` and `completeFileProjectCharacterPortrait`; both call file-project endpoints directly and throw visible errors instead of silently falling back to mock data.

- [ ] **Step 5: Run API tests**

Run: `pytest tests/api/test_story_routes.py -q`

Expected: all story-route tests pass.

### Task 5: Editable character-card page

**Files:**
- Modify: `apps/web/app/projects/[id]/characters/page.tsx`
- Modify: `apps/web/app/globals.css`
- Test: `apps/web` production build

- [ ] **Step 1: Add local edit state and section schema**

Represent the portrait as grouped textarea and line-list fields. Keep one character open at a time. `编辑` copies the canonical card into local draft state; `取消` discards it.

- [ ] **Step 2: Add commands**

Use icon buttons with tooltips for edit and cancel, a clear `保存角色卡` command, and a `补全基础侧写` command. Disable commands during requests and show an inline success or error message.

- [ ] **Step 3: Render all portrait sections**

Display identity, temperament, psychology, behavior, emotion, social modes, voice, growth, relationships, and writing limits. Arrays use newline-separated editors and are normalized back to trimmed unique arrays before saving.

- [ ] **Step 4: Refresh canonical state after mutation**

Call the workspace `refresh()` after save or completion. Never mutate chapter history or trigger generation from this page.

- [ ] **Step 5: Build the frontend**

Run: `npm.cmd run build` in `apps/web`

Expected: Next.js production build succeeds without TypeScript errors.

### Task 6: End-to-end verification

**Files:**
- Verify only; no planned production edits.

- [ ] **Step 1: Run focused backend tests**

Run: `pytest tests/story_core/test_character_portraits.py tests/story_core/test_webnovel_character_cards.py tests/story_core/test_file_project_store.py tests/api/test_story_routes.py -q`

Expected: all focused tests pass.

- [ ] **Step 2: Run full backend tests**

Run: `pytest -q`

Expected: no failures.

- [ ] **Step 3: Verify prompt size and selection**

Use `FileProjectStore.prompt_preview(1)` and confirm the writer prompt contains only planned character slices, preserves user-edited fields, and does not contain the full character library.

- [ ] **Step 4: Restart local services and verify routes**

Confirm `http://127.0.0.1:8000/health` and `http://localhost:3000/projects/file%3Ap-gou-webgame-restored/characters` return 200. Edit one non-destructive test field through the API, verify persistence, then restore its original value through the same endpoint.
