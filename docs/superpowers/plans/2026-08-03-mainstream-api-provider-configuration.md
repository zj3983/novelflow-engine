# Mainstream API Provider Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the shared OpenAI-compatible runtime slot with independent mainstream provider accounts and separate planner/writer bindings, while routing Anthropic and Gemini through native protocols and folding memory extraction into planner.

**Architecture:** A data-driven provider catalog owns names, protocols, endpoints, and suggested models. Runtime configuration stores independent provider accounts plus planner/writer stage bindings. A single text model gateway resolves a binding and delegates to OpenAI-compatible, Anthropic, Gemini, or Codex CLI adapters; connection tests and production calls share that gateway.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, urllib-based retry transport, Next.js/React/TypeScript, pytest, Playwright.

---

## File Map

- Create `packages/story_core/model_gateway/provider_catalog.py`: immutable built-in provider metadata and host matching.
- Create `packages/story_core/model_gateway/provider_adapters.py`: protocol request/response conversion and stable error mapping.
- Create `packages/story_core/model_gateway/runtime_gateway.py`: resolve stage bindings and execute through the correct adapter.
- Modify `packages/story_core/model_gateway/contracts.py`: carry messages, JSON mode, timeout, and protocol-neutral request metadata.
- Modify `packages/story_core/model_gateway/__init__.py`: export catalog and gateway contracts.
- Modify `packages/story_core/runtime_config.py`: provider accounts, two stage bindings, legacy migration, encrypted secrets.
- Modify `packages/story_core/agent_base.py`: route shared agent calls through the gateway.
- Modify `packages/story_core/orchestrator.py`: route planner/writer calls through the gateway and map memory extraction to planner.
- Modify direct text callers in `continuation_analysis.py`, `opening_directions.py`, `outline_planning_generation.py`, `prompt_audit_deep.py`, `publishing_assets.py`, and `world_enrichment.py` to use the runtime gateway.
- Delete `packages/story_core/memory_agent.py`: unused duplicate memory agent; keep post-draft memory normalization.
- Create `apps/api/routes/runtime_settings.py`: runtime configuration, catalog, secret reveal, and connection-test endpoints.
- Modify `apps/api/routes/stories.py` and `apps/api/main.py`: remove embedded runtime routes and register the focused router.
- Modify `apps/web/lib/api.ts`: new provider account and stage binding types plus catalog API.
- Replace `apps/web/components/config/GlobalApiConfigCard.tsx` and `RuntimeStrategyCard.tsx` with focused provider-account and stage-binding views.
- Create `apps/web/components/config/ProviderAccountsCard.tsx` and `StageBindingsCard.tsx`.
- Modify `apps/web/components/config/ConfigPageClient.tsx` and `apps/web/app/globals.css` for the new page flow.
- Add/modify tests in `tests/story_core/test_provider_catalog.py`, `test_provider_adapters.py`, `test_runtime_config.py`, `test_model_gateway_contract.py`, `tests/api/test_runtime_settings_routes.py`, and `apps/web/tests/config-page.spec.ts`.

### Task 1: Provider Catalog

**Files:**
- Create: `packages/story_core/model_gateway/provider_catalog.py`
- Modify: `packages/story_core/model_gateway/__init__.py`
- Test: `tests/story_core/test_provider_catalog.py`

- [ ] **Step 1: Write failing catalog tests**

```python
from packages.story_core.model_gateway.provider_catalog import (
    BUILTIN_PROVIDER_IDS,
    provider_definition,
    provider_id_for_base_url,
)


def test_builtin_catalog_contains_supported_protocols_and_stable_ids():
    assert {"openai", "deepseek", "kimi", "qwen", "glm", "doubao", "minimax",
            "siliconflow", "openrouter", "xai", "anthropic", "gemini", "ollama",
            "codexcli", "custom_openai"} <= set(BUILTIN_PROVIDER_IDS)
    assert provider_definition("anthropic").protocol == "anthropic"
    assert provider_definition("gemini").protocol == "gemini"
    assert provider_definition("deepseek").protocol == "openai_compatible"
    assert provider_definition("codexcli").protocol == "codex_cli"


def test_catalog_recognizes_legacy_provider_hosts():
    assert provider_id_for_base_url("https://api.deepseek.com") == "deepseek"
    assert provider_id_for_base_url("https://api.moonshot.cn/v1") == "kimi"
    assert provider_id_for_base_url("https://openrouter.ai/api/v1") == "openrouter"
    assert provider_id_for_base_url("https://unknown.example/v1") == "custom_openai"
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/story_core/test_provider_catalog.py -q`

