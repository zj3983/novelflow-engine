from packages.story_core.chapter_governance import build_chapter_governance, review_chapter_governance
from packages.story_core.engine import ChapterBundle
from packages.story_core.chapter_governance import governance_quality_gate
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.writing_packet import build_codex_writing_packet


def _story() -> StoryState:
    return StoryState(
        story_id="s-governance-review",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率。",
        genre="网游",
        style="升级流",
        current_chapter=1,
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )


def test_governance_review_passes_clean_first_chapter_governance():
    bundle = ChapterBundle(chapter_number=1, body="", next_outline="继续验证。", updated_story=_story())
    governance = build_chapter_governance(_story(), bundle, chapter_number=1)

    review = review_chapter_governance(governance)

    assert review["pass"]
    assert review["issues"] == []


def test_governance_review_flags_diagnostic_terms_in_hard_facts():
    governance = {
        "chapter_intent": {"chapter_number": 1, "must_avoid": ["交易行实际成交"]},
        "rule_stack": {
            "hard_facts": ["正文要完成爽点并照顾读者期待。"],
            "soft_guidance": [],
            "diagnostic_only": ["爽点只用于诊断，禁止进入正文。"],
        },
        "runtime_context": {},
    }

    review = review_chapter_governance(governance)

    assert not review["pass"]
    assert any(issue["type"] == "diagnostic_term_in_hard_facts" for issue in review["issues"])


def test_governance_review_flags_missing_first_chapter_market_bans():
    governance = {
        "chapter_intent": {"chapter_number": 1, "must_avoid": ["论坛爆帖"]},
        "rule_stack": {"hard_facts": ["怪物统一为灰鼠。"], "soft_guidance": [], "diagnostic_only": []},
        "runtime_context": {},
    }

    review = review_chapter_governance(governance)

    assert not review["pass"]
    assert any(issue["type"] == "missing_first_chapter_ban" for issue in review["issues"])
    assert any("交易行实际成交" in issue["suggestion"] for issue in review["issues"])


def test_writing_packet_contains_governance_review():
    story = _story()
    bundle = ChapterBundle(chapter_number=1, body="", next_outline="继续验证。", updated_story=story)

    packet = build_codex_writing_packet(story, bundle)

    assert "governance_review" in packet["governance"]
    assert packet["governance"]["governance_review"]["pass"] is True


def test_governance_quality_gate_blocks_dirty_rule_stack_before_writing():
    governance = {
        "chapter_intent": {"chapter_number": 1, "must_avoid": ["论坛爆帖"]},
        "rule_stack": {
            "hard_facts": ["正文要完成爽点并照顾读者期待。"],
            "soft_guidance": [],
            "diagnostic_only": [],
        },
        "runtime_context": {},
    }

    gate = governance_quality_gate(governance)

    assert gate["pass"] is False
    assert gate["blocking"] is True
    assert gate["next_action"] == "fix_governance_before_writing"
    assert "diagnostic_term_in_hard_facts" in gate["issue_types"]
    assert "missing_diagnostic_only" in gate["issue_types"]


def test_governance_quality_gate_allows_clean_governance():
    bundle = ChapterBundle(chapter_number=1, body="", next_outline="继续验证。", updated_story=_story())
    governance = build_chapter_governance(_story(), bundle, chapter_number=1)

    gate = governance_quality_gate(governance)

    assert gate == {
        "reviewer": "chapter_governance_gate/v1",
        "pass": True,
        "blocking": False,
        "next_action": "write_or_revise_chapter",
        "issue_types": [],
        "issues": [],
    }
