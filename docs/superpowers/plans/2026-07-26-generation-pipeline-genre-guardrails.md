# Generation Pipeline Genre Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent director action loss, cross-genre cold-reader advice, and planning meta-language leaks without adding agents or normal-path model calls.

**Architecture:** Normalize all supported director move shapes before validating or projecting the plan. Split cold-reader vocabulary into a universal baseline plus optional genre profiles passed through existing review entrypoints. Treat impossible physical uses of planning terms as a focused hard prose violation so the existing single revision round handles them.

**Tech Stack:** Python 3.12, pytest, existing `packages.story_core` orchestration and review modules.

---

## File Map

- Modify `packages/story_core/orchestrator.py`: normalize director actions, enforce fallback-plan quality, and pass genre context to cold reader.
- Modify `packages/story_core/cold_reader_review.py`: own universal and genre-specific cold-reader vocabulary and suggestions.
- Modify `packages/story_core/file_project_store.py`: pass project genre context through manual chapter review.
- Modify `packages/story_core/prose_rule_review.py`: detect impossible physical uses of planning terminology and classify them as hard errors.
- Modify `tests/story_core/test_generation_quality_guardrails.py`: cover object-shaped director moves.
- Modify `tests/story_core/test_director_plan_quality.py`: cover empty action plans and fallback projects without the new outline schema.
- Modify `tests/story_core/test_cold_reader_review.py`: cover game, xuanhuan, and genre-less cold-reader behavior.
- Modify `tests/story_core/test_prose_rule_review.py`: cover meta-language detection and legitimate use.
- Modify `tests/story_core/test_file_project_store.py`: verify manual review forwards genre context.

### Task 1: Preserve And Validate Director Actions

**Files:**
- Modify: `packages/story_core/orchestrator.py:2194-2218`
- Modify: `packages/story_core/orchestrator.py:2278-2317`
- Modify: `packages/story_core/orchestrator.py:6376-6428`
- Test: `tests/story_core/test_generation_quality_guardrails.py`
- Test: `tests/story_core/test_director_plan_quality.py`

- [ ] **Step 1: Write failing tests for object-shaped moves and empty action plans**

Add tests that require grouped model output to retain its character name and require at least one usable action:

```python
def test_director_moves_accept_character_keyed_object():
    moves = _normalize_moves(
        {
            "林照": [
                {"goal": "查清香火来源", "action": "带周满去祖祠查看香灰", "priority": "高"},
            ],
            "赵管事": {"goal": "压住消息", "action": "提前锁上祖祠侧门", "priority": 2},
        }
    )

    assert [(item["name"], item["action"]) for item in moves] == [
        ("林照", "带周满去祖祠查看香灰"),
        ("赵管事", "提前锁上祖祠侧门"),
    ]


def test_director_quality_gate_rejects_plan_without_usable_actions():
    plan = {
        "character_moves": {},
        "event_plan": {
            "ordered_actions": [],
            "chapter_satisfaction": {
                "core_event": "查清香灰异常",
                "obstacle": "赵管事阻拦",
                "visible_payoff": "找到残留气息",
                "cost": "暴露调查意图",
                "state_change": "祖祠被列为疑点",
                "next_hook": "侧门后传出动静",
            },
            "chapter_end_hook": {"content": "锁住的侧门从里面响了一声"},
        },
    }

    assert any("可执行动作" in issue for issue in _director_plan_quality_issues(_story(), plan))
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_generation_quality_guardrails.py::test_director_moves_accept_character_keyed_object tests/story_core/test_director_plan_quality.py::test_director_quality_gate_rejects_plan_without_usable_actions -q
```

Expected: both tests fail because object-shaped moves are discarded and empty plans are not rejected.

- [ ] **Step 3: Implement one canonical move normalizer**

Refactor `_normalize_moves` so dictionaries are flattened before the existing field normalization:

```python
def _normalize_moves(raw_moves: object) -> list[dict]:
    candidates: list[dict] = []
    if isinstance(raw_moves, list):
        candidates = [item for item in raw_moves if isinstance(item, dict)]
    elif isinstance(raw_moves, dict):
        for name, raw_character_moves in raw_moves.items():
            items = raw_character_moves if isinstance(raw_character_moves, list) else [raw_character_moves]
            for item in items:
                if not isinstance(item, dict):
                    continue
                candidate = dict(item)
                candidate.setdefault("name", str(name).strip())
                candidates.append(candidate)

    moves: list[dict] = []
    for item in candidates[:6]:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        moves.append(
            {
                "name": name,
                "goal": compact_text(str(item.get("goal", "")).strip() or "推进当前主线", 80),
                "emotion": str(item.get("emotion", "")).strip() or "alert",
                "action": compact_text(str(item.get("action", "")).strip() or "继续推进当前主线", 120),
                "priority": _normalize_priority(item.get("priority")),
                "new_character_candidates": compact_list(
                    item.get("new_character_candidates", []), max_items=4, item_chars=60
                ),
            }
        )
    return moves
```

