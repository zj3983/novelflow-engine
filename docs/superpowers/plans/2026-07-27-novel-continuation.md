# Existing Novel Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to import a TXT/Markdown novel or chapter directory, review extracted continuity data, create a standard file project, and generate the next chapter.

**Architecture:** Add a continuation-import domain beside the legacy structured-book importer. A disk-backed import session owns source parsing, editable normalized chapters, resumable analysis, and evidence; only the final conversion step creates a normal `FileProjectStore` project, after which existing outline and generation APIs are reused.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, existing story-core model/runtime adapters, Next.js 14, React 18, TypeScript, pytest, Playwright.

---

## File Map

- Create `packages/story_core/continuation_import.py`: source decoding, chapter detection, normalization, fingerprints, validation.
- Create `packages/story_core/continuation_sessions.py`: atomic disk persistence and session lifecycle.
- Create `packages/story_core/continuation_analysis.py`: batched analysis contracts, evidence merge, continuation-start state.
- Create `packages/story_core/continuation_project.py`: convert confirmed sessions into standard file projects.
- Create `apps/api/routes/continuation_imports.py`: REST models, filesystem authorization, background analysis jobs.
- Modify `apps/api/main.py`: register the new router.
- Modify `packages/story_core/file_project_creation.py`: expose a reusable atomic project writer for imported state.
- Create `apps/web/components/ContinuationImportWizard.tsx`: import, preview, analysis, settings, and completion workflow.
- Modify `apps/web/app/projects/new/page.tsx`: add the `续写已有小说` creation mode.
- Modify `apps/web/lib/api.ts`: continuation API types and calls.
- Modify `apps/web/app/globals.css`: wizard layout and stable progress/preview dimensions.
- Create focused pytest and Playwright files listed in each task.

## Task 1: Parse TXT, Markdown, and Chapter Directories

**Files:**
- Create: `packages/story_core/continuation_import.py`
- Test: `tests/story_core/test_continuation_import.py`

- [ ] **Step 1: Write failing parser tests**

```python
from pathlib import Path

from packages.story_core.continuation_import import scan_continuation_source


def test_scans_single_gbk_txt_into_ordered_chapters(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_bytes("第一章 开端\n正文一\n第二章 相遇\n正文二".encode("gbk"))

    result = scan_continuation_source(source)

    assert result.encoding == "gbk"
    assert [item.number for item in result.chapters] == [1, 2]
    assert [item.title for item in result.chapters] == ["开端", "相遇"]
    assert result.can_analyze is True


def test_directory_uses_natural_chapter_order_and_flags_duplicates(tmp_path: Path) -> None:
    (tmp_path / "第10章.txt").write_text("重复正文", encoding="utf-8")
    (tmp_path / "第2章.md").write_text("# 第二章\n重复正文", encoding="utf-8")

    result = scan_continuation_source(tmp_path)

    assert [item.source_name for item in result.chapters] == ["第2章.md", "第10章.txt"]
    assert result.duplicate_groups == [[result.chapters[0].chapter_id, result.chapters[1].chapter_id]]
    assert result.can_analyze is False
```

- [ ] **Step 2: Run tests and confirm the missing module failure**

Run: `pytest tests/story_core/test_continuation_import.py -q`

Expected: FAIL with `ModuleNotFoundError: packages.story_core.continuation_import`.

- [ ] **Step 3: Implement immutable scan models and decoding**

```python
class ContinuationChapter(BaseModel):
    chapter_id: str
    number: int
    title: str
    body: str
    source_name: str
    source_start: int = 0
    source_end: int = 0
    fingerprint: str


class ContinuationScanResult(BaseModel):
    source_path: str
    source_kind: Literal["file", "directory"]
    encoding: str
    chapters: list[ContinuationChapter]
    total_chars: int
    warnings: list[str] = Field(default_factory=list)
    duplicate_groups: list[list[str]] = Field(default_factory=list)
    numbering_gaps: list[int] = Field(default_factory=list)
    can_analyze: bool = False


def decode_novel_bytes(payload: bytes, forced_encoding: str | None = None) -> tuple[str, str]:
    candidates = [forced_encoding] if forced_encoding else ["utf-8-sig", "utf-8", "gb18030", "gbk"]
    for encoding in candidates:
        if not encoding:
            continue
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("source_encoding_unknown")
```

