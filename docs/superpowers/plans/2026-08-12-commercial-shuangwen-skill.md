# Commercial Shuangwen Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a composable “商业爽文推进” Skill that preserves concrete SOPs and examples, participates in outline/chapter-plan/writer/manual-review stages, and can be selected only for newly created books.

**Architecture:** Keep genre selection and narrative enhancement separate. Install one independent `commercial-shuangwen` Skill pack with stage-specific modules, extend the Skill loader with explicit purposes and complete example-section extraction, then route only the relevant module into each pipeline stage. Persist the selection through existing `enabled_skill_ids` and `enabled_skill_module_ids`; old projects remain unchanged.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, pytest, Next.js 14, TypeScript, Playwright.

---

## File Structure

**Create**

- `data/skill-packs/commercial-shuangwen/manifest.json`: package identity and module metadata.
- `data/skill-packs/commercial-shuangwen/SKILL.md`: package-level scope and exclusions.
- `data/skill-packs/commercial-shuangwen/skills/plot-engine/SKILL.md`: 5–15 chapter emotional loop.
- `data/skill-packs/commercial-shuangwen/skills/chapter-sop/SKILL.md`: concrete chapter SOP.
- `data/skill-packs/commercial-shuangwen/skills/writer-execution/SKILL.md`: writer-facing execution rules.
- `data/skill-packs/commercial-shuangwen/skills/review-checklist/SKILL.md`: manual review rubric.
- `data/skill-packs/commercial-shuangwen/skills/genre-examples/SKILL.md`: tagged examples by genre.
- `packages/story_core/shuangwen_review.py`: non-mutating manual Skill review adapter.
- `tests/story_core/test_commercial_shuangwen_skill.py`: package and stage-isolation tests.

**Modify**

- `packages/story_core/skill_packs.py`: explicit purposes, section-aware extraction, genre-aware example selection.
- `packages/story_core/file_project_creation.py`: accept and persist narrative enhancements.
- `packages/story_core/file_project_store.py`: pass enabled Skill selection into outline briefs and expose manual review.
- `packages/story_core/outline_planning.py`: persist structured payoff/SOP fields in chapter plans.
- `packages/story_core/outline_planning_generation.py`: load outline/chapter-plan Skill contexts.
- `packages/story_core/outline_rolling.py`: validate and adapt rolling SOP fields.
- `packages/story_core/genre_stages/common_writer.py`: include writer-only Skill context and trace it.
- `apps/api/routes/file_projects.py`: manual Skill review endpoint.
- `apps/web/lib/api.ts`: creation fields and review API types.
- `apps/web/app/projects/new/page.tsx`: “叙事增强” selector.
- `apps/web/app/projects/[id]/review/page.tsx`: explicit review action and not-run state.
- `apps/web/components/ws/SimplifiedReview.tsx`: distinguish not-run from passed.

---

### Task 1: Add explicit Skill purposes and section-aware extraction

**Files:**
- Modify: `packages/story_core/skill_packs.py`
- Test: `tests/story_core/test_skill_packs.py`

- [ ] **Step 1: Write failing tests for explicit purposes and complete examples**

Create a test module with:

```python
module_text = """---
name: chapter-sop
description: 商业爽文单章结构
purposes: chapter_plan,writer
---
# 单章结构
## 规则
先承接上一章，再兑现具体反馈。
## 正例
铜镜亮起后没有映出林修，而是映出失踪十年的父亲。
## 反例
林修觉得事情没有这么简单。
"""
```

Assert:

```python
assert module.purposes == ["chapter_plan", "writer"]
context = skill_pack_prompt_context(
    ["test-pack"], purpose="chapter_plan", include_examples=True
)
instructions = context[0]["modules"][0]["instructions"]
assert "先承接上一章" in instructions
assert "铜镜亮起后" in instructions
assert "事情没有这么简单" in instructions
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run `python -m pytest tests/story_core/test_skill_packs.py -k "explicit_purposes or complete_examples" -q`.

Expected: FAIL because `purposes` is inferred and example sections are skipped.

- [ ] **Step 3: Implement explicit purpose parsing**

Add:

```python
def _declared_purposes(meta: Mapping[str, str], *fallback_values: str) -> list[str]:
    raw = str(meta.get("purposes") or "")
    declared = [item.strip() for item in raw.split(",") if item.strip()]
    return list(dict.fromkeys(declared)) or infer_skill_purposes(*fallback_values)
```

Use this result for `SkillModule.purposes` in `load_skill_pack`.

- [ ] **Step 4: Implement complete section extraction**

Change the signature to:

```python
def extract_skill_instructions(
    text: str,
    *,
    limit: int = 1000,
    include_examples: bool = False,
    genre_id: str = "",
) -> str:
```

Parse Markdown by heading blocks. Always keep `规则`; keep `正例`, `反例`, and `结构示例` only when `include_examples=True`. For `genre-examples`, keep headings tagged `[通用]` plus the canonical `genre_id`. Add a whole block only if it fits; never cut a block in the middle. Add matching arguments to `skill_pack_prompt_context`.

- [ ] **Step 5: Run and commit**

```powershell
python -m pytest tests/story_core/test_skill_packs.py tests/api/test_skill_pack_routes.py -q
git add packages/story_core/skill_packs.py tests/story_core/test_skill_packs.py
git commit -m "feat: route skill content by explicit purpose"
```

---

### Task 2: Create the commercial shuangwen Skill pack

**Files:**
- Create: `data/skill-packs/commercial-shuangwen/manifest.json`
- Create: root and five module `SKILL.md` files listed above
- Create: `tests/story_core/test_commercial_shuangwen_skill.py`

- [ ] **Step 1: Write the package contract test**

```python
def test_commercial_shuangwen_pack_has_stage_modules():
    pack = get_skill_pack("commercial-shuangwen")
    assert pack is not None
    assert {item.module_id for item in pack.modules} == {
        "plot-engine", "chapter-sop", "writer-execution",
        "review-checklist", "genre-examples",
    }
    purposes = {item.module_id: item.purposes for item in pack.modules}
    assert purposes["plot-engine"] == ["outline"]
    assert purposes["chapter-sop"] == ["chapter_plan"]
    assert purposes["writer-execution"] == ["writer"]
    assert purposes["review-checklist"] == ["reviewer"]
```

- [ ] **Step 2: Run and verify failure**

Run `python -m pytest tests/story_core/test_commercial_shuangwen_skill.py -q`.

Expected: FAIL because the package does not exist.

- [ ] **Step 3: Add manifest and root contract**

```json
{
  "schema_version": "skill-pack/v1",
  "skill_id": "commercial-shuangwen",
  "name": "商业爽文推进",
  "version": "1.0.0",
  "author": "local",
  "description": "可叠加到任意题材的需求、压制、反击、回报写作方法。"
}
```

The root `SKILL.md` states that the pack changes narrative method only, cannot invent canon, is disabled by default, and never requests automatic revision.

- [ ] **Step 4: Add all five concrete modules**

Copy the complete rules from the approved design. Preserve these method names in `plot-engine`: `情绪过山车`, `信息差`, `设局/需求`, `打压/拉仇恨`, `降维打击`, `震惊与收割`. Preserve `起/承/转/合` in `chapter-sop`.

Each module contains `## 规则`, `## 正例`, `## 反例`, and `## 结构示例` where applicable. `genre-examples` contains `[通用]`, `[game_webnovel]`, `[xuanhuan]`, `[xianxia]`, `[urban]`, and `[science_fiction]` headings.

- [ ] **Step 5: Assert concrete methods survive extraction**