Use `_normalize_moves(plan.get("character_moves"))` and `_normalize_moves(event_plan.get("ordered_actions"))` inside `_director_plan_quality_issues`. Append `导演计划缺少可执行动作。` when both normalized collections are empty.

- [ ] **Step 4: Enforce quality checks for every model-fallback plan**

Replace the schema-dependent condition at the generation call site with a source-dependent condition:

```python
director_issues = (
    _director_plan_quality_issues(working_story, plan)
    if planning_source == "model_fallback"
    else []
)
```

Keep the existing single planner retry and failure bundle unchanged. Remove `_director_quality_gate_enabled` if no callers remain.

- [ ] **Step 5: Add an orchestration regression test without `outline-context/v1`**

Create a story from `_story()`, set `story.outline_context = {}`, return the existing `bad_plan` twice from `_timed_chat`, and assert:

```python
assert calls == ["planner:剧情计划生成", "planner:剧情计划重做"]
assert bundle.body.startswith("生成失败：director_plan_quality_failed")
```

- [ ] **Step 6: Run director tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_director_plan_quality.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit director changes**

```powershell
git add packages/story_core/orchestrator.py tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_director_plan_quality.py
git commit -m "fix: preserve and validate director actions"
```

### Task 2: Make Cold-Reader Review Genre-Aware

**Files:**
- Modify: `packages/story_core/cold_reader_review.py`
- Modify: `packages/story_core/orchestrator.py:3772-3781`
- Modify: `packages/story_core/file_project_store.py:492-506`
- Test: `tests/story_core/test_cold_reader_review.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] **Step 1: Write failing genre-isolation tests**

Update the existing passing game test to call:

```python
review = review_cold_reader_experience(body, genre_context={"genre": "网游"})
```

Add these tests:

```python
def test_xuanhuan_cold_reader_suggestion_does_not_leak_game_terms():
    review = review_cold_reader_experience(
        "林照跟着周满进了祖祠，两人查完香炉便回房歇下。",
        genre_context={"genre": "玄幻"},
    )

    suggestions = "\n".join(review["revision_plan"])
    assert not any(term in suggestions for term in ("交易行", "公会", "NPC", "材料异动"))
    assert any(term in suggestions for term in ("修炼", "势力", "线索", "时限", "人物目标"))


def test_genreless_cold_reader_uses_only_universal_suggestions():
    review = review_cold_reader_experience("他办完事情，回屋睡了。")

    suggestions = "\n".join(review["revision_plan"])
    assert not any(term in suggestions for term in ("交易行", "公会", "NPC", "修炼", "宗门"))
    assert "具体行动" in suggestions or "人物目标" in suggestions
```

Update the existing cognitive-overload test to pass `genre_context={"genre": "网游"}` so its game concepts are evaluated by the game profile rather than the universal baseline.

- [ ] **Step 2: Run the cold-reader tests and verify failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_cold_reader_review.py -q
```

Expected: xuanhuan and genre-less tests fail because suggestions are currently hardcoded for games.

- [ ] **Step 3: Split universal and genre-specific review profiles**

In `cold_reader_review.py`, define a small profile structure and resolver:

```python
UNIVERSAL_HOOK_TERMS = ("下一步", "期限", "真相", "线索", "答复", "决定", "必须", "今晚")
UNIVERSAL_CARE_TERMS = ("失去", "欠", "伤", "怕", "担心", "必须", "只剩", "代价", "家人", "工作")
UNIVERSAL_PAYOFF_TERMS = ("发现", "得到", "赢", "突破", "改变", "答应", "确认", "异常")

GENRE_PROFILES = {
    "game": {
        "aliases": ("网游", "游戏", "虚拟现实"),
        "hook_terms": ("任务", "交易行", "委托", "公会", "倒计时", "未鉴定", "隐藏"),
        "care_terms": ("房租", "账单", "余额", "药水", "耐久"),
        "payoff_terms": ("稀有", "掉落", "装备", "技能", "经验", "协议"),
        "overload_terms": ("底层协议", "灰烬王庭", "星门议会", "七阶职业", "天启拍卖行", "白塔公会", "神格碎片", "深渊税则"),
        "hook_suggestion": "把结尾落到具体行动：下一项任务、交易选择、装备变化、材料去向或现实期限。",
        "loop_suggestion": "让重复操作发生变化：敌人反扑、掉落变化、路线改变、资源消耗或人物介入。",
    },
    "xuanhuan": {
        "aliases": ("玄幻", "仙侠", "修仙"),
        "hook_terms": ("修炼", "突破", "宗门", "差事", "资格", "线索", "时限", "传承"),
        "care_terms": ("寿命", "修为", "伤势", "师门", "家族", "身份", "处境"),
        "payoff_terms": ("突破", "功法", "传承", "灵物", "真相", "资格"),
        "overload_terms": ("太古血脉", "九重天门", "上古神庭", "因果道印", "万族战场", "帝兵残魂"),
        "hook_suggestion": "把结尾落到具体行动：修炼选择、势力差事、资格变化、关键线索、时限或人物目标。",
        "loop_suggestion": "让重复行动发生变化：修炼受阻、关系变化、线索反转、代价出现或对手介入。",
    },
}
```

