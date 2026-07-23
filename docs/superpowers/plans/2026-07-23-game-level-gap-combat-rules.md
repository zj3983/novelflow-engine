# Game Level-Gap Combat Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent normal solo kills against monsters three or more levels above the player unless an established special condition and visible cost justify the result.

**Architecture:** Add one focused `game_level_gap` policy module that owns the threshold, exception vocabulary, level extraction, and review result. The game genre rulebook, world-scene simulation, writer method card, and post-draft reviewer consume that shared policy; current project data is migrated separately so old outlines do not keep reintroducing invalid fights.

**Tech Stack:** Python 3.11, Pydantic story models, pytest, JSON/Markdown file-project storage.

---

### Task 1: Add the shared level-gap policy

**Files:**
- Create: `packages/story_core/game_level_gap.py`
- Create: `tests/story_core/test_game_level_gap.py`

- [ ] **Step 1: Write failing policy tests**

```python
from packages.story_core.game_level_gap import assess_level_gap, level_gap_rule_text


def test_two_level_gap_is_a_normal_challenge():
    result = assess_level_gap(player_level=5, monster_level=7, evidence_text="")
    assert result.allowed is True
    assert result.requires_special_reason is False


def test_three_level_gap_requires_an_established_special_reason():
    result = assess_level_gap(player_level=5, monster_level=8, evidence_text="他靠走位和计算单杀精英怪。")
    assert result.allowed is False
    assert result.requires_special_reason is True


def test_three_level_gap_accepts_a_real_preexisting_advantage():
    result = assess_level_gap(
        player_level=5,
        monster_level=8,
        evidence_text="任务道具先压制了精英怪，夜烬和三名队友合力击杀，法力耗尽。",
    )
    assert result.allowed is True
    assert result.reason_codes == ("party", "quest_item")
    assert result.has_visible_cost is True


def test_rule_text_does_not_treat_skill_as_a_special_reason():
    text = level_gap_rule_text()
    assert "高出1至2级" in text
    assert "高出3级及以上" in text
    assert "走位、计算和操作不能单独" in text
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/story_core/test_game_level_gap.py -q`

Expected: FAIL because `packages.story_core.game_level_gap` does not exist.

- [ ] **Step 3: Implement the minimal shared policy**

```python
from __future__ import annotations

from dataclasses import dataclass

MAX_NORMAL_LEVEL_GAP = 2
SPECIAL_REASON_MARKERS = {
    "party": ("组队", "队友", "合力", "小队"),
    "quest_item": ("任务道具", "任务物品", "压制道具"),
    "counter": ("属性克制", "弱点", "克制"),
    "equipment": ("特殊装备", "套装效果", "临时装备效果"),
    "terrain": ("地形机关", "陷阱", "机关", "坠落伤害"),
    "wounded": ("残血", "重伤", "只剩一成生命"),
    "established_power": ("已解锁", "既有能力", "此前获得"),
}
COST_MARKERS = ("受伤", "生命下降", "法力耗尽", "药水耗尽", "装备损坏", "失败风险", "撤退")


@dataclass(frozen=True)
class LevelGapAssessment:
    allowed: bool
    gap: int
    requires_special_reason: bool
    reason_codes: tuple[str, ...] = ()
    has_visible_cost: bool = False


def assess_level_gap(*, player_level: int, monster_level: int, evidence_text: str) -> LevelGapAssessment:
    gap = monster_level - player_level
    if gap <= MAX_NORMAL_LEVEL_GAP:
        return LevelGapAssessment(True, gap, False)
    reasons = tuple(
        code for code, markers in SPECIAL_REASON_MARKERS.items()
        if any(marker in evidence_text for marker in markers)
    )
    has_cost = any(marker in evidence_text for marker in COST_MARKERS)
    return LevelGapAssessment(bool(reasons) and has_cost, gap, True, reasons, has_cost)


def level_gap_rule_text() -> str:
    return (
        "怪物高出玩家1至2级可以挑战，但要体现难度和消耗；高出3级及以上默认不能正常单杀，"
        "只有提前建立的组队、任务道具、明确克制、特殊装备、地形机关、怪物残血或既有特殊能力才能例外。"
        "走位、计算和操作不能单独构成越级理由。"
    )
```

- [ ] **Step 4: Run the policy tests and verify GREEN**

Run: `python -m pytest tests/story_core/test_game_level_gap.py -q`

Expected: 4 passed.

- [ ] **Step 5: Commit the shared policy**

```bash
git add packages/story_core/game_level_gap.py tests/story_core/test_game_level_gap.py
git commit -m "feat: add game level-gap combat policy"
```

### Task 2: Enforce the policy in world rules and scene simulation

**Files:**
- Modify: `packages/story_core/genre_types/game_webnovel.py:17-23`
- Modify: `packages/story_core/world_simulation.py:719-738`
- Modify: `tests/story_core/test_world_simulation.py`
- Modify: `tests/story_core/test_genre_plugins.py`