Implement `scan_continuation_source(path, forced_encoding=None)` with anchored Chinese chapter-title regexes, Markdown headings, natural numeric ordering, recursive `.txt`/`.md` collection, SHA-256 fingerprints, empty-chapter checks, duplicate groups, numbering gaps, and preview-safe source ranges. Do not silently split an unmarked long file; return one provisional chapter plus `chapter_boundaries_unconfirmed` and `can_analyze=False`.

- [ ] **Step 4: Run parser tests**

Run: `pytest tests/story_core/test_continuation_import.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the parser**

```powershell
git add packages/story_core/continuation_import.py tests/story_core/test_continuation_import.py
git commit -m "feat: parse continuation novel sources"
```

## Task 2: Persist Editable Import Sessions

**Files:**
- Create: `packages/story_core/continuation_sessions.py`
- Test: `tests/story_core/test_continuation_sessions.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_session_edits_chapters_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("第一章 A\n甲\n第二章 B\n乙", encoding="utf-8")
    store = ContinuationSessionStore(tmp_path / "sessions")

    session = store.create(scan_continuation_source(source))
    updated = store.replace_chapters(session.session_id, [
        session.chapters[1].model_copy(update={"number": 1, "title": "新的第一章"}),
        session.chapters[0].model_copy(update={"number": 2}),
    ])

    assert source.read_text(encoding="utf-8").startswith("第一章 A")
    assert [item.title for item in updated.chapters] == ["新的第一章", "A"]
    assert store.get(session.session_id).revision == 2
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/story_core/test_continuation_sessions.py -q`

Expected: FAIL because `ContinuationSessionStore` does not exist.

- [ ] **Step 3: Implement atomic session storage**

```python
class ContinuationImportSession(BaseModel):
    schema_version: Literal["continuation-import-session/v1"] = "continuation-import-session/v1"
    session_id: str
    revision: int = 1
    status: Literal["parsed", "analyzing", "ready", "failed", "cancelled"] = "parsed"
    source_path: str
    source_fingerprint: str
    encoding: str
    chapters: list[ContinuationChapter]
    analysis: dict[str, Any] = Field(default_factory=dict)
    analysis_progress: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class ContinuationSessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, scan: ContinuationScanResult) -> ContinuationImportSession:
        session = ContinuationImportSession(
            session_id=f"ci-{uuid4().hex}",
            source_path=scan.source_path,
            source_fingerprint=fingerprint_source(Path(scan.source_path)),
            encoding=scan.encoding,
            chapters=scan.chapters,
        )
        self._write(session)
        return session

    def get(self, session_id: str) -> ContinuationImportSession:
        return ContinuationImportSession.model_validate_json(self._path(session_id).read_text(encoding="utf-8"))

    def replace_chapters(self, session_id: str, chapters: list[ContinuationChapter]) -> ContinuationImportSession:
        validate_confirmed_chapters(chapters)
        return self.update(session_id, lambda item: item.model_copy(update={"chapters": chapters}))

    def update(self, session_id: str, mutate: Callable[[ContinuationImportSession], ContinuationImportSession]) -> ContinuationImportSession:
        current = self.get(session_id)
        updated = mutate(current).model_copy(update={"revision": current.revision + 1})
        self._write(updated)
        return updated
```

Store each session in `<root>/<session_id>/session.json`; copy original bytes into `source/original/`; write through a temporary file, `fsync`, and `os.replace`. Reject stale revisions, invalid numbering, empty confirmed chapters, and source fingerprints that changed since scan.

- [ ] **Step 4: Run lifecycle tests**

Run: `pytest tests/story_core/test_continuation_sessions.py -q`

Expected: PASS.

- [ ] **Step 5: Commit session persistence**

```powershell
git add packages/story_core/continuation_sessions.py tests/story_core/test_continuation_sessions.py
git commit -m "feat: persist continuation import sessions"
```

## Task 3: Add Resumable Hierarchical Analysis

**Files:**
- Create: `packages/story_core/continuation_analysis.py`
- Test: `tests/story_core/test_continuation_analysis.py`

- [ ] **Step 1: Write failing evidence and resume tests**

```python
class FakeAnalyzer:
    def analyze_chapters(self, chapters):
        return [ChapterAnalysis(chapter_id=item.chapter_id, summary=item.title, characters=[], facts=[], hooks=[])
                for item in chapters]

    def merge(self, chapter_results, recent_chapters):
        return ContinuationAnalysis(title="原书", continuation_start={"latest_chapter": len(chapter_results)})


