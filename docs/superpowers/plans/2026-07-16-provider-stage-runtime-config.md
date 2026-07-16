# Provider Stage Runtime Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace misleading four-Agent model settings with provider-specific configuration for the three stages that actually run: planning, writing, and memory.

**Architecture:** Add one provider/stage runtime schema in `runtime_config.py` and make it the only source for connection details and models. Keep legacy story settings as read compatibility only. Record each stage immediately after its real request instead of marking four nominal Agents together.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, pytest, TypeScript, React, Next.js, Playwright.

---

## File Map

- `packages/story_core/runtime_config.py`: schema, persistence, migration, stage resolver.
- `packages/story_core/codex_cli_provider.py`: forward the resolved stage model to Codex CLI.
- `packages/story_core/models.py`: three-stage runtime status and legacy normalization.
- `packages/story_core/runtime.py`: stage status recording and labels.
- `packages/story_core/orchestrator.py`: resolve and record planner, writer, and memory calls.
- `apps/api/routes/stories.py`: strict runtime API and connection tests.
- `apps/web/lib/api.ts`: new TypeScript contract and API normalization.
- `apps/web/components/config/*.tsx`: provider and stage configuration UI.
- `tests/story_core/test_runtime_config.py`: migration and resolution tests.
- `tests/story_core/test_codex_cli_provider.py`: CLI model forwarding tests.
- `tests/story_core/test_engine.py`: real stage execution-status tests.
- `tests/api/test_story_routes.py`: API contract tests.
- `apps/web/tests/story-workbench.spec.ts`: configuration UI tests.

### Task 1: Add the Provider/Stage Runtime Schema

**Files:**
- Modify: `packages/story_core/runtime_config.py`
- Create: `tests/story_core/test_runtime_config.py`

- [ ] **Step 1: Write failing migration tests**

Add a legacy Codex configuration fixture whose five model fields contain `qwen3.6-plus`. Assert migration creates only `planner`, `writer`, and `memory`, each using `gpt-5.4`; assert `character_model` and `global_model` are absent from serialized output. Add tests for idempotent migration, preservation of non-Qwen OpenAI stage models, unknown-field rejection, and empty selected-stage model rejection.

```python
settings = load_runtime_configuration(config_path)
assert settings.provider == "codexcli"
assert settings.providers.codexcli.stages.planner.model == "gpt-5.4"
assert settings.providers.codexcli.stages.writer.model == "gpt-5.4"
assert settings.providers.codexcli.stages.memory.model == "gpt-5.4"
assert "character_model" not in settings.model_dump_json()
```

- [ ] **Step 2: Verify RED**

Run `python -m pytest tests/story_core/test_runtime_config.py -q`.

Expected: FAIL because `load_runtime_configuration` and the provider/stage models do not exist.

- [ ] **Step 3: Implement strict models and migration**

Create strict `StageModelSettings`, `StageSettings`, `CodexCLIProviderSettings`, `OpenAIProviderSettings`, `RuntimeProviders`, and `RuntimeConfiguration` Pydantic models. Add `load_runtime_configuration`, `save_runtime_configuration`, `get_runtime_configuration`, `set_runtime_configuration`, and:

```python
def resolve_stage_runtime(stage: Literal["planner", "writer", "memory"]) -> ResolvedStageRuntime:
    config = get_runtime_configuration()
    selected = getattr(config.providers, config.provider)
    stage_config = getattr(selected.stages, stage)
    return ResolvedStageRuntime(
        provider=config.provider,
        model=stage_config.model.strip(),
        api_key=getattr(selected, "api_key", ""),
        base_url=getattr(selected, "base_url", "").rstrip("/"),
        codex_command=getattr(selected, "command", "codex") or "codex",
        temperature=config.temperature,
    )
```

Legacy migration maps director/writer/memory models to stages, discards character/global models, and replaces `qwen3.6-plus` only for Codex CLI legacy input.

- [ ] **Step 4: Verify GREEN and commit**

Run `python -m pytest tests/story_core/test_runtime_config.py -q`; expect all tests pass.

```powershell
git add packages/story_core/runtime_config.py tests/story_core/test_runtime_config.py
git commit -m "refactor: add provider stage runtime config"
```

