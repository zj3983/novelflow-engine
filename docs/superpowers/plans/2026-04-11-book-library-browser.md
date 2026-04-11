# Book Library Browser and Workbench History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a left-sidebar directory browser that shows imported source-book files plus workbench-generated chapter history, and lets the user click any item to load it into the current workbench context.

**Architecture:** Keep the existing workbench layout and add one focused browser surface in the left sidebar. The backend will expose a new catalog endpoint that groups source-book documents, state/projection files, and runtime chapter artifacts into clickable items with content previews. The frontend will render that catalog together with the live workbench history list, and clicking any item will hydrate the current draft, chapter preview, or selected history chapter without navigating away.

**Tech Stack:** FastAPI, Pydantic, Python filesystem I/O, Next.js 14, React 18, TypeScript, Playwright, pytest.

---

### Task 1: Build the source-book catalog API

**Files:**
- Create: `packages/story_core/book_browser.py`
- Modify: `apps/api/routes/book_import.py`
- Modify: `tests/api/test_book_import_routes.py`
- Create: `tests/fixtures/book-import-sample/state/manifest.json`
- Create: `tests/fixtures/book-import-sample/state/chapter_summaries.json`
- Create: `tests/fixtures/book-import-sample/runtime/chapter-0001.context.json`
- Create: `tests/fixtures/book-import-sample/runtime/chapter-0001.intent.md`
- Create: `tests/fixtures/book-import-sample/runtime/chapter-0001.rule-stack.yaml`
- Create: `tests/fixtures/book-import-sample/runtime/chapter-0001.trace.json`

- [ ] **Step 1: Write the failing test**

```python
def test_book_import_catalog_groups_source_docs_state_and_runtime(tmp_path: Path):
    (tmp_path / "state").mkdir()
    (tmp_path / "runtime").mkdir()
    _write(tmp_path / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(tmp_path / "current_focus.md", "FOCUS: Open with the first clue.\n")
    _write(tmp_path / "author_intent.md", "INTENT: Keep the opening grounded.\n")
    _write(tmp_path / "character_matrix.md", "| Name | Role |\n| --- | --- |\n| Lin Yue | investigator |\n")
    _write(tmp_path / "state" / "manifest.json", '{"schemaVersion": 2, "lastAppliedChapter": 1}')
    _write(tmp_path / "runtime" / "chapter-0001.intent.md", "# Chapter 1 intent\n\nLoad the first clue.\n")

    response = client.post("/book-import/catalog", json={"source_path": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(tmp_path)
    assert payload["sections"][0]["section_id"] == "source_docs"
    assert payload["sections"][1]["section_id"] == "source_state"
    assert payload["sections"][2]["section_id"] == "runtime_chapters"
    assert payload["sections"][0]["items"][0]["filename"] == "author_intent.md"
    assert payload["sections"][2]["items"][0]["title"] == "Chapter 1"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/api/test_book_import_routes.py::test_book_import_catalog_groups_source_docs_state_and_runtime -q`
Expected: FAIL because `/book-import/catalog` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
@router.post("/book-import/catalog")
def catalog(payload: BookImportRequest) -> BookBrowserCatalogResponse:
    base = _resolve_source_dir(payload.source_path)
    result = build_book_browser_catalog(base)
    return result
```

Implement `build_book_browser_catalog()` in `packages/story_core/book_browser.py` so it:
- reuses `scan_book_folder()` for the source document contents,
- groups items into `source_docs`, `source_state`, and `runtime_chapters`,
- includes content previews for each clickable item,
- extracts chapter numbers and display titles from `runtime/chapter-*.{md,json,yaml}` files,
- and returns a JSON-friendly response model.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/api/test_book_import_routes.py::test_book_import_catalog_groups_source_docs_state_and_runtime -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/book_browser.py apps/api/routes/book_import.py tests/api/test_book_import_routes.py tests/fixtures/book-import-sample/state tests/fixtures/book-import-sample/runtime
git commit -m "feat(api): add book library catalog endpoint"
```

### Task 2: Add the sidebar directory browser and preview loader

