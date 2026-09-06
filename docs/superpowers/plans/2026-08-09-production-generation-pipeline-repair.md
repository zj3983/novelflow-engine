# Production Generation Pipeline Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复真实小说生成链路，使导演、写手、事实审稿和事实提取读取正确资料，稳定生成满足篇幅与连续性要求的候选章节，并完整记录每一步调用。

**Architecture:** 保留“导演决定写什么，写手决定怎么写，事实审稿只查硬事实，事实提取只提出连续性变更”的四段边界。先统一旧项目与新项目的上下文视图，再让导演始终产出可执行场景计划；写手只接收导演产物、相关角色状态、世界规则和明确篇幅，不读取整份项目。机器可判定的问题在候选稿保存前检查，模型审稿失败时不得静默判定通过。

**Tech Stack:** Python 3.11、Pydantic v2、pytest、FastAPI、Next.js 14、现有 RuntimeModelGateway/CLI/API 运行时。

---

## Scope And Acceptance

本计划修复本次真实测试确认的七个问题：

1. `.story-system` 只有运行产物时错误跳过 `.webnovel` 数据，造成串书。
2. 有章节细纲时导演被跳过，产物没有场景节拍、实体要求和钩子。
3. 写手不知道明确篇幅，也看不到主角的游戏状态、装备和任务。
4. 事实审稿只依赖模型且失败时放行，未拦截明显矛盾。
5. 事实提取把普通四字短语识别成新实体。
6. 模块化调用没有进入提示词日志，工作流记录缺少 provider/model。
7. 候选稿页面显示“通过”，直到确认时才因 3800 字门槛失败。

完成标准：

- 导演读取当前书的大纲、上一章、伏笔、角色状态，不出现其他作品内容。
- 导演产物至少包含 2 个有因果结果的场景节拍；章节细纲不能直接充当标题。
- 写手提示词明确包含目标 `4200-5500` 字和硬范围 `3800-6000` 字。
- 网游主角状态中明确出现职业、等级、装备、属性、库存和任务时，写手上下文必须保留这些字段。
- 低于 3800 字、导演产物不完整、事实审稿不可用或存在阻断矛盾时，候选稿质量必须显示失败。
- 普通叙述短语不再进入 `reference_validation`；新人物只由导演实体要求或结构化事实提出。
- 导演、写手、事实审稿的 provider、model、输入模块、耗时和输出摘要均可在工作台查看。

## File Map

- `packages/story_core/agents/pipeline.py`：组合新旧上下文，传递导演、写手、审稿和事实提取结果。
- `packages/story_core/context/director_context.py`：导演结构上下文。
- `packages/story_core/context/writer_context.py`：写手操作上下文和角色当前状态投影。
- `packages/story_core/context/legacy_adapter.py`：旧 `.webnovel` 数据到模块化上下文的只读适配。
- `packages/story_core/agents/contracts.py`：导演和写手之间的稳定契约。
- `packages/story_core/agents/director/agent.py`：导演唯一执行入口。
- `packages/story_core/agents/director/prompt.py`：把章节细纲转成可执行场景计划。
- `packages/story_core/agents/writer/prompt.py`：正文提示词，仅渲染写手需要的上下文。
- `packages/story_core/agents/consistency/agent.py`：只检查事实、状态和导演计划。
- `packages/story_core/agents/fact_extractor/agent.py`：生成候选连续性变更。
- `packages/story_core/agents/pipeline_artifacts.py`：阶段记录和可视化摘要。
- `packages/story_core/prompt_call_log.py`：真实模型调用日志。
- `packages/story_core/file_project_store.py`：候选稿质量与确认门槛。
- `apps/api/routes/file_projects.py`：工作台阶段数据接口。
- `apps/web/app/projects/[id]/write/page.tsx`：工作台阶段状态展示。

---

### Task 1: Finish The Legacy/Canonical Context Compatibility Fix

**Files:**
- Modify: `packages/story_core/agents/pipeline.py:147-330`
- Test: `tests/story_core/test_modular_pipeline_e2e.py`

- [ ] **Step 1: Preserve the two failing regression cases already added**

The tests must cover a project that has `.story-system/workflow/` but no canonical `outline.json`, plus legacy string facts and a dict `progression_ledger`:

```python
def test_director_context_falls_back_to_legacy_when_story_system_is_partial(tmp_path):
    _seed_legacy_project(tmp_path, with_outline=True)
    (tmp_path / ".story-system" / "workflow").mkdir(parents=True)
    state = json.loads((tmp_path / ".webnovel/state.json").read_text("utf-8"))
    state["chapter_summaries"] = [{
        "chapter_number": 1,
        "summary": "主角进入游戏。",
        "facts": ["主角仍是一级。"],
    }]
    _write_json(tmp_path / ".webnovel/state.json", state)

    context = _ensure_director_context(project_root=tmp_path, chapter_number=2)

    assert context.book_outline_summary == "概述"
    assert context.character_cards[0]["role"] == "protagonist"
    assert context.continuity_ledger == [
        {"subject": "", "field": "fact", "value": "主角仍是一级。"}
    ]
```

- [ ] **Step 2: Run the regression tests**

Run:

```powershell
pytest -q tests/story_core/test_modular_pipeline_e2e.py -k "falls_back_to_legacy_when_story_system_is_partial"
```

Expected: `2 passed`.

- [ ] **Step 3: Keep the merge rule field-based, not directory-based**

Use canonical values when non-empty and fill only missing values from legacy:

```python
return canonical.model_copy(update={
    "volume": canonical.volume or legacy.volume,
    "nearby_outline": canonical.nearby_outline or legacy.nearby_outline,
    "previous_chapter_summary": (
        canonical.previous_chapter_summary or legacy.previous_chapter_summary
    ),
    "continuity_ledger": canonical.continuity_ledger or legacy.continuity_ledger,
    "character_cards": canonical.character_cards or legacy.character_cards,
})
```

Normalize string facts once at the adapter boundary:

```python
def _normalize_legacy_facts(items: Any) -> list[dict[str, Any]]:
    return [
        dict(item) if isinstance(item, dict)
        else {"subject": "", "field": "fact", "value": str(item).strip()}
        for item in (items or [])
        if isinstance(item, dict) or str(item or "").strip()
    ]
```

- [ ] **Step 4: Verify the complete modular context group**

Run:

```powershell
pytest -q tests/story_core/test_modular_pipeline_e2e.py tests/story_core/test_legacy_context_adapter.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit only this compatibility change**

```powershell
git add packages/story_core/agents/pipeline.py tests/story_core/test_modular_pipeline_e2e.py
git commit -m "fix: merge partial canonical and legacy agent context"
```

---

### Task 2: Make The Director Produce An Executable Plan Every Time

**Files:**
- Modify: `packages/story_core/agents/contracts.py`
- Modify: `packages/story_core/agents/director/agent.py:61-170`
- Modify: `packages/story_core/agents/director/prompt.py`
- Modify: `packages/story_core/agents/pipeline.py` module documentation
- Modify: `packages/story_core/orchestrator.py:4090-4130`
- Test: `tests/story_core/test_modular_director_agent.py`
- Test: `tests/story_core/test_modular_pipeline_e2e.py`

- [ ] **Step 1: Replace the outline-shortcut test with a runtime-call test**

```python
def test_director_uses_target_outline_as_input_instead_of_returning_it_verbatim(tmp_path):
    runtime = _RecordingRuntime(responses=[{
        "chapter_title": "灰狼坡的红光",
        "chapter_goal": "交付清道夫任务后赶到动态事件外围",
        "opening_state": "夜烬为Lv.2，任务进度8/16",
        "scene_beats": [
            {"order": 1, "location": "灰狼坡", "action": "补齐八份毒腺", "result": "任务达到16/16"},
            {"order": 2, "location": "灰烬村", "action": "提交清道夫任务", "result": "升到Lv.3"},
            {"order": 3, "location": "灰狼坡北侧", "action": "观察动态事件", "result": "确认首领机制"},
        ],
        "ending_state": "夜烬留在事件外围",
        "hook": "流霜打断狼王冲锋",
        "entity_requirements": [{"kind": "character", "name": "流霜"}],
    }])
    context = _context_with_outline(chapter_number=2, include_target=True)

    artifact = DirectorAgent(runtime=runtime, project_root=tmp_path).plan(context)

    assert runtime.call_count == 1
    assert artifact.chapter_title == "灰狼坡的红光"
    assert len(artifact.scene_beats) == 3
    assert artifact.chapter_goal != context.nearby_outline[0]["summary"]
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```powershell
pytest -q tests/story_core/test_modular_director_agent.py::test_director_uses_target_outline_as_input_instead_of_returning_it_verbatim
```

