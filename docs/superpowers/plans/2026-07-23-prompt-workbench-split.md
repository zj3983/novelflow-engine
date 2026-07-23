# Prompt Workbench Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the project prompt screen into editable source templates, read-only chapter context modules, and immutable records of every real model call.

**Architecture:** Add focused template and call-record modules in `story_core`. The orchestrator renders registered templates and reports every provider call through a context-local recorder installed by `FileProjectStore`; APIs expose each data layer separately, and the existing prompt preview remains explicitly reconstructed. The Next.js screen keeps one route with three URL-addressable views.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, JSON/JSONL file storage, React 18, Next.js 14, TypeScript, pytest, Playwright.

---

## File Map

- Create `packages/story_core/prompt_templates.py`: template definitions, variable validation, global persistence and rendering.
- Create `packages/story_core/prompt_call_log.py`: context-local recording contract and immutable project call records.
- Modify `packages/story_core/orchestrator.py`: render registered templates and instrument `_timed_chat`.
- Modify `packages/story_core/file_project_store.py`: project overrides, context extraction, reconstructed preview marker and call-log persistence.
- Modify `apps/api/routes/file_projects.py`: project template, context and call APIs.
- Modify `apps/api/routes/stories.py`: global template APIs.
- Modify `apps/web/lib/api.ts`: separate response types and API clients.
- Refactor `apps/web/app/projects/[id]/prompts/page.tsx`: three-view shell.
- Create `apps/web/components/prompts/PromptTemplatesView.tsx`.
- Create `apps/web/components/prompts/PromptContextView.tsx`.
- Create `apps/web/components/prompts/PromptCallsView.tsx`.
- Add backend tests in `tests/story_core/test_prompt_templates.py`, `tests/story_core/test_prompt_call_log.py`, `tests/api/test_story_routes.py`, and `tests/api/test_skill_pack_routes.py` only where existing fixtures fit.
- Extend `apps/web/tests/story-workbench.spec.ts` for the three prompt views.

### Task 1: Source Template Registry

**Files:**
- Create: `packages/story_core/prompt_templates.py`
- Create: `tests/story_core/test_prompt_templates.py`
- Modify: `packages/story_core/orchestrator.py`

- [ ] **Step 1: Write failing registry and rendering tests**

```python
def test_writer_template_source_contains_placeholders_not_project_content():
    template = get_default_prompt_template("writer")
    assert "{{chapter_direction}}" in template.content
    assert "夜烬" not in template.content


def test_render_rejects_unknown_or_missing_variables():
    template = PromptTemplate(key="writer", content="正文：{{chapter_direction}}")
    with pytest.raises(ValueError, match="missing_template_variable:chapter_direction"):
        render_prompt_template(template, {})
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/story_core/test_prompt_templates.py -q`

Expected: collection fails because `packages.story_core.prompt_templates` does not exist.

- [ ] **Step 3: Implement definitions and strict rendering**

```python
@dataclass(frozen=True)
class PromptTemplate:
    key: str
    title: str
    stage: str
    content: str
    required_variables: tuple[str, ...]


def render_prompt_template(template: PromptTemplate, values: Mapping[str, str]) -> str:
    variables = set(_VARIABLE_PATTERN.findall(template.content))
    missing = variables - values.keys()
    if missing:
        raise ValueError(f"missing_template_variable:{sorted(missing)[0]}")
    unknown = variables - set(template.required_variables)
    if unknown:
        raise ValueError(f"unknown_template_variable:{sorted(unknown)[0]}")
    return _VARIABLE_PATTERN.sub(lambda match: str(values[match.group(1)]), template.content)
```

Register `director`, `writer`, `revision`, `expansion`, and `compression`. Extract fixed prose from `_plan_prompt`, `_body_prompt`, `_revision_prompt`, and conditional expansion/compression prompts into these definitions; leave all project values in named renderer inputs.

- [ ] **Step 4: Make orchestrator prompt methods render the registry**

Each method must build a dictionary such as:

```python
return render_effective_prompt(
    "writer",
    {
        "output_contract": output_contract,
        "chapter_direction": chapter_direction,
        "chapter_facts": chapter_facts,
        "character_context": character_context,
        "prose_method": prose_method,
    },
)
```

