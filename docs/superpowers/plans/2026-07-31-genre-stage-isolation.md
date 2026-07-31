# Genre Stage Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all web-game-specific director, writer, review, and revision prompt behavior out of `orchestrator.py` so non-game novels cannot receive game rules.

**Architecture:** Add a small static genre-stage registry. The orchestrator resolves one profile and delegates stage-specific content to it; generic prompt construction lives in focused common modules, while web-game behavior lives under `genre_stages/game_webnovel/`. API contracts, model calls, and persisted chapter schemas stay unchanged.

**Tech Stack:** Python 3.11, dataclasses and protocols, pytest, FastAPI prompt audit endpoints, Playwright workbench tests.

---

## File Map

- Create `packages/story_core/genre_stages/base.py`: stage context and contribution dataclasses plus the profile protocol.
- Create `packages/story_core/genre_stages/registry.py`: resolve the active profile from a story and optional plan.
- Create `packages/story_core/genre_stages/generic.py`: neutral director, writer, review, revision behavior.
- Create `packages/story_core/genre_stages/common_writer.py`: genre-neutral writer sections currently embedded in the orchestrator.
- Create `packages/story_core/genre_stages/game_webnovel/director.py`: game director template and attribute/progression additions.
- Create `packages/story_core/genre_stages/game_webnovel/writer.py`: game ledger, monster, dual-state, task, economy, and craft sections.
- Create `packages/story_core/genre_stages/game_webnovel/review.py`: game-only deterministic review checks and review fan-out.
- Create `packages/story_core/genre_stages/game_webnovel/revision.py`: game fact lock, forbidden terms, and legacy economy normalization.
- Create `packages/story_core/genre_stages/game_webnovel/__init__.py`: compose the game profile.
- Modify `packages/story_core/orchestrator.py`: delegate by profile and delete game prompt/review branches.
- Modify `packages/story_core/prompt_templates.py`: keep generic and game templates separate, without changing template keys.
- Create `tests/story_core/test_genre_stage_profiles.py`: registry and profile contract tests.
- Create `tests/story_core/test_genre_prompt_isolation.py`: cross-genre contamination tests.
- Modify focused existing prompt, review, revision, API, and workbench tests only where ownership moves.

### Task 1: Add The Genre Stage Contract And Registry

**Files:**
- Create: `packages/story_core/genre_stages/__init__.py`
- Create: `packages/story_core/genre_stages/base.py`
- Create: `packages/story_core/genre_stages/registry.py`
- Create: `tests/story_core/test_genre_stage_profiles.py`

- [ ] **Step 1: Write failing registry tests**

```python
from packages.story_core.genre_stages.registry import genre_stage_profile_for
from packages.story_core.models import StoryState


def test_registry_returns_game_profile_only_for_game_story():
    game = StoryState(story_id="game", outline="玩家进入虚拟世界", genre="网游")
    xianxia = StoryState(story_id="xianxia", outline="杂役踏上修行路", genre="修仙仙侠")

    assert genre_stage_profile_for(game).profile_id == "game_webnovel"
    assert genre_stage_profile_for(xianxia).profile_id == "generic"


def test_profile_contract_exposes_all_four_generation_stages():
    profile = genre_stage_profile_for(StoryState(story_id="generic", outline="旧案重查", genre="悬疑"))

    assert callable(profile.render_director_prompt)
    assert callable(profile.render_writer_prompt)
    assert callable(profile.review_chapter)
    assert callable(profile.render_revision_prompt)
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run: `pytest tests/story_core/test_genre_stage_profiles.py -q --tb=short`

Expected: collection fails because `packages.story_core.genre_stages` does not exist.

- [ ] **Step 3: Add the profile contract**

```python
# packages/story_core/genre_stages/base.py
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class GenreStageProfile:
    profile_id: str
    render_director_prompt: Callable[..., str]
    render_writer_prompt: Callable[..., str]
    review_chapter: Callable[..., dict[str, Any]]
    render_revision_prompt: Callable[..., str]
```

Implement `registry.py` with one static decision point. It may use the existing normalized type helpers, but the orchestrator must not perform the game check itself.

```python
def genre_stage_profile_for(story, plan=None):
    from packages.story_core.genre_stages.game_webnovel import GAME_WEBNOVEL_STAGES
    from packages.story_core.genre_stages.generic import GENERIC_STAGES

    return GAME_WEBNOVEL_STAGES if is_game_story(story) else GENERIC_STAGES
