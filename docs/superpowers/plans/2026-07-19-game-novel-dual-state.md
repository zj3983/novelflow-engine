# Game Novel Dual State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `game_webnovel` 项目建立现实线与游戏线两套可追踪状态，让角色卡、写作包和章节同步按场景取用，且旧项目和非网游类型继续兼容。

**Architecture:** 保留通用人物档案和旧版 `game_panel` 作为兼容入口，在 `CharacterState` 与项目角色卡中增加可选的 `real_state`、`game_state` 两个命名空间。新增一个小型归一化模块负责旧字段映射、场景选择和状态合并；写作包只把当前场景需要的状态投影给正文模块，章节同步分别写入对应命名空间，不做现实到游戏或游戏到现实的隐式改写。网游页面显示并编辑两套状态，其他类型隐藏游戏状态。

**Tech Stack:** Python 3、Pydantic、FastAPI、pytest、Next.js/React、TypeScript。

---

### Task 1: 建立双状态数据模型和兼容归一化

**Files:**
- Create: `packages/story_core/dual_state.py`
- Modify: `packages/story_core/models.py:218-235,335-380`
- Modify: `packages/story_core/character_profiles.py:55-145`
- Test: `tests/story_core/test_dual_state.py`

- [x] **Step 1: Write failing tests for the public normalization contract**

```python
from packages.story_core.dual_state import normalize_dual_state, project_dual_state


def test_legacy_game_panel_is_mapped_to_game_state_current_without_losing_panel():
    card = {"name": "夜烬", "game_panel": {"game_id": "夜烬", "level": "Lv.1", "currency": "0铜币"}}
    normalized = normalize_dual_state(card, is_game_story=True)
    assert normalized["game_state"]["current"]["game_id"] == "夜烬"
    assert normalized["game_state"]["current"]["level"] == "Lv.1"
    assert normalized["game_panel"]["currency"] == "0铜币"


def test_non_game_story_does_not_create_game_state():
    card = {"name": "沈砚", "current_life_profile": {"occupation": "抄书"}}
    normalized = normalize_dual_state(card, is_game_story=False)
    assert "real_state" in normalized
    assert "game_state" not in normalized


def test_scene_projection_keeps_only_requested_line():
    card = {"name": "夜烬", "real_state": {"current": {"balance": "27.60元"}}, "game_state": {"current": {"level": "Lv.1"}}}
    assert project_dual_state(card, scene_kind="game") == {"game_state": {"current": {"level": "Lv.1"}}}
    assert project_dual_state(card, scene_kind="reality") == {"real_state": {"current": {"balance": "27.60元"}}}
```

- [x] **Step 2: Run the focused tests and verify the new API is absent**

Run: `pytest -q tests/story_core/test_dual_state.py`

Expected: FAIL with an import error for `packages.story_core.dual_state`.

- [x] **Step 3: Add typed state envelopes and normalization helpers**

Implement `dual_state.py` with these exact public functions:

```python
def normalize_dual_state(card: Mapping[str, Any], *, is_game_story: bool) -> dict[str, Any]: ...
def project_dual_state(card: Mapping[str, Any], *, scene_kind: str) -> dict[str, Any]: ...
def merge_state_change(card: Mapping[str, Any], *, line: str, change: Mapping[str, Any], chapter: int) -> dict[str, Any]: ...
```

Use `{ "current": {...}, "recent_changes": [...] }` as the envelope. Map legacy top-level real fields (`identity_profile`, `background_profile`, `current_life_profile`, `story_drive`) into `real_state.current`; map `game_panel` into `game_state.current`. Preserve the legacy fields in the returned card. `scene_kind` accepts only `game`, `reality`, or `transition`; `transition` returns both namespaces. `merge_state_change` updates only the selected namespace and appends a compact fact record containing `chapter` and `fact`.

Add optional `real_state: dict` and `game_state: dict` to `CharacterState`; leave `game_panel` unchanged for old JSON. Update `normalize_character_profile` to call the helper only when a caller explicitly supplies `is_game_story=True`; generic profile normalization must remain genre-neutral.

- [x] **Step 4: Run the focused tests and existing character tests**

Run: `pytest -q tests/story_core/test_dual_state.py tests/story_core/test_concrete_character_profiles.py tests/story_core/test_character_game_panel.py`

Expected: PASS, with the existing game-panel assertions unchanged.

- [x] **Step 5: Commit the model boundary**

```bash
git add packages/story_core/dual_state.py packages/story_core/models.py packages/story_core/character_profiles.py tests/story_core/test_dual_state.py
git commit -m "feat: add dual state character model"
```

