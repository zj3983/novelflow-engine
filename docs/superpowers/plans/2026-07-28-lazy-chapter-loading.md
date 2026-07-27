# Lazy Chapter Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace whole-novel workspace loading with a lightweight story overview and on-demand chapter detail requests so long novels remain fast as chapter count grows.

**Architecture:** File projects receive a new overview response containing story-level state and a lightweight chapter index. A separate detail endpoint hydrates exactly one chapter. The shared workspace provider exposes the overview and normalized chapter index, while chapter-dependent pages use a reusable detail hook; non-file projects retain the existing full-story path.

**Tech Stack:** Python 3.11, FastAPI, pytest, TypeScript 5.6, React 18, Next.js 14, Playwright.

---

## File Map

- Modify `packages/story_core/file_project_store.py`: add a single-pass lightweight chapter index reader and keep `summary()` on that fast path.
- Modify `apps/api/routes/file_projects.py`: expose file-story overview and one-chapter detail endpoints.
- Modify `tests/story_core/test_file_project_store.py`: prove index and summary never hydrate complete chapters.
- Modify `tests/api/test_file_project_creation_routes.py`: verify endpoint schemas, omissions, detail parity, and 404 responses.
- Modify `apps/web/lib/api.ts`: define overview/index types and add overview/detail clients.
- Modify `apps/web/components/ws/ProjectWorkspaceProvider.tsx`: load file overview instead of legacy full story and expose a normalized chapter index.
- Create `apps/web/components/ws/useChapterDetail.ts`: load one file chapter while preserving non-file behavior.
- Modify `apps/web/app/projects/[id]/page.tsx`: render totals and recent entries from the lightweight index.
- Modify `apps/web/app/projects/[id]/write/page.tsx`: render the directory from the index and the reader from one chapter detail.
- Modify `apps/web/app/projects/[id]/review/page.tsx`: load the requested chapter detail.
- Modify `apps/web/app/projects/[id]/prompts/page.tsx`: use index metadata and request detail only where chapter data is displayed.
- Modify `apps/web/app/projects/[id]/dissection/page.tsx`: use the index for selection and one detail for source text.
- Modify `apps/web/app/projects/[id]/sim/page.tsx`: use index simulation markers and one selected chapter detail.
- Modify `apps/web/components/StorySidebar.tsx`: accept normalized chapter index entries rather than complete bundles.
- Modify `apps/web/tests/story-workbench.spec.ts`: route the new endpoints and assert the legacy endpoint is unused.

### Task 1: Lightweight Chapter Index in the File Store

**Files:**
- Modify: `tests/story_core/test_file_project_store.py`
- Modify: `packages/story_core/file_project_store.py:3921-3945,4567-4586`

- [ ] **Step 1: Extend the failing store test to specify the index contract**

Add assertions to `test_summary_reads_chapter_metadata_without_hydrating_full_chapters` and a separate index test:

```python
def test_chapter_index_reads_each_file_once_without_display_hydration(tmp_path, monkeypatch):
    store = _make_minimal_file_project(tmp_path / "novel")
    chapter_path = store.story_system_dir / "chapters" / "0001.json"
    chapter_path.write_text(
        json.dumps(
            {
                "chapter_number": 1,
                "chapter_title": "Chapter 1",
                "body": "alpha beta\n gamma",
                "chapter_summary": {"summary": "A short summary."},
                "next_outline": "Open the sealed door.",
                "simulation_status": {"status": "simulated"},
                "quality_report": {"writing_review": {"pass": True, "issues": []}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        store,
        "chapter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not hydrate")),
    )

    assert store.chapter_index() == [
        {
            "chapter_number": 1,
            "chapter_title": "Chapter 1",
            "body_chars": 14,
            "summary": "A short summary.",
            "next_focus": "Open the sealed door.",
            "has_quality_report": True,
            "has_simulation": True,
        }
    ]
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest tests/story_core/test_file_project_store.py::test_chapter_index_reads_each_file_once_without_display_hydration -q
```