Expected: FAIL because the current `_outline_artifact()` returns without calling the runtime.

- [ ] **Step 3: Remove `_outline_artifact()` and always call the director runtime**

`DirectorAgent.plan()` must always build a prompt and parse a structured response:

```python
prompt = build_director_prompt(context)
response = self._runtime.complete(_ModelRequest(
    prompt=prompt,
    stage="director",
    metadata={
        "chapter_number": context.chapter_number,
        "agent": "director",
        "schema_version": "director-artifact/v1",
    },
))
payload = _extract_payload(response)
payload.setdefault("chapter_number", context.chapter_number)
artifact = parse_director_response(payload)
```

Do not keep an `outline_only` status. The stored status is `ok` only after a valid model artifact is parsed.

Add a dedicated title field to the contract so downstream code never substitutes `chapter_goal` for a title:

```python
class DirectorArtifact(BaseModel):
    schema_version: Literal["director-artifact/v1"] = "director-artifact/v1"
    chapter_number: int
    chapter_title: str = ""
    chapter_goal: str
    opening_state: str
    scene_beats: list[SceneBeat]
    ending_state: str
    hook: str = ""
    entity_requirements: list[EntityRequirement] = Field(default_factory=list)
```

`parse_director_response()` reads `chapter_title`. In `_generate_next_chapter_bundle_via_modular_agents()`, use `director_artifact.chapter_title.strip()` and fall back only to `f"第{chapter_number}章"`; never use `chapter_goal` as the title.

- [ ] **Step 4: Validate director output before writing**

Add a focused validator in `director/agent.py`:

```python
def _validate_executable_artifact(artifact: DirectorArtifact) -> None:
    if len(artifact.scene_beats) < 2:
        raise ValueError("director_artifact_insufficient_beats")
    if any(not beat.location or not beat.action or not beat.result for beat in artifact.scene_beats):
        raise ValueError("director_artifact_incomplete_beat")
    if not artifact.chapter_goal.strip() or not artifact.ending_state.strip():
        raise ValueError("director_artifact_missing_state")
```

Call it before saving the artifact. A bad director response stops generation instead of making the writer improvise the missing plan.

- [ ] **Step 5: Make the target outline explicit in the prompt**

Render one separate section for the target chapter and keep neighboring chapters as boundaries:

```python
## 本章细纲（必须展开，不得照抄为标题或正文）
标题：灰狼坡的红光
目标：...
阻碍：...
行动：...

## 相邻章节边界
- 上一章：...
- 下一章：...
```

The prompt must say: `输出简短chapter_title、2至5个有因果结果的scene_beats；不得把整段细纲作为chapter_goal或标题。`

- [ ] **Step 6: Verify director tests**

Run:

```powershell
pytest -q tests/story_core/test_modular_director_agent.py tests/story_core/test_modular_pipeline_e2e.py
```

Expected: all tests pass and no assertion expects `outline_only`.

- [ ] **Step 7: Commit**

```powershell
git add packages/story_core/agents/contracts.py packages/story_core/agents/director packages/story_core/agents/pipeline.py packages/story_core/orchestrator.py tests/story_core/test_modular_director_agent.py tests/story_core/test_modular_pipeline_e2e.py
git commit -m "fix: require executable director artifacts"
```

---

### Task 3: Give The Writer A Complete But Bounded Writing Packet

**Files:**
- Modify: `packages/story_core/agents/contracts.py`
- Modify: `packages/story_core/context/writer_context.py`
- Modify: `packages/story_core/agents/pipeline.py`
- Modify: `packages/story_core/agents/writer/prompt.py`
- Test: `tests/story_core/test_modular_writer_agent.py`
- Test: `tests/story_core/test_modular_pipeline_e2e.py`

- [ ] **Step 1: Add failing tests for length and dual-state rendering**

