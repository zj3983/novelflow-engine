# Global Novel Type Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a global novel type library that users can view, add, and edit, and make project creation, project settings, simulation, and writing resolve the same current type definitions.

**Architecture:** Keep immutable built-in Python plugins as recovery defaults, then overlay user edits and custom types from one global JSON file. Expose the merged library through FastAPI and have the frontend load it through a shared hook. Convert merged records back into `GenrePlugin` objects at runtime so existing prompt, rulebook, and quality code keeps one interface.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, atomic JSON persistence, Next.js 14, React 18, TypeScript, pytest, Playwright.

---

### Task 1: Editable type model and persistent library

**Files:**
- Create: `packages/story_core/novel_type_library.py`
- Modify: `packages/story_core/genre_plugins.py`
- Test: `tests/story_core/test_novel_type_library.py`

- [ ] **Step 1: Write failing model, overlay, persistence, and built-in protection tests**

Cover these exact behaviors: built-ins are returned with `builtin=True`; editing a built-in preserves its ID; a custom type persists after constructing a fresh library; duplicate IDs fail; built-ins cannot be deleted; custom types can be deleted; `resolve_genre_plugin("xuanhuan")` contains an edited core promise.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `python -m pytest tests/story_core/test_novel_type_library.py -q`

Expected: collection fails because `novel_type_library` does not exist.

- [ ] **Step 3: Implement the canonical editable record and atomic JSON store**

Define `NovelTypeRecord` with `id`, `name`, `description`, `keywords`, `core_promises`, `ledger_fields`, `rulebook`, `quality_checks`, `trope_templates`, and `builtin`. Normalize all `RULEBOOK_FIELDS`, reject blank IDs/names, and use `NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH` or `~/.novel-autogrowth-engine/novel_types.json`. Persist only overrides and custom records through a temporary file plus `os.replace`.

Expose:

```python
def list_novel_types() -> list[NovelTypeRecord]: ...
def get_novel_type(type_id: str) -> NovelTypeRecord | None: ...
def create_novel_type(payload: NovelTypeRecord | dict) -> NovelTypeRecord: ...
def update_novel_type(type_id: str, payload: NovelTypeRecord | dict) -> NovelTypeRecord: ...
def delete_novel_type(type_id: str) -> None: ...
def resolve_genre_plugin(type_id: str) -> GenrePlugin | None: ...
```

- [ ] **Step 4: Make genre selection resolve the live library**

Replace static registry matching in `select_genre_plugins` with `get_novel_type`/`resolve_genre_plugin`. Keep `EASTERN_FANTASY` as an internal shared plugin for `xuanhuan` and `xianxia`; do not expose it as a selectable type.

- [ ] **Step 5: Run focused and genre regression tests**

Run: `python -m pytest tests/story_core/test_novel_type_library.py tests/story_core/test_genre_plugins.py tests/story_core/test_novel_type_catalog.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

Commit message: `feat: add persistent global novel type library`

### Task 2: Novel type management API

**Files:**
- Create: `apps/api/routes/novel_types.py`
- Modify: `apps/api/main.py`
- Test: `tests/api/test_novel_type_routes.py`

- [ ] **Step 1: Write failing CRUD route tests**

Use a temporary `NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH`. Assert `GET /novel-types` returns built-ins, `POST` creates a custom type, `PUT` edits built-in content without changing ID, `DELETE` rejects built-ins, and deleting an unused custom type succeeds.

- [ ] **Step 2: Run the API test and confirm 404 failures**

Run: `python -m pytest tests/api/test_novel_type_routes.py -q`

Expected: requests fail because routes are missing.

- [ ] **Step 3: Implement strict request models and CRUD routes**

Use `ConfigDict(extra="forbid")`. Return `409` for duplicate IDs, built-in deletion, or a custom type still referenced by a SQLite/file project; return `404` for unknown IDs and `422` for invalid fields.

- [ ] **Step 4: Add project usage detection**

Check `apps.api.routes.stories.store.list_projects()` and file projects below `NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR` (or `data/exported-projects`) for `world_blueprint.genre_plugin_ids`. Return the referencing project IDs in the conflict detail.

- [ ] **Step 5: Register the router and run API tests**

Run: `python -m pytest tests/api/test_novel_type_routes.py tests/api/test_file_project_creation_routes.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

Commit message: `feat: expose novel type management api`

### Task 3: Shared frontend API and global management page