```

Use lazy imports inside the resolver to avoid circular imports while the migration is in progress.

- [ ] **Step 4: Add inactive-stage migration guards**

Create `generic.py` and `game_webnovel/__init__.py` with concrete guards for stages that are not delegated yet. They are not called by production until the corresponding task replaces them.

```python
def inactive_prompt_stage(**_kwargs) -> str:
    raise RuntimeError("genre_stage_not_migrated")


def inactive_review_stage(**_kwargs) -> dict:
    raise RuntimeError("genre_stage_not_migrated")
```

Bind these guards to the initial profile fields. Tasks 2 through 5 replace one field immediately before changing the orchestrator to call it; Task 6 deletes both guards.

- [ ] **Step 5: Run the registry tests**

Run: `pytest tests/story_core/test_genre_stage_profiles.py -q --tb=short`

Expected: all tests pass.

- [ ] **Step 6: Commit the contract**

```powershell
git add packages/story_core/genre_stages tests/story_core/test_genre_stage_profiles.py
git commit -m "refactor: add genre stage profile registry"
```

### Task 2: Move Director Prompt Ownership

**Files:**
- Create: `packages/story_core/genre_stages/game_webnovel/director.py`
- Modify: `packages/story_core/genre_stages/generic.py`
- Modify: `packages/story_core/orchestrator.py:5975-6016`
- Modify: `tests/story_core/test_prompt_templates.py`
- Modify: `tests/story_core/test_director_plan_quality.py`

- [ ] **Step 1: Write failing director isolation tests**

```python
@pytest.mark.parametrize("genre", ["修仙仙侠", "东方玄幻", "都市", "悬疑"])
def test_non_game_director_prompt_has_no_game_contract(orchestrator, story_factory, genre):
    prompt = orchestrator._plan_prompt(story_factory(genre=genre), 3)
    for term in ("游戏ID", "等级", "背包", "装备耐久", "任务进度", "outsider_misread"):
        assert term not in prompt


def test_game_director_prompt_keeps_game_continuity(orchestrator, story_factory):
    prompt = orchestrator._plan_prompt(story_factory(genre="网游"), 3)
    assert "游戏ID" in prompt
    assert "等级" in prompt
    assert "任务进度" in prompt
```

- [ ] **Step 2: Run the tests and verify the generic prompt fails before extraction**

Run: `pytest tests/story_core/test_prompt_templates.py tests/story_core/test_director_plan_quality.py -q --tb=short`

Expected: the new isolation assertion fails on the current shared path.

- [ ] **Step 3: Implement the generic director renderer**

Move neutral value preparation and `director_generic` rendering into `generic.py`. The renderer must only reference chapter number, phase, project snapshot, chapter seed, character cards, and the neutral output schema.

- [ ] **Step 4: Implement the game director renderer**

Move selection of `director`, active game characters, attribute allocation contract, game continuity, and game planning wording into `game_webnovel/director.py`.

```python
def render_game_director_prompt(*, story, chapter_number, values, plan):
    values = {**values, "active_characters": active_character_names(story, plan)}
    rendered = render_prompt_template(get_effective_prompt_template("director"), values)
    allocation = director_attribute_allocation_contract() if attribute_allocation_rule_from_story(story) else ""
    return "\n".join(part for part in (rendered, allocation) if part)
```

- [ ] **Step 5: Replace `_render_plan_prompt` branching with one profile call**

```python
profile = genre_stage_profile_for(story, plan)
return profile.render_director_prompt(
    story=story,
    chapter_number=chapter_number,
    plan=plan,
    values=values,
)
```

Delete direct `director`/`director_generic` selection and attribute-allocation appending from the orchestrator.

- [ ] **Step 6: Run director tests**

Run: `pytest tests/story_core/test_prompt_templates.py tests/story_core/test_director_plan_quality.py tests/story_core/test_orchestrator.py -q --tb=short`

Expected: all pass.

- [ ] **Step 7: Commit director extraction**

```powershell
git add packages/story_core/genre_stages packages/story_core/orchestrator.py tests/story_core/test_prompt_templates.py tests/story_core/test_director_plan_quality.py
git commit -m "refactor: isolate genre director prompts"
```

### Task 3: Move Writer Prompt Ownership

**Files:**
- Create: `packages/story_core/genre_stages/common_writer.py`
- Create: `packages/story_core/genre_stages/game_webnovel/writer.py`
- Modify: `packages/story_core/genre_stages/generic.py`
- Modify: `packages/story_core/orchestrator.py:4690-5518,6018-6079`
- Create: `tests/story_core/test_genre_prompt_isolation.py`
- Modify: `tests/story_core/test_writer_prompt_method.py`

- [ ] **Step 1: Write failing writer isolation tests**

```python
GAME_TERMS = ("游戏ID", "本章怪物卡", "属性面板", "装备耐久", "任务进度", "## 网游写法")