Expected: FAIL because `FileProjectStore.chapter_index` does not exist.

- [ ] **Step 3: Implement the single-pass index reader and reuse it in summary**

Add to `FileProjectStore`:

```python
def chapter_index(self) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for number in self.chapter_numbers():
        chapter = self._read_json(
            self.story_system_dir / "chapters" / f"{number:04d}.json",
            {},
        )
        chapter = chapter if isinstance(chapter, dict) else {}
        body = str(chapter.get("body") or "")
        chapter_summary = chapter.get("chapter_summary")
        summary = chapter_summary if isinstance(chapter_summary, dict) else {}
        quality_report = chapter.get("quality_report")
        simulation_status = chapter.get("simulation_status")
        entries.append(
            {
                "chapter_number": int(chapter.get("chapter_number") or number),
                "chapter_title": str(chapter.get("chapter_title") or f"第{number}章"),
                "body_chars": len(re.sub(r"\s+", "", body)),
                "summary": str(summary.get("summary") or ""),
                "next_focus": str(chapter.get("next_outline") or summary.get("next_focus") or ""),
                "has_quality_report": isinstance(quality_report, dict) and bool(quality_report),
                "has_simulation": isinstance(simulation_status, dict) and bool(simulation_status),
            }
        )
    return entries
```

Change `summary()` to derive its `chapters` list from `chapter_index()` without calling `chapter()`.

- [ ] **Step 4: Run focused store tests and benchmark the imported novel**

Run:

```powershell
python -m pytest tests/story_core/test_file_project_store.py::test_chapter_index_reads_each_file_once_without_display_hydration tests/story_core/test_file_project_store.py::test_summary_reads_chapter_metadata_without_hydrating_full_chapters tests/story_core/test_file_project_store.py::test_file_project_store_writes_rewrites_and_commits -q
```

Expected: 3 passed.

Then run a one-off benchmark against `data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0` and require both `chapter_index()` and `summary()` to complete in under one second on the current machine.

- [ ] **Step 5: Commit the store change**

```powershell
git add packages/story_core/file_project_store.py tests/story_core/test_file_project_store.py
git commit -m "perf: add lightweight chapter index"
```

### Task 2: Overview and Single-Chapter API Endpoints

**Files:**
- Modify: `tests/api/test_file_project_creation_routes.py`
- Modify: `apps/api/routes/file_projects.py:631-691,1108-1116`

- [ ] **Step 1: Write failing API tests**

Create a three-chapter file project fixture and add tests with these central assertions:

```python
def test_file_story_overview_returns_lightweight_chapter_index(creation_api, monkeypatch):
    client, root = creation_api
    project = _create_three_chapter_project(client, root)
    monkeypatch.setattr(
        FileProjectStore,
        "chapter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("overview hydrated a chapter")),
    )

    response = client.get(f"/file-stories/{project['project_id']}/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["chapter_count"] == 3
    assert payload["chapters"][0]["chapter_number"] == 1
    assert "body" not in payload["chapters"][0]
    assert "quality_report" not in payload["chapters"][0]


def test_file_story_chapter_detail_hydrates_only_requested_chapter(creation_api, monkeypatch):
    client, root = creation_api
    project = _create_three_chapter_project(client, root)
    calls: list[int] = []
    original = FileProjectStore.chapter

    def record(store, number=None):
        calls.append(int(number or 0))
        return original(store, number)

    monkeypatch.setattr(FileProjectStore, "chapter", record)
    response = client.get(f"/file-stories/{project['project_id']}/chapters/2")

    assert response.status_code == 200
    assert response.json()["chapter_number"] == 2
    assert response.json()["body"]
    assert calls == [2]
```

Also assert missing story and missing chapter return `404` with `file_story_not_found` and `chapter_not_found:999` details.