def test_analysis_resumes_after_completed_batch(session_store, parsed_session):
    session_store.update(parsed_session.session_id, lambda item: item.model_copy(update={
        "analysis_progress": {"completed_chapter_ids": [parsed_session.chapters[0].chapter_id]}
    }))

    result = run_continuation_analysis(session_store, parsed_session.session_id, FakeAnalyzer(), batch_size=1)

    assert result.status == "ready"
    assert result.analysis["continuation_start"]["latest_chapter"] == len(parsed_session.chapters)
    assert result.analysis["evidence_index"]
```

- [ ] **Step 2: Verify failure**

Run: `pytest tests/story_core/test_continuation_analysis.py -q`

Expected: FAIL because analysis contracts are missing.

- [ ] **Step 3: Implement analysis contracts and orchestration**

Define Pydantic contracts for `EvidenceRef`, `ChapterAnalysis`, `CharacterAnalysis`, `TimelineEvent`, `HookAnalysis`, `StyleProfile`, `ContinuationStart`, and `ContinuationAnalysis`. Implement `ContinuationAnalyzer` as a protocol and `run_continuation_analysis()` as the resumable orchestrator. Persist each completed batch before requesting the next one.

Use the configured writer/planner runtime adapter for the production analyzer. Require JSON-only model output and validate it before merging. The merge prompt must produce these top-level keys:

```python
REQUIRED_ANALYSIS_KEYS = {
    "story_overview", "characters", "world", "power_system", "timeline",
    "open_hooks", "style_profile", "continuation_start", "evidence_index",
}
```

Only claims with `EvidenceRef(chapter_id, excerpt_start, excerpt_end)` can become confirmed facts. Unsupported model claims receive `confidence="inferred"` and appear in `needs_confirmation`.

- [ ] **Step 4: Run analysis tests**

Run: `pytest tests/story_core/test_continuation_analysis.py -q`

Expected: PASS, including interrupted-batch resume and unsupported-claim tests.

- [ ] **Step 5: Commit analysis**

```powershell
git add packages/story_core/continuation_analysis.py tests/story_core/test_continuation_analysis.py
git commit -m "feat: analyze imported novels for continuation"
```

## Task 4: Expose Continuation Import APIs

**Files:**
- Create: `apps/api/routes/continuation_imports.py`
- Modify: `apps/api/main.py`
- Test: `tests/api/test_continuation_import_routes.py`

- [ ] **Step 1: Write failing API lifecycle tests**

```python
def test_scan_create_edit_and_analyze_lifecycle(client, tmp_path, monkeypatch):
    source = tmp_path / "book.txt"
    source.write_text("第一章 开端\n正文\n第二章 结尾\n正文", encoding="utf-8")

    scan = client.post("/continuation-imports/scan", json={"source_path": str(source)})
    assert scan.status_code == 200
    created = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    session_id = created["session_id"]

    started = client.post(f"/continuation-imports/{session_id}/analyze")
    assert started.status_code == 202
    assert client.get(f"/continuation-imports/{session_id}").status_code == 200


def test_scan_rejects_paths_outside_allowed_roots(client, tmp_path):
    response = client.post("/continuation-imports/scan", json={"source_path": str(tmp_path)})
    assert response.status_code == 403


def test_source_browser_lists_supported_files_and_directories(client, allowed_root):
    (allowed_root / "novel.txt").write_text("第一章", encoding="utf-8")
    (allowed_root / "notes.json").write_text("{}", encoding="utf-8")
    (allowed_root / "chapters").mkdir()
    response = client.post("/continuation-imports/list-sources", json={"source_path": str(allowed_root)})
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["files"]] == ["novel.txt"]
    assert [item["name"] for item in response.json()["directories"]] == ["chapters"]
