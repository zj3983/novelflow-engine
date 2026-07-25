# Trading and Exchange Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mixed auction, appraisal, guaranteed-delivery, and real-money flow with a clear in-game trading house followed by a separate official currency exchange.

**Architecture:** Add one focused economy-boundary module as the source of truth for market, appraisal, and exchange semantics. Prompt builders and reviewers consume that contract instead of repeating book-specific wording. Code changes are developed in the tracked worktree; the ignored file-project data is migrated in the main workspace only after the code branch passes review.

**Tech Stack:** Python 3.12, pytest, JSON/Markdown file-project storage, existing story-core prompt and review pipeline.

---

## File Map

- Create `packages/story_core/web_game_economy.py`: canonical market/appraisal/exchange vocabulary and chapter-one authorization helper.
- Modify `packages/story_core/genre_types/game_webnovel.py`: separate trade and exchange language cards and generic economy rules.
- Modify `packages/story_core/chapter_scope.py`: recognize the new chapter-one market-plus-exchange contract.
- Modify prompt composition modules: remove old guaranteed-delivery wording and render only scene-relevant market or exchange rules.
- Modify review modules: reject direct real-world settlement from the trading house, redundant appraisal, buyer reconfirmation, and the forbidden full currency name.
- Modify current file-project world, outline, and chapter-one files in the main workspace after code integration.

### Task 1: Define the economy boundary contract

**Files:**
- Create: `packages/story_core/web_game_economy.py`
- Create: `tests/story_core/test_web_game_economy.py`

- [ ] **Step 1: Write failing contract tests**

```python
from packages.story_core.web_game_economy import (
    appraisal_rules,
    exchange_rules,
    first_chapter_market_exchange_authorized,
    market_rules,
)


def test_market_exchange_and_appraisal_are_separate() -> None:
    market = "\n".join(market_rules())
    exchange = "\n".join(exchange_rules())
    appraisal = "\n".join(appraisal_rules())
    assert "游戏币" in market and "现实账户" not in market and "鉴定" not in market
    assert "官方兑换渠道" in exchange and "交易行直接" in exchange
    assert "未鉴定" in appraisal and "鉴定师" in appraisal


def test_new_opening_contract_authorizes_market_then_exchange() -> None:
    assert first_chapter_market_exchange_authorized(
        {"turn": "第一章卖出裂纹狼心，再走官方兑换渠道解决现实急账。"},
        [],
    )
```

- [ ] **Step 2: Run the focused test and verify import failure**

Run: `python -m pytest tests/story_core/test_web_game_economy.py -q`

Expected: FAIL because `web_game_economy` does not exist.

- [ ] **Step 3: Implement the compact source of truth**

Implement immutable tuples for the three rule groups. Add `first_chapter_market_exchange_authorized(event_plan, world_facts)` that accepts new phrases such as `交易行卖出裂纹狼心`, `官方兑换渠道`, and `解决现实急账`. Keep legacy markers temporarily for reading old projects, but never return legacy wording to prompts.

- [ ] **Step 4: Run the focused test**

Run: `python -m pytest tests/story_core/test_web_game_economy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/web_game_economy.py tests/story_core/test_web_game_economy.py
git commit -m "feat: define web game economy boundaries"
```

### Task 2: Split trading and exchange language cards

**Files:**
- Modify: `packages/story_core/genre_types/game_webnovel.py`
- Modify: `tests/story_core/test_game_webnovel_language.py`

- [ ] **Step 1: Add failing language-card tests**

Add one market plan containing `求购单` and assert the selected `trade` card includes `立即出售`, `游戏币到账`, and no exchange terms. Add one plan containing `官方兑换渠道` and assert a separate `currency_exchange` card includes `兑换价`, `预计到账`, and `现实账户`, with no appraisal or auction settlement wording.

- [ ] **Step 2: Verify the focused tests fail**

Run: `python -m pytest tests/story_core/test_game_webnovel_language.py -q`

Expected: FAIL because exchange still shares the trade card.

