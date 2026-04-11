# Book Import Pre-Read and Start Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept quoted file paths or single-file paths in the import panel, auto-discover all readable book materials, let the director pre-read the import before creation, and add a one-click `载入并开始` action that starts chapter generation immediately after import.

**Architecture:** Normalize import paths in both the API and the browser before any scan happens. Expand the book scanner to walk the whole book directory, recognize additional text-like materials, and feed those into the browser catalog instead of only the canonical five markdown files. Carry the import pre-read forward from bootstrap so the sidebar can show what the director saw, then let the import panel chain `bootstrap -> load draft -> first generation` when the user presses `载入并开始`. The story engine itself stays unchanged except for consuming the imported draft in the usual first-story creation path.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, TypeScript, React, Playwright, pytest.

---

### Task 1: Normalize import paths and broaden material discovery

**Files:**
- Modify: `apps/api/routes/book_import.py`
- Modify: `packages/story_core/book_import.py`
- Modify: `apps/web/components/BookImportPanel.tsx`
- Test: `tests/api/test_book_import_routes.py`

- [ ] **Step 1: Write the failing tests**

Add API coverage for two path cases:

```python
def test_book_import_scan_accepts_quoted_file_path_and_normalizes_to_parent_dir(tmp_path: Path):
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    _write(story_dir / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(story_dir / "current_focus.md", "FOCUS: Open with the first clue.\n")

    response = client.post("/book-import/scan", json={"source_path": f'"{story_dir / "story_bible.md"}"'})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(story_dir)
```

And a second case for a plain file path:

```python
def test_book_import_bootstrap_accepts_file_path_and_uses_parent_folder(tmp_path: Path):
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    _write(story_dir / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(story_dir / "current_focus.md", "FOCUS: Open with the first clue.\n")

    response = client.post("/book-import/bootstrap", json={"source_path": str(story_dir / "volume_outline.md")})

    assert response.status_code == 200
    assert response.json()["report"]["source_path"] == str(story_dir)
```

Also add a discovery test that proves extra files are recognized, not ignored:

```python
def test_book_import_catalog_recognizes_extra_text_materials(tmp_path: Path):
    _write(tmp_path / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(tmp_path / "current_focus.md", "FOCUS: Open with the first clue.\n")
    _write(tmp_path / "notes.txt", "Director note: keep the witness hidden.\n")
    _write(tmp_path / "sidecar.yaml", "theme: noir\n")

    response = client.post("/book-import/catalog", json={"source_path": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert any(
        item["filename"] == "notes.txt"
        for section in payload["sections"]
        for item in section["items"]
    )
```

- [ ] **Step 2: Run the tests and confirm the current behavior fails**

Run:

```bash
pytest tests/api/test_book_import_routes.py -q
```

Expected: at least one of the new path-normalization tests should fail because the API currently treats a file path as a file, not its parent directory, and the catalog still only recognizes the old canonical file set.

- [ ] **Step 3: Implement minimal normalization and discovery**

Add a backend helper that:

1. strips wrapping quotes from the incoming path string
2. resolves the path without requiring an existing directory first
3. if the resolved path is a file, uses `path.parent` as the book root
4. keeps the original file path only for reporting/debugging

Update the scanner to walk the directory and include additional readable materials such as:
- `.md`
- `.txt`
- `.json`
- `.yaml`
- `.yml`

Keep the canonical required-file checks intact, but do not hide extra readable files from the catalog.

Update `BookImportPanel` to normalize the input before calling scan/bootstrap so the UI mirrors backend behavior instead of surprising the user.

- [ ] **Step 4: Re-run the targeted tests**

Run:

```bash
pytest tests/api/test_book_import_routes.py -q
```

Expected: all book import route tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/routes/book_import.py packages/story_core/book_import.py apps/web/components/BookImportPanel.tsx tests/api/test_book_import_routes.py
git commit -m "feat(book-import): normalize paths and discover extra materials"
```

### Task 2: Add director pre-read and a one-click `载入并开始` flow

**Files:**
- Modify: `packages/story_core/book_import.py`
- Modify: `apps/api/routes/book_import.py`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/components/BookImportPanel.tsx`
- Modify: `apps/web/components/StorySidebar.tsx`
- Modify: `apps/web/app/page.tsx`
- Test: `tests/e2e/story-workbench.spec.ts`

