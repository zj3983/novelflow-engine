# New Novel Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在作品列表加入可靠的新建小说入口，支持空白建书和从一句灵感生成三套开书方向，并让两种方式都落为可继续写作的文件项目。

**Architecture:** 新建流程只使用文件项目。`file_project_creation.py` 负责确定性的目录初始化，`opening_directions.py` 负责独立的灵感候选模型和 LLM 调用，`FileProjectStore` 只负责读取、保存和选择候选。前端使用 `/projects/new` 和 `/projects/[id]/setup` 两个聚焦页面，不把开书逻辑塞进项目列表或总纲编辑器。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、Next.js 14、React、TypeScript、pytest、Playwright。

---

## File Map

- Create `packages/story_core/file_project_creation.py`: 校验创建参数，构造干净的最小项目，原子创建项目目录。
- Create `packages/story_core/opening_directions.py`: 候选方向数据模型、提示词、LLM 调用和结构校验。
- Modify `packages/story_core/file_project_store.py`: 读取开书资料、持久化候选、选择候选并更新总纲。
- Modify `apps/api/routes/file_projects.py`: 文件项目创建、候选生成、候选查询和选择 API。
- Modify `apps/web/lib/api.ts`: 新建流程类型和请求函数；这些请求禁止 mock 回退。
- Reuse `apps/web/lib/novelTypes.ts`: 创建表单直接读取现有题材选项，不修改或复制题材列表。
- Modify `apps/web/app/projects/page.tsx`: 始终显示“新建小说”。
- Create `apps/web/app/projects/new/page.tsx`: 双模式新建表单。
- Create `apps/web/app/projects/[id]/setup/page.tsx`: 生成、重试和选择三套方向。
- Modify `apps/web/app/globals.css`: 新建表单和方向列表的局部样式。
- Create `tests/story_core/test_file_project_creation.py`: 初始化器单元测试。
- Create `tests/story_core/test_opening_directions.py`: 候选模型和 LLM 解析单元测试。
- Create `tests/api/test_file_project_creation_routes.py`: 文件创建及开书 API 集成测试。
- Modify `apps/web/tests/story-workbench.spec.ts`: 新建入口和两个流程的定向浏览器测试。

### Task 1: Deterministic File Project Initializer

**Files:**
- Create: `packages/story_core/file_project_creation.py`
- Create: `tests/story_core/test_file_project_creation.py`

- [ ] **Step 1: Write failing tests for blank and inspiration projects**

```python
def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_create_blank_project_writes_clean_minimum(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(mode="blank", title="照夜行", novel_type_id="xuanhuan"),
        project_id_factory=lambda: "p-test-blank",
    )
    assert created.project_id == "p-test-blank"
    assert created.next_path == "/projects/file%3Ap-test-blank/outline"
    assert (created.root / ".story-system/MASTER_SETTING.json").exists()
    project = read_json(created.root / ".webnovel/project.json")
    state = read_json(created.root / ".webnovel/state.json")
    outline = read_json(created.root / ".webnovel/outline.json")
    assert project["world_blueprint"] == {"genre_plugin_ids": ["xuanhuan"]}
    assert project["pipeline_stage"] == "draft"
    assert state["current_chapter"] == 0
    assert state["characters"] == []
    assert outline == normalize_project_outline({})
    assert not (created.root / ".webnovel/opening_brief.json").exists()


def test_create_inspiration_project_keeps_idea_separate(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(mode="inspiration", novel_type_id="urban", idea="失业律师替陌生人追一笔旧账"),
        project_id_factory=lambda: "p-test-idea",
    )
    project = read_json(created.root / ".webnovel/project.json")
    brief = read_json(created.root / ".webnovel/opening_brief.json")
    assert project["title"] == "未命名作品"
    assert project["pipeline_stage"] == "idea_pending"
    assert brief == {
        "schema_version": "opening-brief/v1",
        "mode": "inspiration",
        "novel_type_id": "urban",
        "idea": "失业律师替陌生人追一笔旧账",
        "working_title": "",
    }
    assert "失业律师" not in json.dumps(project, ensure_ascii=False)
```