```python
def test_writer_prompt_contains_numeric_length_policy_and_current_character_state():
    request = WriterRequest(
        chapter_number=2,
        director_artifact=_artifact(),
        target_chars={"min": 4200, "max": 5500},
        acceptance_chars={"min": 3800, "max": 6000},
        character_cards=[{
            "name": "苏叶",
            "role": "protagonist",
            "real_state": {"current": {"balance": "61.10元"}},
            "game_state": {"current": {
                "game_id": "夜烬",
                "level": "Lv.2",
                "class_path": "见习者（未转职）",
                "equipment": {"main_hand": "新手法杖"},
                "inventory": {"灰狼毒腺": 8},
                "quests": {"active": "清道夫：8/16；未提交"},
            }},
        }],
    )

    prompt = build_writer_prompt(request)

    assert "目标4200至5500字" in prompt
    assert "低于3800字不能交稿" in prompt
    assert "新手法杖" in prompt
    assert "清道夫：8/16；未提交" in prompt
```

- [ ] **Step 2: Run the test and confirm it fails**

```powershell
pytest -q tests/story_core/test_modular_writer_agent.py::test_writer_prompt_contains_numeric_length_policy_and_current_character_state
```

Expected: FAIL because `WriterRequest` has no length fields and the renderer drops `real_state/game_state`.

- [ ] **Step 3: Extend `WriterRequest` with transport-neutral policy fields**

```python
class WriterRequest(BaseModel):
    chapter_number: int
    director_artifact: DirectorArtifact
    project_title: str = ""
    genre: str = ""
    target_chars: dict[str, int] = Field(default_factory=lambda: {"min": 4200, "max": 5500})
    acceptance_chars: dict[str, int] = Field(default_factory=lambda: {"min": 3800, "max": 6000})
    previous_tail: str = ""
    continuity_facts: list[Any] = Field(default_factory=list)
    character_cards: list[dict] = Field(default_factory=list)
    entity_cards: list[dict] = Field(default_factory=list)
    world_rules: list[Any] = Field(default_factory=list)
    craft_modules: list[dict] = Field(default_factory=list)
```

These fields are generic. Game-specific rules remain in genre/world modules and game-specific state appears only when a character actually has `game_state`.

Add `project_title` and `genre` to `WriterContext`. `build_writer_context()` reads them from canonical `.story-system/project.json`; `_legacy_writer_context()` reads them through `legacy_project_view(system_root)`. `_build_writer_request()` copies both fields and the two length ranges into `WriterRequest`:

```python
return WriterRequest(
    chapter_number=context.chapter_number,
    director_artifact=director_artifact,
    project_title=context.project_title,
    genre=context.genre,
    target_chars={"min": 4200, "max": 5500},
    acceptance_chars={"min": 3800, "max": 6000},
    previous_tail=context.previous_tail,
    continuity_facts=context.continuity_facts,
    character_cards=context.character_cards,
    entity_cards=context.entity_cards,
    world_rules=context.world_rules,
    craft_modules=context.craft_modules,
)
```

- [ ] **Step 4: Render only the current state, not the whole role card**

Add a compact JSON renderer:

```python
def _current_character_state(card: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for namespace in ("current_state", "real_state", "game_state"):
        value = card.get(namespace)
        if isinstance(value, dict):
            current = value.get("current") if isinstance(value.get("current"), dict) else value
            if current:
                state[namespace] = current
    return state
```

Render with `json.dumps(state, ensure_ascii=False, separators=(",", ":"))`. Do not include personality dumps, memory arrays, old chapter histories or unrelated characters.

- [ ] **Step 5: Render concrete length instructions**

```python
sections.append(
    f"## 篇幅\n正文目标{target_min}至{target_max}字；"
    f"低于{hard_min}字或超过{hard_max}字不能交稿。"
)
```

Remove the vague sentence `控制在目标篇幅内`.

- [ ] **Step 6: Add a deterministic pre-candidate length result**

In `run_writer`, calculate compact body length immediately and add a blocking finding when outside the hard range:

```python
body_chars = len("".join(result.body.split()))
if body_chars < request.acceptance_chars["min"]:
    consistency_findings.append(ConsistencyFinding(
        code="chapter.length_too_short",
        message=f"正文约{body_chars}字，低于{request.acceptance_chars['min']}字。",
        source="deterministic",
        blocking=True,
    ))
```

This makes the candidate page show failure immediately; confirmation remains the final duplicate guard.

- [ ] **Step 7: Verify writer and candidate tests**

```powershell
pytest -q tests/story_core/test_modular_writer_agent.py tests/story_core/test_modular_pipeline_e2e.py tests/story_core/test_candidate_confirmation_transaction.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add packages/story_core/agents/contracts.py packages/story_core/context/writer_context.py packages/story_core/agents/pipeline.py packages/story_core/agents/writer/prompt.py tests/story_core/test_modular_writer_agent.py tests/story_core/test_modular_pipeline_e2e.py
git commit -m "fix: pass concrete chapter policy and current state to writer"
```