Preserve existing prompt text and prompt hygiene tests while changing its source of truth.

- [ ] **Step 5: Run focused and existing prompt tests**

Run: `python -m pytest tests/story_core/test_prompt_templates.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_governance_prompt.py tests/story_core/test_fallback_prompt_hygiene.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add packages/story_core/prompt_templates.py packages/story_core/orchestrator.py tests/story_core/test_prompt_templates.py
git commit -m "refactor: extract source prompt templates"
```

### Task 2: Global Templates and Project Overrides

**Files:**
- Modify: `packages/story_core/prompt_templates.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/stories.py`
- Modify: `apps/api/routes/file_projects.py`
- Modify: `tests/story_core/test_prompt_templates.py`
- Modify: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing inheritance and API tests**

```python
def test_project_override_changes_only_that_project(tmp_path):
    first = FileProjectStore(make_project(tmp_path / "first"))
    second = FileProjectStore(make_project(tmp_path / "second"))
    first.set_prompt_template_override("writer", "项目写法：{{chapter_direction}}")
    assert first.effective_prompt_template("writer")["source"] == "project_override"
    assert second.effective_prompt_template("writer")["source"] == "global_default"


def test_delete_override_restores_global_template(file_project):
    client.put(f"/file-projects/{file_project}/prompt-templates/writer", json={"content": "覆盖：{{chapter_direction}}"})
    response = client.delete(f"/file-projects/{file_project}/prompt-templates/writer")
    assert response.json()["source"] == "global_default"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/story_core/test_prompt_templates.py tests/api/test_story_routes.py -k "prompt_template" -q`

Expected: missing methods/routes.

- [ ] **Step 3: Add atomic persistence**

Store global overrides at `data/prompt-templates/templates.json`; store project overrides at `FileProjectStore.story_system_dir / "prompt_templates.json"`. Use atomic temporary-file replacement. Persist only changed `content`, `updated_at`, and a SHA-256 `version`; defaults remain in code.

- [ ] **Step 4: Add global and project APIs**

Implement the routes from the design with Pydantic payloads using `extra="forbid"`. Return:

```json
{"key":"writer","title":"正文写作","content":"...","source":"project_override","version":"sha256:...","variables":["chapter_direction"]}
```

Map validation failures to `422`; map unknown template keys to `404`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/story_core/test_prompt_templates.py tests/api/test_story_routes.py -k "prompt_template" -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add packages/story_core/prompt_templates.py packages/story_core/file_project_store.py apps/api/routes/stories.py apps/api/routes/file_projects.py tests/story_core/test_prompt_templates.py tests/api/test_story_routes.py
git commit -m "feat: add prompt template inheritance"
```

### Task 3: Separate Context From Reconstructed Preview

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/file_projects.py`
- Modify: `tests/story_core/test_file_project_store.py`
- Modify: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing context-boundary tests**

```python
def test_prompt_context_returns_modules_without_assembled_prompts(store):
    result = store.prompt_context(1)
    assert result["schema_version"] == "file-project-prompt-context/v1"
    assert result["modules"]
    assert "prompts" not in result


def test_prompt_preview_is_explicitly_reconstructed(store):
    result = store.prompt_preview(1)
    assert result["reconstructed"] is True
    assert result["source"] == "rebuilt_from_current_project_files"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/story_core/test_file_project_store.py tests/api/test_story_routes.py -k "prompt_context or prompt_preview" -q`

- [ ] **Step 3: Extract context assembly**

Move module creation from `prompt_preview()` into `prompt_context()`. Each declared stage dependency must return either a module record or:

```json
{"key":"dialogue_context","available":false,"reason":"not_provided_for_chapter"}
```

Keep `prompt_preview()` as a compatibility wrapper that consumes `prompt_context()` and sets `reconstructed: true`.

- [ ] **Step 4: Add the context route and verify**

Run: `python -m pytest tests/story_core/test_file_project_store.py tests/api/test_story_routes.py -k "prompt_context or prompt_preview" -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/file_project_store.py apps/api/routes/file_projects.py tests/story_core/test_file_project_store.py tests/api/test_story_routes.py
git commit -m "refactor: separate prompt context from preview"
```