- [ ] **Step 2: Write failing validation and cleanup tests**

```python
@pytest.mark.parametrize(
    "payload,error",
    [
        ({"mode": "blank", "title": "", "novel_type_id": "urban"}, "title_required"),
        ({"mode": "inspiration", "idea": "", "novel_type_id": "urban"}, "idea_required"),
        ({"mode": "blank", "title": "书", "novel_type_id": "unknown"}, "invalid_novel_type"),
    ],
)
def test_create_spec_rejects_invalid_inputs(payload, error):
    with pytest.raises(ValueError, match=error):
        FileProjectCreateSpec.model_validate(payload)


def test_user_title_never_controls_directory(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(mode="blank", title="../../别处", novel_type_id="urban"),
        project_id_factory=lambda: "p-safe-id",
    )
    assert created.root == tmp_path / "p-safe-id"


def test_failed_initialization_removes_temporary_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(file_project_creation, "_write_project_files", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        create_file_project(
            tmp_path,
            FileProjectCreateSpec(mode="blank", title="失败测试", novel_type_id="urban"),
            project_id_factory=lambda: "p-failed",
        )
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 3: Run the focused tests and confirm they fail**

Run: `python -m pytest tests/story_core/test_file_project_creation.py -q`

Expected: FAIL because `file_project_creation` does not exist.

- [ ] **Step 4: Implement the creation models and atomic directory initialization**

```python
class FileProjectCreateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["blank", "inspiration"]
    title: str = Field(default="", max_length=120)
    novel_type_id: str
    idea: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_mode_fields(self):
        self.title = self.title.strip()
        self.idea = self.idea.strip()
        normalized = normalize_novel_type_id(self.novel_type_id)
        if not normalized:
            raise ValueError("invalid_novel_type")
        self.novel_type_id = normalized
        if self.mode == "blank" and not self.title:
            raise ValueError("title_required")
        if self.mode == "inspiration" and not self.idea:
            raise ValueError("idea_required")
        return self


@dataclass(frozen=True)
class CreatedFileProject:
    project_id: str
    root: Path
    next_path: str


def create_file_project(export_root, spec, *, project_id_factory=None):
    project_id = (project_id_factory or (lambda: f"p-{uuid4().hex}"))()
    if not re.fullmatch(r"p-[a-zA-Z0-9-]+", project_id):
        raise ValueError("invalid_generated_project_id")
    export_root.mkdir(parents=True, exist_ok=True)
    final_root = export_root / project_id
    if final_root.exists():
        raise FileExistsError("project_id_conflict")
    temp_root = Path(tempfile.mkdtemp(prefix=f".{project_id}.tmp-", dir=export_root))
    try:
        _write_project_files(temp_root, project_id, spec)
        _validate_created_project(temp_root)
        os.replace(temp_root, final_root)
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise
    route_id = quote(f"file:{project_id}", safe="")
    next_page = "setup" if spec.mode == "inspiration" else "outline"
    return CreatedFileProject(project_id, final_root, f"/projects/{route_id}/{next_page}")