### Task 2: Make project character cards and API persistence dual-state aware

**Files:**
- Modify: `apps/api/storage.py:336-380,1000-1060`
- Modify: `packages/story_core/file_project_store.py:2260-2305,2900-2980`
- Modify: `apps/api/routes/file_projects.py:482-495`
- Modify: `apps/web/lib/api.ts:500-540,1140-1165`
- Test: `tests/api/test_project_context_sync.py`
- Test: `tests/api/test_file_project_creation_routes.py`

- [x] **Step 1: Add failing persistence tests**

Extend the project-context tests with a game card containing both states. Assert that a load/save round trip preserves `real_state.current`, `game_state.current`, and legacy `game_panel`. Add a non-game project assertion that a character payload with no game fields remains free of a synthesized game namespace.

- [x] **Step 2: Run the new tests and capture the current failure**

Run: `pytest -q tests/api/test_project_context_sync.py tests/api/test_file_project_creation_routes.py`

Expected: FAIL because project-to-runtime synchronization currently copies only the old fields and `game_panel`.

- [x] **Step 3: Normalize profiles at the storage boundary**

In `_sync_project_character_profiles`, determine `is_game_story` from the project genre plugin IDs using the existing `game_webnovel` resolver. Normalize incoming profiles before merging them into `CharacterState`, and copy both `real_state` and `game_state` without replacing non-empty author-confirmed values. In `update_character`, accept both namespaces as ordinary JSON objects, validate their envelopes through `normalize_dual_state`, and keep the old `game_panel` mirror for compatibility.

- [x] **Step 4: Extend the API and TypeScript response types**

Add optional `real_state?: CharacterStateLayer` and `game_state?: CharacterStateLayer` to `StoryResponse.characters` and define `CharacterStateLayer` as `{ current?: Record<string, unknown>; recent_changes?: Array<{ chapter?: number; fact: string }> }`. The existing PUT route remains generic JSON; its response must include the normalized fields.

- [x] **Step 5: Run persistence and route tests**

Run: `pytest -q tests/api/test_project_context_sync.py tests/api/test_file_project_creation_routes.py tests/api/test_story_routes.py -k "project or character"`

Expected: PASS, including all legacy assertions for `game_panel`.

- [x] **Step 6: Commit persistence changes**

```bash
git add apps/api/storage.py apps/api/routes/file_projects.py apps/web/lib/api.ts packages/story_core/file_project_store.py tests/api/test_project_context_sync.py tests/api/test_file_project_creation_routes.py
git commit -m "feat: persist dual character states"
```

### Task 3: Scope the writing packet by scene line

**Files:**
- Modify: `packages/story_core/file_project_store.py:2307-2350,3262-3375`
- Modify: `packages/story_core/orchestrator.py:3613-3675,4140-4180`
- Modify: `packages/story_core/dual_state.py`
- Test: `tests/story_core/test_dual_state.py`
- Test: `tests/story_core/test_writing_packet.py`
- Test: `tests/api/test_story_routes.py`

- [x] **Step 1: Write failing writing-packet tests**

Add tests that create a `game_webnovel` project with a scene whose location/action is explicitly marked `line: game`, then assert the packet's character card contains `game_state` but not `real_state`. Add a reality scene assertion for the inverse and a transition scene assertion for both. Assert that the compact prompt preview contains the selected line only.

- [x] **Step 2: Run the packet tests and verify leakage**

Run: `pytest -q tests/story_core/test_writing_packet.py tests/api/test_story_routes.py -k "packet or writing"`

Expected: FAIL because `_writer_character_cards` currently calls `project_character_for_writer` without a scene line and the packet copies complete cards.

- [x] **Step 3: Add deterministic scene-line selection**

Implement `infer_scene_kind(scene_card, *, is_game_story)` in `dual_state.py`: honor an explicit `line`/`scene_line` value first; otherwise classify known game markers (`game`, `游戏`, `副本`, `任务`, `背包`, `等级`) as game and real-life markers (`reality`, `现实`, `出租屋`, `工作`, `房租`, `银行`) as reality; default to `transition` for a game novel and `reality` for other genres. Pass the selected kind from `writing_packet` into `_writer_character_cards`, and attach the projected state under `state_context` so the generic identity/personality card is still available without mixing the two lines.

- [x] **Step 4: Keep the writer prompt compact and explicit**