- [ ] **Step 2: Run API tests and verify RED**

Run:

```powershell
python -m pytest tests/api/test_file_project_creation_routes.py -k "story_overview or chapter_detail" -q
```

Expected: FAIL with 404 because the routes do not exist.

- [ ] **Step 3: Add payload helpers and routes**

Implement:

```python
def _story_overview_payload(store: FileProjectStore) -> dict[str, Any]:
    state = store.state()
    chapters = store.chapter_index()
    return {
        "story_id": _story_id_for(store),
        "outline": str(state.get("outline") or store.project().get("seed_outline") or ""),
        "genre": str(state.get("genre") or ""),
        "style": str(state.get("style") or ""),
        "current_chapter": int(state.get("current_chapter") or (chapters[-1]["chapter_number"] if chapters else 0)),
        "agent_settings": state.get("agent_settings") or AgentSettings().model_dump(),
        "agent_runtime": state.get("agent_runtime") or AgentRuntimeState().model_dump(),
        "author_constraints": state.get("author_constraints") or [],
        "writing_lessons": state.get("writing_lessons") or [],
        "world_facts": state.get("world_facts") or [],
        "characters": state.get("characters") or [],
        "chapter_count": len(chapters),
        "total_body_chars": sum(int(item["body_chars"]) for item in chapters),
        "chapters": chapters,
        "parent_story_id": None,
        "branched_from_chapter": None,
        "storage_source": "file",
    }


@router.get("/file-stories/{story_id}/overview")
def get_file_story_overview(story_id: str) -> dict[str, Any]:
    store = _store_for(story_id)
    if _strip_file_prefix(_story_id_for(store)) != _strip_file_prefix(story_id):
        raise HTTPException(status_code=404, detail="file_story_not_found")
    return _story_overview_payload(store)


@router.get("/file-stories/{story_id}/chapters/{chapter_number}")
def get_file_story_chapter(story_id: str, chapter_number: int) -> dict[str, Any]:
    store = _store_for(story_id)
    if _strip_file_prefix(_story_id_for(store)) != _strip_file_prefix(story_id):
        raise HTTPException(status_code=404, detail="file_story_not_found")
    try:
        chapter = dict(store.chapter(chapter_number))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    quality = dict(chapter.get("quality_report") or {})
    quality["simplified_review"] = build_simplified_review(quality)
    chapter["quality_report"] = quality
    return chapter
```

Route order must place `/overview` and `/chapters/{chapter_number}` before the generic `/file-stories/{story_id}` handler if FastAPI matching requires it.

- [ ] **Step 4: Run API and store tests**

Run:

```powershell
python -m pytest tests/api/test_file_project_creation_routes.py -k "story_overview or chapter_detail or blank_file_project_creation" -q
python -m pytest tests/story_core/test_file_project_store.py -k "chapter_index or summary_reads" -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the API change**

```powershell
git add apps/api/routes/file_projects.py tests/api/test_file_project_creation_routes.py
git commit -m "feat: expose lazy file chapter APIs"
```

### Task 3: Frontend API Types and Clients

**Files:**
- Modify: `apps/web/lib/api.ts:377-535,3063-3075`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Add a failing client-export test**

Import the two new clients from `api.ts` and add:

```typescript
test("file chapter loading clients are exported", () => {
  expect(typeof fetchFileStoryOverview).toBe("function");
  expect(typeof fetchFileChapter).toBe("function");
});
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
npx playwright test apps/web/tests/story-workbench.spec.ts -g "file chapter loading clients are exported" --config apps/web/playwright.config.ts
```

Expected: FAIL during TypeScript compilation because the two exports do not exist.

- [ ] **Step 3: Define explicit overview and index types and clients**

Add to `api.ts`:

```typescript
export type ChapterIndexEntry = {
  chapter_number: number;
  chapter_title: string;
  body_chars: number;
  summary: string;
  next_focus: string;
  has_quality_report: boolean;
  has_simulation: boolean;
};