---

### Task 4: Make Fact Consistency Review Fail Closed And Fact-Focused

**Files:**
- Modify: `packages/story_core/agents/consistency/agent.py`
- Modify: `packages/story_core/agents/pipeline.py`
- Create: `tests/story_core/test_modular_consistency_agent.py`
- Test: `tests/story_core/test_modular_pipeline_e2e.py`

- [ ] **Step 1: Add failing tests for state contradiction and unavailable review**

```python
def test_consistency_prompt_includes_relevant_character_state():
    prompt = build_consistency_prompt(
        body="夜烬握紧新手短剑。",
        director_artifact=_artifact(),
        active_facts=[],
        character_states=[{"name": "苏叶", "game_state": {"equipment": {"main_hand": "新手法杖"}}}],
    )
    assert "新手法杖" in prompt
    assert "新手短剑" in prompt


def test_consistency_runtime_failure_is_not_silent_pass():
    class BrokenRuntime:
        def complete(self, request):
            raise RuntimeError("offline")

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        character_states=[],
        runtime=BrokenRuntime(),
    )
    assert findings[0].code == "consistency.unavailable"
    assert findings[0].blocking is True
```

- [ ] **Step 2: Run and confirm failure**

```powershell
pytest -q tests/story_core/test_modular_consistency_agent.py -k "character_state or unavailable"
```

Expected: FAIL because state is absent and exceptions are swallowed in `run_writer`.

- [ ] **Step 3: Pass relevant current state into the fact review**

Extend `build_consistency_prompt` and `focused_consistency_review` with `character_states`. Render only names plus current state namespaces. Keep the instruction narrow:

```text
只检查：人物身份、位置、职业、等级、属性、装备、库存、任务、已知信息、导演场景结果。
不要评价文笔、节奏、对话、修辞或爽点。
```

- [ ] **Step 4: Stop swallowing runtime and parse failures**

Return one blocking finding instead of `[]`:

```python
except Exception as exc:
    return [ConsistencyFinding(
        code="consistency.unavailable",
        message=f"事实审稿未完成：{type(exc).__name__}",
        source="consistency",
        blocking=True,
    )]
```

If the response is not the required JSON object/list, return `consistency.invalid_response` as blocking.

- [ ] **Step 5: Keep style findings advisory**

Retain `_STYLE_CODES` downgrade behavior. This task must not bring back reader/editor/reviewer style agents or add another model call.

- [ ] **Step 6: Verify**

```powershell
pytest -q tests/story_core/test_modular_consistency_agent.py tests/story_core/test_modular_pipeline_e2e.py
```

Expected: all pass; runtime failure produces a visible blocking finding.

- [ ] **Step 7: Commit**

```powershell
git add packages/story_core/agents/consistency/agent.py packages/story_core/agents/pipeline.py tests/story_core/test_modular_consistency_agent.py tests/story_core/test_modular_pipeline_e2e.py
git commit -m "fix: make factual consistency review fail closed"
```

---

### Task 5: Remove Phrase-Based Fake Entity Detection

**Files:**
- Modify: `packages/story_core/agents/fact_extractor/agent.py:386-434`
- Test: `tests/story_core/test_fact_extractor.py`

- [ ] **Step 1: Add a regression test using the actual false-positive pattern**

```python
def test_fact_extractor_does_not_treat_sentence_fragments_as_entities():
    body = (
        "夜烬深吸了一口气，将注意力拉回灰狼坡。"
        "很显然，那边触发了动态事件。"
        "稳妥起见，他先把任务做完。"
    )
    canon_view = {
        "by_id": {"char-yeyan": {"kind": "character", "canonical_name": "夜烬"}},
        "by_kind": {"character": ["char-yeyan"]},
        "by_alias": {"夜烬": ["char-yeyan"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    orphan_names = {item["name"] for item in delta.reference_validation if item["status"] == "orphan"}
    assert orphan_names == set()
```

- [ ] **Step 2: Run and confirm failure**

```powershell
pytest -q tests/story_core/test_fact_extractor.py::test_fact_extractor_does_not_treat_sentence_fragments_as_entities
```

