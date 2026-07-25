# Genre Power System Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every novel type a concrete supernatural power-system skeleton, generate and validate a project-specific structured system, and upgrade `p-gou-webgame-restored` to a coherent six-class MMO progression.

**Architecture:** Add an editable `power_system_template` to the novel-type record and a focused `power_systems.py` domain module for normalization, validation, summaries, and prompt slices. Store generated project details under `world_blueprint.power_system_spec`, preserve the legacy `power_system` list as a derived summary, and pass only stage-relevant structured slices into outline and writing prompts.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, pytest, Next.js/React, TypeScript, Playwright.

---

## File Map

- Create `packages/story_core/power_system_templates.py`: immutable built-in skeletons for all eight novel types.
- Create `packages/story_core/power_systems.py`: project-spec normalization, completeness validation, legacy summary, and prompt slicing.
- Modify `packages/story_core/genre_types/base.py`: expose `power_system_template` on `GenrePlugin`.
- Modify the eight files in `packages/story_core/genre_types/`: attach the matching built-in skeleton.
- Modify `packages/story_core/novel_type_library.py`: persist editable skeletons and inherit the generic skeleton for custom types.
- Modify `packages/story_core/novel_type_catalog.py`: include a compact skeleton in generation prompt context.
- Modify `apps/api/routes/novel_types.py` and `apps/web/lib/api.ts`: transport the new field.
- Modify `packages/story_core/world_enrichment.py`: request, validate, merge, and summarize `power_system_spec`.
- Modify `packages/story_core/world_blueprint_context.py`: render the structured system to Markdown and preserve hand-written files.
- Modify `packages/story_core/world_blueprint_context.py` and its prompt consumers: select stage-relevant power context.
- Modify `apps/web/components/novel-types/NovelTypeLibraryClient.tsx`: edit the type skeleton as JSON.
- Modify `apps/web/components/ws/WorldRulesEditor.tsx`: display structured project sections and legacy fallback status.
- Create `scripts/upgrade_project_power_system.py`: idempotent current-project migration with backup.
- Modify the matching pytest and Playwright suites listed below.

### Task 1: Built-In Type Skeletons

**Files:**
- Create: `packages/story_core/power_system_templates.py`
- Modify: `packages/story_core/genre_types/base.py`
- Modify: `packages/story_core/genre_types/generic.py`
- Modify: `packages/story_core/genre_types/game_webnovel.py`
- Modify: `packages/story_core/genre_types/xuanhuan.py`
- Modify: `packages/story_core/genre_types/xianxia.py`
- Modify: `packages/story_core/genre_types/urban.py`
- Modify: `packages/story_core/genre_types/romance.py`
- Modify: `packages/story_core/genre_types/suspense.py`
- Modify: `packages/story_core/genre_types/rules_mystery.py`
- Test: `tests/story_core/test_power_system_templates.py`

- [ ] **Step 1: Write the failing skeleton coverage test**

```python
from packages.story_core.genre_types import (
    GAME_WEBNOVEL, GENERIC_WEBNOVEL, ROMANCE, RULES_MYSTERY,
    SUSPENSE, URBAN, XIANXIA, XUANHUAN,
)

REQUIRED = {
    "system_form", "required_sections", "progression_shape",
    "branching_rules", "resource_rules", "cost_rules",
    "conflict_rules", "ledger_fields", "quality_checks",
}

def test_every_builtin_type_has_complete_power_system_template():
    for plugin in (GENERIC_WEBNOVEL, GAME_WEBNOVEL, XUANHUAN, XIANXIA,
                   URBAN, ROMANCE, SUSPENSE, RULES_MYSTERY):
        assert REQUIRED <= plugin.power_system_template.keys()
        assert set(plugin.power_system_template["required_sections"]) >= {
            "origin", "stages", "paths", "skills", "resources",
            "costs", "counters", "boundaries", "continuity_ledger",
        }

def test_game_template_requires_six_classes_and_four_milestones():
    template = GAME_WEBNOVEL.power_system_template
    assert template["minimum_path_count"] == 6
    assert template["fixed_milestones"] == [1, 10, 20, 30, 60]
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/story_core/test_power_system_templates.py -q`

Expected: FAIL because `GenrePlugin` has no `power_system_template`.

- [ ] **Step 3: Add the typed field and eight immutable templates**

Add to `GenrePlugin`:

```python
power_system_template: dict[str, object] = field(default_factory=dict)
```