export type FileStoryOverview = Omit<StoryResponse, "history"> & {
  chapter_count: number;
  total_body_chars: number;
  chapters: ChapterIndexEntry[];
  storage_source: "file";
};

export async function fetchFileStoryOverview(storyId: string): Promise<FileStoryOverview> {
  return await tryFetchJson(`${fileStoryPath(storyId)}/overview`, { method: "GET" }, 30000);
}

export async function fetchFileChapter(storyId: string, chapterNumber: number): Promise<ChapterBundle> {
  return await tryFetchJson(
    `${fileStoryPath(storyId)}/chapters/${chapterNumber}`,
    { method: "GET" },
    30000,
  );
}
```

- [ ] **Step 4: Run the client test and type checking**

Run:

```powershell
npx playwright test apps/web/tests/story-workbench.spec.ts -g "file chapter loading clients are exported" --config apps/web/playwright.config.ts
cd apps/web
npx tsc --noEmit
```

Expected: the client test passes and TypeScript reports zero errors.

- [ ] **Step 5: Commit API types and clients**

```powershell
git add apps/web/lib/api.ts apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add file chapter loading client"
```

### Task 4: Migrate the Workspace Provider and All Chapter-Dependent Pages

**Files:**
- Create: `apps/web/components/ws/useChapterDetail.ts`
- Modify: `apps/web/components/ws/ProjectWorkspaceProvider.tsx`
- Modify: `apps/web/app/projects/[id]/page.tsx`
- Modify: `apps/web/app/projects/[id]/write/page.tsx`
- Modify: `apps/web/app/projects/[id]/review/page.tsx`
- Modify: `apps/web/app/projects/[id]/prompts/page.tsx`
- Modify: `apps/web/app/projects/[id]/dissection/page.tsx`
- Modify: `apps/web/app/projects/[id]/sim/page.tsx`
- Modify: `apps/web/components/StorySidebar.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Update fixtures and add failing overview/write assertions**

Change `routeCurrentFileProject` to route:

```typescript
await page.route(`**/file-stories/${encodedId}/overview`, overviewHandler);
await page.route(`**/file-stories/${encodedId}/chapters/*`, chapterHandler);
await page.route(`**/file-stories/${encodedId}`, async (route) => {
  throw new Error(`legacy full story endpoint requested: ${route.request().url()}`);
});
```

The overview fixture must expose `chapters` with `body_chars`, `summary`, and `next_focus`, while the detail fixture retains the full body and quality report. Assert overview total words and chapter directory character counts still render.

Add route-count coverage for review, prompts, dissection, and simulation. Each page must fail immediately if the legacy full-story endpoint is requested. For simulation, include one `has_simulation: true` entry and assert only the selected simulated chapter detail is fetched.

Add the route-count behavior test:

```typescript
test("file workspace loads overview and one chapter without requesting the full story", async ({ page }) => {
  const calls: string[] = [];
  const { encodedId } = await routeCurrentFileProject(page, "lazy-file-story", { calls });

  await page.goto(`/projects/${encodedId}/write?chapter=1`);
  await expect(page.getByRole("heading", { name: "章节：第 1 章" })).toBeVisible();

  expect(calls).toContain(`/file-stories/file%3Alazy-file-story/overview`);
  expect(calls).toContain(`/file-stories/file%3Alazy-file-story/chapters/1`);
  expect(calls).not.toContain(`/file-stories/file%3Alazy-file-story`);
});
```

- [ ] **Step 2: Run the two page tests and verify RED**

Run:

```powershell
npx playwright test apps/web/tests/story-workbench.spec.ts -g "project overview foregrounds|write page shows current|loads overview and one chapter|review lazy chapter|prompts lazy chapter|dissection lazy chapter|simulation lazy chapter" --config apps/web/playwright.config.ts
```

