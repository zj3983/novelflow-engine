# Story Core Opening Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the selected opening direction into a persistent, editable story core that guides outlines, characters, world building, and chapter writing without injecting the tutorial or the full card into every prompt.

**Architecture:** Add a focused `story_core_card.py` domain module for schema validation, legacy fallback, outline seeding, and per-stage projections. Keep `OpeningDirection` backward compatible while requiring newly generated candidates to contain the complete core fields. `FileProjectStore` owns atomic persistence; API routes expose the card; the outline page edits it separately from the outline.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, pytest, Next.js/React/TypeScript, Playwright.

---

## File Map

- Create `packages/story_core/story_core_card.py`: story-core schema, legacy fallback, direction conversion, outline seed, stage projections.
- Modify `packages/story_core/opening_directions.py`: complete candidate fields and generation contract while accepting old saved candidates.
- Modify `packages/story_core/file_project_store.py`: read/update/persist core card and include projected context at model-call boundaries.
- Modify `packages/story_core/world_enrichment.py`: consume only the world projection when world context is assembled.
- Modify `packages/story_core/outline_planning_generation.py`: include the full card only in whole-book outline generation.
- Modify `packages/story_core/orchestrator.py`: include only the compact writer projection in chapter writing context.
- Modify `apps/api/routes/file_projects.py`: GET/PUT story-core endpoints and world-enrichment projection wiring.
- Modify `apps/web/lib/api.ts`: story-core and expanded opening-direction contracts plus fetch/update helpers.
- Modify `apps/web/app/projects/[id]/setup/page.tsx`: display all core candidate fields.
- Modify `apps/web/app/projects/[id]/outline/page.tsx`: independent story-core editor and save state.
- Modify `apps/web/app/globals.css`: responsive story-core form and candidate layout.
- Create `tests/story_core/test_story_core_card.py`: domain and projection tests.
- Modify `tests/story_core/test_opening_directions.py`: generation and persistence behavior.
- Modify `tests/api/test_file_project_creation_routes.py`: API and atomic selection behavior.
- Modify `apps/web/tests/story-workbench.spec.ts`: setup and outline UI behavior.

### Task 1: Story Core Domain Model

**Files:**
- Create: `packages/story_core/story_core_card.py`
- Create: `tests/story_core/test_story_core_card.py`

- [ ] **Step 1: Write failing schema and projection tests**

```python
from packages.story_core.story_core_card import (
    StoryCoreCard,
    story_core_from_direction,
    story_core_projection,
)


def complete_payload() -> dict[str, str]:
    return {
        "schema_version": "story-core/v1",
        "title": "明日来信",
        "logline": "一个害怕承担责任的快递员收到明天的失踪报告后，必须在当天找到失踪者，否则妹妹会成为下一名失踪者。",
        "protagonist_profile": "二十四岁的夜班快递员，观察细但遇事习惯躲开。",
        "inciting_incident": "他收到一份日期为明天、收件人却是自己的失踪报告。",
        "protagonist_goal": "在午夜前找到报告中的失踪者并查明寄件人。",
        "main_conflict": "寄件人不断修改当天事件，警方也把他列为嫌疑人。",
        "failure_stakes": "失踪者会死亡，他的妹妹会成为下一名目标。",
        "growth_path": "从只求自保变成愿意承担选择后果的人。",
        "excitement_point": "用一张张未来单据追查正在发生的案件。",
        "target_audience": "喜欢都市悬疑、连续反转和人物成长的网文读者。",
        "reader_promise": "每个阶段解决一份未来单据，同时逼近寄件人的真实目的。",
        "ending_direction": "主角主动寄出第一份改变过去的单据，承担新规则的代价。",
        "source_direction_id": "direction-1",
    }


def test_writer_projection_contains_only_direction_anchor() -> None:
    card = StoryCoreCard.model_validate(complete_payload())
    assert story_core_projection(card, "writing") == {
        "logline": card.logline,
        "reader_promise": card.reader_promise,
    }


def test_world_projection_does_not_include_audience_or_ending() -> None:
    card = StoryCoreCard.model_validate(complete_payload())
    projection = story_core_projection(card, "world")
    assert set(projection) == {"inciting_incident", "main_conflict", "excitement_point"}
```

