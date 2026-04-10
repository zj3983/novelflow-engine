# Book Folder Import Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a visible sidebar entry that lets the user paste a local story folder path, validate that folder, and bootstrap the existing workbench draft from the parsed story files.

**Architecture:** Keep the current workbench flow intact and add a thin import layer in front of it. A new core parser reads the on-disk book folder, produces a structured import report plus a bootstrap draft, and the API exposes that data to the web app. The web UI gets a dedicated left-sidebar panel so the entry is obvious and the result can be used immediately without changing the rest of the generator.

**Tech Stack:** FastAPI, Pydantic, Next.js App Router, React state, Playwright, pytest.

---

## File Map

- `packages/story_core/book_import.py`
  - Pure parsing and normalization for local story folders.
  - Produces the import report and a bootstrap draft for the workbench.
- `apps/api/routes/book_import.py`
  - HTTP endpoints for scanning and bootstrapping a folder.
- `apps/api/main.py`
  - Registers the new router.
- `apps/web/lib/api.ts`
  - Request/response types plus client helpers for the new endpoints.
- `apps/web/components/BookImportPanel.tsx`
  - Visible left-sidebar entry for folder path input, validation, and bootstrap.
- `apps/web/components/StorySidebar.tsx`
  - Mounts the new import panel above the existing settings sections.
- `apps/web/app/page.tsx`
  - Stores import results, pushes bootstrap data into the current draft, and surfaces errors.
- `apps/web/app/globals.css`
  - Styles for the new import panel and status blocks.
- `tests/story_core/test_book_import.py`
  - Parser/unit coverage.
- `tests/api/test_book_import_routes.py`
  - HTTP coverage for scan/bootstrap endpoints.
- `tests/e2e/book-import-entry.spec.ts`
  - Browser coverage for the visible entry and bootstrap flow.
- `tests/fixtures/book-import-sample/`
  - Small fixture book folder used by the browser test.

---

### Task 1: Add the folder parser and bootstrap schema

**Files:**
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/book_import.py`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_book_import.py`

- [ ] **Step 1: Write the failing test**

Add a parser test that builds a temporary folder with these files:

- `author_intent.md`
- `book_rules.md`
- `story_bible.md`
- `volume_outline.md`
- `current_focus.md`
- `current_state.md`
- `pending_hooks.md`
- `subplot_board.md`
- `character_matrix.md`

Assert that scanning the folder returns:

- `exists == true`
- `missing_required_files == []`
- `can_bootstrap == true`
- `outline` includes the current focus text
- `warnings` is empty for a complete folder

Add a second test that omits `current_focus.md` and `volume_outline.md` and asserts:

- `missing_required_files` contains both names
- `can_bootstrap == false`
- the report still preserves the readable text from the files that do exist

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
pytest tests/story_core/test_book_import.py -q
```

Expected: FAIL because `scan_book_folder()` and the report models do not exist yet.

- [ ] **Step 3: Implement the parser**

Implement a small parser in `packages/story_core/book_import.py` that:

- accepts an absolute folder path
- reads the canonical story files listed above
- marks `current_focus.md` and `volume_outline.md` as required
- treats the state/supporting files as optional but reported when missing
- extracts a bootstrap draft with:
  - `outline` from `current_focus.md` plus a condensed `volume_outline.md`
  - `characters` from `character_matrix.md` when present
  - a `source_path`
  - a `summary` describing the import target

Keep the output JSON-serializable and deterministic so both the API and the browser test can use it.

- [ ] **Step 4: Run the test and verify it passes**

Run:

```bash
pytest tests/story_core/test_book_import.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/packages/story_core/book_import.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/story_core/test_book_import.py
git commit -m "feat(core): add book folder import parser"
```

### Task 2: Expose scan/bootstrap endpoints

**Files:**
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/api/routes/book_import.py`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/api/main.py`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/api/test_book_import_routes.py`

- [ ] **Step 1: Write the failing test**

Add route tests for:

1. `POST /book-import/scan`
   - body: `{"source_path": "<temp fixture folder>"}`
   - expect a 200 response with:
     - `exists == true`
     - `can_bootstrap == true`
     - `missing_required_files == []`

2. `POST /book-import/bootstrap`
   - body: `{"source_path": "<temp fixture folder>"}`
   - expect a 200 response with:
     - `draft.outline` populated
     - `draft.characters` populated or empty but valid
     - `report.can_bootstrap == true`

