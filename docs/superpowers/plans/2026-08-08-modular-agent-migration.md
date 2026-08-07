# Modular Novel Agent Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the current monolithic chapter generator into explicit director, entity, writer, review, and continuity modules so every agent reads only the material it needs, every intermediate artifact is inspectable, and confirmed or rewritten chapters update long-form state safely.

**Architecture:** Keep `StoryEngine` as the public entry point and turn `StoryOrchestrator` into a thin coordinator. A shared `ProjectContextReader` reads canonical project artifacts and records exact reads; role-specific context builders select director and writer views. The director produces a structured scene plan plus entity requirements, `CanonService` validates or creates required cards before prose generation, `WriterAgent` receives the approved director artifact and scoped canon, deterministic checks and a focused consistency agent produce candidate deltas, and only candidate confirmation commits prose and state in one transaction.

**Tech Stack:** Python 3.11, Pydantic 2, dataclasses where existing persistence contracts use them, FastAPI, Next.js 14/React 18/TypeScript, pytest, Playwright.

---

## Guardrails And Target Flow

The implementation must preserve the existing API routes while migrating internals. Do not replace the whole pipeline in one commit.

```text
FileProjectStore
  -> StoryEngine
  -> ProjectContextReader
  -> DirectorContextBuilder
  -> DirectorAgent
  -> CanonService / EntityDesigner
  -> WriterContextBuilder
  -> WriterAgent
  -> deterministic checks
  -> ConsistencyAgent
  -> FactExtractor
  -> CandidateDraft + pending ContinuityDelta
  -> user confirmation
  -> transactional Markdown + metadata + canon commit
```

Authority order for conflicting facts:

```text
confirmed chapter event
  > confirmed continuity ledger
  > active entity card
  > world rule
  > outline
  > director plan
  > model invention
```

The director decides what happens. The writer decides how it is rendered. Neither agent writes confirmed canon directly.

---

### Task 1: Add Shared Agent Contracts And Read Traces

**Files:**
- Create: `packages/story_core/context/__init__.py`
- Create: `packages/story_core/context/contracts.py`
- Create: `packages/story_core/agents/__init__.py`
- Create: `packages/story_core/agents/contracts.py`
- Test: `tests/story_core/test_agent_contracts.py`

- [ ] **Step 1: Write failing contract tests**

```python
from packages.story_core.agents.contracts import DirectorArtifact, WriterResult
from packages.story_core.context.contracts import ArtifactRead, ContextTrace


def test_context_trace_records_exact_artifact_reads() -> None:
    trace = ContextTrace(agent="writer", chapter_number=12)
    trace.add(ArtifactRead(kind="outline", path=".story-system/outline.json", sha256="abc", chars=80))
    assert trace.reads[0].kind == "outline"
    assert trace.reads[0].path == ".story-system/outline.json"


def test_director_artifact_requires_scene_progression() -> None:
    artifact = DirectorArtifact.model_validate({
        "schema_version": "director-artifact/v1",
        "chapter_number": 12,
        "chapter_goal": "拿到进入矿区的许可",
        "opening_state": "主角在守备处等待核验",
        "scene_beats": [{"order": 1, "location": "守备处", "action": "提交证据", "result": "获得许可"}],
        "ending_state": "主角进入矿区",
        "entity_requirements": [],
    })
    assert artifact.scene_beats[0].result == "获得许可"


def test_writer_result_cannot_confirm_facts() -> None:
    result = WriterResult(body="正文", proposed_facts=[{"subject_id": "char-1", "field": "level", "value": 2}])
    assert result.proposed_facts[0]["value"] == 2
    assert not hasattr(result, "confirmed_facts")
```

- [ ] **Step 2: Run the tests and verify they fail because the modules do not exist**

Run: `uv run pytest tests/story_core/test_agent_contracts.py -q`

Expected: collection fails with `ModuleNotFoundError`.

- [ ] **Step 3: Implement Pydantic contracts**

Implement:

```python
class ArtifactRead(BaseModel):
    kind: str
    path: str
    sha256: str
    chars: int = 0


class ContextTrace(BaseModel):
    schema_version: str = "context-trace/v1"
    agent: Literal["director", "entity_designer", "writer", "consistency", "fact_extractor"]
    chapter_number: int
    reads: list[ArtifactRead] = Field(default_factory=list)
    selected_entity_ids: list[str] = Field(default_factory=list)
    selected_module_ids: list[str] = Field(default_factory=list)

    def add(self, read: ArtifactRead) -> None:
        self.reads.append(read)
```

Also define `SceneBeat`, `EntityRequirement`, `DirectorArtifact`, `WriterRequest`, and `WriterResult`. `WriterRequest` must contain the approved director artifact instead of a free-form director string.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/story_core/test_agent_contracts.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/context packages/story_core/agents tests/story_core/test_agent_contracts.py
git commit -m "refactor: add agent and context contracts"
```

### Task 2: Build A Canonical Project Context Reader

**Files:**
- Create: `packages/story_core/context/project_reader.py`
- Test: `tests/story_core/test_project_context_reader.py`

- [ ] **Step 1: Write failing reader tests**

Cover these cases:

1. Reads only paths declared by the caller.
2. Rejects a path escaping the project root.
3. Returns parsed JSON or Markdown text with SHA-256 and character count.
4. Uses UTF-8 with BOM tolerance for existing project data.
5. Records missing optional artifacts without inventing content.

```python
def test_reader_rejects_path_outside_project(tmp_path: Path) -> None:
    reader = ProjectContextReader(tmp_path)
    with pytest.raises(ValueError, match="artifact_path_outside_project"):
        reader.read_text("../secret.txt", kind="world")
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `uv run pytest tests/story_core/test_project_context_reader.py -q`

Expected: import failure.

- [ ] **Step 3: Implement the reader**

`ProjectContextReader` must expose `read_json`, `read_text`, and `trace`. Resolve every path against `root`, verify containment before reading, and hash the exact bytes that were read. Do not let agents recursively scan directories.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/story_core/test_project_context_reader.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/context/project_reader.py tests/story_core/test_project_context_reader.py
git commit -m "refactor: add canonical project context reader"
```

### Task 3: Create Role-Specific Director And Writer Contexts

**Files:**
- Create: `packages/story_core/context/director_context.py`
- Create: `packages/story_core/context/writer_context.py`
- Test: `tests/story_core/test_role_contexts.py`

- [ ] **Step 1: Write failing scope tests**

Build a temporary project containing a general outline, current volume, world rules, four character cards, inventory, unresolved foreshadowing, and two writing modules.

Assert that director context contains:

- current volume and nearby chapter outline;
- previous chapter summary and current continuity ledger;
- active plot threads and unresolved foreshadowing;
- concise cards for characters relevant to the target chapter;
- no prose-writing module text.

Assert that writer context contains:

- the approved `DirectorArtifact`;
- previous chapter tail, selected full character cards, scene world rules, active entity cards, and selected craft modules;
- no complete book outline, unrelated character cards, retired entities, or raw review history.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_role_contexts.py -q`

Expected: import failure.

- [ ] **Step 3: Implement both builders**

Use immutable Pydantic context models. Apply explicit budgets per section, but trim at item boundaries rather than cutting arbitrary Chinese text. Record every selected file and entity ID in `ContextTrace`.

```python
class WriterContext(BaseModel):
    chapter_number: int
    director_artifact: DirectorArtifact
    previous_tail: str
    continuity_facts: list[dict[str, Any]]
    character_cards: list[dict[str, Any]]
    entity_cards: list[dict[str, Any]]
    world_rules: list[dict[str, Any]]
    craft_modules: list[dict[str, Any]]
    trace: ContextTrace
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/story_core/test_role_contexts.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/context/director_context.py packages/story_core/context/writer_context.py tests/story_core/test_role_contexts.py
git commit -m "refactor: split director and writer context views"
```

### Task 4: Extract The Writer Agent Behind A Stable Runtime Boundary

**Files:**
- Create: `packages/story_core/agents/writer/__init__.py`
- Create: `packages/story_core/agents/writer/agent.py`
- Create: `packages/story_core/agents/writer/prompt.py`
- Create: `packages/story_core/agents/writer/runtime.py`
- Modify: `packages/story_core/pipeline/writing_stage.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_modular_writer_agent.py`
- Test: `tests/story_core/test_orchestrator.py`

