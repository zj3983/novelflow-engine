"""Mock the StoryOrchestrator._chat method so engine tests don't need a real LLM API."""
import json
from unittest.mock import patch

import pytest

from packages.story_core.runtime_config import OpenAIRuntimeSettings


@pytest.fixture(autouse=True)
def isolate_novel_type_library(monkeypatch, tmp_path):
    """Keep story_core tests isolated from the user's global type library."""
    monkeypatch.setenv(
        "NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH",
        str(tmp_path / "novel_types.json"),
    )


def _make_plan(story, chapter_number: int) -> dict:
    """Generate a plan JSON that matches test expectations."""
    active_chars = [c for c in story.characters if c.lifecycle_state == "active" and not c.frozen]
    char_names = [c.name for c in active_chars]

    # Build character moves with proper priorities for cadence computation
    # For urgent: 4+ chars with priority >= 9, 3+ unresolved threads, foreshadowing
    # For breathing: 1-2 chars with priority 0
    # For measured: everything else

    has_many_threads = False
    if story.chapter_summaries:
        threads = story.chapter_summaries[-1].unresolved_threads
        has_many_threads = len(threads) >= 3
    has_foreshadowing = len(story.foreshadowing) > 0

    # Urgent: 4+ chars + many threads + foreshadowing
    is_urgent = len(active_chars) >= 4 and has_many_threads and has_foreshadowing
    # Breathing: 1-2 chars, no existing threads
    is_breathing = len(active_chars) <= 2 and not has_many_threads

    char_moves = []
    for c in active_chars:
        goal = c.goals[0] if c.goals else "推进主线"
        move_name = c.game_id or c.name
        priority = 9 if is_urgent else (0 if is_breathing else 1)
        candidates = []
        for secret in getattr(c, "secrets", []):
            if "archivist" in str(secret).lower() or "档案" in str(secret):
                candidates.append("Archivist")
        char_moves.append({
            "name": move_name,
            "goal": goal,
            "emotion": c.current_emotion or "determined",
            "action": f"{move_name} 开始执行 {goal}",
            "priority": priority,
            "new_character_candidates": candidates,
        })

    cadence = "urgent" if is_urgent else ("breathing" if is_breathing else "measured")

    # Build primary conflict - lead is first char, opposition is last char (for 3-char tests)
    lead = char_names[0] if len(char_names) >= 1 else "主角"
    opposition = char_names[-1] if len(char_names) >= 2 else "circumstance"

    # Build secondary conflict participants (exclude lead)
    secondary_participants = []
    for c in active_chars[1:]:
        secondary_participants.append({
            "name": c.name,
            "goal": c.goals[0] if c.goals else "hold the line",
        })

    # Build next_focus - include both lead and opposition for tests that check this
    if len(char_names) >= 2:
        next_focus = f"回到{lead}与{opposition}围绕核心线索的争夺"
    else:
        next_focus = f"{lead} 继续追查"

    plan = {
        "character_moves": char_moves,
        "chapter_intent": {
            "chapter_title": f"第{chapter_number}章标题",
            "cadence": cadence,
            "next_focus": next_focus,
            "primary_conflict": {
                "type": "goal_collision",
                "lead": lead,
                "opposition": opposition,
                "collision": f"{lead} 与 {opposition} 正面交锋",
            },
            "secondary_conflict": {
                "pressure": "time",
                "detail": "时间紧迫，必须尽快行动。",
                "participants": secondary_participants[:2],
            },
        },
        "event_plan": {
            "chapter_title": f"第{chapter_number}章标题",
            "turn": f"{lead} 发现关键线索",
            "pivot": "局势发生转折",
            "collision": f"{lead} 与 {opposition} 正面交锋",
            "ordered_actions": char_moves,
            "stakes": "如果失败，后果严重。",
            "next_focus": next_focus,
            "chapter_satisfaction": {
                "core_event": f"{lead}发现关键线索",
                "obstacle": f"{opposition}阻止调查继续推进",
                "visible_payoff": f"{lead}拿到可验证的关键证据",
                "cost": "调查行动暴露了主角的关注方向",
                "state_change": "关键事件从无头绪变为可以继续追查",
                "next_hook": next_focus,
            },
            "chapter_end_hook": {
                "type": "悬念钩",
                "strength": "medium",
                "content": f"新的证据迫使{lead}继续追查",
            },
        },
        "memory_constraints": {
            "must_keep_facts": ["主角正在调查关键事件"],
            "unresolved_threads": ["关键线索的真相是什么？"],
            "protected_characters": [],
            "protected_foreshadowing": [],
            "author_constraints": [],
            "current_focus": "调查",
            "conflict_anchor": "目标冲突",
            "event_guardrail": "保持紧张感",
        },
        "chapter_summary": {
            "summary": f"{lead}展开调查，发现重要线索。",
            "facts": ["发现了关键证据"],
            "unresolved_threads": ["证据背后的真相"],
            "next_focus": next_focus,
            "chapter_title": f"第{chapter_number}章标题",
        },
    }

    # If secrets mention "archivist", add new character candidate
    for c in story.characters:
        for s in getattr(c, 'secrets', []):
            if "archivist" in str(s).lower() or "档案" in str(s):
                plan["chapter_intent"]["approved_new_characters"] = [{"name": "沈离", "role": "archivist"}]
                break

    return plan