```python
outline_context = skill_pack_prompt_context(
    ["commercial-shuangwen"], purpose="outline",
    include_examples=True, genre_id="xuanhuan",
)
text = json.dumps(outline_context, ensure_ascii=False)
assert "设局/需求" in text
assert "降维打击" in text
assert "玄幻" in text
assert "网游" not in text
```

- [ ] **Step 6: Run and commit**

```powershell
python -m pytest tests/story_core/test_commercial_shuangwen_skill.py tests/story_core/test_skill_packs.py -q
git add data/skill-packs/commercial-shuangwen tests/story_core/test_commercial_shuangwen_skill.py
git commit -m "feat: add commercial shuangwen skill pack"
```

---

### Task 3: Persist narrative enhancements when creating a new book

**Files:**
- Modify: `packages/story_core/file_project_creation.py`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/new/page.tsx`
- Test: `tests/story_core/test_file_project_creation.py`
- Test: `tests/api/test_file_project_creation_routes.py`
- Test: `apps/web/tests/novel-type-selectors.spec.ts`

- [ ] **Step 1: Write backend creation tests**

```python
spec = FileProjectCreateSpec(
    mode="blank",
    title="新书",
    novel_type_id="xuanhuan",
    narrative_enhancement_ids=["commercial-shuangwen"],
)
created = create_file_project(tmp_path, spec)
project = json.loads((created.root / ".webnovel/project.json").read_text("utf-8"))
assert project["enabled_skill_ids"] == ["commercial-shuangwen"]
assert project["enabled_skill_module_ids"] == [
    "commercial-shuangwen::plot-engine",
    "commercial-shuangwen::chapter-sop",
    "commercial-shuangwen::writer-execution",
    "commercial-shuangwen::review-checklist",
    "commercial-shuangwen::genre-examples",
]
```

Also assert omitted and empty selections persist both arrays as `[]`.

- [ ] **Step 2: Run and verify failure**

Run `python -m pytest tests/story_core/test_file_project_creation.py tests/api/test_file_project_creation_routes.py -k "enhancement" -q`.

Expected: FAIL because `narrative_enhancement_ids` is forbidden.

- [ ] **Step 3: Implement the creation contract**

Add to `FileProjectCreateSpec`:

```python
narrative_enhancement_ids: list[str] = Field(default_factory=list, max_length=8)
```

Validate against:

```python
NARRATIVE_ENHANCEMENT_MODULES = {
    "commercial-shuangwen": [
        "plot-engine", "chapter-sop", "writer-execution",
        "review-checklist", "genre-examples",
    ]
}
```

Derive `enabled_skill_ids` and module keys in `_project_payload`. Mirror the same selection in state so project/state synchronization is deterministic.

- [ ] **Step 4: Add the frontend request and selector**

Extend `NewFileProjectRequest`:

```ts
narrative_enhancement_ids?: string[];
```

Add below novel type:

```ts
const NARRATIVE_ENHANCEMENTS = [{
  id: "commercial-shuangwen",
  name: "商业爽文推进",
  description: "需求、压制、反击、回报；按题材加载具体例子。",
}];
```

Use checkboxes, default `[]`, and submit selected IDs.

- [ ] **Step 5: Add Playwright coverage**

Intercept project creation; assert the checkbox starts clear, then check it and verify the POST body contains `narrative_enhancement_ids: ["commercial-shuangwen"]`.

- [ ] **Step 6: Run and commit**

```powershell
python -m pytest tests/story_core/test_file_project_creation.py tests/api/test_file_project_creation_routes.py -q
cd apps/web
npx tsc --noEmit
npx playwright test tests/novel-type-selectors.spec.ts -g "narrative enhancement"
cd ../..
git add packages/story_core/file_project_creation.py apps/web/lib/api.ts apps/web/app/projects/new/page.tsx tests/story_core/test_file_project_creation.py tests/api/test_file_project_creation_routes.py apps/web/tests/novel-type-selectors.spec.ts
git commit -m "feat: select narrative enhancements for new books"
```

---

### Task 4: Route the Skill into total and stage outline generation

**Files:**
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write a prompt-capture test**

Create an `OutlinePlanningBrief` with enabled IDs and a fake model gateway. Assert the foundation request contains `skill_context.outline`, `设局/需求`, and only the selected genre example. Assert a brief with empty IDs contains no `skill_context`.

- [ ] **Step 2: Run and verify failure**

Run `python -m pytest tests/story_core/test_outline_planning_generation.py -k "shuangwen_skill_context" -q`.

Expected: FAIL because the brief has no Skill fields.

- [ ] **Step 3: Add Skill selection to the planning brief**

```python
enabled_skill_ids: list[str] = Field(default_factory=list)
enabled_skill_module_ids: list[str] = Field(default_factory=list)
```

Populate both in `FileProjectStore._outline_planning_brief` with `resolve_enabled_skill_ids` and `resolve_enabled_skill_module_ids`.

- [ ] **Step 4: Add outline context to prompt construction**

```python
outline_skill_context = skill_pack_prompt_context(
    validated.enabled_skill_ids,
    enabled_module_ids=validated.enabled_skill_module_ids,
    purpose="outline",
    include_examples=True,
    genre_id=effective_novel_type_id,
    max_chars_per_pack=3600,
)
if outline_skill_context:
    prompt_context["skill_context"] = {"outline": outline_skill_context}