```

Build `state.json` from `StoryState(story_id=f"file:{project_id}", outline="", genre=NOVEL_TYPE_CATALOG[id].label, style="通俗网文")` so all runtime collections use model defaults. Write the master, project, state and normalized empty outline with UTF-8 JSON; create `chapters`, `commits`, `reviews`, `.story-system/chapters`, and `.story-system/reviews` before validation.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/story_core/test_file_project_creation.py -q`

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add packages/story_core/file_project_creation.py tests/story_core/test_file_project_creation.py
git commit -m "feat: initialize clean file novel projects"
```

### Task 2: File Project Creation API

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Create: `tests/api/test_file_project_creation_routes.py`

- [ ] **Step 1: Write failing route tests**

```python
def test_post_file_projects_creates_blank_project(client, tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    response = client.post("/file-projects", json={
        "mode": "blank", "title": "照夜行", "novel_type_id": "xuanhuan"
    })
    assert response.status_code == 201
    payload = response.json()
    assert payload["project_id"].startswith("file:p-")
    assert payload["storage_source"] == "file"
    assert payload["next_path"].endswith("/outline")
    assert client.get(f'/file-projects/{payload["project_id"]}').status_code == 200


def test_post_file_projects_returns_422_without_leaving_project(client, tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    response = client.post("/file-projects", json={
        "mode": "inspiration", "novel_type_id": "urban", "idea": ""
    })
    assert response.status_code == 422
    assert list(tmp_path.glob("*")) == []
```

- [ ] **Step 2: Run the route tests and confirm 405/404 failure**

Run: `python -m pytest tests/api/test_file_project_creation_routes.py -q`

Expected: FAIL because `POST /file-projects` is missing.

- [ ] **Step 3: Add the request model and route**

```python
class FileProjectCreateRequest(BaseModel):
    mode: Literal["blank", "inspiration"]
    title: str = ""
    novel_type_id: str
    idea: str = ""


@router.post("/file-projects", status_code=201)
def create_new_file_project(payload: FileProjectCreateRequest) -> dict[str, Any]:
    try:
        created = create_file_project(
            _export_root(),
            FileProjectCreateSpec.model_validate(payload.model_dump()),
        )
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store = FileProjectStore(created.root)
    return {**_project_payload(store), "next_path": created.next_path}
```

Do not call the SQLite `store.create_project` path. Let unexpected disk errors return 500 so the frontend cannot mistake them for successful creation.

- [ ] **Step 4: Run route and existing file-project tests**

Run: `python -m pytest tests/api/test_file_project_creation_routes.py tests/api/test_book_dissection_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/routes/file_projects.py tests/api/test_file_project_creation_routes.py
git commit -m "feat: expose file novel creation api"
```

### Task 3: Opening Direction Domain, Generation, and Selection

**Files:**
- Create: `packages/story_core/opening_directions.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/file_projects.py`
- Create: `tests/story_core/test_opening_directions.py`
- Modify: `tests/api/test_file_project_creation_routes.py`

- [ ] **Step 1: Write failing domain tests**

```python
def direction(direction_id):
    return {
        "id": direction_id,
        "title": f"书名{direction_id}",
        "hook": f"看点{direction_id}",
        "protagonist_goal": f"目标{direction_id}",
        "main_conflict": f"冲突{direction_id}",
        "growth_path": f"成长{direction_id}",
        "opening_promise": f"开篇承诺{direction_id}",
    }


def test_direction_set_requires_exactly_three_unique_candidates():
    with pytest.raises(ValidationError):
        OpeningDirectionSet.model_validate({"directions": [direction("a"), direction("b")]})
    with pytest.raises(ValidationError):
        OpeningDirectionSet.model_validate({"directions": [direction("a"), direction("a"), direction("c")]})


def test_generator_prompt_contains_only_brief_and_genre(monkeypatch):
    captured = {}
    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": json.dumps({
                "directions": [direction("direction-1"), direction("direction-2"), direction("direction-3")]
            }, ensure_ascii=False)}}]
        }

    generator = LLMOpeningDirectionGenerator(
        post_json=fake_post,
        runtime_resolver=lambda _: OpenAIRuntimeSettings(provider="codexcli", codex_command="codex"),
        strategy_resolver=lambda: AgentSettings(director_model="test-model"),
    )
    result = generator.generate(OpeningBrief(mode="inspiration", novel_type_id="urban", idea="替陌生人追旧账"))
    assert len(result.directions) == 3
    prompt = captured["payload"]["messages"][1]["content"]
    assert "替陌生人追旧账" in prompt
    assert "角色卡" not in prompt
    assert "历史章节" not in prompt