Expected: FAIL because the provider requests the legacy endpoint and pages expect `history`.

- [ ] **Step 3: Create a reusable detail hook**

Create `useChapterDetail.ts` with this public contract:

```typescript
export function useChapterDetail({
  projectId,
  story,
  chapterNumber,
  refreshVersion,
}: {
  projectId: string;
  story: StoryResponse | FileStoryOverview | null;
  chapterNumber: number;
  refreshVersion: number;
}) {
  // File project: fetch exactly one detail and retain the previous detail while loading.
  // Non-file project: resolve the bundle from StoryResponse.history without a request.
  return { chapter, loading, error, reload };
}
```

Use cancellation in the effect cleanup and ignore stale responses when chapter number changes.

- [ ] **Step 4: Migrate `ProjectWorkspaceProvider`**

Change its context shape to expose:

```typescript
type WorkspaceStory = StoryResponse | FileStoryOverview;

type ProjectWorkspaceContextValue = {
  projectId: string;
  encodedProjectId: string;
  project: ProjectResponse | null;
  story: WorkspaceStory | null;
  chapterIndex: ChapterIndexEntry[];
  loading: boolean;
  error: string | null;
  refreshVersion: number;
  refresh: () => void;
};
```

When `projectId.startsWith("file:")` or `proj.storage_source === "file"`, call `fetchFileStoryOverview`; otherwise call `fetchStory`. Normalize non-file `story.history` into index entries inside a pure helper so all pages receive `chapterIndex`.

- [ ] **Step 5: Migrate overview and sidebar**

Use `chapterIndex.slice(-5)` for recent chapters, `story.total_body_chars` for file projects, and the existing history reduction for non-file projects. Use `summary` and `next_focus` from index entries. `StorySidebar` receives `ChapterIndexEntry[]` and no longer reads chapter bodies.

- [ ] **Step 6: Migrate the write page**

Use `chapterIndex` for search, sorting, pagination, title, and `body_chars`. Use `useChapterDetail` for `requestedChapter`, render local chapter-loading errors inside the reader, and retain the directory while detail loads. After generation/regeneration, call `refresh()` and `reload()` for the target chapter only.

- [ ] **Step 7: Migrate review, prompts, dissection, and simulation**

Review uses `chapterIndex` to select a chapter and `useChapterDetail` to obtain the complete quality report. Prompts uses index metadata for navigation and detail only for chapter-specific visible fields; prompt-context API behavior remains unchanged.

Dissection uses the index for selection and one detail for source text. Disable dissection while detail is loading and leave the directory visible on a detail error.

Simulation filters index entries by `has_simulation`, selects the newest matching chapter, and fetches that one detail for simulation status and scene cards. Switching simulation chapters requests only the new detail.

- [ ] **Step 8: Run page tests and full type checking**

Run:

```powershell
npx playwright test apps/web/tests/story-workbench.spec.ts -g "project overview foregrounds|write page shows current|loads overview and one chapter|lazy chapter|切换项目时" --config apps/web/playwright.config.ts
cd apps/web
npx tsc --noEmit
```

Expected: selected browser tests pass and TypeScript reports zero errors.

- [ ] **Step 9: Commit the workspace migration**

```powershell
git add apps/web/components/ws/useChapterDetail.ts apps/web/components/ws/ProjectWorkspaceProvider.tsx apps/web/components/StorySidebar.tsx apps/web/app/projects/[id]/page.tsx apps/web/app/projects/[id]/write/page.tsx apps/web/app/projects/[id]/review/page.tsx apps/web/app/projects/[id]/prompts/page.tsx apps/web/app/projects/[id]/dissection/page.tsx apps/web/app/projects/[id]/sim/page.tsx apps/web/tests/story-workbench.spec.ts
git commit -m "perf: lazy load file project chapters"
```

### Task 5: Generation Refresh and Regression Coverage