- [ ] **Step 2: Run the focused tests and verify the module is missing**

Run: `pytest tests/story_core/test_story_core_card.py -q`

Expected: FAIL with `ModuleNotFoundError: packages.story_core.story_core_card`.

- [ ] **Step 3: Implement the strict card, tolerant legacy fallback, and stage projections**

```python
class StoryCoreCard(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["story-core/v1"] = "story-core/v1"
    title: str = Field(default="", max_length=120)
    logline: str = Field(default="", max_length=1000)
    protagonist_profile: str = Field(default="", max_length=1000)
    inciting_incident: str = Field(default="", max_length=1000)
    protagonist_goal: str = Field(default="", max_length=1000)
    main_conflict: str = Field(default="", max_length=1000)
    failure_stakes: str = Field(default="", max_length=1000)
    growth_path: str = Field(default="", max_length=1000)
    excitement_point: str = Field(default="", max_length=1000)
    target_audience: str = Field(default="", max_length=1000)
    reader_promise: str = Field(default="", max_length=1000)
    ending_direction: str = Field(default="", max_length=1000)
    source_direction_id: str = Field(default="", max_length=120)


_STAGE_FIELDS = {
    "character": ("protagonist_profile", "protagonist_goal", "failure_stakes", "growth_path", "main_conflict"),
    "world": ("inciting_incident", "main_conflict", "excitement_point"),
    "outline": tuple(name for name in StoryCoreCard.model_fields if name != "schema_version"),
    "planning": ("logline", "reader_promise"),
    "writing": ("logline", "reader_promise"),
}


def story_core_projection(card: StoryCoreCard, stage: str) -> dict[str, str]:
    fields = _STAGE_FIELDS[stage]
    return {name: str(getattr(card, name)).strip() for name in fields if str(getattr(card, name)).strip()}
```

Also implement `story_core_from_direction()`, `story_core_from_legacy()`, and `outline_seed_from_story_core()` as pure functions. Legacy fallback leaves unknown fields empty and never calls a model.

- [ ] **Step 4: Run the domain tests**

Run: `pytest tests/story_core/test_story_core_card.py -q`

Expected: PASS.

### Task 2: Complete Opening Candidates And Atomic Selection

**Files:**
- Modify: `packages/story_core/opening_directions.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `tests/story_core/test_opening_directions.py`

- [ ] **Step 1: Add failing tests for complete candidates and selection persistence**

```python
def test_new_direction_generation_requires_complete_story_core_fields():
    payload = direction_set()
    payload["directions"][0].pop("failure_stakes")
    with pytest.raises(ValidationError):
        GeneratedOpeningDirectionSet.model_validate(payload)


def test_selecting_direction_atomically_writes_story_core(tmp_path):
    store = make_opening_store(tmp_path)
    store.generate_opening_directions(StaticDirectionGenerator(complete_direction_set()))
    store.select_opening_direction("direction-2")
    core = json.loads((store.webnovel_dir / "story_core.json").read_text(encoding="utf-8"))
    assert core["schema_version"] == "story-core/v1"
    assert core["source_direction_id"] == "direction-2"
```

- [ ] **Step 2: Run focused opening tests**

Run: `pytest tests/story_core/test_opening_directions.py -q`

Expected: FAIL because the generated schema and `story_core.json` do not exist.

- [ ] **Step 3: Extend candidates without breaking old files**

Keep `OpeningDirection` fields optional/defaulted for reading `opening-directions/v1`. Add `GeneratedOpeningDirection` with all core text fields required and non-empty, and validate model output through `GeneratedOpeningDirectionSet`. Update the system prompt so every item returns:

```text
id, title, logline, protagonist_profile, inciting_incident,
protagonist_goal, main_conflict, failure_stakes, growth_path,
excitement_point, target_audience, reader_promise,
ending_direction, primary_trope_id
```

Do not include tutorial prose in the prompt. Express the logline requirement as a field contract: protagonist trait/defect, incident, goal, and concrete failure consequence.

- [ ] **Step 4: Persist the selected core in the existing transaction**

In `select_opening_direction()`, convert the selected candidate with `story_core_from_direction()`, seed the outline with `outline_seed_from_story_core()`, and add this entry to `_replace_json_transaction()`:

```python
self.webnovel_dir / "story_core.json": core.model_dump(mode="json")
```

This keeps project, outline, selected direction, and core card all-or-nothing.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/story_core/test_opening_directions.py tests/story_core/test_story_core_card.py -q`

