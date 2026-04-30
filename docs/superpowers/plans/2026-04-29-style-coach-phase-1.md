# Style Coach Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight Style Coach that turns web-game simulation events into actionable writing guidance and performance-card fields for Writer and Revision prompts.

**Architecture:** Implement a deterministic `style_coach.py` module with typed guidance dictionaries, extend scene cards with `write_as`, `avoid`, and `fact_locks`, then inject the guidance into initial writing and revision prompts. Keep it local and testable; no model calls or UI work in this phase.

**Tech Stack:** Python 3.12, Pydantic models already in `packages/story_core`, pytest.

---

## File Structure

- Create `packages/story_core/style_coach.py`
  - Owns `build_style_guidance`, `enrich_performance_cards`, and the first `web_game_leveling_opening` playbook.
- Modify `packages/story_core/orchestrator.py`
  - Imports Style Coach helpers.
  - Adds style guidance and enriched scene cards to Writer and Revision prompts.
  - Stores style guidance in the generated bundle's `simulation_plan` or `chapter_seed` for inspection.
- Add `tests/story_core/test_style_coach.py`
  - Unit tests for guidance and performance-card enrichment.
- Modify `tests/story_core/test_chapter_seed.py`
  - Prompt-level regression test that Writer/Revision prompts include Style Coach guidance.

---

### Task 1: Add Style Coach Module

**Files:**
- Create: `packages/story_core/style_coach.py`
- Test: `tests/story_core/test_style_coach.py`

- [ ] **Step 1: Write failing tests**

Create `tests/story_core/test_style_coach.py` with:

```python
from packages.story_core.style_coach import build_style_guidance, enrich_performance_cards


def test_build_style_guidance_returns_web_game_opening_playbook():
    guidance = build_style_guidance(
        genre="网游",
        chapter_number=1,
        world_events=[{"template_id": "market_weak_trace"}],
        scene_cards=[],
    )

    assert guidance["profile_id"] == "web_game_leveling_opening"
    assert "现实压力" in guidance["chapter_pattern"]
    assert any("交易规则通过界面" in item for item in guidance["show_rules"])
    assert any("机械短段" in item for item in guidance["avoid_rules"])


def test_enrich_performance_cards_adds_market_writing_instructions():
    cards = [
        {
            "scene_id": "s5-c1-market",
            "template_id": "market_weak_trace",
            "must_show": ["价格", "数量", "手续费", "到账"],
        }
    ]
    guidance = build_style_guidance(
        genre="网游",
        chapter_number=1,
        world_events=[{"template_id": "market_weak_trace"}],
        scene_cards=cards,
    )

    enriched = enrich_performance_cards(cards, guidance)

    assert enriched[0]["template_id"] == "market_weak_trace"
    assert "界面操作" in enriched[0]["write_as"]
    assert "解释市场规则" in enriched[0]["avoid"]
    assert any("余额" in item or "手续费" in item for item in enriched[0]["fact_locks"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
pytest tests\story_core\test_style_coach.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'packages.story_core.style_coach'`.

- [ ] **Step 3: Implement `style_coach.py`**

Create `packages/story_core/style_coach.py`:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any


WEB_GAME_OPENING_GUIDANCE: dict[str, Any] = {
    "profile_id": "web_game_leveling_opening",
    "genre": "web_game_leveling",
    "voice": "直白、紧凑、生活化，有爽点但不喊爽点",
    "chapter_pattern": "现实压力 -> 游戏入口 -> 异常伏笔 -> 小额验证 -> 交易弱线索",
    "show_rules": [
        "交易规则通过界面、手续费、到账、批次号和旁人脚本记录表现。",
        "金手指先异常再验证，不直接解释成百科。",
        "公会压力只给资源点目击、论坛截图或批次记录，不正面对抗。",
        "NPC服务通过地点、口吻、价格、账本和信息边界影响选择。",
    ],
    "avoid_rules": [
        "不要用意味着、很直接、很清楚、风险也是这类报告式判断。",
        "不要连续使用孤立机械短段，让段落像 AI 卡片。",
        "不要让润色新增消费、装备、任务结果或改变账本。",
        "不要把交易行、公会、NPC规则写成说明书。",
    ],
}