Change `_writer_character_section` to render `state_context` only when non-empty, with headings `现实状态` and `游戏状态`; do not render both for a single-line scene. Add one sentence for transition scenes: `这一段要写清楚现实动作如何影响游戏选择，不能凭空改变另一条线的数值。` Keep `game_panel` out of the new prompt projection unless an old card has no `game_state`, in which case use the normalized compatibility mirror.

- [x] **Step 5: Run packet, prompt, and API regression tests**

Run: `pytest -q tests/story_core/test_dual_state.py tests/story_core/test_writing_packet.py tests/story_core/test_writer_prompt_method.py tests/api/test_story_routes.py -k "packet or prompt or writing"`

Expected: PASS; existing prompt snapshots may change only where the new state headings replace the old full panel dump.

- [x] **Step 6: Commit packet scoping**

```bash
git add packages/story_core/dual_state.py packages/story_core/file_project_store.py packages/story_core/orchestrator.py tests/story_core/test_dual_state.py tests/story_core/test_writing_packet.py tests/story_core/test_writer_prompt_method.py tests/api/test_story_routes.py
git commit -m "feat: scope writing packets to story line"
```

### Task 4: Separate chapter synchronization for reality and game changes

**Files:**
- Modify: `packages/story_core/file_project_store.py:1423-1515,1659-1770`
- Modify: `packages/story_core/orchestrator.py:1760-1845`
- Modify: `packages/story_core/dual_state.py`
- Test: `tests/story_core/test_character_game_panel.py`
- Test: `tests/api/test_project_context_sync.py`

- [x] **Step 1: Add failing no-cross-write tests**

Create a card with a real balance of `27.60元` and game currency `0铜币`. Feed a chapter ledger containing game experience, HP, inventory, and game currency; assert only `game_state.current` and the legacy `game_panel` mirror change. Feed a chapter event explicitly marked `line: reality` with an income or payment fact; assert only `real_state.current` and its `recent_changes` change. Assert that a game reward never changes the real balance.

- [x] **Step 2: Run the focused tests and verify current cross-line behavior**

Run: `pytest -q tests/story_core/test_character_game_panel.py tests/api/test_project_context_sync.py`

Expected: FAIL for the new state assertions because ledger sync currently writes only the legacy panel and has no reality-state path.

- [x] **Step 3: Route game ledger updates through `merge_state_change`**

In `_sync_ledger_from_chapter_body` and `_sync_character_game_panels`, build one normalized game change from the parsed progression ledger and call `merge_state_change(..., line="game", ...)`. Keep the existing `game_panel` update exactly as a compatibility mirror. Do not infer reality balance changes from game currency, item drops, or experience.

- [x] **Step 4: Route explicit reality events through the reality namespace**

In `_sync_project_after_chapter`, consume only explicit chapter facts or ledger entries with `line` equal to `reality`/`transition` and a concrete real-world change field. Call `merge_state_change(..., line="reality", ...)`; transition events may update both only when each side has its own explicit change object. Do not treat prose mentions of money as a state mutation unless the chapter ledger records the event.

- [x] **Step 5: Run all synchronization tests**

Run: `pytest -q tests/story_core/test_character_game_panel.py tests/api/test_project_context_sync.py tests/story_core/test_file_project_store.py -k "sync or ledger or character"`

Expected: PASS, with the original five-gray-wolf/game-panel compatibility tests still green.

- [x] **Step 6: Commit separated synchronization**

```bash
git add packages/story_core/file_project_store.py packages/story_core/orchestrator.py packages/story_core/dual_state.py tests/story_core/test_character_game_panel.py tests/api/test_project_context_sync.py
git commit -m "fix: prevent cross-line character state updates"
```

### Task 5: Show and edit the two states in the character-card page

**Files:**
- Modify: `apps/web/lib/api.ts:500-540`
- Modify: `apps/web/app/projects/[id]/characters/page.tsx:180-360`
- Modify: `apps/web/app/projects/[id]/page.tsx:135-150`
- Modify: `apps/web/lib/worldDisplay.ts:1-140`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [x] **Step 1: Add a browser regression test for game and non-game cards**

Use the existing workbench fixture to load a game project and assert the character page shows `现实状态` and `游戏状态`, with game ID/level under the latter. Load a non-game project and assert `游戏状态` is absent. Edit a state field, save, reload, and assert the PUT payload contains only the edited namespace plus existing portrait fields.

- [x] **Step 2: Run the browser test to establish the current failure**

Run: `npx playwright test apps/web/tests/story-workbench.spec.ts --grep "角色卡|状态"`

Expected: FAIL because the page currently renders only `game_panel` and has no dual-state editor.