Define `POWER_SYSTEM_TEMPLATES` keyed by the canonical IDs. Every entry contains all `REQUIRED` fields. Use these exact type forms: generic `自适应超凡体系`, game `等级职业体系`, xuanhuan `境界血脉体系`, xianxia `修真因果体系`, urban `都市异能体系`, romance `血脉契约共鸣体系`, suspense `超凡调查体系`, rules mystery `规则权限污染体系`. The game entry sets `minimum_path_count=6` and `fixed_milestones=[1, 10, 20, 30, 60]`; other entries set `minimum_path_count=2` and at least three progression stages.

Attach a deep copy of the matching entry to each plugin declaration so callers cannot mutate global defaults.

- [ ] **Step 4: Run focused and existing plugin tests**

Run: `pytest tests/story_core/test_power_system_templates.py tests/story_core/test_genre_plugins.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/power_system_templates.py packages/story_core/genre_types tests/story_core/test_power_system_templates.py
git commit -m "feat: add power skeletons to novel types"
```

### Task 2: Editable Novel-Type Contract

**Files:**
- Modify: `packages/story_core/novel_type_library.py`
- Modify: `packages/story_core/novel_type_catalog.py`
- Modify: `apps/api/routes/novel_types.py`
- Modify: `apps/web/lib/api.ts`
- Test: `tests/story_core/test_novel_type_library.py`
- Test: `tests/story_core/test_novel_type_catalog.py`
- Test: `tests/api/test_novel_type_routes.py`

- [ ] **Step 1: Write failing persistence and prompt-context tests**

```python
def test_custom_type_inherits_generic_power_template(tmp_path):
    library = NovelTypeLibrary(tmp_path / "types.json")
    created = library.create({"id": "psychic_sports", "name": "异能竞技"})
    assert created.power_system_template["system_form"] == "自适应超凡体系"

def test_custom_type_can_override_power_template(tmp_path):
    library = NovelTypeLibrary(tmp_path / "types.json")
    created = library.create({
        "id": "psychic_sports", "name": "异能竞技",
        "power_system_template": {"system_form": "赛事异能体系"},
    })
    assert library.get(created.id).power_system_template["system_form"] == "赛事异能体系"

def test_prompt_context_contains_compact_power_template():
    context = novel_type_prompt_context(runtime_novel_type("game_webnovel"))
    assert context["genre_power_system_template"]["minimum_path_count"] == 6
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/story_core/test_novel_type_library.py tests/story_core/test_novel_type_catalog.py -q`

Expected: FAIL because the record and context omit the new field.

- [ ] **Step 3: Persist, serialize, and compact the field**

Add `power_system_template: dict[str, object] = field(default_factory=dict)` to `NovelTypeRecord`, deep-copy it in `from_payload()`/`to_dict()`, and merge custom records over `POWER_SYSTEM_TEMPLATES["generic_webnovel"]`. Add the same field to the FastAPI request model and TypeScript `NovelTypeRecord`/write payload.

Expose this compact context key by adding `compact_power_system_template()` to `power_system_templates.py`:

```python
context["genre_power_system_template"] = compact_power_system_template(
    record.power_system_template
)
```

Include it in the existing 6000-character budget loop, trimming quality checks before required skeleton keys.

- [ ] **Step 4: Run model, API, and runtime integration tests**

Run: `pytest tests/story_core/test_novel_type_library.py tests/story_core/test_novel_type_catalog.py tests/story_core/test_novel_type_runtime_integration.py tests/api/test_novel_type_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/power_system_templates.py packages/story_core/novel_type_library.py packages/story_core/novel_type_catalog.py apps/api/routes/novel_types.py apps/web/lib/api.ts tests/story_core tests/api/test_novel_type_routes.py
git commit -m "feat: persist power templates in novel type library"
```

### Task 3: Project Power Specification and Validation

**Files:**
- Create: `packages/story_core/power_systems.py`
- Test: `tests/story_core/test_power_systems.py`

- [ ] **Step 1: Write failing normalization and validation tests**