```

Add a validation rule: Skill methods may shape conflict and payoff, but cannot invent canon or replace the output schema.

- [ ] **Step 5: Run and commit**

```powershell
python -m pytest tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py -k "outline_planning or shuangwen" -q
git add packages/story_core/outline_planning_generation.py packages/story_core/file_project_store.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_file_project_store.py
git commit -m "feat: apply shuangwen skill to outline planning"
```

---

### Task 5: Persist concrete chapter SOP fields

**Files:**
- Modify: `packages/story_core/outline_planning.py`
- Modify: `packages/story_core/outline_planning_generation.py`
- Modify: `packages/story_core/outline_rolling.py`
- Test: `tests/story_core/test_outline_planning.py`
- Test: `tests/story_core/test_outline_planning_generation.py`
- Test: `tests/story_core/test_outline_rolling.py`

- [ ] **Step 1: Add failing schema tests**

Validate and preserve:

```python
{
  "payoff_contract": {
    "need": "林修必须拿到替换镜芯",
    "pressure": "买家只给他一夜验货",
    "hidden_advantage": "他能恢复物品上次完整运行状态",
    "concrete_reward": "修复订单并获得父亲失踪线索"
  },
  "chapter_sop": {
    "opening_carry": "接上铜镜第一次亮起",
    "mid_feedback": "镜面恢复一段旧影像",
    "turn": "影像中的人认出了林修",
    "ending_hook": "镜中人叫出林修父亲的名字"
  }
}
```

Assert all values survive outline normalization and rolling adaptation.

- [ ] **Step 2: Run and verify failure**

Run `python -m pytest tests/story_core/test_outline_planning.py tests/story_core/test_outline_rolling.py -k "payoff_contract or chapter_sop" -q`.

- [ ] **Step 3: Add models and optional chapter fields**

Create `ChapterPayoffContract` and `ChapterSop` Pydantic models with bounded strings and add optional fields to `ChapterPlan` and `GeneratedDetailedChapter`. Defaults are empty so projects without the Skill remain valid.

- [ ] **Step 4: Require fields only when the module is enabled**

Detect `commercial-shuangwen::chapter-sop` in the planning generator. When selected, require all fields to be non-empty and concrete; otherwise do not mention them. Copy the fields through `rolling_chapter_to_outline_entry` and rolling payload validation.

- [ ] **Step 5: Run and commit**

```powershell
python -m pytest tests/story_core/test_outline_planning.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_outline_rolling.py -q
git add packages/story_core/outline_planning.py packages/story_core/outline_planning_generation.py packages/story_core/outline_rolling.py tests/story_core/test_outline_planning.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_outline_rolling.py
git commit -m "feat: persist concrete shuangwen chapter contracts"
```

---

### Task 6: Limit writer context to writer rules and relevant examples

**Files:**
- Modify: `packages/story_core/genre_stages/common_writer.py`
- Modify: `packages/story_core/agents/writer/agent.py`
- Test: `tests/story_core/test_writer_prompt_method.py`
- Test: `tests/story_core/test_modular_writer_agent.py`

- [ ] **Step 1: Write a stage-isolation test**

Build the writer prompt with every commercial-shuangwen module enabled and assert:

```python
assert "对手为什么会作出错误判断" in prompt
assert "铜镜亮起后" in prompt
assert "5—15章" not in prompt
assert "审稿检查" not in prompt
assert "能断句就断句" not in prompt
```

Also assert `writer_skill_trace` contains `writer-execution` and `genre-examples`, but not `plot-engine`, `chapter-sop`, or `review-checklist`.

- [ ] **Step 2: Run and verify failure**

Run `python -m pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_modular_writer_agent.py -k "commercial_shuangwen" -q`.

- [ ] **Step 3: Build writer-only context**

Call `skill_pack_prompt_context` for purpose `writer` with `include_examples=True`, the canonical genre ID, and a 2200-character budget. Assign it to `WriterContext.skill_context` before `build_common_writer_sections`. Update `_writer_skill_lines` to preserve complete example blocks and deduplicate `genre-examples`.

- [ ] **Step 4: Run and commit**

```powershell
python -m pytest tests/story_core/test_writer_prompt_method.py tests/story_core/test_modular_writer_agent.py -q
git add packages/story_core/genre_stages/common_writer.py packages/story_core/agents/writer/agent.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_modular_writer_agent.py
git commit -m "feat: scope shuangwen guidance to the writer stage"
```

---

### Task 7: Add non-mutating manual shuangwen review

**Files:**
- Create: `packages/story_core/shuangwen_review.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/file_projects.py`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/projects/[id]/review/page.tsx`
- Modify: `apps/web/components/ws/SimplifiedReview.tsx`
- Test: `tests/story_core/test_review_service.py`
- Test: `tests/api/test_story_routes.py`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write failing service and API tests**

