# World Context Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate static worldbuilding, the current world snapshot, and chapter-derived continuity facts without breaking legacy file projects.

**Architecture:** Add one normalization module as the only boundary for legacy `world_facts` and `world_blueprint.continuity_state`. File-project reads and chapter confirmation call this module, while writer packets consume its compact, deduplicated projection. The web UI displays static worldbuilding on the world page and dynamic snapshot/facts on the world-state page.

**Tech Stack:** Python 3, Pydantic, pytest, TypeScript, React, Next.js, Playwright tests.

---

### Task 1: World context normalization

**Files:**
- Create: `packages/story_core/world_state.py`
- Create: `tests/story_core/test_world_state.py`

- [ ] **Step 1: Write failing normalization tests**

Cover these behaviors with real data fixtures:

```python
def test_normalize_world_context_separates_static_snapshot_and_facts():
    result = normalize_world_context(
        blueprint={
            "premise": "灵气依赖地脉。",
            "current_arc": "雪山神殿封锁。",
            "continuity_state": {"running_facts": ["林修负伤。"]},
        },
        state={"world_facts": ["世界前提：灵气依赖地脉。", "第147章事实：林修负伤。"]},
        current_focus="守住神殿入口。",
    )
    assert result.static_blueprint == {"premise": "灵气依赖地脉。"}
    assert result.world_snapshot["current_arc"] == "雪山神殿封锁。"
    assert [item["text"] for item in result.continuity_facts] == ["林修负伤。"]
```

Also assert that chapter summaries, full-body fragments, static-rule copies and exact duplicates are excluded from the compact fact projection, while unknown short legacy facts are retained.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/story_core/test_world_state.py -q`

Expected: import failure for `packages.story_core.world_state`.

- [ ] **Step 3: Implement the focused normalization module**

Define immutable result data and pure functions:

```python
@dataclass(frozen=True)
class NormalizedWorldContext:
    static_blueprint: dict[str, Any]
    world_snapshot: dict[str, Any]
    continuity_facts: list[dict[str, Any]]

def normalize_world_context(*, blueprint: Any, state: Any, current_focus: Any = "") -> NormalizedWorldContext: ...
def relevant_continuity_facts(facts: Any, *, query_terms: Iterable[str] = (), limit: int = 12) -> list[dict[str, Any]]: ...
def append_continuity_facts(existing: Any, *, chapter_number: int, facts: Iterable[str]) -> list[dict[str, Any]]: ...
```

Dynamic blueprint keys are `current_arc`, `continuity_state`, and `time_state`. Fact records use `text`, `source_chapter`, `status`, and `updated_chapter`. Deduplication normalizes whitespace and strips legacy chapter prefixes.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest tests/story_core/test_world_state.py -q`

Expected: all tests pass.

### Task 2: Persist only dynamic state changes

**Files:**
- Modify: `packages/story_core/models.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing persistence tests**

Add tests proving that a confirmed chapter writes short facts to `continuity_facts`, updates `world_snapshot`, and does not append `第N章摘要` or full prose into `world_facts`. Add a legacy-load test proving old fields are projected without deleting the original source data.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `pytest tests/story_core/test_file_project_store.py -q -k "world_snapshot or continuity_facts or world_facts_no_summary"`

Expected: new assertions fail because state has no normalized fields and summaries are still appended to `world_facts`.

- [ ] **Step 3: Add model fields and replace write sites**

Add to `StoryState`:

```python
world_snapshot: dict = Field(default_factory=dict)
continuity_facts: list[dict] = Field(default_factory=list)
```

In file-project state loading, merge the normalized projection into the returned state. In `_sync_state_after_chapter`, call `append_continuity_facts(...)` with `chapter_summary["facts"]`; keep `chapter_summaries`, `timeline`, and `memory_index` in their existing stores; stop appending body facts and chapter summaries to `world_facts`. In project sync, stop creating new `world_blueprint.continuity_state` entries.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/story_core/test_file_project_store.py -q -k "world_snapshot or continuity_facts or world_facts_no_summary"`

Expected: all selected tests pass.