3. invalid path handling
   - body: `{"source_path": "Z:/does/not/exist"}`
   - expect a 404 or 400 response with a clear error message

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
pytest tests/api/test_book_import_routes.py -q
```

Expected: FAIL because the endpoints are not registered yet.

- [ ] **Step 3: Implement the API**

Create a new router that:

- calls the parser from `packages/story_core/book_import.py`
- returns a `BookImportReport` for scan
- returns a `BookImportBootstrap` payload for bootstrap
- raises a clear error when the folder does not exist or required files are missing

Register the router in `apps/api/main.py` so the web app can call it without changing the rest of the story routes.

- [ ] **Step 4: Run the test and verify it passes**

Run:

```bash
pytest tests/api/test_book_import_routes.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/api/routes/book_import.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/api/main.py D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/api/test_book_import_routes.py
git commit -m "feat(api): add book import scan and bootstrap endpoints"
```

### Task 3: Add the visible sidebar entry and wire bootstrap into the workbench

**Files:**
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/components/BookImportPanel.tsx`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/components/StorySidebar.tsx`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/app/page.tsx`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/lib/api.ts`
- Modify: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/app/globals.css`

- [ ] **Step 1: Write the failing test**

Add a front-end test that renders the sidebar and checks for:

- a visible `导入书籍目录` section
- a path input with a stable label such as `书籍目录路径`
- a `校验目录` button
- a `载入到工作台` button

The test should also assert that when bootstrap succeeds, the workbench draft outline updates to the imported text.

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
npm run test:e2e -- tests/e2e/book-import-entry.spec.ts --workers=1 --trace=off
```

Expected: FAIL because the panel and API wiring do not exist yet.

- [ ] **Step 3: Build the panel and wire state**

Create `BookImportPanel.tsx` with:

- a local path input
- a scan button
- a bootstrap button
- a report area that shows:
  - path status
  - required file coverage
  - missing file names
  - bootstrap readiness

In `StorySidebar.tsx`, render the panel above the existing settings blocks so the entry is visible immediately on page load.

In `page.tsx`, add state for:

- the current import path
- the latest scan report
- the latest bootstrap result
- any import error

When bootstrap succeeds, populate the existing draft state from the returned bootstrap payload so the current workbench can immediately generate from the imported book data.

In `api.ts`, add the request and response types plus client helpers for scan/bootstrap.

In `globals.css`, add a compact but obvious card treatment so the entry does not look like a hidden advanced setting.

- [ ] **Step 4: Run the test and verify it passes**

Run:

```bash
npm run test:e2e -- tests/e2e/book-import-entry.spec.ts --workers=1 --trace=off
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/components/BookImportPanel.tsx D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/components/StorySidebar.tsx D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/app/page.tsx D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/lib/api.ts D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/apps/web/app/globals.css
git commit -m "feat(web): add visible book import entry"
```

### Task 4: Add fixture coverage and verify the whole flow

**Files:**
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/fixtures/book-import-sample/author_intent.md`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/fixtures/book-import-sample/book_rules.md`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/fixtures/book-import-sample/story_bible.md`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/fixtures/book-import-sample/volume_outline.md`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/fixtures/book-import-sample/current_focus.md`
- Create: `D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/e2e/book-import-entry.spec.ts`

- [ ] **Step 1: Write the failing test**

Create a small fixture folder inside the repo so the browser test can run without depending on the user’s private filesystem.

The E2E test should:

- open the workbench
- verify `导入书籍目录` is visible
- fill the fixture path
- click `校验目录`
- verify the report says the folder can be bootstrapped
- click `载入到工作台`
- verify the outline field now contains fixture text from `current_focus.md` or `volume_outline.md`

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
npm run test:e2e -- tests/e2e/book-import-entry.spec.ts --workers=1 --trace=off
```

Expected: FAIL until the fixture and end-to-end wiring are present.

- [ ] **Step 3: Add the fixture and finalize the flow**

Add the minimal fixture files so the E2E test can validate the import path end to end. Keep the fixture tiny and deterministic; it only needs enough content to prove the entry works.

Then run the full regression set:

```bash
pytest -q
npm run build
npm run test:e2e -- tests/e2e/book-import-entry.spec.ts --workers=1 --trace=off
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/fixtures/book-import-sample D:/xiaoshuofish/.worktrees/novel-autogrowth-engine/tests/e2e/book-import-entry.spec.ts
git commit -m "test(e2e): cover book import entry flow"
```