### Task 2: Make Configured Stage Models the Real Provider Input

**Files:**
- Modify: `packages/story_core/codex_cli_provider.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/opening_directions.py`
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/world_enrichment.py`
- Test: `tests/story_core/test_codex_cli_provider.py`
- Test: `tests/story_core/test_engine.py`
- Test: `tests/story_core/test_opening_directions.py`
- Test: `tests/story_core/test_outline_planning_generation.py`

- [ ] **Step 1: Write a failing Codex CLI test**

Patch `subprocess.run`, set obsolete environment variables to conflicting values, submit payload model `gpt-5.4-mini`, and assert the spawned command contains `--model gpt-5.4-mini`.

- [ ] **Step 2: Verify RED**

Run `python -m pytest tests/story_core/test_codex_cli_provider.py -q`.

Expected: FAIL because `NOVEL_CODEX_MODEL` still overrides the payload.

- [ ] **Step 3: Remove hidden model selection**

Use only the payload model and reject an empty value:

```python
model = str(payload.get("model") or "").strip()
if not model:
    raise ValueError("codexcli_model_required")
```

Do not change isolated `CODEX_HOME`, sandbox, timeout, or output handling.

- [ ] **Step 4: Write failing orchestrator routing tests**

Assert planning resolves `planner`, body/expansion/revision resolve `writer`, and final extraction resolves `memory`. Assert no `character` runtime resolution occurs.

- [ ] **Step 5: Verify RED**

Run `python -m pytest tests/story_core/test_engine.py -k "stage_runtime" -q`.

Expected: FAIL because `_chat` still reads legacy strategy fields.

- [ ] **Step 6: Route calls through `resolve_stage_runtime`**

At the private boundary map legacy `director` to `planner`, resolve the stage once, put `runtime.model` in the payload, and pass the resolved provider credentials and command to `post_json_with_retry`. Route opening-direction generation, outline planning, and world enrichment through the same `planner` resolver so non-chapter planning cannot retain the legacy model source.

- [ ] **Step 7: Verify GREEN and commit**

Run `python -m pytest tests/story_core/test_codex_cli_provider.py tests/story_core/test_engine.py tests/story_core/test_opening_directions.py tests/story_core/test_outline_planning_generation.py -q`; expect all tests pass.

```powershell
git add packages/story_core/codex_cli_provider.py packages/story_core/orchestrator.py packages/story_core/opening_directions.py packages/story_core/outline_planning_generation.py packages/story_core/world_enrichment.py tests/story_core/test_codex_cli_provider.py tests/story_core/test_engine.py tests/story_core/test_opening_directions.py tests/story_core/test_outline_planning_generation.py
git commit -m "fix: use configured model for each writing stage"
```

### Task 3: Record Only Stages That Actually Run

**Files:**
- Modify: `packages/story_core/models.py`
- Modify: `packages/story_core/runtime.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_engine.py`
- Test: `tests/story_core/test_models.py`

- [ ] **Step 1: Write failing execution-status tests**

Successful generation must contain planner, writer, and memory entries with actual provider/model snapshots. Planner failure must mark only planner as fallback while writer and memory remain idle. Serialized runtime state must not contain `character_agent`.

- [ ] **Step 2: Verify RED**

Run `python -m pytest tests/story_core/test_engine.py -k "runtime_status" -q`.

Expected: FAIL because `_record_success` and `_record_failure` update four entries together.

- [ ] **Step 3: Implement three-stage status**

Create `StageRuntimeEntry` with `source`, `provider`, `model`, `fallback_reason`, and `last_run_chapter`. Change `AgentRuntimeState` to `planner`, `writer`, and `memory`. Normalize old `director_agent`, `writer_agent`, and `memory_agent` on read; discard `character_agent`. Replace bulk recording with `record_stage_runtime(...)` immediately after each request.

- [ ] **Step 4: Verify GREEN and commit**

Run `python -m pytest tests/story_core/test_engine.py tests/story_core/test_models.py -q`; expect all tests pass.

```powershell
git add packages/story_core/models.py packages/story_core/runtime.py packages/story_core/orchestrator.py tests/story_core/test_engine.py tests/story_core/test_models.py
git commit -m "fix: report actual writing stage runtime"
```

### Task 4: Replace the Runtime Settings API

**Files:**
- Modify: `apps/api/routes/stories.py`
- Test: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing API tests**

Assert `GET /runtime-settings` returns only `provider`, `providers`, `temperature`, and `new_character_policy`. Recursively assert the five legacy model fields are absent. Assert `PUT /runtime-settings` rejects unknown legacy fields and connection tests accept only `planner`, `writer`, or `memory`.

- [ ] **Step 2: Verify RED**

Run `python -m pytest tests/api/test_story_routes.py -k "runtime_settings or runtime_connection" -q`.

Expected: FAIL because the endpoint still returns global/agents/strategy.

- [ ] **Step 3: Implement the strict contract**

Use `RuntimeConfiguration` for request and response. Make `/runtime-strategy` expose only non-model compatibility fields until frontend callers are removed. Route connection tests through `resolve_stage_runtime(stage)` and return supplier, stage, and model in the result message.

- [ ] **Step 4: Verify GREEN and commit**

Run `python -m pytest tests/api/test_story_routes.py -q`; expect all tests pass.

```powershell
git add apps/api/routes/stories.py tests/api/test_story_routes.py
git commit -m "refactor: expose provider stage runtime api"
```

### Task 5: Rebuild the Configuration Page Around Real Stages

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/components/config/ConfigPageClient.tsx`
- Modify: `apps/web/components/config/GlobalApiConfigCard.tsx`
- Modify: `apps/web/components/config/RuntimeStrategyCard.tsx`
- Delete if unused: `apps/web/components/config/AgentOverrideGrid.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing Playwright tests**

Mock the new API and assert the page shows exactly “剧情规划模型”“正文写作模型”“记忆回写模型”. Assert “全局默认模型”“角色代理模型” are absent. Verify supplier switching retains separate values, and each test button sends its stage and model.

- [ ] **Step 2: Verify RED**

Run `npm.cmd run test:e2e -- story-workbench.spec.ts --grep "供应商阶段配置"` from `apps/web`.

Expected: FAIL because the new contract and controls do not exist.

- [ ] **Step 3: Implement TypeScript contract and UI**

Add `RuntimeStageName`, stage settings, provider settings, and runtime configuration types. Render one supplier selector, supplier-specific connection fields, and three compact stage model rows with test buttons. Remove `AgentOverrideGrid` from this flow and delete it when `rg "AgentOverrideGrid" apps/web` finds no consumer.

- [ ] **Step 4: Verify GREEN, build, and commit**

Run the focused Playwright command, then `npm.cmd run build`; expect zero failures and exit 0.

```powershell
git add apps/web/lib/api.ts apps/web/components/config apps/web/tests/story-workbench.spec.ts
git commit -m "feat: configure real writing stages by provider"
```

### Task 6: Migrate Live Data and Verify End to End

**Files:**
- Runtime data only: `%USERPROFILE%/.novel-autogrowth-engine/runtime_config.json`

- [ ] **Step 1: Back up and migrate live configuration**

Copy the current file to `runtime_config.pre-stage-config.json`. Start the API once, then verify `GET /runtime-settings` contains no legacy fields and all three Codex CLI stages use `gpt-5.4`. Do not commit either user file.

- [ ] **Step 2: Run full backend verification**

Run `python -m pytest -q`; expected result is zero failures.

- [ ] **Step 3: Run full frontend verification**

From `apps/web`, run `npm.cmd run build` and `npm.cmd run test:e2e`; expected result is build exit 0 and zero Playwright failures.

- [ ] **Step 4: Verify the live page and CLI argument**

Open `http://localhost:3000/config`, confirm only three stage fields appear, run one connection test, and confirm the result names supplier, stage, and model. Use the provider unit test capture as evidence that `--model` equals the page value.

- [ ] **Step 5: Check repository cleanliness**

Run `git diff --check` and `git status --short`. Commit only repository fixture or documentation changes if any remain; never commit the user runtime configuration or its backup.