### Task 4: Immutable Prompt Call Records

**Files:**
- Create: `packages/story_core/prompt_call_log.py`
- Create: `tests/story_core/test_prompt_call_log.py`
- Modify: `packages/story_core/file_project_store.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_prompt_call_records_started_success_and_failure(tmp_path):
    log = PromptCallLog(tmp_path, project_id="file:p-test")
    call = log.start(chapter_number=1, stage="正文写作", prompt="真实 prompt", modules=["core_context"])
    log.succeed(call.call_id, provider="openai", model="deepseek-v4-flash", elapsed_seconds=1.2, output="正文")
    saved = log.get(call.call_id)
    assert saved["status"] == "succeeded"
    assert saved["user_prompt"] == "真实 prompt"


def test_each_retry_gets_a_distinct_call_id(tmp_path):
    log = PromptCallLog(tmp_path, project_id="file:p-test")
    assert log.start(chapter_number=1, stage="导演").call_id != log.start(chapter_number=1, stage="导演重试").call_id
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/story_core/test_prompt_call_log.py -q`

- [ ] **Step 3: Implement storage and context-local recorder**

Write details under `FileProjectStore.story_system_dir / "prompt_calls" / f"{call_id}.json"` and append summaries to `FileProjectStore.story_system_dir / "prompt_calls" / "index.jsonl"`. Expose:

```python
@contextmanager
def prompt_call_recording(recorder: PromptCallRecorder) -> Iterator[None]: ...

def start_prompt_call(**payload: Any) -> str | None: ...
def finish_prompt_call(call_id: str | None, **result: Any) -> None: ...
```

Detail writes are atomic. If `start()` cannot persist, raise before the provider request. Output storage is limited to summary and character count; the full generated chapter already has its own storage.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/story_core/test_prompt_call_log.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/prompt_call_log.py packages/story_core/file_project_store.py tests/story_core/test_prompt_call_log.py
git commit -m "feat: persist prompt call records"
```

### Task 5: Record Every Orchestrator Model Call

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/file_projects.py`
- Modify: `tests/story_core/test_orchestrator.py`
- Modify: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing integration tests**

```python
def test_timed_chat_records_exact_prompt_on_success(fake_runtime, recorder):
    with prompt_call_recording(recorder):
        orchestrator._timed_chat(story, "EXACT PROMPT", max_tokens=10, json_mode=False, agent="writer", stage="正文写作")
    assert recorder.records[0]["user_prompt"] == "EXACT PROMPT"
    assert recorder.records[0]["status"] == "succeeded"


def test_failed_and_retried_calls_are_both_recorded(file_project):
    result = run_generation_with_first_planner_failure(file_project)
    calls = client.get(f"/file-projects/{file_project}/prompt-calls?chapter_number=1").json()["calls"]
    assert [item["status"] for item in calls[:2]] == ["failed", "succeeded"]
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/story_core/test_orchestrator.py tests/api/test_story_routes.py -k "prompt_call" -q`

- [ ] **Step 3: Instrument `_timed_chat`**

Call `start_prompt_call()` immediately before `_chat()`, then call `finish_prompt_call()` in success, returned-error and raised-exception paths. Record the resolved provider/model from `_last_runtime_request`, exact `prompt`, stage, chapter, elapsed time, template source/version and module keys supplied by the renderer.

- [ ] **Step 4: Install the recorder around file generation**

Wrap both `generate_next_chapter()` and `regenerate_chapter()` engine calls with `prompt_call_recording(self.prompt_call_log())`. Do not install a global mutable recorder.

- [ ] **Step 5: Add list/detail routes and run integration tests**

Run: `python -m pytest tests/story_core/test_orchestrator.py tests/api/test_story_routes.py -k "prompt_call" -q`

Expected: success, failure and retry records pass.

- [ ] **Step 6: Commit**

```powershell
git add packages/story_core/orchestrator.py packages/story_core/file_project_store.py apps/api/routes/file_projects.py tests/story_core/test_orchestrator.py tests/api/test_story_routes.py
git commit -m "feat: trace real model prompt calls"
```