```python
from packages.story_core.power_systems import (
    PowerSystemValidationError, legacy_power_summary,
    normalize_power_system_spec, validate_power_system_spec,
)

def complete_spec():
    return {
        "name": "神域职业体系", "origin": ["完成觉醒任务获得职业权能"],
        "attributes": [{"name": "智力", "effect": "提高法术强度"}],
        "paths": [{"name": name, "branches": [f"{name}分支甲", f"{name}分支乙"]}
                  for name in ("战士", "法师", "游侠", "盗贼", "牧师", "召唤师")],
        "stages": [{"name": name, "entry": entry, "change": change, "failure": failure}
                   for name, entry, change, failure in (
                       ("见习者", "创建角色", "获得通用技能", "无"),
                       ("正式职业", "Lv.10转职任务", "获得职业资源", "任务冷却"),
                       ("专精", "Lv.20专精试炼", "强化战斗方向", "专精材料损失"),
                       ("进阶职业", "Lv.30分支任务", "获得分支技能", "转职延期"),
                       ("传承", "Lv.60传承试炼", "获得职业权柄", "传承反噬"),
                   )],
        "skills": ["职业技能由导师、技能书和试炼获得"],
        "equipment": ["职业熟练度限制武器与护甲"],
        "resources": ["技能消耗职业资源并通过战斗恢复"],
        "advancement": ["晋升必须满足等级、任务和材料"],
        "costs": ["透支会造成虚弱并降低恢复速度"],
        "counters": ["控制克制蓄力，突进克制远程"],
        "boundaries": ["越级只能依赖情报、环境和克制，不可无条件碾压"],
        "social_impact": ["公会按职业配置开荒队"],
        "visibility": ["只能观察已公开等级和装备"],
        "continuity_ledger": ["level", "class_path", "skills", "equipment", "resources", "conditions"],
    }

def test_game_spec_accepts_complete_six_class_system():
    result = validate_power_system_spec(complete_spec(), novel_type_id="game_webnovel")
    assert result["paths"][1]["name"] == "法师"

def test_validation_rejects_missing_costs():
    spec = complete_spec(); spec["costs"] = []
    try:
        validate_power_system_spec(spec, novel_type_id="game_webnovel")
    except PowerSystemValidationError as exc:
        assert "costs" in exc.missing_sections
    else:
        raise AssertionError("missing costs must fail")

def test_legacy_summary_is_derived_without_exact_money():
    assert legacy_power_summary(complete_spec())[0] == "力量体系：神域职业体系。"
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/story_core/test_power_systems.py -q`

Expected: ERROR importing the missing module.

- [ ] **Step 3: Implement the domain module**

Implement `normalize_power_system_spec(value) -> dict[str, object]` with deep-copy semantics and stable list/dict shapes. Implement `validate_power_system_spec(spec, novel_type_id, template=None)` to return normalized data or raise `PowerSystemValidationError(missing_sections, violations)`. Enforce required sections, at least three stages, entry/change/failure on each stage, minimum path count, branches, costs, counters, boundaries, and the game milestones/classes. Implement `legacy_power_summary()` as no more than 16 concise strings and `power_system_prompt_slice(spec, stage_hint)` returning only identity, current/next stages, matching paths, resources, costs, counters, boundaries, and ledger fields.

- [ ] **Step 4: Run tests**

Run: `pytest tests/story_core/test_power_systems.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/power_systems.py tests/story_core/test_power_systems.py
git commit -m "feat: validate structured project power systems"
```

### Task 4: World Generation, Merge, and Markdown

**Files:**
- Modify: `packages/story_core/world_enrichment.py`
- Modify: `packages/story_core/world_blueprint_context.py`
- Test: `tests/api/test_project_world_enrichment.py`
- Test: `tests/story_core/test_world_blueprint_context.py`

- [ ] **Step 1: Write failing generation and rendering tests**

```python
def test_world_enrichment_prompt_requests_structured_power_system(monkeypatch, game_project):
    captured = capture_world_request(monkeypatch, game_project, power_system_spec=complete_spec())
    prompt = captured["payload"]["messages"][1]["content"]
    assert "power_system_spec" in prompt
    assert "minimum_path_count" in prompt
    assert captured["project"].world_blueprint["power_system_spec"]["name"] == "神域职业体系"

def test_render_power_markdown_prefers_structured_sections():
    rendered = render_power_markdown("神域", {
        "power_system_spec": complete_spec(),
        "power_system": ["旧力量规则"],
    })
    assert "## 职业与路线" in rendered
    assert "元素法师" in rendered
    assert "旧力量规则" not in rendered
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/api/test_project_world_enrichment.py tests/story_core/test_world_blueprint_context.py -q`

Expected: FAIL because enrichment and Markdown only understand the legacy list.

- [ ] **Step 3: Connect generation and deterministic merging**

Add `power_system_spec` and the selected `genre_power_system_template` to the enrichment request. Require JSON output to include the structured field. Validate before `_apply_world_enrichment`; if validation fails, raise the stable `invalid_power_system_spec:<sections>` error so the existing retry/error path handles it. Merge a valid incoming spec as one atomic module, preserve an existing valid spec when the incoming field is absent, and regenerate the legacy summary only when the structured spec changes.