Expected: collection fails because `provider_catalog` does not exist.

- [ ] **Step 3: Implement immutable provider definitions**

```python
@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    name: str
    protocol: Literal["openai_compatible", "anthropic", "gemini", "codex_cli"]
    default_base_url: str
    planner_models: tuple[str, ...]
    writer_models: tuple[str, ...]
    host_patterns: tuple[str, ...] = ()
    requires_api_key: bool = True
    base_url_editable: bool = True
    help_text: str = ""


def provider_id_for_base_url(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    for definition in PROVIDER_DEFINITIONS:
        if any(host == pattern or host.endswith(f".{pattern}") for pattern in definition.host_patterns):
            return definition.provider_id
    return "custom_openai"
```

Populate every ID listed by the failing test with its official default endpoint and a short conservative model list. Do not fetch model lists from the network.

- [ ] **Step 4: Run catalog tests and confirm GREEN**

Run: `python -m pytest tests/story_core/test_provider_catalog.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the catalog**

```powershell
git add packages/story_core/model_gateway/provider_catalog.py packages/story_core/model_gateway/__init__.py tests/story_core/test_provider_catalog.py
git commit -m "feat: add built-in model provider catalog"
```

### Task 2: Runtime Configuration and Legacy Migration

**Files:**
- Modify: `packages/story_core/runtime_config.py`
- Test: `tests/story_core/test_runtime_config.py`

- [ ] **Step 1: Add failing tests for accounts, bindings, and migration**

```python
def test_runtime_configuration_supports_separate_planner_and_writer_providers():
    configuration = RuntimeConfiguration.model_validate({
        "schema_version": "runtime-config/v2",
        "accounts": {
            "deepseek": {"api_key": "ds", "base_url": "https://api.deepseek.com", "custom_models": []},
            "anthropic": {"api_key": "claude", "base_url": "https://api.anthropic.com", "custom_models": []},
        },
        "stages": {
            "planner": {"provider_id": "deepseek", "model": "deepseek-chat"},
            "writer": {"provider_id": "anthropic", "model": "claude-sonnet-4-5"},
        },
    })
    assert resolve_stage_runtime("planner", configuration=configuration).provider_id == "deepseek"
    assert resolve_stage_runtime("writer", configuration=configuration).provider_id == "anthropic"
    assert resolve_stage_runtime("memory", configuration=configuration).provider_id == "deepseek"


def test_legacy_deepseek_slot_migrates_secret_and_binds_both_stages(tmp_path):
    legacy = _configuration_data(provider="openai")
    legacy["providers"]["openai"].update({
        "api_key": "deepseek-secret",
        "base_url": "https://api.deepseek.com",
        "planner": "deepseek-reasoner",
        "writer": "deepseek-chat",
        "memory": "obsolete-memory",
    })
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    migrated = load_runtime_configuration(path)
    assert migrated.accounts["deepseek"].api_key == "deepseek-secret"
    assert migrated.stages.planner.model == "deepseek-reasoner"
    assert migrated.stages.writer.model == "deepseek-chat"
    assert "memory" not in migrated.stages.model_dump()
```

Add cases for Kimi host recognition, unknown custom endpoints, Codex CLI, DPAPI round-trip, masked secret preservation, and migration idempotency.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/story_core/test_runtime_config.py -q`

Expected: failures for missing `accounts`, `stages`, and `provider_id` fields.

- [ ] **Step 3: Implement the v2 schema**

```python
RuntimeStage = Literal["planner", "writer"]
RuntimeStageInput = Literal["planner", "writer", "memory"]


class ProviderAccount(_StrictModel):
    api_key: str = ""
    base_url: str = ""
    custom_models: list[str] = Field(default_factory=list)
    codex_command: str = ""


class StageBinding(_StrictModel):
    provider_id: str
    model: str


class StageBindings(_StrictModel):
    planner: StageBinding
    writer: StageBinding


class RuntimeConfiguration(_StrictModel):
    schema_version: Literal["runtime-config/v2"] = "runtime-config/v2"
    accounts: dict[str, ProviderAccount]
    stages: StageBindings
    image: ImageRuntimeConfiguration = Field(default_factory=ImageRuntimeConfiguration)
    temperature: float = 0.7
    new_character_policy: NewCharacterPolicy = "Director review"
```

