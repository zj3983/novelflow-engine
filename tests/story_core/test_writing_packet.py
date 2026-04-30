from packages.story_core.engine import ChapterBundle
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.writing_packet import build_codex_writing_packet


def test_first_chapter_packet_contains_manual_drafting_contract():
    story = StoryState(
        story_id="s-writing-packet",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率。",
        genre="网游",
        style="升级流",
        current_chapter=1,
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["安全升到10级", "隐藏混沌之种"],
            )
        ],
        world_facts=["灰烬村是新手村，低级收益主要使用铜币。"],
        author_constraints=["现实姓名和游戏ID必须分层。"],
    )
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="第1章 灰烬村的登录者",
        body="苏叶登录游戏，夜烬完成首次验证。",
        next_outline="第2章继续确认任务和补给成本。",
        updated_story=story,
    )

    packet = build_codex_writing_packet(story, bundle)

    assert packet["schema_version"] == "codex-writing-packet/v1"
    assert packet["chapter_number"] == 1
    assert packet["target_chars"] == {"min": 4200, "max": 5500}
    assert packet["protagonist"]["real_name"] == "苏叶"
    assert packet["protagonist"]["game_id"] == "夜烬"
    assert any("现实姓名：苏叶" in item for item in packet["hard_locks"])
    assert any("1金币=100银币=10000铜币" in item for item in packet["hard_locks"])
    assert any(card["id"] == "validation" for card in packet["scene_cards"])
    assert packet["submission_contract"]["endpoint"] == "POST /projects/{project_id}/manual-draft"


def test_packet_uses_existing_scene_cards_when_available():
    story = StoryState(story_id="s-existing-scenes", outline="宫廷调查", genre="fantasy", style="plain")
    bundle = ChapterBundle(
        chapter_number=2,
        body="",
        next_outline="继续推进。",
        updated_story=story,
        scene_cards=[
            {
                "template_id": "market-check",
                "location": "交易行门口",
                "purpose": "确认价格而不暴露身份",
                "conflict": "人多眼杂",
                "must_show": ["匿名寄售规则"],
                "avoid": ["精准暴露身份"],
                "fact_locks": ["只允许弱线索"],
            }
        ],
    )

    packet = build_codex_writing_packet(story, bundle)

    assert packet["scene_cards"] == [
        {
            "index": 1,
            "id": "market-check",
            "location": "交易行门口",
            "purpose": "确认价格而不暴露身份",
            "conflict": "人多眼杂",
            "must_show": ["匿名寄售规则"],
            "avoid": ["精准暴露身份"],
            "fact_locks": ["只允许弱线索"],
        }
    ]


def test_packet_exposes_governance_quality_gate():
    story = StoryState(story_id="s-gate-packet", outline="网游开服。", genre="网游", style="升级流")
    bundle = ChapterBundle(chapter_number=1, body="", next_outline="继续验证。", updated_story=story)

    packet = build_codex_writing_packet(story, bundle)

    assert packet["governance_gate"]["reviewer"] == "chapter_governance_gate/v1"
    assert packet["governance_gate"]["pass"] is True
    assert packet["governance_gate"]["next_action"] == "write_or_revise_chapter"