### Task 3: Deduplicate the writing packet

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/writing_packet.py`
- Modify: `tests/story_core/test_file_project_store.py`
- Modify: `tests/story_core/test_modular_main_flow.py`

- [ ] **Step 1: Write failing packet-boundary tests**

Create a project whose static blueprint, legacy facts, continuity state and chapter summary repeat the same fact. Assert the packet contains:

```python
assert packet["project"]["world_blueprint"] == {"premise": "灵气依赖地脉。"}
assert packet["state"]["world_snapshot"]["current_arc"] == "雪山神殿封锁。"
assert packet["state"]["continuity_facts"] == [expected_fact]
assert "world_facts" not in packet["state"]
assert json.dumps(packet, ensure_ascii=False).count("林修负伤") == 1
```

- [ ] **Step 2: Run packet tests and verify RED**

Run: `pytest tests/story_core/test_file_project_store.py tests/story_core/test_modular_main_flow.py -q -k "world_context_packet"`

Expected: duplicate count and legacy `world_facts` assertions fail.

- [ ] **Step 3: Use normalized context at both packet builders**

Replace `state.get("world_facts", [])[-20:]` and combined legacy lists with `relevant_continuity_facts(...)`. Pass only `static_blueprint` as world context, `world_snapshot` as current state, and at most 12 relevant continuity facts. Preserve the existing recent-three-chapter summaries and chapter outline.

- [ ] **Step 4: Run packet tests and verify GREEN**

Run: `pytest tests/story_core/test_file_project_store.py tests/story_core/test_modular_main_flow.py -q -k "world_context_packet"`

Expected: all selected tests pass.

### Task 4: Separate the workbench pages

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/components/ws/ConfirmedFactsPanel.tsx`
- Modify: `apps/web/app/projects/[id]/world/page.tsx`
- Modify: `apps/web/app/projects/[id]/sim/page.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing component tests**

Assert that the world page source no longer renders `ConfirmedFactsPanel`, the world-state page does render it, and structured facts show their source chapter and status. Keep support for legacy `string[]` facts only as a display fallback.

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `npm --prefix apps/web test -- --runInBand story-workbench.spec.ts`

Expected: placement and structured-fact assertions fail.

- [ ] **Step 3: Implement page and type changes**

Extend `StoryResponse` with:

```ts
world_snapshot?: Record<string, unknown>;
continuity_facts?: Array<{
  text: string;
  source_chapter?: number;
  status?: string;
  updated_chapter?: number;
}>;
```

Remove the facts panel import/render from the world page. Add current-snapshot and continuity-facts sections above chapter pulse history on the world-state page. Update `ConfirmedFactsPanel` to accept structured records and render `来源：第 N 章` when available.

- [ ] **Step 4: Run frontend tests and verify GREEN**

Run: `npm --prefix apps/web test -- --runInBand story-workbench.spec.ts`

Expected: tests pass.

### Task 5: Migration and full verification

**Files:**
- Create: `scripts/migrate_world_context.py`
- Create: `tests/story_core/test_migrate_world_context.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing migration tests**

Test dry-run, idempotent apply, automatic backup, malformed-input rollback, and unchanged chapter-file hashes.

- [ ] **Step 2: Run migration tests and verify RED**

Run: `pytest tests/story_core/test_migrate_world_context.py -q`

Expected: migration module is missing.

- [ ] **Step 3: Implement migration CLI**

Support:

```text
python scripts/migrate_world_context.py <project-root> --dry-run
python scripts/migrate_world_context.py <project-root> --apply
```

On apply, copy `.webnovel/project.json` and `.webnovel/state.json` into `.story-system/world-context-backups/<timestamp>/`, write normalized `world_snapshot` and `continuity_facts`, remove only dynamic keys from `world_blueprint`, and retain a `legacy_world_facts` backup field for unclassified source facts. Use temporary files plus atomic replace.

- [ ] **Step 4: Run migration and regression tests**

Run:

```text
pytest tests/story_core/test_world_state.py tests/story_core/test_migrate_world_context.py tests/story_core/test_file_project_store.py tests/story_core/test_modular_main_flow.py -q
npm --prefix apps/web test -- --runInBand story-workbench.spec.ts
```

Expected: all tests pass.

- [ ] **Step 5: Migrate and inspect the target project**

Run dry-run and then apply to `data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0`. Verify chapter hashes before and after, inspect the chapter 148 writing packet, and confirm that no long chapter body or duplicate world rule appears in it.

- [ ] **Step 6: Run final verification**

Run `git diff --check`, focused backend tests, frontend typecheck/build, and a browser check of `/world`, `/sim`, and the next-chapter prompt context.