Change the public signature to:

```python
def review_cold_reader_experience(
    body: str,
    *,
    previous_summary: str = "",
    genre_context: Any = None,
) -> dict[str, Any]:
```

Resolve aliases from `genre_context["genre"]` and `genre_context["genre_plugin_ids"]`. Score hooks, care, and payoff with universal terms plus the resolved profile. Count unfamiliar high concepts only from the resolved profile; a genre-less review must not inherit either profile's concept list. When no profile matches, use universal terms and universal suggestions only:

```python
generic_hook_suggestion = "把结尾落到一个具体行动、未解决的问题、明确时限或人物目标。"
generic_loop_suggestion = "让重复行动产生变化：加入阻力、关系变化、代价或新的决定。"
```

Keep `reviewer="cold_reader/v1"` and the existing result schema stable.

- [ ] **Step 4: Pass genre context through both review entrypoints**

Change the orchestrator future to:

```python
"cold_reader": _pool.submit(
    review_cold_reader_experience,
    body,
    previous_summary=_previous_summary,
    genre_context=genre_context,
),
```

Change `_manual_chapter_quality_report` to pass the same `genre_context` argument. Add a file-store test that monkeypatches `review_cold_reader_experience`, records the received value, calls `_manual_chapter_quality_report`, and asserts the exact genre context was forwarded.

```python
def test_manual_quality_report_passes_genre_context_to_cold_reader(monkeypatch):
    captured = {}

    def fake_cold_reader(body, *, previous_summary="", genre_context=None):
        captured["genre_context"] = genre_context
        return {"pass": True, "scores": {}, "issues": [], "revision_plan": []}

    monkeypatch.setattr(file_project_store_module, "review_cold_reader_experience", fake_cold_reader)
    genre_context = {"genre": "玄幻", "genre_plugin_ids": ["xuanhuan"]}

    _manual_chapter_quality_report(
        {
            "chapter_number": 1,
            "chapter_title": "祖祠",
            "body": "林照进了祖祠。",
            "next_outline": "查清香灰来源",
            "chapter_summary": {"summary": "林照进入祖祠", "facts": []},
            "updated_story": {"timeline": [], "chapter_summaries": []},
        },
        genre_context=genre_context,
    )

    assert captured["genre_context"] == genre_context
```

- [ ] **Step 5: Run review tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_cold_reader_review.py tests/story_core/test_file_project_store.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit genre-aware review changes**

```powershell
git add packages/story_core/cold_reader_review.py packages/story_core/orchestrator.py packages/story_core/file_project_store.py tests/story_core/test_cold_reader_review.py tests/story_core/test_file_project_store.py
git commit -m "fix: isolate cold reader advice by genre"
```

### Task 3: Reject Planning Meta-Language In Prose

**Files:**
- Modify: `packages/story_core/prose_rule_review.py:43-58`
- Modify: `packages/story_core/prose_rule_review.py:155-180`
- Modify: `packages/story_core/prose_rule_review.py:641-655`
- Test: `tests/story_core/test_prose_rule_review.py`
- Test: `tests/story_core/test_generation_quality_guardrails.py`

- [ ] **Step 1: Write failing narrow-match tests**

Add:

```python
def test_diagnostic_review_rejects_planning_term_used_as_physical_location():
    review = review_diagnostic_terms_in_body("周满站在前置条件边，等林照开口。")

    assert review["pass"] is False
    assert review["scores"]["planning_meta_leak"] == 5
    assert any("前置条件" in issue for issue in review["issues"])


def test_diagnostic_review_allows_legitimate_task_prerequisite_sentence():
    review = review_diagnostic_terms_in_body("这个任务需要先完成前置条件，赵管事才肯放人。")

    assert review["pass"] is True
    assert review["scores"]["planning_meta_leak"] == 8


def test_planning_meta_leak_is_classified_as_hard_error():
    review = review_critical_prose_rules("周满说完，迈出前置条件。")

    assert review["severity_summary"]["has_hard_violation"] is True
    assert any("前置条件" in issue for issue in review["hard_issues"])
```

