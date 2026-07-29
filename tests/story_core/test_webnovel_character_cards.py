from packages.story_core.engine import ChapterBundle
from packages.story_core.memory import build_character_cards
from packages.story_core.models import CharacterPerformanceProfile, CharacterState, StoryState
from packages.story_core.orchestrator import _character_context_for_prompt, _story_snapshot
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


def test_writing_packet_and_character_context_expose_character_cards():
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
    character_context = _character_context_for_prompt(story, {"character_moves": [{"name": "夜烬"}]})

    assert packet["protagonist_card"]["identity"]["game_id"] == "夜烬"
    assert packet["character_cards"][0]["webnovel_profile"]["character_type"].startswith("gap-driven")
    assert "character_cards" not in snapshot
    assert character_context["cards"][0]["identity"]["name"] == "苏叶"


def test_character_context_exposes_scene_portrait_slice_without_full_portrait():
    story = StoryState(
        story_id="s-character-scene-slice",
        outline="都市悬疑，苏叶调查旧楼。",
        genre="都市悬疑",
        style="白描",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                personality_portrait={
                    "behavior": {
                        "pressure_mode": "先把能确认的证据收好，再决定是否追问。",
                        "conflict_response": "不急着争辩，先记住对方的漏洞。",
                    },
                    "emotion": {"triggers": ["别人替他做决定"]},
                    "voice": {"sentence_habit": "先说眼前事实，再说自己的判断。"},
                    "writing_limits": ["不能突然变成冲动型人物"],
                },
            )
        ],
    )

    context = _character_context_for_prompt(
        story,
        {"character_moves": [{"name": "苏叶"}], "scene_cards": [{"name": "苏叶"}]},
    )

    card = context["cards"][0]
    assert card["scene_portrait"]["pressure_behavior"]
    assert card["scene_portrait"]["conflict_response"]
    assert card["scene_portrait"]["voice"]
    assert "personality_portrait" not in card

    summary = _character_context_for_prompt(story, {"character_moves": [{"name": "苏叶"}]})
    assert summary["cards"][0]["scene_portrait"]["pressure_behavior"]


def test_xianxia_character_cards_ignore_stale_game_keywords() -> None:
    story = StoryState(
        story_id="s-xianxia-character-card",
        outline="林修在雪山神殿修复残镜。",
        genre="修仙仙侠",
        genre_plugin_ids=["xianxia"],
        style="白描",
        world_facts=["旧数据曾提到交易行和游戏任务。"],
        characters=[CharacterState(name="林修", role="protagonist")],
    )

    card = build_character_cards(story)[0]

    assert "game_id" not in card["identity"]
    assert "game_panel" not in card["continuity_locks"]
    assert not card["webnovel_profile"]["character_type"].startswith("gap-driven")
