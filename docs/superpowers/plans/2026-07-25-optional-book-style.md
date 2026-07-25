# Optional Book Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the universal plain-prose fallback with an optional five-choice book style that is saved per project and only enters prompts when selected.

**Architecture:** Add one small backend style-profile module as the source of truth. Persist the selected label in `world_blueprint.writing_style`, synchronize it to `StoryState.style`, and have prompt builders request a short profile only for recognized selections. Keep prose correctness checks separate from optional style selection.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest, Next.js, React, TypeScript, Playwright.

---

### Task 1: Define optional style profiles

**Files:**
- Create: `packages/story_core/book_style.py`
- Test: `tests/story_core/test_book_style.py`

- [ ] **Step 1: Write failing profile tests**

Test that `normalize_book_style("")` and legacy values such as `"白描、现代中文"` return an empty string, while the five supported labels remain valid. Test that `book_style_prompt("")` is empty and `book_style_prompt("幽默")` is one concise sentence without genre or plot rules.

- [ ] **Step 2: Run the test and verify failure**

Run: `pytest -q tests/story_core/test_book_style.py`
Expected: FAIL because `packages.story_core.book_style` does not exist.

- [ ] **Step 3: Implement the source of truth**

Create `BOOK_STYLE_OPTIONS = ("幽默", "轻松", "热血", "冷峻", "细腻")`, `normalize_book_style(value) -> str`, and `book_style_prompt(value) -> str`. Each prompt must describe expression only and remain under 80 Chinese characters.

- [ ] **Step 4: Run the profile tests**

Run: `pytest -q tests/story_core/test_book_style.py`
Expected: PASS.

### Task 2: Persist the optional project selection

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/stories.py`
- Modify: `apps/api/storage.py`
- Modify: `apps/web/lib/api.ts`
- Test: `tests/story_core/test_file_project_store.py`
- Test: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing persistence tests**

Cover saving `world_blueprint.writing_style="幽默"`, clearing it with an empty string, rejecting unknown values, and synchronizing the accepted label to `state.style` or the active database story.

- [ ] **Step 2: Run focused persistence tests**

Run: `pytest -q tests/story_core/test_file_project_store.py tests/api/test_story_routes.py -k "writing_style or book_style"`
Expected: FAIL because the field is not validated or synchronized.

- [ ] **Step 3: Implement validation and synchronization**

Use `normalize_book_style` at both file-project and database update boundaries. Preserve the key with `""` when cleared so an old state value cannot reappear. Remove `_default_story_style_for_genre` and stop assigning `"白描、现代中文"` when no style was selected.

- [ ] **Step 4: Add the frontend API type**

Add `writing_style?: string` to `ImportedWorldBlueprint`; do not add a second style storage field.

- [ ] **Step 5: Run persistence tests**

Run: `pytest -q tests/story_core/test_file_project_store.py tests/api/test_story_routes.py -k "writing_style or book_style"`
Expected: PASS.

### Task 3: Make prompts respect the selection

**Files:**
- Modify: `packages/story_core/style_coach.py`
- Modify: `packages/story_core/writing_taskbook.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_style_coach.py`
- Test: `tests/story_core/test_writer_prompt_method.py`
- Test: `tests/story_core/test_writing_taskbook.py`

- [ ] **Step 1: Write failing prompt tests**

Assert that an empty or legacy style produces no style guidance and no `通用白描`, `整体用白描`, or `番茄白话风` text. Assert that `幽默` produces only the short humor profile while retaining separate genre facts and dialogue correctness rules.

- [ ] **Step 2: Run focused prompt tests**

Run: `pytest -q tests/story_core/test_style_coach.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_writing_taskbook.py`
Expected: FAIL on the current generic plain-prose fallback.

- [ ] **Step 3: Remove the universal fallback**

Make `build_style_guidance` accept the selected style and return `{}` when unselected. Remove `GENERIC_STYLE_CONTRACT`, `GAME_STYLE_CONTRACT`, `generic_plain_prose`, and universal plain-prose wording from writer prompt assembly. Keep factual safeguards, modern Chinese sentence completeness, continuity, and genre rules because they are correctness constraints rather than a selected style.

- [ ] **Step 4: Inject only the selected profile**

When a supported style is selected, add one `表达风格：...` line from `book_style_prompt`. Do not repeat that line in the taskbook and writer craft sections.

- [ ] **Step 5: Run focused prompt tests**

Run: `pytest -q tests/story_core/test_style_coach.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_writing_taskbook.py`
Expected: PASS.

### Task 4: Add the simple settings selector

**Files:**
- Modify: `apps/web/app/projects/[id]/settings/page.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Add a failing settings-page test**

Test that the selector contains `未选择、幽默、轻松、热血、冷峻、细腻`, initializes from `world_blueprint.writing_style`, saves through `updateProject`, and can clear the selection.

- [ ] **Step 2: Run the focused frontend test**

Run: `cd apps/web && npx playwright test tests/story-workbench.spec.ts -g "文风选择"`
Expected: FAIL because the selector does not exist.

- [ ] **Step 3: Implement the selector**

Add one compact select section beneath novel type. Save by merging `writing_style` into the existing world blueprint. Show only a short success or failure message.

- [ ] **Step 4: Run frontend checks**

Run: `cd apps/web && npx playwright test tests/story-workbench.spec.ts -g "文风选择"`
Expected: PASS.

Run: `cd apps/web && npm run build`
Expected: PASS.

### Task 5: Verify the integrated behavior

**Files:**
- Modify only if verification exposes a defect in the files above.

- [ ] **Step 1: Run backend tests**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Inspect prompt previews**

For one project without a selected style, verify the writer prompt contains none of the removed fallback labels. Select `幽默`, fetch the preview again, and verify one concise humor line appears.

- [ ] **Step 3: Run the frontend build**

Run: `cd apps/web && npm run build`
Expected: PASS with no TypeScript or route errors.