**Files:**
- Modify: `apps/web/components/ws/useChapterDetail.ts`
- Modify: `apps/web/app/projects/[id]/write/page.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`
- Modify: `tests/api/test_file_project_creation_routes.py`

- [ ] **Step 1: Add failing generation refresh tests**

Extend existing `generated-chapter` and `regenerate-chapter` browser tests to record endpoint calls. After job completion assert:

```typescript
expect(legacyStoryRequests).toEqual([]);
expect(overviewRequests).toBeGreaterThan(1);
expect(detailRequests.at(-1)).toBe(generatedChapterNumber);
```

Add an API regression asserting overview immediately reflects a newly written chapter and its new `body_chars` total.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
npx playwright test apps/web/tests/story-workbench.spec.ts -g "generated chapter|regenerate chapter" --config apps/web/playwright.config.ts
python -m pytest tests/api/test_file_project_creation_routes.py -k "overview_reflects_new_chapter" -q
```

Expected: FAIL until refresh versions and detail reloads are coordinated.

- [ ] **Step 3: Coordinate overview and detail refresh**

Expose `refreshVersion` from the provider. Make `useChapterDetail` depend on it, but retain the last visible chapter during refresh. After generation, navigate to the generated chapter query and refresh; after regeneration, refresh in place. Do not call `fetchStory` for file projects.

- [ ] **Step 4: Run generation and API regression tests**

Run the commands from Step 2 again.

Expected: all selected tests pass, with no legacy full-story request.

- [ ] **Step 5: Commit refresh behavior**

```powershell
git add apps/web/components/ws/useChapterDetail.ts apps/web/app/projects/[id]/write/page.tsx apps/web/tests/story-workbench.spec.ts tests/api/test_file_project_creation_routes.py
git commit -m "fix: refresh only changed chapter data"
```

### Task 6: End-to-End Performance Verification

**Files:**
- Modify only if verification reveals a defect in files already listed above.

- [ ] **Step 1: Run backend regression suites**

```powershell
python -m pytest tests/story_core/test_file_project_store.py -k "chapter_index or summary_reads or writes_rewrites" -q
python -m pytest tests/api/test_file_project_creation_routes.py -k "file_story or file_project" -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run frontend checks**

```powershell
cd apps/web
npx tsc --noEmit
npx playwright test tests/story-workbench.spec.ts -g "project overview foregrounds|write page shows current|lazy chapter|generated chapter|regenerate chapter"
```

Expected: type checking and selected Playwright tests pass.

- [ ] **Step 3: Restart local services from the repository root**

Start FastAPI on `127.0.0.1:8000` with UTF-8 environment variables and Next.js on `127.0.0.1:3000` with `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`. Reuse ports only after confirming stale processes are stopped.

- [ ] **Step 4: Measure endpoint performance on the imported novel**

Measure these URLs independently:

```text
GET /file-projects/file%3Ap-da2c16a6ee9440d6ad52cb402ead88a0
GET /file-stories/file%3Ap-da2c16a6ee9440d6ad52cb402ead88a0/overview
GET /file-stories/file%3Ap-da2c16a6ee9440d6ad52cb402ead88a0/chapters/142
```

Record duration and response bytes. Project, overview, and chapter detail should each complete in about one second, and chapter detail must return only chapter 142.

- [ ] **Step 5: Verify visible browser behavior**

Open:

```text
http://127.0.0.1:3000/projects/file%3Ap-da2c16a6ee9440d6ad52cb402ead88a0/write?chapter=142
```

Verify the project shell and 142-entry directory appear without waiting for all bodies, chapter 142 renders, switching to chapter 141 requests and renders only that chapter, and returning to the project overview is fast.

- [ ] **Step 6: Review final diff and commit any verification-only correction**

```powershell
git diff --check
git status --short
```

Do not stage `data/continuation-imports/` or exported novel runtime data. If a correction was required, stage only source/test files and commit it with a focused `fix:` message.