CARD_GUIDANCE: dict[str, dict[str, list[str]]] = {
    "reality_entry": {
        "write_as": ["账单物件", "房间细节", "手指停顿", "现实技能带来的判断"],
        "avoid": ["直接总结主角很惨", "大段解释现实背景"],
        "fact_locks": ["现实职业/技能来源不得改", "登录动机不得改"],
    },
    "character_creation": {
        "write_as": ["角色创建界面", "职业列表", "成本权衡", "角色面板"],
        "avoid": ["只在旁白里说职业", "漏掉基础属性"],
        "fact_locks": ["游戏ID", "职业", "等级", "经验", "生命/法力", "基础属性"],
    },
    "small_verification": {
        "write_as": ["低级怪战斗", "掉落提示音", "背包数字变化", "主角停顿"],
        "avoid": ["直接宣布金手指无敌", "跳过验证过程"],
        "fact_locks": ["掉落数量", "背包变化", "经验变化"],
    },
    "single_npc_service": {
        "write_as": ["NPC地点", "柜台/工具/账本", "岗位口吻", "服务价格或门槛"],
        "avoid": ["NPC只当任务牌子", "NPC全知隐藏天赋"],
        "fact_locks": ["NPC只能看到服务记录", "NPC不能知道隐藏天赋"],
    },
    "market_weak_trace": {
        "write_as": ["界面操作", "手指停顿", "成交提示音", "旁人脚本记录"],
        "avoid": ["解释市场规则", "直接说风险", "暴露坐标", "新增消费"],
        "fact_locks": ["寄售数量", "单价", "手续费", "到账金额", "最终余额"],
    },
}


def _is_web_game(genre: str, world_events: list[dict[str, Any]], scene_cards: list[dict[str, Any]]) -> bool:
    text = " ".join(
        [
            genre,
            *[str(event.get("template_id", "")) for event in world_events],
            *[str(card.get("template_id", "")) for card in scene_cards],
        ]
    )
    return any(token in text for token in ("网游", "web_game", "market_weak_trace", "character_creation"))