```python
result = review_shuangwen_chapter(
    body=body,
    chapter_plan=plan,
    skill_context=context,
    model_gateway=fake_gateway,
)
assert result["schema_version"] == "skill-review/v1"
assert result["skill_id"] == "commercial-shuangwen"
assert result["executed"] is True
assert "body" not in result
```

The store/API test records the body hash and asserts it is unchanged after review.

- [ ] **Step 2: Run and verify failure**

Run `python -m pytest tests/story_core/test_review_service.py tests/api/test_story_routes.py -k "shuangwen_review" -q`.

- [ ] **Step 3: Implement the review adapter**

Use the configured reviewer runtime once, passing only confirmed body, chapter SOP fields, and `reviewer` Skill context. Require:

```json
{
  "executed": true,
  "status": "passed|warning",
  "summary": "",
  "checks": {
    "goal": [],
    "pressure": [],
    "information_gap": [],
    "counterattack": [],
    "payoff": [],
    "reaction": [],
    "ending_hook": [],
    "cliches": []
  },
  "issues": []
}
```

Save under `quality_report.skill_reviews["commercial-shuangwen"]`. Do not call regeneration, expansion, confirmation, or chapter-writing methods.

- [ ] **Step 4: Add API and UI action**

Add:

```text
POST /file-projects/{project_id}/chapters/{chapter_number}/skill-reviews/commercial-shuangwen
```

The review page shows “尚未执行爽文检查” before a report exists and a “运行爽文检查” button only when the Skill is enabled. After completion it displays the stored summary/issues. Update `SimplifiedReview` so an absent report is not rendered as zero issues or passed.