- [ ] **Step 3: Update cards and generic economy rules**

Keep the `trade` card limited to `交易行、求购单、挂单、立即出售、成交、手续费、游戏币到账`. Add `currency_exchange` with triggers `官方兑换、兑换渠道、兑换价、现实账户` and preferred terms `兑换价、额度、手续费、预计到账、现实账户`. Replace active prompt text containing the full legal currency name with `现实货币`, `元`, or `现实账户` wording.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/story_core/test_game_webnovel_language.py tests/story_core/test_opening_arc.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/genre_types/game_webnovel.py tests/story_core/test_game_webnovel_language.py tests/story_core/test_opening_arc.py
git commit -m "feat: separate market and exchange language"
```

### Task 3: Replace the old chapter-one transaction contract

**Files:**
- Modify: `packages/story_core/chapter_scope.py`
- Modify: `packages/story_core/chapter_governance.py`
- Modify: `packages/story_core/chapter_seed.py`
- Modify: `packages/story_core/world_simulation.py`
- Modify: `packages/story_core/writing_packet.py`
- Modify: `packages/story_core/writing_taskbook.py`
- Modify: `packages/story_core/web_game_author_craft.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify corresponding focused tests under `tests/story_core/`

- [ ] **Step 1: Write failing prompt-contract tests**

Update fixtures to use `交易行卖出裂纹狼心，再走官方兑换渠道解决现实急账`. Assert generated governance and writer prompts contain the ordered chain `交易行游戏币成交 -> 官方兑换 -> 现实账户到账 -> 处理急账`, and assert they contain none of `担保交易`, `匿名交割`, `封存交割`, or `提交鉴定`.

- [ ] **Step 2: Run focused tests and confirm legacy output**

Run: `python -m pytest tests/story_core/test_chapter_governance.py tests/story_core/test_chapter_seed.py tests/story_core/test_world_simulation.py tests/story_core/test_writer_prompt_method.py tests/story_core/test_writing_packet.py tests/story_core/test_writing_taskbook.py tests/story_core/test_web_game_author_craft.py -q`

Expected: FAIL because prompt builders still render the old transaction contract.

- [ ] **Step 3: Route every chapter-one helper through the new contract**

Import `first_chapter_market_exchange_authorized` and the compact rule groups. Replace the old payoff wording with the ordered four-step chain. Keep the existing project fact amounts as continuity facts for prose, but do not add exact amounts or fee percentages to generated outline prompts. Preserve the uncommitted amount-free outline validator in the main workspace during final integration.

- [ ] **Step 4: Run focused tests**