Use `RuntimeStage` in public API models and `RuntimeStageInput` only on the internal resolver. Validate provider IDs against the catalog, reject blank bound models, require configured keys for non-CLI bound providers at API-save time, and make `resolve_stage_runtime("memory")` a compatibility alias for planner.

- [ ] **Step 4: Implement v1 migration and encrypted storage**

Use `provider_id_for_base_url()` to select the destination account. Preserve the existing DPAPI helpers, but iterate over `accounts.values()` instead of fixed provider names. Before the first v2 write, copy the old file to `runtime_config.pre-provider-v2.json` only when that backup does not already exist.

- [ ] **Step 5: Run runtime tests and confirm GREEN**

Run: `python -m pytest tests/story_core/test_runtime_config.py -q`

Expected: all runtime configuration and migration tests pass.

- [ ] **Step 6: Commit the schema and migration**

```powershell
git add packages/story_core/runtime_config.py tests/story_core/test_runtime_config.py
git commit -m "feat: add provider accounts and stage bindings"
```

### Task 3: Native and Compatible Protocol Adapters

**Files:**
- Modify: `packages/story_core/model_gateway/contracts.py`
- Create: `packages/story_core/model_gateway/provider_adapters.py`
- Create: `packages/story_core/model_gateway/runtime_gateway.py`
- Modify: `packages/story_core/model_gateway/__init__.py`
- Test: `tests/story_core/test_provider_adapters.py`
- Test: `tests/story_core/test_model_gateway_contract.py`

- [ ] **Step 1: Write failing adapter tests**

```python
def test_anthropic_adapter_uses_messages_api_and_extracts_text(fake_transport):
    fake_transport.respond({"id": "msg_1", "content": [{"type": "text", "text": "正文"}]})
    response = AnthropicAdapter(fake_transport).complete(
        request(provider="anthropic", model="claude-sonnet-4-5", json_mode=False), account("key")
    )
    assert fake_transport.url == "https://api.anthropic.com/v1/messages"
    assert fake_transport.headers["x-api-key"] == "key"
    assert fake_transport.body["system"] == "system"
    assert response.text == "正文"


def test_gemini_adapter_uses_generate_content_and_json_mime(fake_transport):
    fake_transport.respond({"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]})
    response = GeminiAdapter(fake_transport).complete(
        request(provider="gemini", model="gemini-2.5-pro", json_mode=True), account("key")
    )
    assert ":generateContent" in fake_transport.url
    assert fake_transport.body["generationConfig"]["responseMimeType"] == "application/json"
    assert response.text == '{"ok":true}'


def test_openai_compatible_adapter_keeps_provider_specific_parameters_out_of_generic_requests(fake_transport):
    fake_transport.respond({"choices": [{"message": {"content": "正文"}}]})
    OpenAICompatibleAdapter(fake_transport).complete(
        request(provider="deepseek", model="deepseek-chat"), account("key")
    )
    assert fake_transport.url.endswith("/chat/completions")
    assert "parameters" not in fake_transport.body
```

Add stable error tests for 401, 404 model errors, 429, timeout, malformed response, and secret redaction.

- [ ] **Step 2: Run adapter tests and confirm RED**

Run: `python -m pytest tests/story_core/test_provider_adapters.py tests/story_core/test_model_gateway_contract.py -q`

Expected: failures because adapter classes and request fields do not exist.

- [ ] **Step 3: Extend the neutral contracts**

```python
@dataclass(frozen=True)
class ModelMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[ModelMessage, ...]
    provider: str
    model: str
    operation: str
    json_mode: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Keep compatibility constructors for current `prompt` and `system_prompt` callers until Task 4 migrates them.

- [ ] **Step 4: Implement adapters and runtime gateway**

```python
class RuntimeModelGateway:
    def complete_stage(self, stage: str, request: ModelRequest) -> ModelResponse:
        settings = self._runtime_resolver("planner" if stage == "memory" else stage)
        definition = provider_definition(settings.provider_id)
        adapter = self._adapters[definition.protocol]
        bound_request = replace(request, provider=settings.provider_id, model=settings.model)
        return adapter.complete(bound_request, settings)