Expected: FAIL with orphan names such as `夜烬深吸`、`将注意力`、`很显然`.

- [ ] **Step 3: Delete `_CANDIDATE_NAME_RE` and its sentence-start orphan pass**

`_collect_referenced_names()` should collect only:

```python
for sentence in _split_sentences(context.body):
    for name, _ in _find_entity_in_sentence(sentence, canon_view):
        pairs.append((name, "subject"))
    transfer = _TRANSFER_VERB_RE.search(sentence)
    if transfer:
        for name in (transfer.group("source"), transfer.group("target")):
            if _resolve_entity_id(name, canon_view):
                pairs.append((name, "transfer"))
```

Unknown entities must enter through `DirectorArtifact.entity_requirements` or a structured model delta, not through arbitrary prose fragments.

- [ ] **Step 4: Preserve a real unknown-entity test through director requirements**

```python
def test_unknown_director_requirement_is_flagged_as_orphan():
    context = _context("守龛人推门进来。", director_artifact=_artifact_with_requirement("守龛人"))
    delta = FactExtractor().extract(context)
    assert any(x["name"] == "守龛人" and x["status"] == "orphan" for x in delta.reference_validation)
```

Implement requirement collection explicitly before validation.

- [ ] **Step 5: Verify**

```powershell
pytest -q tests/story_core/test_fact_extractor.py
```

Expected: all pass and ordinary sentence fragments never appear as entities.

- [ ] **Step 6: Commit**

```powershell
git add packages/story_core/agents/fact_extractor/agent.py tests/story_core/test_fact_extractor.py
git commit -m "fix: derive entity references from canon and director requirements"
```

---

### Task 6: Record Every Modular Model Call And Stage Input

**Files:**
- Modify: `packages/story_core/agents/director/runtime.py`
- Modify: `packages/story_core/agents/writer/runtime.py`
- Create: `packages/story_core/agents/consistency/runtime.py`
- Modify: `packages/story_core/agents/pipeline_artifacts.py`
- Modify: `packages/story_core/persistence/workflow_artifact_store.py`
- Test: `tests/story_core/test_modular_director_agent.py`
- Test: `tests/story_core/test_modular_writer_agent.py`
- Test: `tests/story_core/test_modular_pipeline_e2e.py`

- [ ] **Step 1: Add a runtime logging test**

```python
def test_gateway_writer_runtime_records_resolved_provider_model_and_prompt(tmp_path, monkeypatch):
    recorder = PromptCallLog(tmp_path)
    runtime = GatewayWriterRuntime(_FakeGateway())
    with prompt_call_recording(recorder):
        runtime.complete(_LightweightRequest(prompt="正文请求", stage="writer", metadata={"chapter_number": 2}))

    calls = recorder.list_calls()
    assert calls[-1]["agent"] == "writer"
    assert calls[-1]["provider"] == "openai"
    assert calls[-1]["model"] == "gpt-test"
    assert calls[-1]["status"] == "succeeded"
```

- [ ] **Step 2: Run and confirm failure**

```powershell
pytest -q tests/story_core/test_modular_writer_agent.py -k "records_resolved_provider_model"
```

Expected: FAIL because modular runtime calls currently bypass `start_prompt_call/finish_prompt_call`.

- [ ] **Step 3: Give consistency its own runtime route**

Create `packages/story_core/agents/consistency/runtime.py` instead of reusing `GatewayDirectorRuntime`:

```python
class GatewayConsistencyRuntime:
    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    def complete(self, request: Any) -> Any:
        translated = _translate_request(request, stage="consistency")
        return self._gateway.complete_stage("consistency", translated)
```

Move the common lightweight-request translation into one private helper shared by director, writer and consistency runtimes. Update `_default_consistency_runtime()` to return `GatewayConsistencyRuntime(gateway)`. Add an assertion that the fake gateway receives stage `consistency`, never `director`.

- [ ] **Step 4: Wrap each gateway call once**

After resolving settings and before `complete_stage`, call:

```python
call_id = start_prompt_call(
    project_id=str(metadata.get("project_id") or ""),
    chapter_number=int(metadata.get("chapter_number") or 0),
    stage=stage,
    agent=operation,
    provider=provider,
    protocol=str(getattr(settings, "protocol", "") or ""),
    model=model,
    temperature=temperature,
    user_prompt=prompt,
    prompt_chars=len(prompt),
)
```