def build_style_guidance(
    *,
    genre: str,
    chapter_number: int,
    world_events: list[dict[str, Any]] | None = None,
    scene_cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    world_events = world_events or []
    scene_cards = scene_cards or []
    if chapter_number <= 3 and _is_web_game(genre, world_events, scene_cards):
        return deepcopy(WEB_GAME_OPENING_GUIDANCE)
    return {
        "profile_id": "generic_plain_prose",
        "genre": "generic",
        "voice": "清楚、自然、少解释，多用动作和场景承载信息",
        "chapter_pattern": "目标 -> 行动 -> 反馈 -> 新压力",
        "show_rules": ["规则和设定优先通过动作、对话、界面或环境反馈表现。"],
        "avoid_rules": ["不要写成说明书，不要连续机械短段。"],
    }


def enrich_performance_cards(
    scene_cards: list[dict[str, Any]] | None,
    style_guidance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for card in scene_cards or []:
        new_card = deepcopy(card)
        template_id = str(new_card.get("template_id", ""))
        guidance = CARD_GUIDANCE.get(template_id, {})
        for key in ("write_as", "avoid", "fact_locks"):
            existing = [str(item) for item in new_card.get(key, []) if str(item).strip()] if isinstance(new_card.get(key), list) else []
            additions = guidance.get(key, [])
            merged = []
            for item in [*existing, *additions]:
                if item and item not in merged:
                    merged.append(item)
            if merged:
                new_card[key] = merged
        enriched.append(new_card)
    return enriched
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest tests\story_core\test_style_coach.py -q
```

Expected: `2 passed`.

---

### Task 2: Inject Style Guidance Into Prompts

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_chapter_seed.py`

- [ ] **Step 1: Add prompt regression tests**

Append to `tests/story_core/test_chapter_seed.py`:

```python
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


def test_writing_prompt_includes_style_coach_guidance():
    story = StoryState(story_id="s-style-coach", outline="网游开服", genre="网游", style="升级流")
    orchestrator = StoryOrchestrator()
    plan = {
        "scene_cards": [
            {
                "scene_id": "s5-c1-market",
                "template_id": "market_weak_trace",
                "must_show": ["价格", "数量", "手续费", "到账"],
            }
        ],
        "style_guidance": {
            "profile_id": "web_game_leveling_opening",
            "chapter_pattern": "现实压力 -> 游戏入口 -> 异常伏笔 -> 小额验证 -> 交易弱线索",
            "show_rules": ["交易规则通过界面、手续费、到账、批次号和旁人脚本记录表现。"],
            "avoid_rules": ["不要连续使用孤立机械短段，让段落像 AI 卡片。"],
        },
    }

    prompt = orchestrator._writing_prompt(story, 1, plan)

    assert "写作教练 Style Coach" in prompt
    assert "web_game_leveling_opening" in prompt
    assert "交易规则通过界面" in prompt
    assert "不要连续使用孤立机械短段" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests\story_core\test_chapter_seed.py::test_writing_prompt_includes_style_coach_guidance -q
```

Expected: fail because prompt does not include the new Style Coach section.

- [ ] **Step 3: Import Style Coach helpers**

In `packages/story_core/orchestrator.py`, add:

```python
from packages.story_core.style_coach import build_style_guidance, enrich_performance_cards
```

- [ ] **Step 4: Add prompt section**

Inside `_writing_prompt`, after `style_rules = anti_ai_style_rules()`, add:

```python
        style_guidance = plan.get("style_guidance", {})
```

Then add this line to the prompt payload near the anti-AI protocol:

```python
                f"写作教练 Style Coach：{json.dumps(style_guidance, ensure_ascii=False)}",
```

- [ ] **Step 5: Run prompt test**

Run:

```powershell
pytest tests\story_core\test_chapter_seed.py::test_writing_prompt_includes_style_coach_guidance -q
```

Expected: `1 passed`.

---

### Task 3: Build Guidance During Chapter Generation

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_chapter_seed.py`

- [ ] **Step 1: Add generation helper test**

Append:

```python
from packages.story_core.style_coach import build_style_guidance, enrich_performance_cards


def test_style_coach_enriches_market_scene_card_for_generation():
    scene_cards = [{"scene_id": "s5", "template_id": "market_weak_trace", "must_show": ["到账"]}]
    guidance = build_style_guidance(
        genre="网游",
        chapter_number=1,
        world_events=[{"template_id": "market_weak_trace"}],
        scene_cards=scene_cards,
    )
    enriched = enrich_performance_cards(scene_cards, guidance)

    assert guidance["profile_id"] == "web_game_leveling_opening"
    assert "界面操作" in enriched[0]["write_as"]
    assert "新增消费" in enriched[0]["avoid"]
```

- [ ] **Step 2: Run test**

Run:

```powershell
pytest tests\story_core\test_chapter_seed.py::test_style_coach_enriches_market_scene_card_for_generation -q
```

Expected: pass once Task 1 is implemented.

- [ ] **Step 3: Wire guidance into `generate_next_chapter`**

In `generate_next_chapter`, after `scene_cards = [...]`, add:

```python
        style_guidance = build_style_guidance(
            genre=story.genre,
            chapter_number=chapter_number,
            world_events=world_events,
            scene_cards=scene_cards,
        )
        scene_cards = enrich_performance_cards(scene_cards, style_guidance)
```

Then include `style_guidance` anywhere `scene_cards` is passed into prompt plans:

```python
                        "style_guidance": style_guidance,
```

Also set it in the `ChapterBundle` construction:

```python
            simulation_plan={**simulation_plan, "style_guidance": style_guidance},
```

If `simulation_plan` must remain unchanged elsewhere, use:

```python
            simulation_plan={**(simulation_plan or {}), "style_guidance": style_guidance},
```

- [ ] **Step 4: Run targeted tests**

Run:

```powershell
pytest tests\story_core\test_chapter_seed.py tests\story_core\test_style_coach.py -q
```

Expected: all pass.

---

### Task 4: Inject Style Guidance Into Revision Prompt

**Files:**
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_chapter_seed.py`

- [ ] **Step 1: Add revision prompt regression test**

Append:

```python
def test_revision_prompt_includes_style_coach_and_fact_lock_language():
    story = StoryState(story_id="s-style-revision", outline="网游开服", genre="网游", style="升级流")
    orchestrator = StoryOrchestrator()
    prompt = orchestrator._revision_prompt(
        story,
        1,
        "夜烬把毒腺挂上交易行。",
        {
            "scene_cards": [
                {
                    "scene_id": "s5-c1-market",
                    "template_id": "market_weak_trace",
                    "write_as": ["界面操作", "成交提示音"],
                    "avoid": ["新增消费"],
                    "fact_locks": ["最终余额"],
                }
            ],
            "style_guidance": {
                "profile_id": "web_game_leveling_opening",
                "avoid_rules": ["不要让润色新增消费、装备、任务结果或改变账本。"],
            },
        },
        {"issues": ["正文有机械切段或解释腔"], "revision_plan": ["合并连续短句"]},
    )

    assert "写作教练 Style Coach" in prompt
    assert "不要让润色新增消费" in prompt
    assert "新增消费" in prompt
    assert "最终余额" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests\story_core\test_chapter_seed.py::test_revision_prompt_includes_style_coach_and_fact_lock_language -q
```

Expected: fail until revision prompt includes the Style Coach section.

- [ ] **Step 3: Modify `_revision_prompt`**

Inside `_revision_prompt`, add:

```python
        style_guidance = plan.get("style_guidance", {})
```

Add this line in the prompt list near `反AI味改稿协议`:

```python
                f"写作教练 Style Coach：{json.dumps(style_guidance, ensure_ascii=False)}",
```

Add one hard rule:

```python
                "事实锁硬规则：scene_cards.fact_locks 中的职业、余额、库存、任务、装备和NPC信息边界不得被润色改动；若不能确定，保留原文事实。",
```

- [ ] **Step 4: Run revision prompt test**

Run:

```powershell
pytest tests\story_core\test_chapter_seed.py::test_revision_prompt_includes_style_coach_and_fact_lock_language -q
```

Expected: `1 passed`.

---

### Task 5: Verification

**Files:**
- No new files.

- [ ] **Step 1: Run full backend tests**

Run:

```powershell
pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
npm run build
```

Working directory: `apps/web`

Expected: Next build succeeds.

- [ ] **Step 3: Restart backend**

Run:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'uvicorn apps.api.main:app.*8000' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000" -WorkingDirectory "D:\xiaoshuofish\.worktrees\novel-autogrowth-engine" -RedirectStandardOutput "api-dev.out.log" -RedirectStandardError "api-dev.err.log" -WindowStyle Hidden
Start-Sleep -Seconds 6
Invoke-WebRequest -Uri http://127.0.0.1:8000/stories -UseBasicParsing -TimeoutSec 10
```

Expected: HTTP 200.

---

## Self-Review

Spec coverage:

- Style Coach module: Task 1.
- Performance cards: Task 1 and Task 3.
- Prompt injection: Task 2 and Task 4.
- Fact Guard: intentionally deferred to Phase 2; not included in this Phase 1 plan.
- Style Critic upgrade: already partially implemented; further work is deferred outside Phase 1.

Placeholder scan:

- No TBD/TODO placeholders.
- Each task has exact files, commands, and expected outcomes.

Type consistency:

- `build_style_guidance` and `enrich_performance_cards` signatures are consistent across tests and orchestration.
- Guidance is represented as plain dictionaries to avoid broad Pydantic model changes in Phase 1.