- [x] **Step 3: Add shared frontend state types and display helpers**

Extend `CharacterStateLayer` in `apps/web/lib/api.ts`. Add small pure helpers in `worldDisplay.ts` for `isGameWebnovel(project)` and `stateRows(layer)`, keeping layout logic out of the page component. `isGameWebnovel` must use the project’s resolved genre plugin IDs rather than title text.

- [x] **Step 4: Render and edit the two state sections**

In the character page, show `现实状态` for all characters and `游戏状态` only when the project is `game_webnovel` and the card has that namespace. Each section displays `current` key/value pairs and recent changes. During edit, use one textarea per namespace containing JSON; parse it before save and show an inline validation message instead of sending malformed JSON. Include both namespaces in the existing `updateFileProjectCharacter` payload only when present.

- [x] **Step 5: Keep project overview compact**

Update the project overview character summary to read game ID/level from `game_state.current` first and `game_panel` second, without exposing the full two-line state on the overview page.

- [x] **Step 6: Run frontend typecheck and browser tests**

Run: `npx tsc --noEmit` from `apps/web`

Expected: PASS.

Run: `npx playwright test apps/web/tests/story-workbench.spec.ts --grep "角色卡|状态"`

Expected: PASS for game and non-game cases.

- [x] **Step 7: Commit the UI**

```bash
git add apps/web/lib/api.ts apps/web/lib/worldDisplay.ts apps/web/app/projects/[id]/characters/page.tsx apps/web/app/projects/[id]/page.tsx apps/web/tests/story-workbench.spec.ts
git commit -m "feat: expose dual character states in workbench"
```

### Task 6: Full regression, migration safety, and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-07-19-game-novel-dual-state-design.md`
- Create: `tests/story_core/test_dual_state_integration.py`
- Test: `tests/api/test_file_project_creation_routes.py`

- [x] **Step 1: Add an integration fixture covering an old project**

The `story_core` integration fixture only covers an old project's writing packet and chapter synchronization: create a temporary file project with only `game_panel` and top-level real profile fields, load the writing packet, and assert the post-sync state is isolated without a forced bulk migration. The character-page API payload is covered by `tests/api/test_file_project_creation_routes.py`, including GET/PUT/read-back and persisted file contents.

- [x] **Step 2: Run the integration test**

Run: `pytest -q tests/story_core/test_dual_state_integration.py`

Expected: PASS.

- [x] **Step 3: Run the focused backend suite**

Run: `pytest -q tests/story_core/test_dual_state.py tests/story_core/test_character_game_panel.py tests/story_core/test_writing_packet.py tests/story_core/test_writer_prompt_method.py tests/api/test_project_context_sync.py tests/api/test_story_routes.py`

Expected: PASS.

- [x] **Step 4: Run the frontend checks**

Run: `npx tsc --noEmit` from `apps/web`

Expected: PASS.

Run: `npx playwright test apps/web/tests/story-workbench.spec.ts --grep "角色卡|状态|项目"`

Expected: PASS, or a clearly reported environment-only browser failure with the backend tests still passing.

- [x] **Step 5: Update the design spec with the shipped interfaces**

Document the final JSON shape, the supported scene-line markers, the legacy compatibility behavior, and the rule that only explicit reality ledger events can alter `real_state`. Keep the spec free of model-specific prompt text.

- [ ] **Step 6: Commit after verification**

```bash
git add docs/superpowers/specs/2026-07-19-game-novel-dual-state-design.md tests/story_core/test_dual_state_integration.py
git commit -m "test: verify dual state migration safety"
```

The final implementation report must include the exact backend and frontend commands run, the number of passing tests, and any browser/runtime limitation that was not caused by the feature.

---

## Self-review against the approved design

- Generic character cards remain reusable: `real_state` is available to every genre, while `game_state` is only materialized for `game_webnovel` or legacy game data.
- Both namespaces have `current` and `recent_changes`, satisfying the approved state-history requirement.
- The writing packet has explicit game/reality/transition projections and no longer sends the complete card to every scene.
- Synchronization has separate write paths and forbids inferred cross-line mutations, including the real balance vs. game currency case.
- Existing `game_panel` and top-level profile fields remain readable and mirrored, so old projects do not require a destructive migration.
- The character page exposes and edits both states, while non-game projects stay uncluttered.
- Tests cover model normalization, packet leakage, persistence, sync isolation, old projects, UI rendering, and save/reload behavior.

The plan contains no deferred placeholders; each implementation step names its files, interface, command, and expected result.