**Files:**
- Create: `apps/web/components/BookLibraryBrowser.tsx`
- Modify: `apps/web/components/BookImportPanel.tsx`
- Modify: `apps/web/components/StorySidebar.tsx`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/tests/story-workbench.spec.ts`
- Modify: `tests/e2e/book-import-entry.spec.ts`

- [ ] **Step 1: Write the failing test**

```typescript
test("book library browser shows source docs and workbench history", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("目录浏览器", { exact: true })).toBeVisible();
  await expect(page.getByText("源书目录", { exact: true })).toBeVisible();
  await expect(page.getByText("工作台历史", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "author_intent.md", exact: true }).click();
  await expect(page.getByText("预览内容", { exact: true })).toBeVisible();
  await expect(page.getByText(/作者意图|INTENT/)).toBeVisible();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test:e2e -- tests/story-workbench.spec.ts --workers=1 --trace=off`
Expected: FAIL because the directory browser and preview panel do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
export function BookLibraryBrowser({
  catalog,
  history,
  selectedItem,
  onSelectSourceItem,
  onSelectHistoryChapter,
}: Props) {
  return (
    <section className="library-browser">
      <button type="button">目录浏览器</button>
      <div>
        <h3>源书目录</h3>
        <h3>工作台历史</h3>
      </div>
    </section>
  );
}
```

Wire the browser into `StorySidebar.tsx` and `page.tsx` so that:
- clicking a source document sets a preview selection,
- clicking a source state/runtime chapter sets a preview selection,
- clicking a workbench history chapter updates `selectedChapter`,
- the right panel shows the selected item content instead of only the current chapter bundle,
- and source document clicks can copy `volume_outline.md` / `current_focus.md` / `character_matrix.md` into the existing workbench draft fields with explicit labels.

Add API helpers in `apps/web/lib/api.ts` for:
- `fetchBookLibraryCatalog(sourcePath: string)`
- `BookLibraryCatalogResponse`
- `BookLibrarySection`
- `BookLibraryItem`

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm run build && npm run test:e2e -- tests/story-workbench.spec.ts --workers=1 --trace=off && npx playwright test D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/e2e/book-import-entry.spec.ts --workers=1 --trace=off`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/BookLibraryBrowser.tsx apps/web/components/BookImportPanel.tsx apps/web/components/StorySidebar.tsx apps/web/app/page.tsx apps/web/lib/api.ts apps/web/app/globals.css apps/web/tests/story-workbench.spec.ts tests/e2e/book-import-entry.spec.ts
git commit -m "feat(web): add directory browser for source and history"
```

### Task 3: Polish loading, selection, and regression coverage

**Files:**
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/components/BookLibraryBrowser.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`
- Modify: `tests/e2e/book-import-entry.spec.ts`
- Modify: `tests/api/test_book_import_routes.py`

- [ ] **Step 1: Write the failing test**

```typescript
test("clicking a history chapter loads that chapter into the preview", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "生成下一章", exact: true }).click();
  await expect(page.getByText("章节历史", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /查看第 1 章/ }).click();
  await expect(page.getByText(/第 1 章/)).toBeVisible();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test:e2e -- tests/story-workbench.spec.ts --workers=1 --trace=off`
Expected: FAIL because chapter-history selection is not wired yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
const [selectedLibraryItem, setSelectedLibraryItem] = useState<BookLibrarySelection | null>(null);
```

Add small, explicit selection labels and keep the preview state in one place so both source-doc clicks and history-chapter clicks use the same renderer.

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/api/test_book_import_routes.py -q && npm run build && npm run test:e2e -- tests/story-workbench.spec.ts --workers=1 --trace=off`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/app/page.tsx apps/web/components/BookLibraryBrowser.tsx apps/web/tests/story-workbench.spec.ts tests/e2e/book-import-entry.spec.ts tests/api/test_book_import_routes.py
git commit -m "test(web): cover directory browser selection flow"
```

## Self-Review

**Spec coverage**
- Source-book docs browsing: Task 1 and Task 2.
- Source state/runtime chapter artifacts: Task 1 and Task 2.
- Workbench-generated history browsing: Task 2 and Task 3.
- Click-to-load behavior: Task 2 and Task 3.
- Browser entry visibility: Task 2.

**Placeholder scan**
- No TBD/TODO placeholders remain.
- Every task names concrete files and has a concrete command.

**Type consistency**
- `BookBrowserCatalogResponse`, `BookLibrarySection`, `BookLibraryItem`, and `BookLibrarySelection` are introduced once and reused consistently.
- The browser component and page state both use the same selection model.