```

- [ ] **Step 2: Verify route failures**

Run: `pytest tests/api/test_continuation_import_routes.py -q`

Expected: FAIL with 404 responses.

- [ ] **Step 3: Implement router and job state**

Implement the spec routes with request/response models, including `POST /continuation-imports/list-sources` for the desktop file/directory picker. Resolve all sources through `require_allowed_path`; allow only `.txt` and `.md` files. Configure session root through `NOVEL_AUTOGROWTH_CONTINUATION_IMPORTS_DIR`, defaulting to `data/continuation-imports`.

```python
@router.post("/continuation-imports/{session_id}/analyze", status_code=202)
def analyze(session_id: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    session = session_store.get(session_id)
    if session.status == "analyzing":
        return {"session_id": session_id, "status": "analyzing"}
    session_store.mark_analyzing(session_id)
    background_tasks.add_task(_run_analysis_job, session_id)
    return {"session_id": session_id, "status": "analyzing"}
```

Register `init_continuation_import_routes()` in `apps/api/main.py`. Convert domain `ValueError` codes to stable 400/409/422 responses; preserve failed session data and error details.

- [ ] **Step 4: Run API tests**

Run: `pytest tests/api/test_continuation_import_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the API**

```powershell
git add apps/api/main.py apps/api/routes/continuation_imports.py tests/api/test_continuation_import_routes.py
git commit -m "feat: add continuation import api"
```

## Task 5: Convert Confirmed Analysis into a File Project

**Files:**
- Create: `packages/story_core/continuation_project.py`
- Modify: `packages/story_core/file_project_creation.py`
- Test: `tests/story_core/test_continuation_project.py`
- Modify: `tests/api/test_continuation_import_routes.py`

- [ ] **Step 1: Write failing conversion tests**

```python
def test_confirmed_session_creates_readable_file_project(tmp_path, ready_session):
    created = create_continuation_project(
        export_root=tmp_path / "projects",
        session=ready_session,
        settings=ContinuationSettings(
            start_after_chapter=2,
            fidelity="faithful",
            target_chars=4500,
            direction="沿原有冲突继续",
        ),
        project_id_factory=lambda: "p-continuation-test",
    )

    store = FileProjectStore(created.root)
    assert store.summary()["current_chapter"] == 2
    assert store.chapter(2)["body"] == ready_session.chapters[1].body
    assert store.project()["continuation"]["fidelity"] == "faithful"
    assert created.next_path.endswith("/outline")


def test_conversion_excludes_source_chapters_after_branch_point(tmp_path, ready_session):
    created = create_continuation_project(
        export_root=tmp_path / "projects",
        session=ready_session,
        settings=ContinuationSettings(
            start_after_chapter=1,
            fidelity="faithful",
            target_chars=4500,
            direction="沿原有冲突继续",
        ),
        project_id_factory=lambda: "p-continuation-branch",
    )
    store = FileProjectStore(created.root)
    assert store.chapter_numbers() == [1]
    assert store.project()["continuation"]["excluded_source_chapters"] == [2]
```

- [ ] **Step 2: Verify conversion failure**

Run: `pytest tests/story_core/test_continuation_project.py -q`

Expected: FAIL because `create_continuation_project` is undefined.

- [ ] **Step 3: Implement atomic conversion**

Refactor `file_project_creation.py` only enough to expose `write_file_project_atomically(export_root, project_id, writer)`. Use it from `create_continuation_project()` to write:

- imported accepted chapters to `chapters/NNNN-title.md` and `.story-system/chapters/NNNN.json`;
- source manifest and index under `source/` and `.story-system/source-index.json`;
- confirmed analysis into project/state character, world, timeline, hook, and style fields;
- continuation settings and branch metadata into `.webnovel/project.json`;
- `current_chapter` equal to the selected continuation point.

Do not call chapter generation while converting. Validate the final directory with `FileProjectStore`, `StoryState.model_validate`, and JSON round trips before renaming the temporary directory.

Add `POST /continuation-imports/{id}/create-project`; reject sessions not in `ready`, unresolved blocking conflicts, invalid continuation points, and duplicate create requests.

- [ ] **Step 4: Run conversion and API tests**

Run: `pytest tests/story_core/test_continuation_project.py tests/api/test_continuation_import_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit conversion**

```powershell
git add packages/story_core/continuation_project.py packages/story_core/file_project_creation.py tests/story_core/test_continuation_project.py apps/api/routes/continuation_imports.py tests/api/test_continuation_import_routes.py
git commit -m "feat: create projects from imported novels"
```

## Task 6: Build the Import and Analysis Wizard

**Files:**
- Create: `apps/web/components/ContinuationImportWizard.tsx`
- Modify: `apps/web/app/projects/new/page.tsx`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/globals.css`
- Test: `apps/web/tests/continuation-import.spec.ts`

- [ ] **Step 1: Write a failing browser test for the wizard**

```typescript
test("imports a novel, confirms analysis, and creates a continuation project", async ({ page }) => {
  await page.route("**/continuation-imports/scan", route => route.fulfill({ json: scanFixture }));
  await page.route("**/continuation-imports", route => route.fulfill({ status: 201, json: sessionFixture }));
  await page.route("**/continuation-imports/session-1/analyze", route => route.fulfill({ status: 202, json: { status: "analyzing" } }));
  await page.route("**/continuation-imports/session-1", route => route.fulfill({ json: readySessionFixture }));
  await page.route("**/continuation-imports/session-1/create-project", route => route.fulfill({ status: 201, json: { next_path: "/projects/file%3Ap-imported/outline" } }));

  await page.goto("/projects/new");
  await page.getByRole("tab", { name: "续写已有小说" }).click();
  await page.getByLabel("小说文件或章节目录").fill("D:/books/demo.txt");
  await page.getByRole("button", { name: "扫描原文" }).click();
  await expect(page.getByText("共 2 章")).toBeVisible();
  await page.getByRole("button", { name: "开始分析" }).click();
  await expect(page.getByRole("tab", { name: "续写起点" })).toBeVisible();
  await page.getByRole("button", { name: "创建续写项目" }).click();
  await expect(page).toHaveURL(/file%3Ap-imported\/outline/);
});
```

- [ ] **Step 2: Verify the browser test fails**

Run: `cd apps/web; npx playwright test tests/continuation-import.spec.ts`

Expected: FAIL because the tab and wizard do not exist.

- [ ] **Step 3: Add typed API functions and wizard states**

Add `ContinuationScan`, `ContinuationSession`, `ContinuationAnalysis`, and `ContinuationSettings` types to `api.ts`, plus `listContinuationSources`, `scanContinuationSource`, `createContinuationImport`, `updateContinuationChapters`, `startContinuationAnalysis`, `fetchContinuationImport`, `updateContinuationAnalysis`, and `createContinuationProject`.

Implement `ContinuationImportWizard` with explicit steps:

```typescript
type WizardStep = "source" | "chapters" | "analyzing" | "analysis" | "settings";

const ANALYSIS_TABS = [
  ["overview", "故事概况"], ["characters", "人物"], ["world", "世界观"],
  ["power", "力量体系"], ["timeline", "时间线"], ["hooks", "伏笔与未完剧情"],
  ["style", "文风"], ["start", "续写起点"],
] as const;
```

The source step must open a local file/directory picker backed by `listContinuationSources`; when scan returns `source_encoding_unknown`, show an encoding selector and resubmit with `forced_encoding`. The chapter step must support move up/down, rename, merge with previous, split at cursor, and display blocking warnings. Analysis tabs must expose edit/save controls for inferred facts and unresolved conflicts, while evidence links open the referenced chapter excerpt. Poll only while status is `analyzing`; stop polling on unmount or terminal state. Use existing `ws-*` controls and icons already available in the app.

Extend `CreationMode` to `"inspiration" | "blank" | "continuation"`, add the third accessible tab, and render the wizard instead of the normal creation form in continuation mode.

- [ ] **Step 4: Run TypeScript and wizard tests**

Run: `cd apps/web; npx tsc --noEmit`

Expected: PASS.

Run: `cd apps/web; npx playwright test tests/continuation-import.spec.ts`

Expected: PASS.

- [ ] **Step 5: Commit the wizard**

```powershell
git add apps/web/components/ContinuationImportWizard.tsx apps/web/app/projects/new/page.tsx apps/web/lib/api.ts apps/web/app/globals.css apps/web/tests/continuation-import.spec.ts
git commit -m "feat: add novel continuation import wizard"
```

## Task 7: Add Quick Continuation and Draft Safety

**Files:**
- Modify: `apps/api/routes/continuation_imports.py`
- Modify: `packages/story_core/continuation_project.py`
- Modify: `apps/web/components/ContinuationImportWizard.tsx`
- Test: `tests/api/test_continuation_import_routes.py`
- Test: `apps/web/tests/continuation-import.spec.ts`

- [ ] **Step 1: Write failing quick-mode safety tests**

```python
def test_quick_continue_stops_on_unresolved_blocker(client, ready_session_with_conflict):
    response = client.post(
        f"/continuation-imports/{ready_session_with_conflict.session_id}/quick-continue",
        json={"target_chars": 4500},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "analysis_confirmation_required"


def test_quick_continue_creates_project_then_starts_one_generation_job(client, ready_session, monkeypatch):
    started = []
    monkeypatch.setattr("apps.api.routes.continuation_imports.start_file_generation_job", lambda project_id: started.append(project_id))
    response = client.post(f"/continuation-imports/{ready_session.session_id}/quick-continue", json={"target_chars": 4500})
    assert response.status_code == 202
    assert len(started) == 1
```

- [ ] **Step 2: Verify quick-mode tests fail**

Run: `pytest tests/api/test_continuation_import_routes.py -q -k quick_continue`

Expected: FAIL with 404.

- [ ] **Step 3: Implement quick mode using existing generation jobs**

Add `POST /continuation-imports/{id}/quick-continue`. It must:

1. require completed analysis and no unresolved blockers;
2. apply defaults `start_after_chapter=latest`, `fidelity=faithful`, project default target length, inferred direction;
3. create the file project once;
4. start exactly one existing file-project generation job with one review/revision pass;
5. return the project route and job id.

Do not write a chapter directly in the import router. Failed generated drafts remain in the existing `.story-system/failed-drafts` flow and must not update `current_chapter`.

Add a `快速续写` command to the source/analysis flow, with a confirmation summary and blocking-error display.

- [ ] **Step 4: Run quick-mode tests**

Run: `pytest tests/api/test_continuation_import_routes.py -q`

Expected: PASS.

Run: `cd apps/web; npx playwright test tests/continuation-import.spec.ts`

Expected: PASS for both confirm-first and quick paths.

- [ ] **Step 5: Commit quick mode**

```powershell
git add apps/api/routes/continuation_imports.py packages/story_core/continuation_project.py apps/web/components/ContinuationImportWizard.tsx tests/api/test_continuation_import_routes.py apps/web/tests/continuation-import.spec.ts
git commit -m "feat: add safe quick continuation"
```

## Task 8: Full Regression and Visual Verification

**Files:**
- Modify only files required by failures found in this task.

- [ ] **Step 1: Run focused backend suites**

Run:

```powershell
pytest tests/story_core/test_continuation_import.py tests/story_core/test_continuation_sessions.py tests/story_core/test_continuation_analysis.py tests/story_core/test_continuation_project.py tests/api/test_continuation_import_routes.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full backend suite**

Run: `pytest -q`

Expected: all tests pass with only the repository's existing documented skips.

- [ ] **Step 3: Run frontend type and browser suites**

Run:

```powershell
Set-Location apps/web
npx tsc --noEmit
npx playwright test tests/continuation-import.spec.ts tests/story-generation.spec.ts tests/story-workbench.spec.ts
```

Expected: TypeScript PASS and all selected Playwright tests PASS.

- [ ] **Step 4: Verify real desktop layouts**

Start or reuse the API on `127.0.0.1:8010` and web app on `localhost:3000`. Use the in-app browser to verify `/projects/new` at 1440x900 and 390x844. Confirm no text overlap, chapter rows do not resize during progress updates, all tabs are keyboard reachable, long paths wrap, and the next section remains visible without a blank screen.

- [ ] **Step 5: Confirm the final worktree state**

Run: `git status --short`

Expected: no output. If verification exposed a defect, return to the task that owns that file, add a focused regression test there, rerun that task's commands, and commit the fix before repeating this final status check.