- [ ] **Step 2: Run the focused prose tests and verify failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_prose_rule_review.py -q
```

Expected: the new tests fail because no physical-use pattern or hard score key exists.

- [ ] **Step 3: Add focused pattern detection**

Add compiled patterns that require a physical verb or locative construction immediately around a planning term:

```python
_PLANNING_META_PHYSICAL_PATTERNS = (
    re.compile(r"(?:站在|走到|退到|靠在|停在|蹲在)(?:章节|剧情|任务)?(?:前置条件|剧情节点)(?:边|旁|前|后)?"),
    re.compile(r"(?:迈出|跨过|绕过|推开|关上)(?:章节|剧情|任务)?(?:前置条件|剧情节点)"),
)
```

Collect matched text in `review_diagnostic_terms_in_body`, add this issue and revision instruction, and include the score:

```python
issues.append(f"正文把规划术语写成了场景实体：{'、'.join(meta_hits[:4])}。")
revision_plan.append("删除前置条件、剧情节点等后台规划词，改成角色实际面对的门、台阶、规矩、任务要求或具体动作。")
scores["planning_meta_leak"] = 5 if meta_hits else 8
```

Add `planning_meta_leak` to `HARD_REVIEWERS`. Do not add `前置条件` itself to `_DIAGNOSTIC_TERMS`.

- [ ] **Step 4: Verify hard errors still use the existing single revision rule**

Extend the existing `_should_run_full_revision` test with a report built from `review_critical_prose_rules("周满站在前置条件边。")`, then derive the gate explicitly and assert the existing revision predicate accepts it:

```python
critical = review_critical_prose_rules("周满站在前置条件边。")
gate = {
    "needs_revision": bool(critical["requires_revision"]),
    "has_hard_errors": bool(critical["severity_summary"]["has_hard_violation"]),
}
assert _should_run_full_revision(gate) is True
```

Do not change `MAX_REVISION_ROUNDS = 1`.

- [ ] **Step 5: Run prose and generation guardrail tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_prose_rule_review.py tests/story_core/test_generation_quality_guardrails.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit meta-language guard**

```powershell
git add packages/story_core/prose_rule_review.py tests/story_core/test_prose_rule_review.py tests/story_core/test_generation_quality_guardrails.py
git commit -m "fix: reject planning language leaked into prose"
```

### Task 4: Regression And Real Generation Verification

**Files:**
- Verify: `packages/story_core/orchestrator.py`
- Verify: `packages/story_core/cold_reader_review.py`
- Verify: `packages/story_core/prose_rule_review.py`
- Runtime artifact: `data/exported-projects/p-xianxia-incense-test-2/.story-system/chapters/0002.json`
- Runtime artifact: `data/exported-projects/p-xianxia-incense-test-2/.story-system/reviews/0002.json`

- [ ] **Step 1: Run the complete focused suite**

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_director_plan_quality.py tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_cold_reader_review.py tests/story_core/test_prose_rule_review.py tests/story_core/test_file_project_store.py -q
```

Expected: PASS with no failures.

- [ ] **Step 2: Run the broader story-core regression suite**

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core -q
```

Expected: PASS. If unrelated pre-existing failures appear, record their exact test names and verify the focused suite remains green before proceeding.

- [ ] **Step 3: Verify services and runtime provider**

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:3000/api/health
```

Expected: both endpoints respond successfully. Confirm runtime settings still select `codexcli`; do not alter provider configuration during this task.

- [ ] **Step 4: Regenerate chapter 2 of the dedicated xuanhuan test project**

Use the existing file-project generation-job endpoint for `file:p-xianxia-incense-test-2` and chapter 2. Poll the returned job until it reaches `completed` or `failed`. Do not run against `file:p-gou-webgame-restored`.

Expected workbench behavior:

- director artifact contains at least one normalized action;
- writer and reviewer stages remain the existing nodes;
- no extra normal-path model stage appears;
- at most one revision stage appears, only if a hard error is detected.

- [ ] **Step 5: Inspect the saved chapter and review artifacts**

Run targeted searches:

```powershell
rg -n "站在前置条件|迈出前置条件|走到剧情节点|交易行|公会门槛|NPC委托" data/exported-projects/p-xianxia-incense-test-2/.story-system/chapters/0002.json data/exported-projects/p-xianxia-incense-test-2/.story-system/reviews/0002.json
```

Expected:

- no physicalized planning-language phrase in body;
- no game-specific suggestion in the xuanhuan cold-reader report;
- director artifact reports a non-zero usable action count.

- [ ] **Step 6: Check repository cleanliness and commit any test-only assertion adjustment**

```powershell
git diff --check
git status --short
```

Expected: no unintended tracked runtime artifacts. If Step 4 required no code adjustment, do not create an empty commit. If only a test assertion needed correction, commit it separately with:

```powershell
git add tests/story_core
git commit -m "test: verify genre-aware generation pipeline"
```
