from packages.story_core.engine import ChapterBundle
from packages.story_core.memory import build_character_cards
from packages.story_core.models import CharacterPerformanceProfile, CharacterState, StoryState
from packages.story_core.orchestrator import _story_snapshot
from packages.story_core.writing_packet import build_codex_writing_packet


def test_build_character_cards_uses_webnovel_writer_style_axes():
    story = StoryState(
        story_id="s-character-card",
        outline="网游开服，苏叶用夜烬身份低调验证掉落异常。",
        genre="网游",
        style="白描升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["先确认灰狼掉落异常", "不要暴露混沌之种"],
                performance_profile=CharacterPerformanceProfile(
                    speech_style="说完整口语，不用装高手式省略回答",
                    action_style="先看成本和退路，再动手验证",
                    risk_posture="隐藏在幕后，不当众炫耀爆率",
                ),
            )
        ],
    )

    card = build_character_cards(story)[0]

    assert card["identity"] == {"name": "苏叶", "role": "主角", "game_id": "夜烬", "location": ""}
    assert "core_motivation" in card["webnovel_profile"]
    assert "behavior_logic" in card["webnovel_profile"]
    assert "interaction_mode" in card["webnovel_profile"]
    assert "装高手式省略回答" in card["webnovel_profile"]["poison_points"]
    assert "social" in card["three_dimensions"]
    assert "psychological" in card["three_dimensions"]
    assert "moral" in card["three_dimensions"]
    assert card["story_usage"]["this_chapter_usage"]["speech_tendency"] == "说完整口语，不用装高手式省略回答"
    assert card["voice_and_action"]["risk_posture"] == "隐藏在幕后，不当众炫耀爆率"


def test_writing_packet_and_story_snapshot_expose_character_cards():
    story = StoryState(
        story_id="s-character-card-packet",
        outline="网游开服，苏叶用夜烬身份低调验证掉落异常。",
        genre="网游",
        style="白描升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )
    bundle = ChapterBundle(chapter_number=1, body="", next_outline="", updated_story=story)

    packet = build_codex_writing_packet(story, bundle)
    snapshot = _story_snapshot(story)

    assert packet["protagonist_card"]["identity"]["game_id"] == "夜烬"
    assert packet["character_cards"][0]["webnovel_profile"]["character_type"].startswith("gap-driven")
    assert snapshot["character_cards"][0]["identity"]["name"] == "苏叶"
