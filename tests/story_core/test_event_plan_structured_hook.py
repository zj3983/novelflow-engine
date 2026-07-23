"""Tests for structured chapter_end_hook flowing through event_plan normalization."""
from packages.story_core.chapter_hook import parse_chapter_end_hook
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import _normalize_event_plan


def _story() -> StoryState:
    return StoryState(
        story_id="hook-flow",
        outline="网游开服。",
        genre="网游",
        style="升级流",
    )


# ---------------------------------------------------------------------------
# _normalize_event_plan preserves both hook fields
# ---------------------------------------------------------------------------


def test_normalize_preserves_structured_chapter_end_hook_dict():
    raw = {
        "chapter_title": "测试",
        "chapter_end_hook": {
            "type": "危机钩",
            "strength": "strong",
            "content": "倒计时三天，债主上门。",
        },
    }
    out = _normalize_event_plan(raw, chapter_number=1, story=_story())

    assert out["chapter_end_hook"] == {
        "type": "危机钩",
        "strength": "strong",
        "content": "倒计时三天，债主上门。",
    }


def test_normalize_preserves_director_chapter_satisfaction():
    raw = {
        "chapter_satisfaction": {
            "emotion_target": "从提防转为暂时放心",
            "core_event": "主角拿到祖祠账册",
            "obstacle": "执事要求出示旧印",
            "visible_payoff": "账册当场打开",
            "cost": "执事记住了主角",
            "outsider_misread": "执事以为旧印是借来的",
            "state_change": "主角获得查阅资格",
            "next_hook": "账册里少了三个名字",
        }
    }

    out = _normalize_event_plan(raw, chapter_number=1, story=_story())

    assert out["chapter_satisfaction"] == raw["chapter_satisfaction"]


def test_normalize_preserves_legacy_explicit_string_alongside_structured():
    raw = {
        "explicit_chapter_end_hook": "下一章去找散人收购渠道。",
        "chapter_end_hook": {"type": "渴望钩", "strength": "medium", "content": "下一章去找散人收购渠道。"},
    }
    out = _normalize_event_plan(raw, chapter_number=2, story=_story())

    assert out["explicit_chapter_end_hook"] == "下一章去找散人收购渠道。"
    assert isinstance(out["chapter_end_hook"], dict)
    assert out["chapter_end_hook"]["type"] == "渴望钩"


def test_normalize_drops_invalid_chapter_end_hook_shape():
    raw = {"chapter_end_hook": "not a dict, just a string"}
    out = _normalize_event_plan(raw, chapter_number=1, story=_story())

    # String form does not survive into the structured slot
    assert out["chapter_end_hook"] is None


def test_normalize_lowercases_strength_field():
    raw = {"chapter_end_hook": {"type": "悬念钩", "strength": "Strong", "content": "x"}}
    out = _normalize_event_plan(raw, chapter_number=1, story=_story())

    assert out["chapter_end_hook"]["strength"] == "strong"


def test_normalize_strips_blank_type_and_strength():
    raw = {"chapter_end_hook": {"type": "  ", "strength": "", "content": "y"}}
    out = _normalize_event_plan(raw, chapter_number=1, story=_story())

    assert out["chapter_end_hook"]["type"] is None
    assert out["chapter_end_hook"]["strength"] is None
    assert out["chapter_end_hook"]["content"] == "y"


# ---------------------------------------------------------------------------
# Hook lookup priority (structured wins over directive string)
# ---------------------------------------------------------------------------


def test_orchestrator_hook_lookup_prefers_structured_form():
    """Simulate the lookup logic from _review_chapter_body."""
    event_plan = {
        "explicit_chapter_end_hook": "explicit_chapter_end_hook: 章末必须留下下一章诱饵...",  # writer directive
        "chapter_end_hook": {
            "type": "危机钩",
            "strength": "strong",
            "content": "公会追兵迫近，下一章必须撤离。",
        },
    }
    structured = event_plan.get("chapter_end_hook")
    raw_hook = structured if isinstance(structured, dict) else event_plan.get("explicit_chapter_end_hook")
    hook_meta = parse_chapter_end_hook(raw_hook)

    assert hook_meta["type"] == "危机钩"
    assert hook_meta["strength"] == "strong"
    assert "公会追兵迫近" in hook_meta["content"]


def test_orchestrator_hook_lookup_falls_back_to_directive_when_structured_missing():
    event_plan = {
        "explicit_chapter_end_hook": "倒计时三天，债主即将上门。",
    }
    structured = event_plan.get("chapter_end_hook")
    raw_hook = structured if isinstance(structured, dict) else event_plan.get("explicit_chapter_end_hook")
    hook_meta = parse_chapter_end_hook(raw_hook)

    assert hook_meta["type"] == "危机钩"  # inferred from "倒计时" / "债主"
    assert hook_meta["strength"] == "strong"  # inferred from "倒计时"


def test_orchestrator_hook_lookup_returns_blank_when_neither_present():
    event_plan: dict = {}
    structured = event_plan.get("chapter_end_hook")
    raw_hook = structured if isinstance(structured, dict) else event_plan.get("explicit_chapter_end_hook")
    hook_meta = parse_chapter_end_hook(raw_hook)

    assert hook_meta == {"type": None, "strength": None, "content": ""}


# ---------------------------------------------------------------------------
# Plan prompt schema mentions the structured field
# ---------------------------------------------------------------------------


def test_plan_prompt_documents_structured_chapter_end_hook():
    from packages.story_core.orchestrator import StoryOrchestrator

    story = _story()
    prompt = StoryOrchestrator()._plan_prompt(story, chapter_number=1)

    assert "chapter_end_hook" in prompt
    # Schema must enumerate the 5 canonical types
    assert "危机钩" in prompt and "悬念钩" in prompt and "渴望钩" in prompt
    # Strength ladder
    assert "strong" in prompt and "medium" in prompt and "weak" in prompt