- [ ] **Step 1: Write failing writer-agent tests**

Use a fake runtime and assert:

1. The agent gets one `WriterRequest` and returns one `WriterResult`.
2. CLI and API runtimes use the same request contract.
3. The prompt contains the director artifact and selected context, but not internal trace hashes or unrelated cards.
4. Empty model output raises `writer_empty_body`.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_modular_writer_agent.py -q`

Expected: import failure.

- [ ] **Step 3: Implement the runtime adapter**

Wrap `RuntimeModelGateway.complete_stage("writer", request)`. The writer agent must not know whether the backing provider is Codex CLI, Gemini CLI, or HTTP API.

```python
class WriterRuntime(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError


class GatewayWriterRuntime:
    def __init__(self, gateway: RuntimeModelGateway) -> None:
        self.gateway = gateway

    def complete(self, request: ModelRequest) -> ModelResponse:
        return self.gateway.complete_stage("writer", request)
```

- [ ] **Step 4: Move writer prompt assembly**

Move the writer-only assembly currently reached through `StoryOrchestrator._body_prompt`, `_render_body_prompt`, and `_build_writer_context` into `agents/writer/prompt.py`. Reuse generic and genre renderers from `genre_stages`; do not duplicate game rules in the generic writer.

- [ ] **Step 5: Delegate existing orchestration to `WriterAgent`**

Keep current chapter review and length handling intact. Replace only the initial prose-generation call around the current `generate_chapter_body` integration. The compatibility path must still emit the existing workflow steps.

- [ ] **Step 6: Run focused regression tests**

Run:

```bash
uv run pytest tests/story_core/test_modular_writer_agent.py tests/story_core/test_writer.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_orchestrator.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add packages/story_core/agents/writer packages/story_core/pipeline/writing_stage.py packages/story_core/orchestrator.py tests/story_core/test_modular_writer_agent.py
git commit -m "refactor: extract modular writer agent"
```

### Task 5: Extract The Director Agent And Persist Its Artifact

**Files:**
- Create: `packages/story_core/agents/director/__init__.py`
- Create: `packages/story_core/agents/director/agent.py`
- Create: `packages/story_core/agents/director/prompt.py`
- Create: `packages/story_core/persistence/director_store.py`
- Modify: `packages/story_core/pipeline/planning_stage.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_modular_director_agent.py`
- Test: `tests/story_core/test_director_store.py`

- [ ] **Step 1: Write failing tests**

Assert that the director:

- uses an existing chapter outline without calling the model when it is complete;
- calls the planner runtime only to fill missing operational detail;
- returns `DirectorArtifact`, not prose;
- lists new people, equipment, techniques, locations, organizations, tasks, and monsters in `entity_requirements`;
- persists `.story-system/director/NNNN.json` with input trace, output, provider, model, and status.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_modular_director_agent.py tests/story_core/test_director_store.py -q`

Expected: import failure.

- [ ] **Step 3: Implement director prompt and agent**

Move plan creation currently reached through `resolve_chapter_plan` and `_plan_prompt` into the new director package. The prompt must answer only: chapter goal, opening state, ordered scene beats, cause and effect, character decisions, information boundaries, ending state, hook, and entity requirements.

- [ ] **Step 4: Implement `DirectorStore`**

Use atomic temporary-file replacement. The stored artifact is an inspectable work product, not confirmed canon.

- [ ] **Step 5: Replace the orchestrator planning block**

`StoryOrchestrator` calls `DirectorContextBuilder`, then `DirectorAgent`, then passes the returned artifact forward. Preserve current fallback behavior until the new artifact has passed schema validation.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/story_core/test_modular_director_agent.py tests/story_core/test_director_store.py tests/story_core/test_director_agent.py tests/story_core/test_director_plan_quality.py tests/story_core/test_genre_director_isolation.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add packages/story_core/agents/director packages/story_core/persistence/director_store.py packages/story_core/pipeline/planning_stage.py packages/story_core/orchestrator.py tests/story_core/test_modular_director_agent.py tests/story_core/test_director_store.py
git commit -m "refactor: extract and persist director artifacts"
```

### Task 6: Add Stable Canon Entity IDs And Alias Resolution

**Files:**
- Create: `packages/story_core/canon/__init__.py`
- Create: `packages/story_core/canon/contracts.py`
- Create: `packages/story_core/canon/registry.py`
- Test: `tests/story_core/test_canon_registry.py`

- [ ] **Step 1: Write failing registry tests**

Cover:

- one person can have a real name and game ID without becoming two characters;
- organizations and anonymous buyers are not automatically characters;
- entity IDs remain stable when display names change;
- aliases are unique within an entity type;
- only `active` entities enter writer context;
- lifecycle is `proposed -> approved -> active -> retired`.

```python
def test_real_name_and_game_id_resolve_to_one_character() -> None:
    registry = CanonRegistry.empty()
    entity = registry.add_character(name="苏叶", aliases=["夜烬"])
    assert registry.resolve("苏叶", "character").entity_id == entity.entity_id
    assert registry.resolve("夜烬", "character").entity_id == entity.entity_id
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_canon_registry.py -q`

Expected: import failure.

- [ ] **Step 3: Implement contracts and registry**

Use typed entity kinds: `character`, `item`, `equipment`, `technique`, `location`, `organization`, `quest`, `monster`, and `rule`. Persist stable IDs and aliases; never use a display name as a foreign key.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/story_core/test_canon_registry.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/canon tests/story_core/test_canon_registry.py
git commit -m "feat: add canonical entity registry"
```

### Task 7: Generate Required Entity Cards Before Writing

**Files:**
- Create: `packages/story_core/canon/entity_designer.py`
- Create: `packages/story_core/canon/service.py`
- Create: `packages/story_core/canon/schemas.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_entity_preflight.py`

- [ ] **Step 1: Write failing preflight tests**

Assert:

1. A named new character required by the director gets a concrete card before writer context is built.
2. A newly important weapon or cultivation technique receives mechanics, limits, ownership, and narrative use.
3. A disposable unnamed passerby can remain an inline minor entity.
4. Reusing an alias resolves the existing entity instead of creating a duplicate.
5. Invalid generated cards stop before prose generation with `entity_preflight_failed`.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_entity_preflight.py -q`

Expected: import failure.

- [ ] **Step 3: Implement type-specific schemas**

Character cards must include identity, origin, age or age range, occupation or social role, present goal, fear or weakness, behavioral habits, speech tendency, relationships, knowledge boundary, current state, and change arc. Equipment and techniques must include effect, limitation, cost, owner, provenance, and plot function. Keep genre-specific fields inside an `extensions` object.

- [ ] **Step 4: Implement `CanonService.ensure_requirements`**

Resolve existing entities first. Call `EntityDesigner` only for unresolved important requirements. Return approved in-memory cards and a proposed registry delta; do not persist it yet.

- [ ] **Step 5: Insert preflight between director and writer**

Update workflow order to director -> entity preflight -> writer context -> writer. Include generated entity IDs in the writer trace.

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/story_core/test_entity_preflight.py tests/story_core/test_chapter_continuity.py tests/story_core/test_file_project_continuity.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add packages/story_core/canon/entity_designer.py packages/story_core/canon/service.py packages/story_core/canon/schemas.py packages/story_core/orchestrator.py tests/story_core/test_entity_preflight.py
git commit -m "feat: create required canon entities before writing"
```

### Task 8: Make Writing Skills Selective Craft Modules

**Files:**
- Create: `packages/story_core/craft/module_registry.py`
- Create: `packages/story_core/craft/selector.py`
- Modify: `packages/story_core/skill_packs.py`
- Modify: `packages/story_core/context/writer_context.py`
- Modify: `apps/api/routes/skill_packs.py`
- Test: `tests/story_core/test_craft_module_selection.py`
- Test: `tests/api/test_skill_pack_routes.py`

- [ ] **Step 1: Write failing selection tests**

Each module manifest must declare:

```json
{
  "id": "dialogue-natural-cn",
  "purpose": "dialogue",
  "genre_ids": [],
  "stages": ["writer"],
  "priority": 50,
  "max_chars": 1800,
  "conflicts_with": [],
  "enabled_by_default": false
}
```

Assert only explicitly enabled project modules load, at most one module per exclusive purpose loads, genre-specific modules do not leak into other genres, and uninstalling one module leaves the others intact.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_craft_module_selection.py tests/api/test_skill_pack_routes.py -q`

Expected: selection assertions fail.

- [ ] **Step 3: Implement registry and selector**

Treat skills as optional craft knowledge, not replacement agents and not workflow stages. Do not auto-enable newly installed modules.

- [ ] **Step 4: Adapt existing skill-pack APIs**

Preserve existing routes but return manifest, installation state, project enablement, and selection reason. Writer context receives only selected module content and IDs.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/story_core/test_craft_module_selection.py tests/story_core/test_skill_packs.py tests/api/test_skill_pack_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/story_core/craft packages/story_core/skill_packs.py packages/story_core/context/writer_context.py apps/api/routes/skill_packs.py tests/story_core/test_craft_module_selection.py tests/api/test_skill_pack_routes.py
git commit -m "refactor: make writing skills selective craft modules"
```

### Task 9: Replace Broad Review With Deterministic Checks And Focused Consistency

**Files:**
- Create: `packages/story_core/agents/consistency/__init__.py`
- Create: `packages/story_core/agents/consistency/agent.py`
- Create: `packages/story_core/agents/consistency/prompt.py`
- Create: `packages/story_core/continuity/checks.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/simplified_review.py`
- Test: `tests/story_core/test_consistency_review.py`

- [ ] **Step 1: Write failing review-policy tests**

The hard gate must cover only:

- missing or empty body;
- chapter number and title contract;
- minimum/maximum length;
- arithmetic and state contradictions;
- named entity identity conflicts;
- impossible inventory, ownership, location, time, or knowledge changes;
- explicit outline must-have violations.

Style concerns, subjective prose taste, and optional dialogue improvements must be warnings and cannot leave the user stuck with only “discard”.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_consistency_review.py -q`

Expected: current broad quality gate fails the policy assertions.

- [ ] **Step 3: Implement deterministic checks**

Move arithmetic, counts, IDs, state transitions, and required fields into pure functions. Return structured evidence with source fields.

- [ ] **Step 4: Implement focused consistency agent**

Give it the draft, director artifact, active facts, and deterministic findings. Ask only whether the draft contradicts established facts or the approved chapter plan. It must not grade literary style.

- [ ] **Step 5: Change orchestration policy**

Auto-repair only local, evidence-backed defects. Save other concerns as warnings. Keep the candidate confirmable with `accept_quality_warnings=True` whenever no hard inconsistency remains.

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/story_core/test_consistency_review.py tests/story_core/test_orchestrator.py tests/story_core/test_candidate_draft.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add packages/story_core/agents/consistency packages/story_core/continuity/checks.py packages/story_core/orchestrator.py packages/story_core/simplified_review.py tests/story_core/test_consistency_review.py
git commit -m "refactor: focus chapter review on factual consistency"
```

### Task 10: Extract Candidate Facts Into A Pending Continuity Delta

**Files:**
- Create: `packages/story_core/agents/fact_extractor/__init__.py`
- Create: `packages/story_core/agents/fact_extractor/agent.py`
- Create: `packages/story_core/continuity/delta.py`
- Modify: `packages/story_core/candidate_draft.py`
- Modify: `packages/story_core/persistence/candidate_store.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_continuity_delta.py`
- Test: `tests/story_core/test_candidate_draft.py`

- [ ] **Step 1: Write failing delta tests**

Assert that a candidate can carry:

- entity additions and updates;
- relationship changes;
- inventory and equipment changes;
- task and progression changes;
- location and timeline movement;
- newly planted, advanced, or resolved foreshadowing;
- source sentence and confidence for each proposed fact.

Also assert loading a `candidate-draft/v1` file still works.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_continuity_delta.py tests/story_core/test_candidate_draft.py -q`

Expected: delta fields are missing.

- [ ] **Step 3: Implement `ContinuityDelta`**

Every operation must be machine-readable and target stable IDs. Model output is proposed, never confirmed.

- [ ] **Step 4: Implement `FactExtractor`**

Use deterministic extraction first for explicit numeric state and named ownership changes. Use the model only for ambiguous relationships, knowledge changes, and foreshadowing. Validate all referenced IDs against the candidate registry view.

- [ ] **Step 5: Upgrade candidate persistence compatibly**

Write `candidate-draft/v2` with `continuity_delta` and `context_trace_ids`. Keep `body` during this migration; Markdown canonicalization occurs in Task 12.

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/story_core/test_continuity_delta.py tests/story_core/test_candidate_draft.py tests/story_core/test_candidate_store.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add packages/story_core/agents/fact_extractor packages/story_core/continuity/delta.py packages/story_core/candidate_draft.py packages/story_core/persistence/candidate_store.py packages/story_core/orchestrator.py tests/story_core/test_continuity_delta.py tests/story_core/test_candidate_draft.py
git commit -m "feat: attach pending continuity deltas to candidates"
```

### Task 11: Commit Chapters And Canon In One Transaction

**Files:**
- Create: `packages/story_core/persistence/project_transaction.py`
- Create: `packages/story_core/continuity/snapshot.py`
- Create: `packages/story_core/continuity/store.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_candidate_confirmation_transaction.py`
- Test: `tests/story_core/test_rewrite_rollback.py`

- [ ] **Step 1: Write failing transaction tests**

Cover:

1. Confirming a candidate applies prose, metadata, entity registry, continuity delta, and snapshot together.
2. A simulated write failure restores every managed file.
3. Regenerating chapter 12 starts from the confirmed snapshot after chapter 11.
4. Confirming rewritten chapter 12 marks chapters 13 onward `stale` and leaves their files available for review.
5. Discarding a candidate changes no confirmed state.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_candidate_confirmation_transaction.py tests/story_core/test_rewrite_rollback.py -q`

Expected: continuity delta is not transactional yet.

- [ ] **Step 3: Implement transaction and snapshot stores**

Store per-chapter before/after snapshots under `.story-system/continuity/snapshots/NNNN.json`. Store stale markers under `.story-system/continuity/stale.json`. Reuse existing managed-file snapshot/restore logic from `FileProjectStore` rather than creating a second rollback mechanism.

- [ ] **Step 4: Update `confirm_candidate`**

Validate the candidate against its `context_snapshot_id`, apply the pending delta to a copy, then write all managed files in one transaction. Mark the candidate confirmed only after the transaction succeeds.

- [ ] **Step 5: Update regeneration base-state logic**

Make `_generation_state_for_target` and `_regeneration_base_state` use confirmed snapshots. Remove inference from later chapter prose when a valid snapshot exists.

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/story_core/test_candidate_confirmation_transaction.py tests/story_core/test_rewrite_rollback.py tests/story_core/test_file_project_store.py tests/story_core/test_file_project_continuity.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add packages/story_core/persistence/project_transaction.py packages/story_core/continuity/snapshot.py packages/story_core/continuity/store.py packages/story_core/file_project_store.py tests/story_core/test_candidate_confirmation_transaction.py tests/story_core/test_rewrite_rollback.py
git commit -m "feat: make chapter confirmation transactional"
```

### Task 12: Make Chapter Markdown The Canonical Body

**Files:**
- Modify: `packages/story_core/persistence/chapter_store.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/candidate_draft.py`
- Modify: `packages/story_core/persistence/candidate_store.py`
- Test: `tests/story_core/test_chapter_markdown_canonical.py`

- [ ] **Step 1: Write failing Markdown-canonical tests**

Assert:

- new chapter JSON contains `body_path` and `body_sha256`, not a duplicate `body`;
- `ChapterStore.read_chapter` hydrates body from Markdown;
- direct Markdown edits are detected by a hash mismatch and can be re-indexed explicitly;
- legacy JSON-only chapters still load and migrate on next save;
- candidate drafts store body in `.story-system/candidates/bodies/{candidate_id}.md`.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_chapter_markdown_canonical.py -q`

Expected: JSON remains the current body source.

- [ ] **Step 3: Implement metadata/body separation**

Write Markdown first to the transaction staging area, compute SHA-256, then write metadata. Add `include_body: bool = True` to `read_chapter` so list endpoints can avoid loading every chapter body.

- [ ] **Step 4: Add backward-compatible migration**

When a legacy record has `body` and no valid Markdown, return the JSON body. On the next successful write, create Markdown and remove `body` from metadata.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/story_core/test_chapter_markdown_canonical.py tests/story_core/test_file_project_store.py tests/story_core/test_candidate_store.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/story_core/persistence/chapter_store.py packages/story_core/file_project_store.py packages/story_core/candidate_draft.py packages/story_core/persistence/candidate_store.py tests/story_core/test_chapter_markdown_canonical.py
git commit -m "refactor: make Markdown the canonical chapter body"
```

### Task 13: Expose Every Agent Read And Product In The Existing Workbench

**Files:**
- Create: `packages/story_core/persistence/workflow_artifact_store.py`
- Modify: `packages/story_core/generation_progress.py`
- Modify: `packages/story_core/workflow_steps.py`
- Modify: `apps/api/routes/file_projects.py`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/components/ws/WritingFlow.tsx`
- Modify: `apps/web/components/prompts/PromptCallsView.tsx`
- Test: `tests/story_core/test_workflow_artifact_store.py`
- Test: `tests/api/test_file_project_generation_jobs.py`
- Test: `apps/web/tests/writing-flow.spec.ts`

- [ ] **Step 1: Write failing persistence and API tests**

The generation-job response must show, for each stage:

- agent ID and status;
- exact artifact paths and hashes read;
- selected entity and craft module IDs;
- provider and model used;
- prompt template ID and version;
- output artifact path and summary;
- elapsed time and error, if any.

Do not include API tokens or hidden credentials.

- [ ] **Step 2: Run backend tests and verify failure**

Run: `uv run pytest tests/story_core/test_workflow_artifact_store.py tests/api/test_file_project_generation_jobs.py -q`

Expected: structured artifact references are missing.

- [ ] **Step 3: Implement persistent artifact store**

Store artifacts under `.story-system/workflow/{job_id}/{stage_id}.json`. Generation jobs keep summaries and artifact IDs so page refresh does not lose previous records.

- [ ] **Step 4: Extend existing routes and TypeScript contracts**

Add artifact-detail retrieval below the existing generation-job routes in `apps/api/routes/file_projects.py`. Update `GenerationJobStep` in `apps/web/lib/api.ts` with typed reads, modules, model metadata, and artifact references.

- [ ] **Step 5: Update the existing workbench panels**

Keep `WritingFlowPanel` as the main process view. Replace inferred labels with stored stage data and add expandable “读取资料”, “调用模块”, “模型调用”, and “本步产物” sections. Keep `PromptCallsView` focused on raw prompt inspection rather than duplicating workflow state.

- [ ] **Step 6: Run backend and frontend tests**

Run:

```bash
uv run pytest tests/story_core/test_workflow_artifact_store.py tests/api/test_file_project_generation_jobs.py -q
cd apps/web
npm run build
npx playwright test tests/writing-flow.spec.ts
```

Expected: backend tests, Next build, and the focused Playwright test pass.

- [ ] **Step 7: Commit**

```bash
git add packages/story_core/persistence/workflow_artifact_store.py packages/story_core/generation_progress.py packages/story_core/workflow_steps.py apps/api/routes/file_projects.py apps/web/lib/api.ts apps/web/components/ws/WritingFlow.tsx apps/web/components/prompts/PromptCallsView.tsx tests/story_core/test_workflow_artifact_store.py tests/api/test_file_project_generation_jobs.py apps/web/tests/writing-flow.spec.ts
git commit -m "feat: expose agent reads and artifacts in workbench"
```

### Task 14: Thin The Orchestrator And Remove Compatibility Code

**Files:**
- Modify: `packages/story_core/engine.py`
- Modify: `packages/story_core/orchestrator.py`
- Delete: `packages/story_core/writer_agent.py`
- Modify: tests importing `packages.story_core.writer_agent`
- Test: `tests/story_core/test_pipeline_boundaries.py`

- [ ] **Step 1: Write boundary tests**

Assert that:

- `StoryEngine` invokes the coordinator once;
- `StoryOrchestrator` contains no provider-specific CLI/API branching;
- writer prompt construction lives only under `agents/writer`;
- director prompt construction lives only under `agents/director`;
- no agent directly writes project files;
- no generic writer module contains game-only terms such as level, inventory, equipment durability, or auction-house rules.

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/story_core/test_pipeline_boundaries.py -q`

Expected: old imports and prompt-building methods still violate boundaries.

- [ ] **Step 3: Remove migrated helpers from `orchestrator.py`**

Keep only stage ordering, error propagation, workflow reporting, and candidate bundle assembly. Delete duplicate prompt assembly and compatibility branches after all callers use the new agents.

- [ ] **Step 4: Remove the obsolete writer module**

Move any remaining tests to `packages.story_core.agents.writer`. Verify no import remains before deleting:

Run: `rg -n "story_core\.writer_agent|from packages\.story_core import writer_agent" packages apps tests`

Expected: no matches.

- [ ] **Step 5: Run boundary and focused regression tests**

Run:

```bash
uv run pytest tests/story_core/test_pipeline_boundaries.py tests/story_core/test_orchestrator.py tests/story_core/test_orchestrator_prompt_contracts.py tests/story_core/test_genre_director_isolation.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/story_core/engine.py packages/story_core/orchestrator.py packages/story_core/agents tests/story_core
git rm packages/story_core/writer_agent.py
git commit -m "refactor: reduce orchestrator to pipeline coordination"
```

### Task 15: Run Migration, Full Verification, And Handoff Checks

**Files:**
- Create: `scripts/migrate_modular_story_state.py`
- Create: `tests/story_core/test_modular_state_migration.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-08-agent-module-boundaries-design.md` only if implementation deliberately changes a documented contract

- [ ] **Step 1: Write migration tests against copied fixtures**

Test at least:

- the long game project;
- a non-game fantasy project;
- a legacy project with JSON-only chapters;
- a project containing duplicate character aliases;
- a project with no generated chapters.

The migration must be idempotent and create a timestamped backup before writing.

- [ ] **Step 2: Implement the migration script**

Support `--project`, `--dry-run`, and `--all`. Print counts for migrated chapters, entity merges, unresolved alias conflicts, created snapshots, and warnings. Never silently choose between two conflicting confirmed identities.

- [ ] **Step 3: Run migration tests**

Run: `uv run pytest tests/story_core/test_modular_state_migration.py -q`

Expected: all tests pass.

- [ ] **Step 4: Run full backend verification**

Run:

```bash
uv run pytest -q
```

Expected: entire test suite passes.

- [ ] **Step 5: Run full frontend verification**

Run:

```bash
cd apps/web
npm run build
npm run test:e2e
```

Expected: build and Playwright suite pass.

- [ ] **Step 6: Perform two real smoke generations**

Generate one chapter from a game project and one from a non-game project. For each, verify in the workbench:

- director reads and artifact are visible;
- required entities exist before writer starts;
- writer context contains no unrelated genre rules;
- selected skills match project settings;
- candidate facts remain pending before confirmation;
- confirmation updates snapshots and canon;
- regenerating an earlier chapter starts from the correct prior snapshot.

- [ ] **Step 7: Update README architecture and recovery instructions**

Document module ownership, artifact directories, migration command, stale downstream chapters, and how to inspect a failed stage.

- [ ] **Step 8: Commit**

```bash
git add scripts/migrate_modular_story_state.py tests/story_core/test_modular_state_migration.py README.md docs/superpowers/specs/2026-08-08-agent-module-boundaries-design.md
git commit -m "docs: complete modular agent migration"
```

---

## Completion Criteria

- Each agent has one owned package and one typed input/output contract.
- Director and writer read different, traceable context views through the same reader.
- Writer always receives the approved director artifact.
- Important new characters, items, equipment, techniques, tasks, monsters, locations, and organizations are resolved before prose generation.
- Draft-derived facts stay pending until candidate confirmation.
- Rewriting an earlier chapter uses the previous confirmed snapshot and marks later chapters stale.
- Markdown is the canonical chapter body; JSON stores metadata and hashes.
- CLI and API providers use the same agent contracts.
- Skills are optional craft modules with individual install, enable, disable, and uninstall control.
- Review blocks only objective defects; subjective advice remains visible but non-blocking.
- The workbench shows what each stage read, called, produced, and why it failed.
- Game-specific rules cannot enter non-game writer contexts.
- Full backend, frontend build, and Playwright suites pass.