- [ ] **Step 5: Run and commit**

```powershell
python -m pytest tests/story_core/test_review_service.py tests/api/test_story_routes.py -q
cd apps/web
npx tsc --noEmit
npx playwright test tests/story-workbench.spec.ts -g "manual shuangwen review"
cd ../..
git add packages/story_core/shuangwen_review.py packages/story_core/file_project_store.py apps/api/routes/file_projects.py apps/web/lib/api.ts apps/web/app/projects/[id]/review/page.tsx apps/web/components/ws/SimplifiedReview.tsx tests/story_core/test_review_service.py tests/api/test_story_routes.py apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add manual shuangwen review"
```

---

### Task 8: End-to-end isolation and regression verification

**Files:**
- Modify only focused files if verification finds a feature regression.
- Test: `tests/story_core/test_commercial_shuangwen_skill.py`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Add an end-to-end context test**

Create two temporary xuanhuan projects, one without enhancement and one with `commercial-shuangwen`. Assert only the enhanced project outline prompt contains `plot-engine`, only its chapter plan requires `payoff_contract` and `chapter_sop`, and only its writer prompt contains `writer-execution` plus one xuanhuan example. Assert neither body is modified by review until the manual endpoint is called. Assert existing project `p-da2c16a6ee9440d6ad52cb402ead88a0` still has no `commercial-shuangwen` entry.

- [ ] **Step 2: Run backend regression suites**

```powershell
python -m pytest tests/story_core/test_skill_packs.py tests/story_core/test_commercial_shuangwen_skill.py tests/story_core/test_file_project_creation.py tests/story_core/test_outline_planning.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_outline_rolling.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_modular_writer_agent.py tests/story_core/test_review_service.py tests/api/test_file_project_creation_routes.py tests/api/test_skill_pack_routes.py tests/api/test_story_routes.py -q
```

Expected: all pass, with only already-documented skips.

- [ ] **Step 3: Run frontend verification**

```powershell
cd apps/web
npx tsc --noEmit
npx playwright test tests/novel-type-selectors.spec.ts tests/story-workbench.spec.ts
node node_modules/next/dist/bin/next build
cd ../..
```

Expected: typecheck, Playwright, and production build all pass.

- [ ] **Step 4: Inspect a real temporary writing packet**

Create a temporary enhanced xuanhuan project through the API. Generate its outline preview and writing-packet preview without generating a real chapter. Verify the prompt page shows stage-specific modules and no cross-genre examples. Delete only the temporary project after resolving and checking its absolute path under `data/exported-projects`.

- [ ] **Step 5: Final diff and commit**

```powershell
git diff --check
git status --short
git add data/skill-packs/commercial-shuangwen packages/story_core/skill_packs.py packages/story_core/file_project_creation.py packages/story_core/file_project_store.py packages/story_core/outline_planning.py packages/story_core/outline_planning_generation.py packages/story_core/outline_rolling.py packages/story_core/genre_stages/common_writer.py packages/story_core/agents/writer/agent.py packages/story_core/shuangwen_review.py apps/api/routes/file_projects.py apps/web/lib/api.ts apps/web/app/projects/new/page.tsx apps/web/app/projects/[id]/review/page.tsx apps/web/components/ws/SimplifiedReview.tsx tests/story_core/test_skill_packs.py tests/story_core/test_commercial_shuangwen_skill.py tests/story_core/test_file_project_creation.py tests/story_core/test_outline_planning.py tests/story_core/test_outline_planning_generation.py tests/story_core/test_outline_rolling.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_modular_writer_agent.py tests/story_core/test_review_service.py tests/api/test_file_project_creation_routes.py tests/api/test_skill_pack_routes.py tests/api/test_story_routes.py apps/web/tests/novel-type-selectors.spec.ts apps/web/tests/story-workbench.spec.ts
git commit -m "test: verify composable shuangwen workflow"
```

Do not stage unrelated pre-existing worktree changes.