@pytest.mark.parametrize("genre", ["修仙仙侠", "东方玄幻", "都市", "悬疑"])
def test_non_game_writer_prompt_excludes_game_terms(orchestrator, story_factory, genre):
    prompt = orchestrator._body_prompt(story_factory(genre=genre), 2, {"event_plan": {}})
    assert not [term for term in GAME_TERMS if term in prompt]


def test_game_writer_prompt_keeps_game_modules(orchestrator, game_story):
    prompt = orchestrator._body_prompt(game_story, 2, {"event_plan": {}})
    assert "## 网游写法" in prompt
    assert "游戏ID" in prompt
```

- [ ] **Step 2: Run the tests and record the current contamination**

Run: `pytest tests/story_core/test_genre_prompt_isolation.py -q --tb=short`

Expected: at least one non-game case fails because shared writer helpers still contain game wording.

- [ ] **Step 3: Move neutral writer functions to `common_writer.py`**

Move and rename these neutral helpers: compact taskbook, value lines, output contract, direction, neutral world context, trope contract, continuity facts, character context, skills, governance, and generic writing method. Their signatures must not accept `is_game`.

```python
def build_common_writer_sections(context) -> dict[str, list[str]]:
    return {
        "output_section": build_output_section(context),
        "chapter_direction": build_direction_section(context),
        "chapter_facts": build_fact_section(context),
        "character_context": build_character_section(context),
        "prose_method": build_craft_section(context),
    }
```

- [ ] **Step 4: Move all game writer additions to `game_webnovel/writer.py`**

Move `_game_genre_defaults`, inventory filtering, monster selection/formatting, game protagonist state, reality/game balance transition, attribute points, power ledger checks, game language cards, first-chapter game contract, and web-game method lines.

```python
def render_game_writer_prompt(context):
    sections = build_common_writer_sections(context)
    sections["chapter_facts"].extend(build_game_fact_lines(context))
    sections["prose_method"].extend(build_game_method_lines(context))
    return render_writer_template(sections)
```

- [ ] **Step 5: Make generic rendering use common sections only**

`generic.py` must call `build_common_writer_sections` and must not import any `web_game_*`, economy, monster, game language, or attribute allocation module.

- [ ] **Step 6: Replace `_render_body_prompt` with profile delegation**

Keep taskbook, style, character, dialogue, genre, and skill context acquisition in a small context builder. Then call:

```python
profile = genre_stage_profile_for(story, plan)
return profile.render_writer_prompt(context=writer_context)
```

Delete all `is_game` arguments and game imports from the writer assembly region.

- [ ] **Step 7: Run writer and isolation tests**

Run: `pytest tests/story_core/test_genre_prompt_isolation.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_writing_taskbook.py -q --tb=short`

Expected: all pass.

- [ ] **Step 8: Commit writer extraction**

```powershell
git add packages/story_core/genre_stages packages/story_core/orchestrator.py tests/story_core/test_genre_prompt_isolation.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_writing_taskbook.py
git commit -m "refactor: isolate genre writer prompts"
```

### Task 4: Move Game Review Checks

**Files:**
- Create: `packages/story_core/genre_stages/game_webnovel/review.py`
- Modify: `packages/story_core/genre_stages/generic.py`
- Modify: `packages/story_core/orchestrator.py:3518-4402`
- Modify: `tests/story_core/test_generation_quality_guardrails.py`
- Modify: `tests/story_core/test_world_consistency_review.py`

- [ ] **Step 1: Write failing review-isolation tests**

```python
def test_xianxia_review_does_not_run_game_review(orchestrator, xianxia_story, prose_body):
    report = orchestrator.review_body_for_story(xianxia_story, 1, prose_body, {"event_plan": {}})
    assert "web_game_review" not in report["active_genre_reviews"]
    assert not any("游戏ID" in issue or "交易行" in issue for issue in report["issues"])


def test_game_review_runs_game_checks(orchestrator, game_story, prose_body):
    report = orchestrator.review_body_for_story(game_story, 1, prose_body, {"event_plan": {}})
    assert "web_game_review" in report["active_genre_reviews"]