```

- [ ] **Step 2: Write failing store and API tests**

```python
def test_generate_and_select_direction_updates_only_title_and_overall(client, idea_project, monkeypatch):
    monkeypatch.setattr(file_project_routes, "opening_direction_generator", FakeDirectionGenerator())
    generated = client.post(f"/file-projects/{idea_project}/opening-directions")
    assert generated.status_code == 200
    assert len(generated.json()["directions"]) == 3

    selected = client.post(f"/file-projects/{idea_project}/opening-directions/direction-2/select")
    assert selected.status_code == 200
    root = idea_project_root(idea_project)
    project = read_json(root / ".webnovel/project.json")
    outline = read_json(root / ".webnovel/outline.json")
    assert project["title"] == "第二个书名"
    assert project["pipeline_stage"] == "outlining"
    assert outline["overall"]["main_conflict"] == "第二个冲突"
    assert outline["arcs"] == []
    assert outline["chapters"] == []
    assert project["character_profiles"] == []
    assert project["world_summary"] == ""


def test_invalid_model_output_preserves_previous_direction_file(client, idea_project, monkeypatch):
    before = direction_path(idea_project).read_bytes() if direction_path(idea_project).exists() else None
    monkeypatch.setattr(file_project_routes, "opening_direction_generator", InvalidDirectionGenerator())
    response = client.post(f"/file-projects/{idea_project}/opening-directions")
    assert response.status_code == 502
    after = direction_path(idea_project).read_bytes() if direction_path(idea_project).exists() else None
    assert after == before
```

- [ ] **Step 3: Run tests and confirm missing module/method failures**

Run: `python -m pytest tests/story_core/test_opening_directions.py tests/api/test_file_project_creation_routes.py -q`

Expected: FAIL because direction models and routes are missing.

- [ ] **Step 4: Implement strict direction models and isolated LLM generator**

```python
class OpeningBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["opening-brief/v1"] = "opening-brief/v1"
    mode: Literal["inspiration"] = "inspiration"
    novel_type_id: str
    idea: str = Field(min_length=1, max_length=1000)
    working_title: str = Field(default="", max_length=120)


class OpeningDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str = Field(min_length=1, max_length=120)
    hook: str = Field(min_length=1, max_length=500)
    protagonist_goal: str = Field(min_length=1, max_length=500)
    main_conflict: str = Field(min_length=1, max_length=500)
    growth_path: str = Field(min_length=1, max_length=500)
    opening_promise: str = Field(min_length=1, max_length=500)


class OpeningDirectionSet(BaseModel):
    schema_version: Literal["opening-directions/v1"] = "opening-directions/v1"
    directions: list[OpeningDirection] = Field(min_length=3, max_length=3)
    selected_id: str = ""

    @model_validator(mode="after")
    def unique_ids(self):
        if len({item.id for item in self.directions}) != 3:
            raise ValueError("duplicate_direction_id")
        return self
```

`LLMOpeningDirectionGenerator.generate()` must use `resolve_openai_runtime_settings("director")`, `get_runtime_strategy_settings().director_model`, `post_json_with_retry`, JSON response format, and a prompt containing only the type label, type description, working title and idea. It must raise `ValueError("opening_direction_generation_failed")` for unavailable runtime, malformed JSON or schema failure; there is no deterministic fake candidate fallback.

- [ ] **Step 5: Add store methods with rollback on selection failure**

```python
def opening_brief(self) -> dict[str, Any]:
    return OpeningBrief.model_validate(self._read_json(self.webnovel_dir / "opening_brief.json", {})).model_dump()


def opening_directions(self) -> dict[str, Any] | None:
    path = self.webnovel_dir / "opening_directions.json"
    return OpeningDirectionSet.model_validate(self._read_json(path, {})).model_dump() if path.exists() else None