Expected: PASS.

### Task 3: Store API And Legacy Compatibility

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/file_projects.py`
- Modify: `tests/api/test_file_project_creation_routes.py`
- Modify: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing GET/PUT and legacy tests**

```python
def test_story_core_route_reads_and_updates_card(creation_api, monkeypatch):
    client, _, _ = creation_api
    project, _ = _create_selected_inspiration_project(client, monkeypatch)
    path = f"/file-projects/{project['project_id']}/story-core"
    current = client.get(path).json()
    current["reader_promise"] = "每卷解决一个现实难题，同时揭开能力来源。"
    response = client.put(path, json=current)
    assert response.status_code == 200
    assert response.json()["reader_promise"] == current["reader_promise"]


def test_legacy_project_without_story_core_remains_readable(tmp_path):
    store = make_legacy_store(tmp_path)
    assert store.story_core()["schema_version"] == "story-core/v1"
    assert not (store.webnovel_dir / "story_core.json").exists()
```

- [ ] **Step 2: Run focused route and store tests**

Run: `pytest tests/api/test_file_project_creation_routes.py tests/story_core/test_file_project_store.py -q`

Expected: FAIL with missing route/method.

- [ ] **Step 3: Add store methods**

Implement:

```python
def story_core(self) -> dict[str, Any]:
    path = self.webnovel_dir / "story_core.json"
    if path.exists():
        return StoryCoreCard.model_validate(self._read_json(path, {})).model_dump(mode="json")
    return story_core_from_legacy(
        selected_direction=self._selected_opening_direction(),
        outline=self.project_outline(),
        title=str(self.project().get("title") or ""),
    ).model_dump(mode="json")

@_with_project_update_lock
def update_story_core(self, payload: dict[str, Any]) -> dict[str, Any]:
    card = StoryCoreCard.model_validate(payload)
    self._write_json_atomic(self.webnovel_dir / "story_core.json", card.model_dump(mode="json"))
    return card.model_dump(mode="json")
```

The fallback read must not write a file. The first successful PUT creates the formal card.

- [ ] **Step 4: Add FastAPI routes**

```python
@router.get("/file-projects/{project_id}/story-core")
def get_file_project_story_core(project_id: str) -> dict[str, Any]:
    return _store_for(project_id).story_core()