### Task 6: Three-View Prompt Workbench

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/prompts/page.tsx`
- Create: `apps/web/components/prompts/PromptTemplatesView.tsx`
- Create: `apps/web/components/prompts/PromptContextView.tsx`
- Create: `apps/web/components/prompts/PromptCallsView.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing Playwright coverage**

```ts
test("提示词工作台分开模板、上下文和真实调用", async ({ page }) => {
  await page.goto(`/projects/${encodeURIComponent(projectId)}/prompts`);
  await expect(page.getByRole("tab", { name: "提示词模板" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("{{chapter_direction}}", { exact: false })).toBeVisible();
  await expect(page.getByText("夜烬", { exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: "上下文模块" }).click();
  await expect(page.getByText("本章人物模块", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "实际调用" }).click();
  await expect(page.getByText("第 1 次 · 正文写手", { exact: false })).toBeVisible();
});
```

- [ ] **Step 2: Verify RED**

Run: `npm.cmd run test:e2e -- --grep "提示词工作台分开"`

- [ ] **Step 3: Add typed API clients**

Define separate `PromptTemplateEntry`, `PromptContextResponse`, `PromptCallSummary`, and `PromptCallDetail` types. Do not reuse `PromptPreviewResponse` for the new endpoints.

- [ ] **Step 4: Build the three views**

Use an ARIA tab list and URL query state. Templates support global/project source selection, save override and restore default. Context is read-only and links to source pages. Calls list summaries and opens one immutable detail; reconstructed preview appears in a separate warning panel only when no real calls exist.

- [ ] **Step 5: Handle loading independently**

Each view owns its request state and retry button. A failed calls request must not hide templates or context, and no view may remain in loading after rejection.

- [ ] **Step 6: Run page tests and build**

Run: `npm.cmd run test:e2e -- apps/web/tests/story-workbench.spec.ts`

Run: `npm.cmd run build`

Expected: tests and build pass.

- [ ] **Step 7: Commit**

```powershell
git add apps/web/lib/api.ts apps/web/app/projects/[id]/prompts/page.tsx apps/web/components/prompts apps/web/tests/story-workbench.spec.ts
git commit -m "feat: split prompt workbench views"
```

### Task 7: Full Verification and Compatibility Audit

**Files:**
- Modify only files required by failures found in this task.

- [ ] **Step 1: Run backend prompt and generation suites**

Run: `python -m pytest tests/story_core/test_prompt_templates.py tests/story_core/test_prompt_call_log.py tests/story_core/test_orchestrator.py tests/story_core/test_file_project_store.py tests/api/test_story_routes.py -q`

Expected: all pass.

- [ ] **Step 2: Run all frontend tests and production build**

Stop the dev server before the production build, then run:

```powershell
npm.cmd run test:e2e
npm.cmd run build
```

Expected: all Playwright tests pass and Next.js build exits 0. Restart the dev server afterward; development uses `.next-dev` and production uses `.next`.

- [ ] **Step 3: Perform a real local generation smoke test**

After the automated temporary-project generation test, verify the running API contract against the current project without printing credentials or changing the novel:

```powershell
$projectId = [uri]::EscapeDataString('file:p-gou-webgame-restored')
$calls = Invoke-RestMethod "http://127.0.0.1:8000/file-projects/$projectId/prompt-calls?chapter_number=1"
$calls.calls | Select-Object stage,status,provider,model,attempt
```

Expected: director and writer calls are present, final prompts can be opened, and no reconstructed preview is labeled as a real call.

- [ ] **Step 4: Review changed files and commit final fixes**

```powershell
git diff --check
git status --short
git add packages/story_core/prompt_templates.py packages/story_core/prompt_call_log.py packages/story_core/orchestrator.py packages/story_core/file_project_store.py apps/api/routes/stories.py apps/api/routes/file_projects.py apps/web/lib/api.ts apps/web/app/projects/[id]/prompts/page.tsx apps/web/components/prompts tests/story_core/test_prompt_templates.py tests/story_core/test_prompt_call_log.py tests/story_core/test_orchestrator.py tests/story_core/test_file_project_store.py tests/api/test_story_routes.py apps/web/tests/story-workbench.spec.ts
git commit -m "test: verify prompt workbench split"
```