```

- [ ] **Step 2: Run the new tests and verify the shared report behavior fails**

Run: `pytest tests/story_core/test_generation_quality_guardrails.py -q --tb=short`

Expected: the non-game report still contains the compatibility web-game reviewer entry.

- [ ] **Step 3: Extract deterministic game checks**

Move every game-only block from `_review_chapter_body` to `game_webnovel/review.py`, including game ID, currency conversion, exchange rates, marketplace batch limits, first-chapter game pacing, task/level/transfer restrictions, monster panels, player/NPC visibility, game opening NPC requirements, and project-specific game checks.

```python
def review_game_chapter(context) -> dict:
    issues, revision_plan, scores = [], [], {}
    run_game_identity_checks(context, issues, revision_plan, scores)
    run_game_economy_checks(context, issues, revision_plan, scores)
    run_game_progression_checks(context, issues, revision_plan, scores)
    run_game_visibility_checks(context, issues, revision_plan, scores)
    external = review_web_game_chapter(...)
    return merge_genre_review(scores, issues, revision_plan, external)
```

- [ ] **Step 4: Keep the generic reviewer genre-neutral**

The generic profile returns an empty genre review. The common review coordinator continues running prose, continuity, world consistency, reader, style, and plot checks, then merges only the active profile review.

- [ ] **Step 5: Replace `game_context` branches with profile review output**

Remove game inference from body text. Resolve genre from the project only, call `profile.review_chapter(context)`, and expose `active_genre_reviews` in the report. Preserve old `web_game_review` only for actual game projects.

- [ ] **Step 6: Run review tests**

Run: `pytest tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_world_consistency_review.py tests/story_core/test_progression_lead_review.py tests/story_core/test_orchestrator.py -q --tb=short`

Expected: all pass.

- [ ] **Step 7: Commit review extraction**

```powershell
git add packages/story_core/genre_stages packages/story_core/orchestrator.py tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_world_consistency_review.py
git commit -m "refactor: isolate game chapter review"
```

### Task 5: Move Revision Rules And Prompt Normalization

**Files:**
- Create: `packages/story_core/genre_stages/game_webnovel/revision.py`
- Modify: `packages/story_core/genre_stages/generic.py`
- Modify: `packages/story_core/orchestrator.py:4454-4530,6081-6151`
- Modify: `tests/story_core/test_revision_safety.py`
- Modify: `tests/story_core/test_prompt_templates.py`

- [ ] **Step 1: Write failing revision isolation tests**

```python
def test_generic_revision_uses_generic_fact_lock(orchestrator, xianxia_story):
    prompt = orchestrator._revision_prompt(xianxia_story, 2, "原正文", {"event_plan": {}}, {})
    assert "职业、余额、库存、任务、装备" not in prompt


def test_game_revision_keeps_game_fact_lock(orchestrator, game_story):
    prompt = orchestrator._revision_prompt(game_story, 2, "原正文", {"event_plan": {}}, {})
    assert "职业" in prompt
    assert "装备" in prompt
```

- [ ] **Step 2: Run the tests and verify the shared normalizer path is detected**

Run: `pytest tests/story_core/test_revision_safety.py tests/story_core/test_prompt_templates.py -q --tb=short`

Expected: the new ownership assertion fails while revision normalization remains in the orchestrator.

- [ ] **Step 3: Implement generic revision rendering**

Move the neutral consolidated review, manual instructions, style reminder, scene repair, length ceiling, generic fact lock, and source-body template rendering to `generic.py` or a neutral revision helper.

- [ ] **Step 4: Implement game revision rendering**

`game_webnovel/revision.py` augments the neutral revision context with game forbidden terms and `web_game_revision_fact_lock`, then applies `normalize_legacy_economy_prompt_value`.

```python
def render_game_revision_prompt(context):
    rendered = render_common_revision_prompt(context, fact_lock=web_game_revision_fact_lock())
    return normalize_legacy_economy_prompt_value(
        rendered,
        game_context=True,
        chapter_number=context.chapter_number,
    )
```

- [ ] **Step 5: Replace revision branching with profile delegation**

```python
profile = genre_stage_profile_for(story, plan)
return profile.render_revision_prompt(context=revision_context)
```

Delete direct imports of game economy normalization and the game fact lock from the orchestrator revision path.

- [ ] **Step 6: Run revision tests**

Run: `pytest tests/story_core/test_revision_safety.py tests/story_core/test_prompt_templates.py tests/story_core/test_orchestrator.py -q --tb=short`

Expected: all pass.

- [ ] **Step 7: Commit revision extraction**

```powershell
git add packages/story_core/genre_stages packages/story_core/orchestrator.py tests/story_core/test_revision_safety.py tests/story_core/test_prompt_templates.py
git commit -m "refactor: isolate genre revision prompts"
```

### Task 6: Remove Compatibility Scaffolding And Enforce The Boundary

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/genre_stages/registry.py`
- Modify: `tests/story_core/test_genre_prompt_isolation.py`
- Modify: `tests/story_core/test_orchestrator.py`