Update Markdown rendering with these headings in order: `体系总览`, `力量来源`, `属性`, `阶段与晋升`, `职业与路线`, `技能与装备`, `资源与代价`, `克制与边界`, `社会影响`, `信息可见性`, `连续性账本`. Keep the managed-marker protection unchanged.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/api/test_project_world_enrichment.py tests/story_core/test_world_blueprint_context.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/world_enrichment.py packages/story_core/world_blueprint_context.py tests/api/test_project_world_enrichment.py tests/story_core/test_world_blueprint_context.py
git commit -m "feat: generate structured power systems with world settings"
```

### Task 5: Outline and Writing Context

**Files:**
- Modify: `packages/story_core/world_blueprint_context.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/writing_packet.py`
- Test: `tests/story_core/test_world_blueprint_context.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_writing_packet.py`

- [ ] **Step 1: Write failing context-slicing tests**

```python
def test_outline_context_includes_progression_contract_without_full_dump(game_project):
    selected = select_world_context(game_project.world_blueprint, "主角准备转职", max_rules=8)
    power = selected["power_system_spec"]
    assert power["stages"]
    assert power["boundaries"]
    assert "social_impact" not in power

def test_chapter_packet_selects_current_and_next_power_stage(game_story):
    packet = build_writing_packet(game_story, target_chapter=12)
    stages = packet["power_system"]["stages"]
    assert [stage["name"] for stage in stages] == ["见习者", "正式职业"]
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/story_core/test_world_blueprint_context.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_writing_packet.py -q`

Expected: FAIL because structured power context is not selected.

- [ ] **Step 3: Add purpose- and stage-aware slices**

For `outline`, include stages, path names/branches, advancement, costs, counters, and boundaries. For chapter planning/writing, call `power_system_prompt_slice()` using the protagonist level/class path from `progression_ledger` and include only current/next stages plus matching paths. For review, include boundaries, costs, and ledger fields so reviewers can flag invented skills, free advancement, and impossible level gaps.

Add explicit prompt contracts: Lv.20 is a specialization node for game stories, not a transfer; unrecorded skills/equipment cannot appear as owned facts; any new unlock must produce a ledger update.

- [ ] **Step 4: Run prompt and writing tests**

Run: `pytest tests/story_core/test_world_blueprint_context.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_writing_packet.py tests/story_core/test_writer_prompt_method.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/world_blueprint_context.py packages/story_core/orchestrator.py packages/story_core/writing_packet.py tests/story_core
git commit -m "feat: enforce power contracts in outline and writing"
```

### Task 6: Type Library and Project World UI

**Files:**
- Modify: `apps/web/components/novel-types/NovelTypeLibraryClient.tsx`
- Modify: `apps/web/components/ws/WorldRulesEditor.tsx`
- Modify: `apps/web/lib/api.ts`
- Test: `apps/web/tests/novel-types.spec.ts`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing Playwright tests**

```typescript
test("小说类型可以编辑力量体系骨架", async ({ page }) => {
  await openNovelTypeLibrary(page);
  await page.getByLabel("小说类型列表").getByText("网游升级流").click();
  const editor = page.getByLabel("力量体系骨架 JSON");
  await expect(editor).toContainText('"minimum_path_count": 6');
  await editor.fill('{"system_form":"测试体系","required_sections":["origin"]}');
  await page.getByRole("button", { name: "保存小说类型" }).click();
  expect(lastUpdate.power_system_template.system_form).toBe("测试体系");
});

test("世界页分节显示结构化力量体系", async ({ page }) => {
  await openWorldPage(page, structuredPowerFixture);
  await expect(page.getByRole("heading", { name: "职业与路线" })).toBeVisible();
  await expect(page.getByText("战士")).toBeVisible();
  await expect(page.getByText("力量体系需要补全")).toHaveCount(0);
});
```

- [ ] **Step 2: Run and verify RED**

Run: `npm --prefix apps/web run test:e2e -- novel-types.spec.ts story-workbench.spec.ts`

Expected: FAIL because neither editor exists.

- [ ] **Step 3: Implement complete controls and states**

Add a labeled JSON textarea below trope templates, parse it with the same canonical JSON/error pattern, and include it in dirty-state comparison and save payloads. On the world page, render unframed sections for structured data; show `力量体系需要补全` only when a legacy list exists without `power_system_spec`. Keep the existing legacy textarea editable for compatibility and do not nest cards.

- [ ] **Step 4: Run UI tests and type checks**

Run: `npm --prefix apps/web run test:e2e -- novel-types.spec.ts story-workbench.spec.ts`

Run: `npm --prefix apps/web run typecheck`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/novel-types/NovelTypeLibraryClient.tsx apps/web/components/ws/WorldRulesEditor.tsx apps/web/lib/api.ts apps/web/tests
git commit -m "feat: edit and display structured power systems"
```