@router.put("/file-projects/{project_id}/story-core")
def update_file_project_story_core(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _store_for(project_id).update_story_core(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/api/test_file_project_creation_routes.py tests/story_core/test_file_project_store.py -q`

Expected: PASS.

### Task 4: Stage-Specific Context Wiring

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/world_enrichment.py`
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `tests/story_core/test_outline_planning_generation.py`
- Modify: `tests/story_core/test_writing_packet.py`
- Modify: `tests/api/test_project_world_enrichment.py`

- [ ] **Step 1: Write failing boundary tests**

```python
def test_writer_packet_receives_only_compact_story_core(store):
    packet = store.build_writing_packet(1)
    assert set(packet["story_core"]) == {"logline", "reader_promise"}
    assert "target_audience" not in json.dumps(packet, ensure_ascii=False)


def test_outline_generator_receives_complete_story_core(captured_context):
    assert captured_context["story_core"]["failure_stakes"]
    assert captured_context["story_core"]["ending_direction"]


def test_world_enrichment_receives_world_projection_only(captured_context):
    assert set(captured_context["story_core"]) == {
        "inciting_incident", "main_conflict", "excitement_point"
    }
```

- [ ] **Step 2: Run focused context tests**

Run: `pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_writing_packet.py tests/api/test_project_world_enrichment.py -q`

Expected: FAIL because no story-core context is wired.

- [ ] **Step 3: Add one store projection entry point**

```python
def story_core_context(self, stage: str) -> dict[str, str]:
    return story_core_projection(StoryCoreCard.model_validate(self.story_core()), stage)
```

Use this method at the boundaries only:

- outline generation: `stage="outline"`
- opening character roster: `stage="character"`
- world enrichment: `stage="world"`
- chapter planning: `stage="planning"`
- final writer packet: `stage="writing"`

Do not add the tutorial or full card to project snapshots, generic state, or every prompt.

- [ ] **Step 4: Run focused context tests**

Run: `pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_writing_packet.py tests/api/test_project_world_enrichment.py -q`

Expected: PASS.

### Task 5: Frontend Contracts And Story Core Editor

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/setup/page.tsx`
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Add failing Playwright coverage**

```typescript
test("opening setup shows complete core choices and outline edits the selected core", async ({ page }) => {
  await page.goto("/projects/file%3Ap-opening/setup");
  await expect(page.getByRole("heading", { name: "选择故事核心" })).toBeVisible();
  await expect(page.getByText("失败后果")).toBeVisible();
  await page.getByLabel("选择方向一").check();
  await page.getByRole("button", { name: "采用这个方向" }).click();
  await page.goto("/projects/file%3Ap-opening/outline");
  await expect(page.getByRole("heading", { name: "故事核心" })).toBeVisible();
  await page.getByLabel("读者持续能得到什么").fill("每卷都兑现一次明确回报。")
  await page.getByRole("button", { name: "保存故事核心" }).click();
  await expect(page.getByText("故事核心已保存")).toBeVisible();
});
```

- [ ] **Step 2: Run the focused Playwright test**

Run: `npm --prefix apps/web run test:e2e -- story-workbench.spec.ts`

Expected: FAIL because the fields and API helpers do not exist.

- [ ] **Step 3: Add TypeScript types and API helpers**

```typescript
export type StoryCoreCard = {
  schema_version: "story-core/v1";
  title: string;
  logline: string;
  protagonist_profile: string;
  inciting_incident: string;
  protagonist_goal: string;
  main_conflict: string;
  failure_stakes: string;
  growth_path: string;
  excitement_point: string;
  target_audience: string;
  reader_promise: string;
  ending_direction: string;
  source_direction_id: string;
};

export async function fetchStoryCore(projectId: string): Promise<StoryCoreCard> {
  return await tryFetchJson(`${fileProjectPath(projectId)}/story-core`, { method: "GET" }) as StoryCoreCard;
}

export async function updateStoryCore(projectId: string, payload: StoryCoreCard): Promise<StoryCoreCard> {
  return await tryFetchJson(`${fileProjectPath(projectId)}/story-core`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  }) as StoryCoreCard;
}
```

Make `OpeningDirection` extend the core candidate fields except `schema_version` and `source_direction_id`.

- [ ] **Step 4: Update setup and outline pages**

The setup page renders the nine readable groups from the design with normal paragraphs, not nested cards. The outline page loads outline and story core in parallel, keeps separate draft/save/error state, and places the core editor before the outline tabs. Saving the core never saves or rewrites the outline.

- [ ] **Step 5: Add responsive CSS and run frontend verification**

Run:

```powershell
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- story-workbench.spec.ts
```

Expected: all commands PASS and the form has no horizontal overflow at mobile width.

### Task 6: Regression And Acceptance Verification

**Files:**
- Modify only files required by failures caused by this feature.

- [ ] **Step 1: Run backend focused suite**

Run:

```powershell
pytest tests/story_core/test_story_core_card.py tests/story_core/test_opening_directions.py tests/story_core/test_file_project_store.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_writing_packet.py tests/api/test_file_project_creation_routes.py tests/api/test_project_world_enrichment.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full backend suite**

Run: `pytest -q`

Expected: PASS with only the repository's documented skips.

- [ ] **Step 3: Run frontend build and relevant browser tests**

Run:

```powershell
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- story-workbench.spec.ts
```

Expected: PASS.

- [ ] **Step 4: Verify prompt boundaries by source search**

Run:

```powershell
rg -n "story_core|story-core" packages/story_core apps/api apps/web
rg -n "写长篇最怕|一句话简介|初稿就是|不要回头修改" packages/story_core apps/api apps/web
```

Expected: story-core references occur only at declared boundaries; tutorial prose has no production-code matches.

- [ ] **Step 5: Start services and verify the real flow**

Start the API on `127.0.0.1:8000` and the web app on `127.0.0.1:3000`. Create one inspiration project, generate three candidates, select one, open the outline page, edit the story core, save it, reload, and confirm the value persists.