```

Use the existing retry transport for HTTP execution. Anthropic uses `x-api-key` and `anthropic-version`; Gemini uses its native endpoint and key handling; OpenAI-compatible uses Bearer auth; Codex CLI delegates to the existing CLI execution code. No adapter may log request headers.

- [ ] **Step 5: Run adapter tests and confirm GREEN**

Run: `python -m pytest tests/story_core/test_provider_adapters.py tests/story_core/test_model_gateway_contract.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the gateway**

```powershell
git add packages/story_core/model_gateway tests/story_core/test_provider_adapters.py tests/story_core/test_model_gateway_contract.py
git commit -m "feat: add native and compatible model adapters"
```

### Task 4: Route Production Text Calls Through the Gateway

**Files:**
- Modify: `packages/story_core/agent_base.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/continuation_analysis.py`
- Modify: `packages/story_core/opening_directions.py`
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/prompt_audit_deep.py`
- Modify: `packages/story_core/publishing_assets.py`
- Modify: `packages/story_core/world_enrichment.py`
- Delete: `packages/story_core/memory_agent.py`
- Test: `tests/story_core/test_provider_adapters.py`
- Test: `tests/story_core/test_orchestrator.py`
- Test: `tests/story_core/test_post_draft_memory.py`

- [ ] **Step 1: Add failing routing tests**

```python
def test_orchestrator_memory_extraction_uses_planner_binding(monkeypatch, story):
    stages = []
    monkeypatch.setattr(gateway, "complete_stage", lambda stage, request: stages.append(stage) or success_json())
    StoryOrchestrator()._extract_final_body_memory(story, accepted_body(), 3)
    assert stages == ["planner"]


def test_writer_and_planner_can_use_different_provider_adapters(monkeypatch, story):
    calls = []
    monkeypatch.setattr(gateway, "complete_stage", lambda stage, request: calls.append(stage) or response_for(stage))
    generate_one_chapter(story)
    assert "planner" in calls
    assert "writer" in calls
```

Add import-graph assertions that production text modules no longer call `post_json_with_retry(..., "/chat/completions", ...)` directly. Exclude image generation.

- [ ] **Step 2: Run routing tests and confirm RED**

Run: `python -m pytest tests/story_core/test_orchestrator.py tests/story_core/test_post_draft_memory.py tests/story_core/test_provider_adapters.py -q`

Expected: routing assertions fail because callers still use direct OpenAI payloads and memory resolves separately.

- [ ] **Step 3: Replace shared agent and orchestrator calls**

Build `ModelRequest` from system/user messages in `BaseOpenAIProvider.complete`, `BaseLLMAgent.call_llm`, and `StoryOrchestrator._chat`. Pass `json_mode`, timeout, temperature, and max tokens through the gateway; parse JSON only after receiving normalized text.

Change:

```python
runtime_stage = "planner" if agent in {"director", "memory"} else agent
response = runtime_model_gateway().complete_stage(runtime_stage, request)
```

Record the resolved `provider_id`, protocol, and model in prompt-call logs.

- [ ] **Step 4: Migrate secondary text callers**

Replace injected `post_json_with_retry` defaults with an injected `ModelGateway` or a small callable accepting `stage` and `ModelRequest`. Assign opening directions, outline generation, continuation analysis, prompt audit, publishing synopsis, and world enrichment to `planner`. Keep cover image generation on its existing image provider.

- [ ] **Step 5: Remove the unused memory agent**

Delete `memory_agent.py` after `rg -n "MemoryAgent|OpenAIMemorySummaryProvider" packages apps tests` shows no live imports. Keep `post_draft_memory.py`, `memory.py`, and `apply_post_chapter_updates` unchanged except for planner routing.

- [ ] **Step 6: Run routing and continuity tests**

Run: `python -m pytest tests/story_core/test_orchestrator.py tests/story_core/test_post_draft_memory.py tests/story_core/test_opening_directions.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_continuation_analysis.py -q`

Expected: all selected tests pass and post-draft summaries/ledger updates remain populated.

- [ ] **Step 7: Commit production routing**

```powershell
git add packages/story_core tests/story_core
git commit -m "refactor: route text generation through model gateway"
```

### Task 5: Focused Runtime Settings API

**Files:**
- Create: `apps/api/routes/runtime_settings.py`
- Modify: `apps/api/routes/stories.py`
- Modify: `apps/api/main.py`
- Create: `tests/api/test_runtime_settings_routes.py`
- Modify: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write failing API contract tests**

```python
def test_runtime_settings_exposes_catalog_accounts_and_two_stage_bindings(client):
    response = client.get("/runtime-settings")
    assert response.status_code == 200
    assert set(response.json()["stages"]) == {"planner", "writer"}
    assert "memory" not in response.text