def generate_opening_directions(self, generator) -> dict[str, Any]:
    result = generator.generate(OpeningBrief.model_validate(self.opening_brief()))
    payload = OpeningDirectionSet.model_validate(result).model_dump()
    project = {**self.project(), "pipeline_stage": "direction_ready"}
    self._replace_json_transaction({
        self.webnovel_dir / "project.json": project,
        self.webnovel_dir / "opening_directions.json": payload,
    })
    return self.opening_setup()


def select_opening_direction(self, direction_id: str) -> dict[str, Any]:
    directions = OpeningDirectionSet.model_validate(self.opening_directions())
    if directions.selected_id:
        raise ValueError("direction_already_selected")
    selected = next((item for item in directions.directions if item.id == direction_id), None)
    if selected is None:
        raise KeyError("direction_not_found")
    # Snapshot all three target files, prepare all normalized payloads, write them,
    # and restore every snapshot if any write raises.
    return self._commit_opening_direction_selection(directions, selected)
```

Map the selection to outline fields as: `story=hook`, `protagonist_goal`, `main_conflict`, `growth_path`, `ending_direction=opening_promise`. Preserve empty `arcs` and `chapters`. `_replace_json_transaction()` must snapshot every target path as raw bytes or “missing”, prepare every temporary JSON file first, replace each target, and restore every snapshot if any replace raises. Use it both when saving generated candidates plus `direction_ready` and when selecting a candidate across `project.json`, `outline.json`, and `opening_directions.json`.

- [ ] **Step 6: Add GET/POST direction routes**

```python
opening_direction_generator = LLMOpeningDirectionGenerator()

@router.get("/file-projects/{project_id}/opening-directions")
def get_opening_directions(project_id: str):
    return _store_for(project_id).opening_setup()

@router.post("/file-projects/{project_id}/opening-directions")
def generate_opening_directions(project_id: str):
    try:
        return _store_for(project_id).generate_opening_directions(opening_direction_generator)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@router.post("/file-projects/{project_id}/opening-directions/{direction_id}/select")