Run the command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core tests/story_core
git commit -m "fix: use market then exchange in opening flow"
```

### Task 4: Enforce the three system boundaries

**Files:**
- Modify: `packages/story_core/web_game_review.py`
- Modify: `packages/story_core/world_consistency_review.py`
- Modify: `packages/story_core/prose_style_review.py`
- Modify: `tests/story_core/test_web_game_review_agent.py`
- Modify: `tests/story_core/test_world_consistency_review.py`
- Modify: `tests/story_core/test_prose_style_review.py`

- [ ] **Step 1: Add failing review cases**

Add must-fix cases for:

```text
交易行直接把卖出物品的钱打进现实账户。
裂纹狼心已经显示正式名称和用途，却又被送去鉴定。
求购单已经冻结游戏币，成交后仍等待买家再次确认。
```

Construct the forbidden full currency name in tests with Unicode escapes so active prompt source never teaches that literal to the model. Add passing cases for `求购单立即成交并获得游戏币` and `官方兑换后现实账户到账`.

- [ ] **Step 2: Verify the new cases fail**

Run: `python -m pytest tests/story_core/test_web_game_review_agent.py tests/story_core/test_world_consistency_review.py tests/story_core/test_prose_style_review.py -q`

Expected: FAIL because only prose explanation terms are currently checked.

- [ ] **Step 3: Implement conservative boundary checks**

Report only explicit mixed flows. Do not flag ordinary uses of `鉴定`, `求购`, or `到账` in isolation. Revision suggestions must say what scene to use instead and must not repeat the forbidden full currency name.

- [ ] **Step 4: Run focused and regression tests**

Run the command from Step 2, then:

`python -m pytest tests/story_core/test_generation_quality_guardrails.py tests/story_core/test_systemic_consistency_review.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/story_core/web_game_review.py packages/story_core/world_consistency_review.py packages/story_core/prose_style_review.py tests/story_core
git commit -m "feat: review web game economy boundaries"
```

### Task 5: Migrate the current project data

**Files in the main workspace, not the Git worktree:**
- Modify: `data/exported-projects/p-gou-webgame-restored/设定集/世界观.md`
- Modify: `data/exported-projects/p-gou-webgame-restored/设定集/力量体系.md`
- Modify: `data/exported-projects/p-gou-webgame-restored/.webnovel/project.json`
- Modify: `data/exported-projects/p-gou-webgame-restored/.webnovel/outline.json`
- Modify: `data/exported-projects/p-gou-webgame-restored/大纲/第1卷-详细大纲.md`
- Modify: `data/exported-projects/p-gou-webgame-restored/chapters/0001-灰狼坡的第一笔到账.md`

- [ ] **Step 1: Back up the file project with the existing project backup mechanism**

Create a timestamped project backup before writing ignored data files. Verify the backup contains the chapter, `.webnovel` state, and setting documents.

- [ ] **Step 2: Replace project-level market rules**

Write the approved three-system boundary into world and power-system sources. Replace all active `担保交易/鉴定后求购/拍卖物品现实结算` directions with `交易行游戏币成交 -> 官方兑换 -> 现实账户到账`.

- [ ] **Step 3: Preserve amount-free outline work**

Merge with `docs/superpowers/plans/2026-07-25-outline-without-hardcoded-amounts.md`: outlines describe the financial outcome without exact currency amounts or percentages. Do not overwrite the existing uncommitted validator and tests in the main workspace.

- [ ] **Step 4: Rewrite only the chapter-one market sequence**

Keep the combat, drop, inventory, reality pressure, and ending continuity intact. Replace the platform sequence with: search exact item, select an already-funded buy order, receive game currency, open the separate official exchange channel, review the quote, confirm exchange, and receive the existing continuity amount in the reality account. Remove appraisal, manual verification, sealed delivery, direct item-to-reality settlement, and the forbidden full currency name.

- [ ] **Step 5: Verify active project text**

Run:

```powershell
rg -n "提交鉴定|鉴定中|平台验货|封存交割|担保交易|人民币" data/exported-projects/p-gou-webgame-restored/.webnovel data/exported-projects/p-gou-webgame-restored/设定集 data/exported-projects/p-gou-webgame-restored/大纲 data/exported-projects/p-gou-webgame-restored/chapters
```

Expected: no matches in active sources. Archived chapters and backups are excluded.

### Task 6: Full verification and integration

**Files:**
- Verify all code and project data changed above.

- [ ] **Step 1: Run focused economy suites**

Run all tests named in Tasks 1-4.

Expected: PASS.

- [ ] **Step 2: Run complete backend regression**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Verify prompt exposure**

Search active generation prompt code for the old mixed-flow terms and forbidden full currency name. Allow Unicode-based detection logic in reviewers, but no active instruction may contain those strings.

- [ ] **Step 4: Review chapter one**

Run the local chapter reviewer on chapter one and confirm no market-boundary, continuity, inventory, amount, or prose-explanation issue remains.

- [ ] **Step 5: Integrate without overwriting main-workspace changes**

Apply the reviewed feature branch to `codex/global-novel-types`, preserving the existing uncommitted outline-amount files. Re-run focused outline tests and the complete backend suite in the combined workspace.

- [ ] **Step 6: Commit tracked integration changes**

```powershell
git add packages/story_core tests/story_core docs/superpowers/plans/2026-07-25-trading-exchange-rules.md
git commit -m "fix: separate trading from official exchange"
```