def _make_body(story, chapter_number: int) -> str:
    """Generate a chapter body that includes all character names and Chinese markers."""
    char_names = [c.name for c in story.characters if c.lifecycle_state == "active"]

    # Build opening with all characters
    if len(char_names) >= 2:
        opening = f"第{chapter_number}章\n\n夜色深沉，{char_names[0]} 和 {char_names[1]} 走在寂静的长廊中。"
    elif len(char_names) == 1:
        opening = f"第{chapter_number}章\n\n夜色深沉，{char_names[0]} 走在寂静的长廊中。"
    else:
        opening = f"第{chapter_number}章\n\n夜色深沉，主角走在寂静的长廊中。"

    body = (
        f"{opening}\n"
        "月光透过雕花窗棂，在地上投下斑驳的影子。\n"
        "空气中弥漫着一股陈旧的气息，像是尘封已久的秘密正在等待被发现。\n"
    )

    # Add character-specific content
    for name in char_names[:3]:
        body += f"\n{name} 停下脚步，仔细打量着周围的每一个角落。\n"
        body += f'"{name} 知道，真相就在不远处。"\n'

    # Add Chinese markers that tests look for
    body += "\n事实：主角发现了关键证据。\n"
    body += "真相：幕后黑手仍然隐藏在暗处。\n"
    body += "见证：一切都有目击者。\n"

    # Add cadence markers
    active_chars = [c for c in story.characters if c.lifecycle_state == "active" and not c.frozen]
    has_many_threads = False
    if story.chapter_summaries:
        threads = story.chapter_summaries[-1].unresolved_threads
        has_many_threads = len(threads) >= 3
    has_foreshadowing = len(story.foreshadowing) > 0

    is_urgent = len(active_chars) >= 4 and has_many_threads and has_foreshadowing
    is_breathing = len(active_chars) <= 2 and not has_many_threads

    if is_urgent:
        body += "\n节奏：紧迫\n"
        body += "时间紧迫，每一秒都至关重要。\n"
    elif is_breathing:
        body += "\n节奏：舒缓\n"
        body += "一切都在缓缓展开，无需急躁。\n"
    else:
        body += "\n节奏：平稳\n"

    return body


def _mock_chat(self, story, prompt: str, *, max_tokens: int, json_mode: bool, agent: str = "director") -> tuple[str, str]:
    """Dynamic mock that generates responses based on the actual story state."""
    chapter_number = getattr(story, 'current_chapter', 0) or 1
    if json_mode:
        return json.dumps(_make_plan(story, chapter_number), ensure_ascii=False), ""
    return _make_body(story, chapter_number), ""


@pytest.fixture(autouse=True)
def isolate_openai_runtime(monkeypatch):
    """Keep story_core unit tests from using local runtime/API credentials."""

    def empty_runtime_settings(agent_name: str | None = None) -> OpenAIRuntimeSettings:
        return OpenAIRuntimeSettings(api_key="", base_url="")

    monkeypatch.setattr(
        "packages.story_core.agent_base.resolve_openai_runtime_settings",
        empty_runtime_settings,
    )
    yield


@pytest.fixture(autouse=True)
def mock_llm_api():
    """Patch StoryOrchestrator._chat to return mock responses."""
    with patch("packages.story_core.orchestrator.StoryOrchestrator._chat", _mock_chat):
        yield


@pytest.fixture
def passing_hard_gate(monkeypatch):
    """Explicitly bypass the canonical hard gate for orchestrator
    tests that do not want the real length / continuity / critical /
    genre / soft-review checks to fire.

    The bounded review flow in
    ``packages.story_core.pipeline.review_revision_stage`` is the
    unit of work covered by ``test_review_revision_stage.py``.
    Surrounding tests in ``test_orchestrator.py`` and
    ``test_engine.py`` focus on the orchestrator's compression,
    expansion, memory, progress, and quality-report machinery.
    Those tests opt into this fixture by adding ``passing_hard_gate``
    to the test signature; tests that omit it run the real
    ``ReviewService.run_hard_gate`` and would surface any wiring
    regression immediately.

    Tests that need a passing soft review alongside should also
    set ``passing_soft_review`` (``monkeypatch.setattr`` on
    ``ReviewService.run_soft_review``).
    """
    from packages.story_core.review.contracts import ReviewResult
    from packages.story_core.review.service import ReviewService

    def _passing(self, *, body, context):
        return ReviewResult.from_findings([])

    monkeypatch.setattr(ReviewService, "run_hard_gate", _passing)
    yield


@pytest.fixture
def passing_review_service(monkeypatch):
    """Bypass both ``run_hard_gate`` and ``run_soft_review`` for
    tests that want the bounded controller to accept any body
    without re-running the soft reviewers.
    """
    from packages.story_core.review.contracts import ReviewResult
    from packages.story_core.review.service import ReviewService

    def _passing(self, *, body, context):
        return ReviewResult.from_findings([])

    monkeypatch.setattr(ReviewService, "run_hard_gate", _passing)
    monkeypatch.setattr(ReviewService, "run_soft_review", _passing)
    yield


@pytest.fixture
def real_review_only(monkeypatch, request):
    """Run the real canonical hard gate but bypass the soft
    reviewers. Useful for tests that need the bounded controller
    to actually block on the gate but don't care about the soft
    review path.
    """
    from packages.story_core.review.contracts import ReviewResult
    from packages.story_core.review.service import ReviewService

    def _passing(self, *, body, context):
        return ReviewResult.from_findings([])

    monkeypatch.setattr(ReviewService, "run_soft_review", _passing)
    yield