def select_opening_direction(project_id: str, direction_id: str):
    try:
        return _store_for(project_id).select_opening_direction(direction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

`opening_setup()` returns the brief, optional candidates, pipeline stage, and `next_path`; it never generates on GET.

- [ ] **Step 7: Run focused and file-store tests**

Run: `python -m pytest tests/story_core/test_opening_directions.py tests/story_core/test_file_project_store.py tests/api/test_file_project_creation_routes.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add packages/story_core/opening_directions.py packages/story_core/file_project_store.py apps/api/routes/file_projects.py tests/story_core/test_opening_directions.py tests/api/test_file_project_creation_routes.py
git commit -m "feat: generate and select opening directions"
```

### Task 4: New Novel Form and Persistent Entry Point

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/page.tsx`
- Create: `apps/web/app/projects/new/page.tsx`
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write a failing Playwright test for both form modes**

```typescript
test("projects page creates blank and inspiration file novels", async ({ page }) => {
  const requests: unknown[] = [];
  await page.route("**/file-projects", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      requests.push(body);
      const id = body.mode === "blank" ? "file:p-blank" : "file:p-idea";
      const next = body.mode === "blank" ? "outline" : "setup";
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
        project_id: id, title: body.title || "未命名作品", storage_source: "file",
        status: "draft", current_chapter: 0, next_path: `/projects/${encodeURIComponent(id)}/${next}`,
      }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto("/projects");
  await page.getByRole("link", { name: "新建小说" }).click();
  await page.getByRole("tab", { name: "建立空白小说" }).click();
  await page.getByLabel("小说名").fill("照夜行");
  await page.getByLabel("小说类型").selectOption("xuanhuan");
  await page.getByRole("button", { name: "创建小说" }).click();
  await expect(page).toHaveURL(/file%3Ap-blank\/outline$/);
  expect(requests[0]).toEqual({ mode: "blank", title: "照夜行", novel_type_id: "xuanhuan", idea: "" });
});
```

Add a second test for inspiration mode that asserts title is optional, idea is required, and redirect ends in `/setup`.

- [ ] **Step 2: Run the Playwright test and confirm the entry is missing**

Run: `cd apps/web; npx playwright test tests/story-workbench.spec.ts -g "projects page creates"`

Expected: FAIL because the new link/page does not exist.

- [ ] **Step 3: Add strict frontend API functions without mock fallback**

```typescript
export type NewFileProjectRequest = {
  mode: "blank" | "inspiration";
  title: string;
  novel_type_id: string;
  idea: string;
};

export type NewFileProjectResponse = ProjectResponse & { next_path: string };

export async function createFileProject(payload: NewFileProjectRequest): Promise<NewFileProjectResponse> {
  return (await tryFetchJson(`${apiBase()}/file-projects`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  })) as NewFileProjectResponse;
}
```

Do not catch and call `mockCreateProject` in this function.

Extend `ProjectPipelineStage` with `"draft" | "idea_pending" | "direction_ready" | "outlining"` so the new file states remain typed instead of being cast to legacy stages.

- [ ] **Step 4: Add the list-page entry and focused new-project form**

`projects/page.tsx` always passes this action to `PageHeader`:

```tsx
<Link href="/projects/new" className="ws-btn ws-btn--primary">新建小说</Link>
```

If a last project exists, render both actions without hiding “新建小说”. The empty state repeats a normal link to `/projects/new`.

`projects/new/page.tsx` owns only:

```tsx
const [mode, setMode] = useState<"inspiration" | "blank">("inspiration");
const [title, setTitle] = useState("");
const [novelTypeId, setNovelTypeId] = useState(DEFAULT_NOVEL_TYPE_ID);
const [idea, setIdea] = useState("");
const [submitting, setSubmitting] = useState(false);
const [error, setError] = useState("");
```

Use a `role="tablist"` segmented control. Show title as required only for blank mode and idea only for inspiration mode. On success call `router.push(response.next_path)`. On error keep the entered values and show `创建失败：<message>`.

- [ ] **Step 5: Run Playwright and production build**

Run: `cd apps/web; npx playwright test tests/story-workbench.spec.ts -g "projects page creates"`

Expected: PASS.

Run: `cd apps/web; npm run build`

Expected: Next.js build and type checking PASS.

- [ ] **Step 6: Commit**

```powershell
git add apps/web/lib/api.ts apps/web/app/projects/page.tsx apps/web/app/projects/new/page.tsx apps/web/app/globals.css apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add new novel creation entry"
```

### Task 5: Opening Setup Page

**Files:**
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/app/projects/[id]/setup/page.tsx`
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing Playwright tests for generate, retry, and select**

```typescript
test("opening setup generates and selects one direction", async ({ page }) => {
  let selected = "";
  await page.route("**/file-projects/file%3Ap-idea/opening-directions**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === "POST" && url.pathname.endsWith("/select")) {
      selected = url.pathname.split("/").at(-2) || "";
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        selected_id: selected,
        next_path: "/projects/file%3Ap-idea/outline",
      }) });
      return;
    }
    if (route.request().method() === "POST") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(directionSetup()) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(emptySetup()) });
  });
  await page.goto("/projects/file%3Ap-idea/setup");
  await page.getByRole("button", { name: "生成故事方向" }).click();
  await expect(page.getByRole("radio")).toHaveCount(3);
  await page.getByRole("radio", { name: /第二个书名/ }).check();
  await page.getByRole("button", { name: "采用这个方向" }).click();
  expect(selected).toBe("direction-2");
  await expect(page).toHaveURL(/\/outline$/);
});
```

Add a failure test where generation returns 502; assert the idea remains visible and both “重新生成” and “手动填写总纲” are available.

- [ ] **Step 2: Run tests and confirm the setup page is missing**

Run: `cd apps/web; npx playwright test tests/story-workbench.spec.ts -g "opening setup"`

