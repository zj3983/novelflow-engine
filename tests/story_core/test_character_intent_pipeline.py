from __future__ import annotations

import json

from packages.story_core.agents.contracts import DirectorArtifact, WriterRequest
from packages.story_core.agents.director.prompt import parse_director_response
from packages.story_core.agents.fact_extractor.agent import _fact_extractor_director_view
from packages.story_core.agents.pipeline import _chapter_cast_names
from packages.story_core.agents.writer.prompt import build_writer_prompt
from packages.story_core.context.director_context import DirectorContext
from packages.story_core.context.legacy_adapter import legacy_outline_view
from packages.story_core.models import CharacterState, StoryState


def _rich_artifact() -> DirectorArtifact:
    return parse_director_response(
        {
            "chapter_number": 3,
            "chapter_title": "试探",
            "chapter_goal": "林渊处理比试后的关系压力",
            "opening_state": "比试刚结束",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "演武场外",
                    "purpose": "让人物对胜负作出不同反应",
                    "conflict": "苏瑶想确认林渊伤势，王胖子想拿他开玩笑",
                    "participants": ["林渊", "苏瑶", "王胖子"],
                    "action": "三人离开演武场",
                    "result": "苏瑶和林渊的关系产生轻微变化",
                    "character_intents": [
                        {
                            "name": "苏瑶",
                            "want": "确认林渊有没有受伤",
                            "target": "林渊",
                            "emotion": "担心但不愿表现得太明显",
                            "move": "借检查伤势靠近",
                            "speech_strategy": "先问伤，不直接说担心",
                            "withhold": "不承认自己一直在关注他",
                            "reaction": "被调侃后转移话题",
                            "dramatic_function": "romance_progression",
                        },
                        {
                            "name": "王胖子",
                            "want": "确认林渊到底藏了多少实力",
                            "target": "林渊",
                            "emotion": "兴奋",
                            "move": "半开玩笑地追问",
                            "dramatic_function": "comic_relief",
                        },
                    ],
                    "emotional_turn": "林渊开始察觉苏瑶的在意",
                    "relationship_shift": "两人距离略微拉近",
                    "ending_pressure": "赵家的人在远处盯上林渊",
                },
                {
                    "order": 2,
                    "location": "宗门石阶",
                    "action": "林渊察觉有人跟踪",
                    "result": "下一步压力转向赵家",
                },
            ],
            "ending_state": "林渊确认自己被盯上",
            "hook": "赵家开始调查林渊",
        }
    )


def test_director_response_keeps_rich_scene_character_intents() -> None:
    artifact = _rich_artifact()

    beat = artifact.scene_beats[0]
    assert beat.purpose == "让人物对胜负作出不同反应"
    assert beat.participants == ["林渊", "苏瑶", "王胖子"]
    assert [intent.name for intent in beat.character_intents] == ["苏瑶", "王胖子"]
    assert beat.character_intents[0].withhold == "不承认自己一直在关注他"
    assert beat.relationship_shift == "两人距离略微拉近"
    assert beat.ending_pressure == "赵家的人在远处盯上林渊"


def test_legacy_director_artifact_still_validates_without_character_intents() -> None:
    artifact = DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 1,
            "chapter_goal": "离开山谷",
            "opening_state": "天将亮",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "山谷",
                    "action": "林昭起身",
                    "result": "找到出口",
                }
            ],
            "ending_state": "走出山谷",
        }
    )

    assert artifact.scene_beats[0].character_intents == []
    assert artifact.schema_version == "director-artifact/v1"


def test_writer_prompt_treats_character_intents_as_private_control() -> None:
    artifact = _rich_artifact()
    request = WriterRequest(
        chapter_number=3,
        director_artifact=artifact,
        character_cards=[
            {
                "name": "林渊",
                "role": "protagonist",
                "performance_profile": {"speech_style": "说话直接"},
            },
            {
                "name": "苏瑶",
                "role": "女主",
                "performance_profile": {"speech_style": "嘴硬，关心时绕着说"},
            },
            {
                "name": "王胖子",
                "role": "盟友",
                "performance_profile": {"speech_style": "熟人面前爱调侃"},
            },
        ],
    )

    prompt = build_writer_prompt(request)

    assert "苏瑶想要：确认林渊有没有受伤" in prompt
    assert "不说出口：不承认自己一直在关注他" in prompt
    assert "character_intents 是作者侧写作控制" in prompt
    assert "禁止为了体现群像而让出场人物依次发表观点" in prompt


def test_fact_extractor_director_view_omits_private_character_intents() -> None:
    projected = _fact_extractor_director_view(_rich_artifact())

    assert projected is not None
    rendered = json.dumps(projected, ensure_ascii=False)
    assert "三人离开演武场" in rendered
    assert "苏瑶" not in rendered
    assert "不承认自己一直在关注他" not in rendered
    assert "speech_strategy" not in rendered
    assert "character_intents" not in rendered


def test_legacy_outline_view_preserves_cast(tmp_path) -> None:
    legacy_root = tmp_path / ".webnovel"
    legacy_root.mkdir(parents=True)
    (legacy_root / "outline.json").write_text(
        json.dumps(
            {
                "chapters": [
                    {
                        "chapter_number": 3,
                        "title": "比试之后",
                        "goal": "处理赛后压力",
                        "obstacle": "赵家盯上林渊",
                        "action": "离开演武场",
                        "turn": "察觉跟踪",
                        "payoff": "关系推进",
                        "ending_hook": "赵家开始调查",
                        "cast": ["林渊", "苏瑶", "王胖子"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    view = legacy_outline_view(tmp_path / ".story-system")

    assert view is not None
    chapter = view["chapters"][0]
    assert chapter["cast"] == ["林渊", "苏瑶", "王胖子"]
    assert chapter["turn"] == "察觉跟踪"
    assert chapter["ending_hook"] == "赵家开始调查"


def test_relevant_cast_prefers_explicit_chapter_cast_and_adds_protagonist() -> None:
    story = StoryState(
        story_id="s-intent-cast",
        outline="宗门比试后各方重新评估林渊。",
        genre="玄幻",
        style="自然口语",
        current_chapter=2,
        outline_context={
            "chapter": {
                "chapter_number": 3,
                "cast": ["苏瑶", "王胖子"],
                "goal": "处理赛后关系和新的敌意",
            }
        },
        characters=[
            CharacterState(name="林渊", role="protagonist"),
            CharacterState(name="苏瑶", role="女主"),
            CharacterState(name="王胖子", role="盟友"),
            CharacterState(name="赵天衡", role="stage_antagonist"),
        ],
    )
    context = DirectorContext(
        chapter_number=3,
        volume={"chapter_range": [1, 20]},
        book_outline_summary="",
        nearby_outline=[
            {
                "number": 3,
                "goal": "处理赛后关系和新的敌意",
                "cast": ["苏瑶", "王胖子"],
            }
        ],
        character_cards=[],
    )

    names = _chapter_cast_names(story, context, 3)

    assert names[:3] == ["苏瑶", "王胖子", "林渊"]
    assert "赵天衡" not in names