def test_provider_catalog_is_public_and_contains_native_protocols(client):
    payload = client.get("/runtime-settings/providers").json()
    by_id = {item["id"]: item for item in payload["providers"]}
    assert by_id["anthropic"]["protocol"] == "anthropic"
    assert by_id["gemini"]["protocol"] == "gemini"


def test_connection_test_uses_selected_stage_provider_without_saving(client, monkeypatch):
    captured = []
    monkeypatch.setattr(runtime_routes.gateway, "complete_stage", lambda stage, request, configuration=None: captured.append((stage, request.provider)) or ok())
    candidate = v2_configuration(planner="deepseek", writer="anthropic")
    response = client.post("/runtime-settings/test", json={"stage": "writer", "runtime_settings": candidate})
    assert response.status_code == 200
    assert captured == [("writer", "anthropic")]
    assert client.get("/runtime-settings").json() != candidate
```

Add tests for per-provider secret reveal, masked updates, invalid bindings, absent API keys, request-size limits, secret-safe validation errors, and CLI information.

- [ ] **Step 2: Run API tests and confirm RED**

Run: `python -m pytest tests/api/test_runtime_settings_routes.py -q`

Expected: 404 for provider catalog and schema mismatches for stage bindings.

- [ ] **Step 3: Extract the runtime router**

Move runtime request models, serialization, secret restoration, connection tests, CLI info, and body-size guard ownership into `runtime_settings.py`. Register it from `main.py`. Keep endpoint URLs stable except for adding `GET /runtime-settings/providers`.

Use request bodies:

```python
class RuntimeSettingsTestRequest(BaseModel):
    stage: Literal["planner", "writer"]
    runtime_settings: RuntimeConfiguration


class RuntimeApiKeyRevealRequest(BaseModel):
    provider_id: str
