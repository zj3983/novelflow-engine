"""Tests for OutlineAgent."""

from packages.story_core.models import CharacterState, StoryState
from packages.story_core.outline_agent import (
    OutlineAgent,
    RuleBasedOutlineGenerator,
    _extract_topic,
    _phase_for_chapter,
    _rule_conflict,
    _rule_cadence,
    _rule_title,
)


# ── heuristics ────────────────────────────────────────────────

def test_extract_topic_finds_known_keywords():
    assert _extract_topic("A witness drives a confrontation.") == "证人"
    assert _extract_topic("Two rivals hunt a ledger.") == "账本"
    assert _extract_topic("A forgery shakes the court.") == "伪证"
    assert _extract_topic("The truth behind the archives.") == "真相"


def test_phase_mapping():
    # intro: first 15% (ch 1-4 out of 30)
    assert _phase_for_chapter(1, 30) == "intro"
    assert _phase_for_chapter(4, 30) == "intro"
    # rising: 15-40% (ch 5-11)
    assert _phase_for_chapter(6, 30) == "rising"
    assert _phase_for_chapter(11, 30) == "rising"
    # midpoint: ~40-50%
    assert _phase_for_chapter(13, 30) == "midpoint"
    # crisis: 50-70%
    assert _phase_for_chapter(18, 30) == "crisis"
    # climax: 70-90%
    assert _phase_for_chapter(24, 30) == "climax"
    # resolution: last 10%
    assert _phase_for_chapter(28, 30) == "resolution"
    assert _phase_for_chapter(30, 30) == "resolution"


def test_rule_title_varies_by_phase():
    topic = "证人"
    assert "证人" in _rule_title(topic, "intro", 0)
    assert "证人" in _rule_title(topic, "rising", 0)
    assert "证人" in _rule_title(topic, "midpoint", 0)
    assert "证人" in _rule_title(topic, "crisis", 0)
    assert "证人" in _rule_title(topic, "climax", 0)
    assert "证人" in _rule_title(topic, "resolution", 0)


def test_rule_cadence_follows_arc():
    assert _rule_cadence("intro", 1, 30) == "breathing"
    assert _rule_cadence("resolution", 30, 30) == "breathing"
    assert _rule_cadence("midpoint", 14, 30) == "urgent"
    assert _rule_cadence("climax", 24, 30) == "urgent"


def test_rule_conflict_uses_characters_and_topic():
    text = _rule_conflict("Lin Yue", "Su Wan", "证人", "rising", 0)
    assert "Lin Yue" in text
    assert "Su Wan" in text
    assert "证人" in text


# ── RuleBasedOutlineGenerator ─────────────────────────────────

def test_rule_based_outline_generates_correct_number_of_chapters():
    story = StoryState(
        story_id="s-outline-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["find the culprit"]),
            CharacterState(name="Su Wan", role="supporting", goals=["protect the family name"]),
        ],
    )

    outline = RuleBasedOutlineGenerator().generate(story, target_chapters=30)

    assert outline.story_id == "s-outline-001"
    assert outline.genre == "fantasy"
    assert outline.style == "noir"
    assert outline.total_chapters == 30
    assert len(outline.chapters) == 30


def test_rule_based_outline_chapters_have_required_fields():
    story = StoryState(
        story_id="s-outline-002",
        outline="A witness drives a confrontation.",
        genre="mystery",
        style="tense",
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["find the witness"]),
            CharacterState(name="Su Wan", role="supporting", goals=["protect the witness"]),
        ],
    )

    outline = RuleBasedOutlineGenerator().generate(story, target_chapters=10)

    for ch in outline.chapters:
        assert ch.chapter_number >= 1
        assert ch.chapter_title
        assert ch.summary
        assert ch.cadence in {"urgent", "measured", "breathing"}
        assert ch.arc_phase


def test_rule_based_outline_act_breaks():
    story = StoryState(
        story_id="s-outline-003",
        outline="A magistrate hunts the source of forged decrees.",
        genre="mystery",
        style="tense",
        characters=[CharacterState(name="Lin Yue", role="protagonist", goals=["find the forger"])],
    )

    outline = RuleBasedOutlineGenerator().generate(story, target_chapters=30)

    assert len(outline.act_breaks) == 3
    assert outline.act_breaks[0]["act"] == 1
    assert outline.act_breaks[2]["act"] == 3
    assert outline.act_breaks[2]["end"] == 30


def test_rule_based_outline_first_chapters_are_intro():
    story = StoryState(
        story_id="s-outline-004",
        outline="Two rivals circle a hidden ledger.",
        genre="fantasy",
        style="court intrigue",
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["find the ledger"]),
            CharacterState(name="Pei An", role="supporting", goals=["hide the ledger"]),
        ],
    )

    outline = RuleBasedOutlineGenerator().generate(story, target_chapters=30)

    # First few chapters should be intro phase
    for ch in outline.chapters[:3]:
        assert ch.arc_phase == "开端：引入人物与世界观"


def test_rule_based_outline_last_chapters_are_resolution():
    story = StoryState(
        story_id="s-outline-005",
        outline="The truth behind the archives.",
        genre="mystery",
        style="suspense",
        characters=[CharacterState(name="Lin Yue", role="protagonist", goals=["find the truth"])],
    )

    outline = RuleBasedOutlineGenerator().generate(story, target_chapters=30)

    # Last chapters should be resolution
    for ch in outline.chapters[-3:]:
        assert ch.arc_phase == "结局：收束与余韵"


# ── OutlineAgent (main entry) ─────────────────────────────────

def test_outline_agent_generates_outline():
    story = StoryState(
        story_id="s-outline-agent-001",
        outline="A witness keeper enters the archive under a false name.",
        genre="mystery",
        style="tense",
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["find the witness"]),
            CharacterState(name="Su Wan", role="supporting", goals=["protect the witness"]),
        ],
    )

    outline = OutlineAgent().generate(story, target_chapters=20)

    assert outline.story_id == "s-outline-agent-001"
    assert outline.total_chapters == 20
    assert len(outline.chapters) == 20


def test_outline_agent_chapter_numbers_are_sequential():
    story = StoryState(
        story_id="s-outline-agent-002",
        outline="A palace clerk follows a hidden ledger.",
        genre="fantasy",
        style="political suspense",
        characters=[CharacterState(name="Pei An", role="protagonist", goals=["find the ledger"])],
    )

    outline = OutlineAgent().generate(story, target_chapters=15)

    numbers = [ch.chapter_number for ch in outline.chapters]
    assert numbers == list(range(1, 16))


def test_outline_agent_different_chapter_counts():
    story = StoryState(
        story_id="s-outline-agent-003",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[CharacterState(name="Lin Yue", role="protagonist", goals=["find the culprit"])],
    )

    for target in [10, 30, 50, 100]:
        outline = OutlineAgent().generate(story, target_chapters=target)
        assert outline.total_chapters == target
        assert len(outline.chapters) == target