- [ ] **Step 1: Add a source-boundary test**

```python
def test_orchestrator_prompt_pipeline_has_no_game_vocabulary():
    source = Path("packages/story_core/orchestrator.py").read_text(encoding="utf-8")
    prompt_region = source[source.index("def _plan_prompt"):source.index("def _extract_final_body_memory")]
    for term in ("游戏ID", "怪物卡", "装备耐久", "交易行", "网游写法", "web_game_revision_fact_lock"):
        assert term not in prompt_region
```

Also assert that the region does not import or call `normalize_legacy_economy_prompt_value`, `review_web_game_chapter`, or `web_game_writer_method_lines`.

- [ ] **Step 2: Run the boundary test and verify remaining references fail it**

Run: `pytest tests/story_core/test_genre_prompt_isolation.py::test_orchestrator_prompt_pipeline_has_no_game_vocabulary -q --tb=short`

Expected: fails until all compatibility references are deleted.

- [ ] **Step 3: Delete compatibility callbacks and dead helpers**

Delete game prompt imports, `_story_game_context` use inside stage prompt assembly, game-only writer helpers, game-only review branches, and temporary profile callbacks. Keep state application and persistence logic only when it is outside prompt/review ownership; route any remaining game-specific state interpretation through the game profile.

- [ ] **Step 4: Run the boundary and focused suites**

Run: `pytest tests/story_core/test_genre_stage_profiles.py tests/story_core/test_genre_prompt_isolation.py tests/story_core/test_prompt_templates.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_revision_safety.py -q --tb=short`

Expected: all pass.

- [ ] **Step 5: Commit cleanup**

```powershell
git add packages/story_core/orchestrator.py packages/story_core/genre_stages tests/story_core/test_genre_prompt_isolation.py tests/story_core/test_orchestrator.py
git commit -m "refactor: remove game rules from orchestrator"
```

### Task 7: Verify Runtime Prompt Transparency

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `tests/api/test_prompt_audit_routes.py`
- Modify: `apps/web/tests/prompt-audit.spec.ts`

- [ ] **Step 1: Add API assertions for stage sources**

For a game project, assert actual calls list `game_webnovel.director`, `game_webnovel.writer`, `game_webnovel.review`, or `game_webnovel.revision` as applicable. For a xianxia project, assert none of those sources or game terms are present.

- [ ] **Step 2: Run the API test and verify source metadata is missing**

Run: `pytest tests/api/test_prompt_audit_routes.py -q --tb=short`

Expected: fails because prompt artifacts do not yet expose the profile source.

- [ ] **Step 3: Add profile source metadata to prompt artifacts**

Store `genre_stage_profile` and `genre_stage_modules` beside existing template source metadata. Do not store duplicate prompt text.

```python
artifact["genre_stage_profile"] = profile.profile_id
artifact["genre_stage_modules"] = list(profile.active_modules)
```

- [ ] **Step 4: Update the workbench test**

Assert the existing “实际调用” view displays the active题材 module source and does not show inactive game modules for non-game projects. Do not add a new page or workflow step.

- [ ] **Step 5: Run API and Playwright tests**

Run: `pytest tests/api/test_prompt_audit_routes.py -q --tb=short`

Run from `apps/web`: `npx playwright test tests/prompt-audit.spec.ts --reporter=line`

Expected: all pass.

- [ ] **Step 6: Run final regression and source scans**

```powershell
pytest tests/story_core -q --tb=short
pytest tests/api/test_prompt_audit_routes.py -q --tb=short
rg -n "游戏ID|怪物卡|装备耐久|交易行|网游写法|web_game_" packages/story_core/orchestrator.py
git diff --check
```

Expected: relevant suites pass; the source scan returns no stage-prompt/review game ownership in `orchestrator.py`. Existing unrelated failures must be reported separately rather than hidden.

- [ ] **Step 7: Commit runtime transparency**

```powershell
git add packages/story_core/file_project_store.py tests/api/test_prompt_audit_routes.py apps/web/tests/prompt-audit.spec.ts
git commit -m "feat: expose active genre stage modules"
```