### Task 7: Upgrade the Current MMO Project

**Files:**
- Create: `scripts/upgrade_project_power_system.py`
- Modify: `data/exported-projects/p-gou-webgame-restored/.webnovel/project.json` (ignored runtime data)
- Modify: `data/exported-projects/p-gou-webgame-restored/.webnovel/outline.json` (ignored runtime data)
- Modify: managed Markdown mirrors under `data/exported-projects/p-gou-webgame-restored/`
- Test: `tests/test_upgrade_project_power_system.py`

- [ ] **Step 1: Write the failing idempotent migration test**

```python
def test_upgrade_adds_six_classes_and_repairs_lv20_without_touching_prose(tmp_path):
    project_dir = copy_fixture_project(tmp_path, "p-gou-webgame-restored")
    before_chapter = (project_dir / "正文" / "第1章.md").read_text(encoding="utf-8")
    result = upgrade_project(project_dir)
    spec = load_json(project_dir / ".webnovel" / "project.json")["world_blueprint"]["power_system_spec"]
    assert [path["name"] for path in spec["paths"]] == ["战士", "法师", "游侠", "盗贼", "牧师", "召唤师"]
    assert "元素法师" in json.dumps(spec, ensure_ascii=False)
    assert "元素宗师" in json.dumps(spec, ensure_ascii=False)
    assert "第二次转职" not in (project_dir / ".webnovel" / "outline.json").read_text(encoding="utf-8")
    assert (project_dir / "正文" / "第1章.md").read_text(encoding="utf-8") == before_chapter
    assert result["changed"] is True
    assert upgrade_project(project_dir)["changed"] is False
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_upgrade_project_power_system.py -q`

Expected: ERROR importing the missing migration.

- [ ] **Step 3: Implement backup and migration**

Create one timestamped backup of `.webnovel/project.json` and `.webnovel/outline.json`. Insert a complete validated game spec with the six base classes, two Lv.30 branches per class, Lv.10 transfer, Lv.20 specialization, Lv.30 advancement, and Lv.60 inheritance. Lock the protagonist route to `见习者 -> 元素法师 -> 元素宗师`; map the heroine to the ranger path. Replace only outline phrases that call Lv.20 a second transfer, regenerate managed power Markdown through the production renderer, and leave chapter prose and monetary facts untouched.

- [ ] **Step 4: Run the migration and verify project data**

Run: `pytest tests/test_upgrade_project_power_system.py -q`

Run: `python scripts/upgrade_project_power_system.py data/exported-projects/p-gou-webgame-restored`

Run: `python scripts/upgrade_project_power_system.py data/exported-projects/p-gou-webgame-restored --check`

Expected: tests PASS; first command reports `changed=true`; check reports `changed=false` and `valid=true`.

- [ ] **Step 5: Commit the reusable migration and test**

```bash
git add scripts/upgrade_project_power_system.py tests/test_upgrade_project_power_system.py
git commit -m "feat: upgrade legacy projects to structured power systems"
```

Project runtime data is gitignored and is verified in place rather than forced into Git.

### Task 8: Full Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run backend tests**

Run: `pytest -q`

Expected: all tests PASS.

- [ ] **Step 2: Run frontend checks**

Run: `npm --prefix apps/web run typecheck`

Run: `npm --prefix apps/web run test:e2e -- novel-types.spec.ts story-workbench.spec.ts`

Expected: all checks PASS.

- [ ] **Step 3: Verify the live project in the browser**

Start the existing API and web commands documented by the repository if they are not already running. Open `http://localhost:3000/projects/file%3Ap-gou-webgame-restored`, enter the world/力量体系 view, and verify desktop and narrow mobile screenshots show all headings, six classes, the protagonist route, and no overlapping or clipped text.

- [ ] **Step 4: Inspect final diff and status**

Run: `git diff --check && git status --short && git log --oneline -10`

Expected: no whitespace errors; only intentional tracked changes remain; runtime project data may remain ignored.