On success call `finish_prompt_call(call_id, status="succeeded", output_chars=...)`; on exception use `status="failed"` and re-raise. Do not log API tokens or authorization headers.

- [ ] **Step 5: Populate workflow artifacts from the resolved call**

The director/writer workflow JSON must carry:

```json
{
  "provider": "antigravity",
  "model": "gemini-3.1-pro-high",
  "prompt_template_id": "modular-director-v1",
  "prompt_template_version": "1",
  "reads": [{"kind": "outline", "id": "chapter-0002"}]
}
```

Use the runtime result metadata; do not infer provider/model in the UI.

- [ ] **Step 6: Verify that copied historical prompt logs remain unchanged**

Run a modular generation against a temp project and assert exactly one new director call, one writer call and one consistency call are appended. Existing `index.jsonl` entries must not be rewritten.

- [ ] **Step 7: Run logging and pipeline tests**

```powershell
pytest -q tests/story_core/test_modular_director_agent.py tests/story_core/test_modular_writer_agent.py tests/story_core/test_modular_consistency_agent.py tests/story_core/test_modular_pipeline_e2e.py tests/story_core/test_prompt_call_log.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add packages/story_core/agents packages/story_core/persistence/workflow_artifact_store.py tests/story_core/test_modular_director_agent.py tests/story_core/test_modular_writer_agent.py tests/story_core/test_modular_consistency_agent.py tests/story_core/test_modular_pipeline_e2e.py tests/story_core/test_prompt_call_log.py
git commit -m "fix: persist modular agent calls and resolved runtime metadata"
```

---

### Task 7: Align Candidate Quality, API, And Workbench Display

**Files:**
- Modify: `packages/story_core/file_project_store.py:7196-7330`
- Modify: `apps/api/routes/file_projects.py`
- Modify: `apps/web/app/projects/[id]/write/page.tsx`
- Test: `tests/story_core/test_candidate_confirmation_transaction.py`
- Modify: `tests/api/test_workflow_artifact_routes.py`
- Modify: `tests/api/test_story_routes.py`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Add a candidate quality regression test**

```python
def test_pending_candidate_exposes_length_and_consistency_failures_before_confirm(tmp_path):
    store = _seed_store(tmp_path)
    result = store.generate_next_chapter(engine=_ShortBodyEngine(), persist=False)
    candidate = result["candidate"]

    assert candidate["quality_report"]["ok"] is False
    assert "chapter.length_too_short" in {
        issue["code"] for issue in candidate["quality_report"]["writing_review"]["blocking"]
    }
```

- [ ] **Step 2: Run and confirm failure**

```powershell
pytest -q tests/story_core/test_candidate_confirmation_transaction.py -k "exposes_length"
```

Expected: FAIL because current candidate quality says `ok=true` while confirmation later rejects it.

- [ ] **Step 3: Use one quality envelope for candidate and confirmation**

Call `_chapter_length_review(body)` while creating the candidate and merge the result into `writing_review`. Confirmation must evaluate the same stored envelope and rerun the deterministic gate to protect against tampering.

- [ ] **Step 4: Return explicit stage status through the API**

Each stage response must contain:

```json
{
  "stage_id": "writer",
  "status": "done",
  "provider": "antigravity",
  "model": "gemini-3.1-pro-high",
  "reads": ["director-artifact", "苏叶角色卡", "世界规则"],
  "output_summary": "正文1677字",
  "blocking_issues": ["正文低于3800字"]
}
```

- [ ] **Step 5: Render stage evidence without showing raw secrets**

In the workbench, show stage name, model, elapsed time, input module names, output summary and blocking issues. Keep raw prompts behind the existing prompt-details page. Never render token values.

- [ ] **Step 6: Verify API and frontend**

```powershell
pytest -q tests/api/test_workflow_artifact_routes.py tests/api/test_story_routes.py tests/story_core/test_candidate_confirmation_transaction.py
cd apps/web
npm run build
npx playwright test tests/story-workbench.spec.ts
```

Expected: backend tests pass, Next.js build succeeds, and Playwright shows the same failure before the user clicks confirm.

- [ ] **Step 7: Commit**

```powershell
git add packages/story_core/file_project_store.py apps/api/routes/file_projects.py apps/web/app/projects/[id]/write/page.tsx tests/api/test_workflow_artifact_routes.py tests/api/test_story_routes.py tests/story_core/test_candidate_confirmation_transaction.py apps/web/tests/story-workbench.spec.ts
git commit -m "fix: align candidate quality with confirmation and workbench"
```