**Files:**
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/lib/novelTypeLibrary.ts`
- Create: `apps/web/app/novel-types/page.tsx`
- Modify: `apps/web/components/ws/WorkspaceShell.tsx`
- Modify: `apps/web/app/globals.css`
- Test: `apps/web/tests/novel-types.spec.ts`

- [ ] **Step 1: Write a failing Playwright management flow**

Mock `/novel-types`, open `/novel-types`, verify the global “小说类型” navigation item, inspect “网游升级”, edit a core promise and save, create a custom type, select it, then delete it. Assert request bodies contain structured arrays and rulebook fields rather than one long prompt string.

- [ ] **Step 2: Run the focused browser test and confirm failure**

Run: `playwright test apps/web/tests/novel-types.spec.ts`

Expected: route or heading is missing.

- [ ] **Step 3: Add API types and a single loader**

Define `NovelTypeDefinition` and `NovelTypeRulebook`, plus `listNovelTypes`, `createNovelType`, `updateNovelType`, and `deleteNovelType`. `novelTypeLibrary.ts` owns loading/error state so pages do not recreate fallback catalogs.

- [ ] **Step 4: Build the global page**

Use an unframed two-column work surface: a searchable type list on the left and the selected type editor on the right. Use textarea line lists for structured arrays, visible built-in/custom badges, disabled ID input for built-ins, and an explicit delete confirmation for custom types. On mobile, stack list above editor with no horizontal overflow.

- [ ] **Step 5: Add the global navigation item and responsive styles**

Place “小说类型” between “作品” and “配置”. Keep project-level navigation unchanged.

- [ ] **Step 6: Run browser test and production build**

Run: `playwright test apps/web/tests/novel-types.spec.ts`

Run: `npm run build`

Expected: focused test and build pass.

- [ ] **Step 7: Commit**

Commit message: `feat: add global novel type manager`

### Task 4: Make project selectors consume the global library

**Files:**
- Modify: `apps/web/app/projects/new/page.tsx`
- Modify: `apps/web/app/projects/[id]/settings/page.tsx`
- Modify: `apps/web/lib/novelTypes.ts`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Add failing selector synchronization tests**

Mock a custom type from `GET /novel-types`; assert it appears in both new-project and project-settings selectors. Assert the settings description comes from the API record.

- [ ] **Step 2: Replace hardcoded option reads with the shared loader**

Keep only label helpers needed for legacy data in `novelTypes.ts`. Both pages must show loading and API errors and must not silently substitute a second editable list.

- [ ] **Step 3: Run project workflow browser tests**

Run: `playwright test apps/web/tests/story-workbench.spec.ts --grep "novel type|小说类型|creates an inspiration novel"`

Expected: all selected tests pass.

- [ ] **Step 4: Commit**

Commit message: `refactor: use global novel types in project flows`

### Task 5: Runtime integration and final verification

**Files:**
- Modify: `packages/story_core/novel_type_catalog.py`
- Modify: `packages/story_core/file_project_creation.py`
- Modify: `packages/story_core/opening_directions.py`
- Modify: `packages/story_core/outline_planning_generation.py`
- Test: `tests/story_core/test_novel_type_runtime_integration.py`

- [ ] **Step 1: Write a failing edited-rule runtime test**

Persist an edited `xuanhuan` core promise and a custom type. Assert file project creation accepts both IDs, opening direction context uses the current description, outline generation uses current type content, and `plugin_prompt_guide` includes the edited promise.

- [ ] **Step 2: Route catalog lookups through the library**

Keep alias normalization in `novel_type_catalog.py`, but replace static option/description lookup at runtime with the merged library. Unknown IDs remain invalid; existing IDs remain stable.

- [ ] **Step 3: Run focused runtime tests**

Run: `python -m pytest tests/story_core/test_novel_type_runtime_integration.py tests/api/test_file_project_creation_routes.py -q`

Expected: all pass.

- [ ] **Step 4: Run full verification**

Run: `python -m pytest -q`

Run: `npm run build` from `apps/web`.

Run focused Playwright suites for `novel-types.spec.ts` and the project type selector tests. Inspect desktop and 390px screenshots for overflow and overlapping controls.

- [ ] **Step 5: Review, merge, and preserve unrelated work**

Run `git diff --check`, review changed call paths, merge `codex/global-novel-types` into `codex/novel-autogrowth-engine`, and do not stage or modify the unrelated config-page files in the main worktree.

- [ ] **Step 6: Commit**

Commit message: `feat: use editable novel types throughout writing flow`