Expected: FAIL with route/page not found.

- [ ] **Step 3: Add setup API types and calls**

```typescript
export type OpeningDirection = {
  id: string;
  title: string;
  hook: string;
  protagonist_goal: string;
  main_conflict: string;
  growth_path: string;
  opening_promise: string;
};

export type OpeningSetup = {
  brief: { idea: string; novel_type_id: string; working_title: string };
  directions: OpeningDirection[];
  selected_id: string;
  pipeline_stage: string;
  next_path: string;
};

export async function fetchOpeningSetup(projectId: string): Promise<OpeningSetup> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/opening-directions`, {
    method: "GET",
  })) as OpeningSetup;
}

export async function generateOpeningDirections(projectId: string): Promise<OpeningSetup> {
  return (await tryFetchJson(`${fileProjectPath(projectId)}/opening-directions`, {
    method: "POST",
  })) as OpeningSetup;
}

export async function selectOpeningDirection(projectId: string, directionId: string): Promise<OpeningSetup> {
  return (await tryFetchJson(
    `${fileProjectPath(projectId)}/opening-directions/${encodeURIComponent(directionId)}/select`,
    { method: "POST" },
  )) as OpeningSetup;
}
```

Use `fileProjectPath(projectId)` for all three functions and let API errors reach the page.

- [ ] **Step 4: Implement the setup page as a recoverable state machine**

The page loads setup on mount and renders exactly one of:

- loading
- no candidates: original idea plus “生成故事方向”
- candidates: three radio choices plus “重新生成” and “采用这个方向”
- generation error: inline error, “重新生成”, and a link to `/outline`
- selected: immediately `router.replace(next_path)`

Candidate text is plain sections, not nested cards. Each choice shows all six fields with compact labels. Disable generate/select while a request is running. Do not write explanatory feature copy or show raw prompts.

- [ ] **Step 5: Run setup tests and build**

Run: `cd apps/web; npx playwright test tests/story-workbench.spec.ts -g "opening setup"`

Expected: PASS.

Run: `cd apps/web; npm run build`

Expected: PASS and `/projects/[id]/setup` appears in the route table.

- [ ] **Step 6: Commit**

```powershell
git add apps/web/lib/api.ts apps/web/app/projects/[id]/setup/page.tsx apps/web/app/globals.css apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add opening direction setup"
```

### Task 6: End-to-End Verification and Service Restart

**Files:**
- Modify only if verification exposes a defect.

- [ ] **Step 1: Run backend full suite**

Run: `python -m pytest -q`

Expected: all tests PASS with no new warnings caused by creation code.

- [ ] **Step 2: Run frontend production build**

Run: `cd apps/web; npm run build`

Expected: PASS.

- [ ] **Step 3: Run focused browser tests together**

Run: `cd apps/web; npx playwright test tests/story-workbench.spec.ts -g "projects page creates|opening setup"`

Expected: all new creation tests PASS.

- [ ] **Step 4: Test a disposable real project against live services**

Use a temporary `NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR`, start API and web on unused ports, then:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:<api-port>/file-projects -ContentType application/json -Body '{"mode":"blank","title":"验证项目","novel_type_id":"xuanhuan","idea":""}'
```

Verify the response project is returned by GET `/file-projects`, its outline endpoint returns `project-outline/v1`, and its writing packet can be requested for chapter 1. Delete only the disposable temporary directory after checking its resolved absolute path.

- [ ] **Step 5: Restart standard local services**

Stop only listeners owned by ports 8000 and 3000, then start:

```powershell
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd apps/web
npm.cmd run dev
```

Verify `http://127.0.0.1:8000/health` and `http://127.0.0.1:3000/projects` both return 200.

- [ ] **Step 6: Confirm clean worktree and report URLs**

Run: `git status --short`

Expected: empty output.

Report:

- `http://127.0.0.1:3000/projects`
- `http://127.0.0.1:3000/projects/new`