```

The connection test calls the same runtime gateway as production with a one-token prompt and never persists the candidate configuration.

- [ ] **Step 4: Remove duplicate route code and run tests**

Run: `python -m pytest tests/api/test_runtime_settings_routes.py tests/api/test_story_routes.py -q`

Expected: all tests pass; FastAPI reports no duplicate route operation IDs.

- [ ] **Step 5: Commit the API split**

```powershell
git add apps/api/routes/runtime_settings.py apps/api/routes/stories.py apps/api/main.py tests/api/test_runtime_settings_routes.py tests/api/test_story_routes.py
git commit -m "refactor: expose provider-based runtime settings API"
```

### Task 6: Provider Accounts and Separate Stage Bindings UI

**Files:**
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/components/config/ProviderAccountsCard.tsx`
- Create: `apps/web/components/config/StageBindingsCard.tsx`
- Modify: `apps/web/components/config/ConfigPageClient.tsx`
- Delete: `apps/web/components/config/GlobalApiConfigCard.tsx`
- Delete: `apps/web/components/config/RuntimeStrategyCard.tsx`
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/tests/config-page.spec.ts`

- [ ] **Step 1: Replace the Playwright fixture and write failing UI expectations**

```typescript
test("/config keeps provider accounts separate and binds planner/writer independently", async ({ page }) => {
  await mockProviderCatalog(page);
  await mockRuntimeV2(page);
  await page.goto("/config");

  await expect(page.getByLabel("剧情规划供应商")).toHaveValue("deepseek");
  await expect(page.getByLabel("正文写作供应商")).toHaveValue("anthropic");
  await expect(page.getByText("记忆回写模型")).toHaveCount(0);
  await expect(page.getByText("正文状态提取跟随剧情规划模型")).toBeVisible();

  await page.getByRole("button", { name: "Kimi" }).click();
  await page.getByLabel("API 密钥").fill("kimi-key");
  await page.getByRole("button", { name: "DeepSeek" }).click();
  await expect(page.getByLabel("API 密钥")).not.toHaveValue("kimi-key");
});
```

Add tests for Claude/Gemini protocol labels, preset plus custom models, Codex CLI fields, custom endpoint validation, secret reveal cancellation, independent connection tests, and save/reload.

- [ ] **Step 2: Run Playwright and confirm RED**

Run: `npm --prefix apps/web run test:e2e -- config-page.spec.ts`

Expected: missing provider account and stage binding controls.

- [ ] **Step 3: Add v2 frontend types and normalization**

```typescript
export type RuntimeStageName = "planner" | "writer";
export type ProviderProtocol = "openai_compatible" | "anthropic" | "gemini" | "codex_cli";
export type RuntimeProviderAccount = {
  api_key: string;
  base_url: string;
  custom_models: string[];
  codex_command: string;
};
export type RuntimeStageBinding = { provider_id: string; model: string };
export type RuntimeSettings = {
  schema_version: "runtime-config/v2";
  accounts: Record<string, RuntimeProviderAccount>;
  stages: Record<RuntimeStageName, RuntimeStageBinding>;
  image: RuntimeImageSettings;
  temperature: number;
  new_character_policy: AgentSettings["new_character_policy"];
};
```

Add `fetchRuntimeProviderCatalog()` and change secret reveal to submit `{provider_id}`.

- [ ] **Step 4: Implement the two focused cards**

`StageBindingsCard` renders exactly two stable rows. Provider options come from the catalog; model options combine stage presets with that account's custom models and preserve an existing unknown model.

`ProviderAccountsCard` uses a compact provider list and one unframed editor. It shows status, protocol, endpoint, secret controls, custom models, and one provider connection test. Do not render a card inside another card.

- [ ] **Step 5: Wire validation and saving**

Block save when a bound provider lacks a required key, a bound model is blank, a custom endpoint is invalid, or the Codex command is blank. Reset connection status only for the account or stage whose configuration changed.

- [ ] **Step 6: Run UI tests and production build**

Run: `npm --prefix apps/web run test:e2e -- config-page.spec.ts`

Run: `npm --prefix apps/web run build`

Expected: Playwright passes and Next.js production build exits 0.

- [ ] **Step 7: Commit the configuration UI**

```powershell
git add apps/web/lib/api.ts apps/web/components/config apps/web/app/globals.css apps/web/tests/config-page.spec.ts
git commit -m "feat: add provider accounts and stage bindings UI"
```

### Task 7: Migration Verification and Full Regression

**Files:**
- Modify only files required by failures found below.
- Test: all focused runtime, API, workflow, and frontend suites.

- [ ] **Step 1: Back up and migrate the current user configuration**

Start the backend once with the v2 loader. Verify with a redacted script that:

```text
schema_version=runtime-config/v2
planner.provider_id=deepseek
writer.provider_id=deepseek
accounts.deepseek.api_key_configured=true
accounts.deepseek.base_url=https://api.deepseek.com
```

Never print the API key. Confirm `runtime_config.pre-provider-v2.json` exists and the active file contains a DPAPI value rather than plaintext.

- [ ] **Step 2: Run the full focused backend suite**

Run:

```powershell
python -m pytest tests/story_core/test_provider_catalog.py tests/story_core/test_provider_adapters.py tests/story_core/test_runtime_config.py tests/story_core/test_model_gateway_contract.py tests/story_core/test_orchestrator.py tests/story_core/test_post_draft_memory.py tests/api/test_runtime_settings_routes.py tests/api/test_story_routes.py -q
```

Expected: 0 failed.

- [ ] **Step 3: Run structural checks**

Run:

```powershell
rg -n 'RuntimeStage.*memory|memory_model|providers\.openai|/chat/completions' packages/story_core apps/api apps/web --glob '*.py' --glob '*.ts' --glob '*.tsx'
```

Expected: no public runtime `memory` field, no fixed `providers.openai` slot, and no direct text-generation `/chat/completions` call outside `provider_adapters.py` and transport tests. Historical `agent_runtime.memory` records may remain.

- [ ] **Step 4: Run frontend verification**

Run:

```powershell
npm --prefix apps/web run test:e2e -- config-page.spec.ts
npm --prefix apps/web run build
```

Expected: both commands exit 0.

- [ ] **Step 5: Smoke-test live DeepSeek without exposing secrets**

Start API and web services, load `/config`, test the configured DeepSeek planner and writer bindings, then call `GET /runtime-settings`. Confirm both tests return `ok=true`, provider ID is `deepseek`, and returned keys are masked.

- [ ] **Step 6: Review the final diff and commit residual fixes**

```powershell
git diff --check
git status --short
git add <only files changed for this feature>
git commit -m "test: verify provider configuration migration"
```

Do not stage unrelated pre-existing changes.