- [ ] **Step 1: Write failing integration tests**

```python
from packages.story_core.models import WorldEvent


def test_combat_scene_card_carries_level_gap_boundary():
    events = [
        WorldEvent(
            event_id="fight-1",
            template_id="combat",
            actor="夜烬",
            action="挑战Lv.8精英怪",
            consequences=["尝试击杀腐沼鳄"],
        )
    ]
    scene_cards = select_scene_cards(events, chapter_seed={}, simulation_plan={})
    surface = "\n".join("\n".join(card.must_show) for card in scene_cards)
    assert "高出3级及以上" in surface
    assert "走位、计算和操作不能单独" in surface


def test_game_genre_rulebook_defines_level_gap_boundary():
    rules = "\n".join(GAME_WEBNOVEL.rulebook["progression_rules"])
    assert "高出1至2级" in rules
    assert "高出3级及以上" in rules
```

- [ ] **Step 2: Run the integration tests and verify RED**

Run: `python -m pytest tests/story_core/test_world_simulation.py tests/story_core/test_genre_plugins.py -q`

Expected: FAIL because no shared level-gap boundary reaches the genre rulebook or combat scene cards.

- [ ] **Step 3: Add the rule to the game genre plugin**

```python
from packages.story_core.game_level_gap import level_gap_rule_text

# game_webnovel.py, progression_rules
level_gap_rule_text(),
```

- [ ] **Step 4: Add the rule only to combat scene cards**

```python
from packages.story_core.game_level_gap import level_gap_rule_text

combat_text = " ".join([event.action, *event.consequences])
if any(token in combat_text for token in ("战斗", "挑战", "攻击", "击杀", "精英怪", "首领", "BOSS")):
    must_show.append(level_gap_rule_text())
```

- [ ] **Step 5: Run the integration tests and verify GREEN**

Run: `python -m pytest tests/story_core/test_world_simulation.py tests/story_core/test_genre_plugins.py -q`

Expected: all tests pass; combat scene cards carry one compact copy of the rule.

- [ ] **Step 6: Commit the simulation and prompt integration**

```bash
git add packages/story_core/genre_types/game_webnovel.py packages/story_core/world_simulation.py tests/story_core/test_world_simulation.py tests/story_core/test_genre_plugins.py
git commit -m "feat: enforce level gaps before game combat writing"
```

### Task 3: Reject unjustified over-level kills after generation

**Files:**
- Modify: `packages/story_core/game_level_gap.py`
- Modify: `packages/story_core/web_game_review.py:652-735`
- Modify: `tests/story_core/test_game_level_gap.py`
- Modify: `tests/story_core/test_web_game_review_agent.py`

- [ ] **Step 1: Write failing extraction and reviewer tests**

```python
def test_review_rejects_three_level_solo_kill_with_only_skill_claims():
    body = (
        "【夜烬】【等级：Lv.5】【生命：100/100】"
        "【腐沼鳄（精英）】【等级：Lv.8】【生命：400/400】【攻击方式：扑咬】【技能：扫尾】【特性：厚皮】"
        "夜烬只靠走位和计算避开攻击，最后单独击杀了腐沼鳄。"
    )
    review = review_web_game_chapter(chapter_number=20, body=body, event_plan={"ordered_actions": ["单刷腐沼鳄"]})
    assert any("高出3级" in issue and "缺少成立条件" in issue for issue in review["issues"])


def test_review_accepts_three_level_kill_with_preexisting_quest_item_and_party():
    body = (
        "【夜烬】【等级：Lv.5】【生命：100/100】"
        "任务说明早已写明缚鳄索能压制腐沼鳄。夜烬和三名队友使用缚鳄索后开怪。"
        "【腐沼鳄（精英）】【等级：Lv.8】【生命：400/400】【攻击方式：扑咬】【技能：扫尾】【特性：厚皮】"
        "四人耗尽药水才将它击杀。"
    )
    review = review_web_game_chapter(
        chapter_number=20,
        body=body,
        event_plan={"special_combat_conditions": ["任务道具缚鳄索", "四人组队"]},
    )
    assert not any("高出3级" in issue for issue in review["issues"])
```

- [ ] **Step 2: Run the reviewer tests and verify RED**

Run: `python -m pytest tests/story_core/test_game_level_gap.py tests/story_core/test_web_game_review_agent.py -q`

Expected: FAIL because the reviewer does not compare player and monster levels.

- [ ] **Step 3: Add conservative level extraction and review helpers**

```python
@dataclass(frozen=True)
class LevelGapCase:
    player_level: int
    monster_level: int
    evidence_text: str


def extract_level_gap_case(body: str, context_text: str = "") -> LevelGapCase | None:
    player = re.search(r"【(?:夜烬|玩家|角色)[^】]*】[^【]{0,120}?【?等级[：:]\s*(?:Lv\.?\s*)?(\d+)", body, re.I)
    monster = re.search(r"【[^】]*(?:精英|首领|BOSS|怪)[^】]*】[^【]{0,160}?【?等级[：:]\s*(?:Lv\.?\s*)?(\d+)", body, re.I)
    if not player or not monster or "击杀" not in body:
        return None
    kill_prefix = body[: body.find("击杀")]
    return LevelGapCase(int(player.group(1)), int(monster.group(1)), "\n".join([context_text, kill_prefix]))
```