- [ ] **Step 1: Write the failing integration test**

Add an E2E case that:

1. opens the workbench
2. pastes a book folder path
3. clicks `校验目录`
4. sees a `导演预读` block appear in the import panel
5. clicks `载入并开始`
6. sees the outline/draft update and the first chapter start generating without a second manual click

Example assertion shape:

```ts
await page.getByRole("button", { name: "载入并开始" }).click();
await expect(page.getByText("导演预读", { exact: true })).toBeVisible();
await expect(page.getByText("绔犺妭鑽夌", { exact: true })).toBeVisible();
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
npm run test:e2e -- tests/story-workbench.spec.ts --workers=1 --trace=off
```

Expected: the new assertions fail because the UI does not yet expose a start button or a visible director pre-read section.

- [ ] **Step 3: Implement the bootstrap summary as a director pre-read**

Use the bootstrap summary as the imported director pre-read, but make it explicit in the UI:
- show it in the import panel as `导演预读`
- keep the original outline editable
- keep the current character seeding behavior

Thread a new callback through the sidebar/import panel so the user can press `载入并开始` and immediately call the existing first-generation path after bootstrap succeeds.

Keep the flow deterministic:
1. bootstrap loads the draft into the sidebar
2. the draft is committed into the parent page state
3. the first generation uses the newly loaded outline/characters

- [ ] **Step 4: Re-run the E2E test**

Run:

```bash
npm run test:e2e -- tests/story-workbench.spec.ts --workers=1 --trace=off
```

Expected: the new one-click start flow passes and the import panel visibly shows the director pre-read.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/book_import.py apps/api/routes/book_import.py apps/web/lib/api.ts apps/web/components/BookImportPanel.tsx apps/web/components/StorySidebar.tsx apps/web/app/page.tsx tests/e2e/story-workbench.spec.ts
git commit -m "feat(book-import): add director pre-read and start flow"
```

### Task 3: Surface the richer catalog in the browser and keep regression coverage tight

**Files:**
- Modify: `packages/story_core/book_browser.py`
- Modify: `apps/web/components/BookLibraryBrowser.tsx`
- Modify: `tests/api/test_book_import_routes.py`
- Modify: `tests/e2e/story-workbench.spec.ts`

- [ ] **Step 1: Write the failing catalog/browser tests**

Add a backend assertion that extra files are visible in the catalog, not just the canonical markdown files:

```python
def test_book_import_catalog_exposes_extra_materials(tmp_path: Path):
    _write(tmp_path / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(tmp_path / "current_focus.md", "FOCUS: Open with the first clue.\n")
    _write(tmp_path / "notes.txt", "Director note: watch the witness.\n")

    response = client.post("/book-import/catalog", json={"source_path": str(tmp_path)})

    payload = response.json()
    assert any(item["filename"] == "notes.txt" for section in payload["sections"] for item in section["items"])
```

Also add a browser assertion that an extra item can be clicked and loaded into the preview.

- [ ] **Step 2: Run the tests and confirm the current browser grouping is incomplete**

Run:

```bash
pytest tests/api/test_book_import_routes.py -q
```

and

```bash
npm run test:e2e -- tests/story-workbench.spec.ts --workers=1 --trace=off
```

Expected: the new coverage fails until the browser groups additional readable files and exposes them in a clickable section.

- [ ] **Step 3: Implement the browser grouping**

Update the catalog builder so the browser can show:
- canonical source docs
- extra recognized notes/materials
- state files
- runtime artifacts

Keep the current click-to-load behavior:
- markdown docs should still populate the outline/character fields when appropriate
- history artifacts should still jump to the corresponding chapter

- [ ] **Step 4: Re-run the browser and API regression suites**

Run:

```bash
pytest tests/api/test_book_import_routes.py -q
npm run build
npm run test:e2e -- tests/story-workbench.spec.ts --workers=1 --trace=off
```

Expected: all three commands pass.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/book_browser.py apps/web/components/BookLibraryBrowser.tsx tests/api/test_book_import_routes.py tests/e2e/story-workbench.spec.ts
git commit -m "feat(book-browser): surface extra materials and history"
```