---

### Task 8: Run A Fresh Real-Model Acceptance Test

**Files:**
- Create: `scripts/smoke_modular_generation.py`
- Modify: `README.md`
- Test fixture only: a temporary copy outside `data/exported-projects/`

- [ ] **Step 1: Add a read-only source / disposable-copy smoke script**

The script must:

```python
source = Path(args.project).resolve()
with TemporaryDirectory(prefix="xiaoshuofish-smoke-") as temp:
    copied = Path(temp) / source.name
    shutil.copytree(source, copied)
    store = FileProjectStore(copied)
    result = store.generate_next_chapter(persist=False)
    candidate = result["candidate"]
    print(json.dumps({
        "chapter": candidate["chapter_number"],
        "title": candidate["chapter_title"],
        "body_chars": len("".join(candidate["body"].split())),
        "quality_ok": candidate["quality_report"]["ok"],
        "blocking": candidate["quality_report"]["writing_review"]["blocking"],
    }, ensure_ascii=False, indent=2))
```

The script must never confirm a candidate and must verify the source directory hash before and after the run.

- [ ] **Step 2: Add deterministic smoke assertions**

For `p-gou-webgame-restored`, assert:

```python
assert "陆辰" not in body
assert "混元道塔" not in body
assert "夜烬" in body
assert 3800 <= compact_chars <= 6000
assert len(director_artifact["scene_beats"]) >= 2
assert not any(x["name"] in {"夜烬深吸", "将注意力", "很显然"} for x in reference_validation)
```

Do not require exact prose wording or exact model output.

- [ ] **Step 3: Run focused tests**

```powershell
pytest -q tests/story_core/test_modular_pipeline_e2e.py tests/story_core/test_modular_director_agent.py tests/story_core/test_modular_writer_agent.py tests/story_core/test_modular_consistency_agent.py tests/story_core/test_fact_extractor.py
```

Expected: all pass.

- [ ] **Step 4: Run the full backend suite**

```powershell
pytest -q
```

Expected: zero failures; existing environment-dependent skips are allowed.

- [ ] **Step 5: Run the frontend production build**

```powershell
cd apps/web
npm run build
```

Expected: Next.js compilation, linting and type checking succeed.

- [ ] **Step 6: Run the live model smoke test**

```powershell
python scripts/smoke_modular_generation.py data/exported-projects/p-gou-webgame-restored
```

Expected: correct book and characters, body within hard range, no blocking findings, no fake orphan phrases, source hash unchanged.

- [ ] **Step 7: Document the workflow and commit**

Add this concise flow to `README.md`:

```text
大纲/上一章/角色状态 -> 导演可执行计划 -> 实体预检 -> 写手正文
-> 确定性检查 + 事实一致性审稿 -> 连续性变更候选 -> 用户确认 -> 原子写入
```

```powershell
git add scripts/smoke_modular_generation.py README.md
git commit -m "test: add real modular generation smoke check"
```

---

## Final Verification Checklist

- [ ] `git diff --check` has no errors.
- [ ] Focused modular tests pass.
- [ ] Full `pytest -q` passes.
- [ ] `npm run build` succeeds.
- [ ] Real-model smoke uses a disposable copy and leaves the source hash unchanged.
- [ ] Director has at least two executable beats and never returns a raw outline summary as the title.
- [ ] Writer prompt displays explicit target and hard length ranges.
- [ ] Writer context includes only relevant current character state and selected rules.
- [ ] Fact review is limited to facts and fails closed when unavailable.
- [ ] Fact extractor has no loose sentence-start entity heuristic.
- [ ] Candidate quality and confirmation quality agree.
- [ ] Prompt-call and workflow records contain provider, model, reads, duration and output summary.
- [ ] No API token, authorization header or CLI credential appears in logs or UI.

## Deliberately Excluded

- 不新增读者、编辑、文风审稿等模型代理。
- 不恢复分段写作。
- 不让写手读取完整总纲、全部角色卡、全部历史日志或未启用 Skill。
- 不在这轮重写既有小说正文；先修复生成链路，再由用户决定是否重新生成。
- 不把网游规则写进通用写手提示词；网游内容继续来自题材模块、世界规则和实际角色状态。