- [ ] **Step 4: Wire the policy into `review_web_game_chapter`**

```python
case = extract_level_gap_case(body, "\n".join([plan_text, facts_text]))
if case:
    assessment = assess_level_gap(
        player_level=case.player_level,
        monster_level=case.monster_level,
        evidence_text=case.evidence_text,
    )
    if not assessment.allowed:
        _append_issue(
            issues=issues,
            revision_plan=revision_plan,
            scores=scores,
            score_key="combat_rules",
            issue=f"越级战斗不成立：怪物高出玩家{assessment.gap}级，缺少提前建立的特殊理由或可见代价。",
            plan="改为撤退、侦察、组队或挑战低等级目标；例外必须同时使用既有任务道具、克制、装备、地形、残血或特殊能力，并写出资源消耗或受伤风险。",
        )
```

- [ ] **Step 5: Run reviewer tests and verify GREEN**

Run: `python -m pytest tests/story_core/test_game_level_gap.py tests/story_core/test_web_game_review_agent.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the reviewer enforcement**

```bash
git add packages/story_core/game_level_gap.py packages/story_core/web_game_review.py tests/story_core/test_game_level_gap.py tests/story_core/test_web_game_review_agent.py
git commit -m "feat: review unjustified over-level monster kills"
```

### Task 4: Migrate the active web-game project and run regression checks

**Files:**
- Modify: `data/exported-projects/p-gou-webgame-restored/.webnovel/outline.json`
- Modify: `data/exported-projects/p-gou-webgame-restored/.webnovel/project.json`
- Modify: `data/exported-projects/p-gou-webgame-restored/.webnovel/state.json`
- Modify: `data/exported-projects/p-gou-webgame-restored/.story-system/chapters/0001.json`
- Modify: `data/exported-projects/p-gou-webgame-restored/chapters/0001-灰狼坡的第一笔到账.md`
- Modify: `data/exported-projects/p-gou-webgame-restored/大纲/爽点规划.md`
- Modify: `data/exported-projects/p-gou-webgame-restored/大纲/第1卷-详细大纲.md`
- Modify: `data/exported-projects/p-gou-webgame-restored/大纲/第2卷-详细大纲.md`

- [ ] **Step 1: Add the world rule to active project metadata**

Add this rule once to the project world rules, then synchronize the existing project/state mirrors without duplicating it into author-style constraints:

```text
怪物高出玩家1至2级可以挑战，但必须体现风险和消耗；高出3级及以上默认不能正常单杀，只有提前建立的组队、任务道具、明确克制、特殊装备、地形机关、怪物残血或既有特殊能力才能例外。走位、计算和操作不能单独作为理由。
```

- [ ] **Step 2: Repair existing invalid combat anchors**

Apply these scoped project edits without touching backups or generation logs:

```text
第一章裂纹狼精英：Lv.5 -> Lv.4，使升级到Lv.2后的挑战保持两级差。
“精算打法越级杀怪” -> “同级或高一两级战斗中，用完整技能循环扩大效率优势”。
Lv.25挑战Lv.28腐沼鳄 -> 提前取得任务道具缚鳄索并四人组队，胜利后药水耗尽。
```

- [ ] **Step 3: Validate active project consistency**

Run:

```powershell
rg -n "精算打法越级杀怪|Lv\.25越级拿下Lv\.28|裂纹狼（精英Lv\.5）|等级Lv\.5" data/exported-projects/p-gou-webgame-restored --glob '!**/generation-jobs/**' --glob '!**/backups/**' --glob '!**/归档-旧正文/**'
```

Expected: no matches. Parse `.webnovel/*.json` and `.story-system/chapters/0001.json` with `ConvertFrom-Json`, and assert the chapter JSON body exactly matches the chapter Markdown file.

- [ ] **Step 4: Run focused and regression tests**

Run:

```bash
python -m pytest tests/story_core/test_game_level_gap.py tests/story_core/test_world_simulation.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_writing_taskbook.py tests/story_core/test_web_game_review_agent.py tests/story_core/test_generation_quality_guardrails.py -q
git diff --check
```

Expected: all selected tests pass; no whitespace errors.

- [ ] **Step 5: Verify the running API returns migrated data**

Run:

```powershell
$response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/file-projects/file%3Ap-gou-webgame-restored'
$response.Content.Contains('怪物高出玩家1至2级')
$response.Content.Contains('裂纹狼（精英Lv.5）')
```

Expected: `True`, then `False`.

- [ ] **Step 6: Commit the project migration**

```bash
git add data/exported-projects/p-gou-webgame-restored
git commit -m "fix: align web-game outline with level-gap rules"
```
