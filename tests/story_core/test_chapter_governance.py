from packages.story_core.chapter_governance import build_chapter_governance
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.writing_packet import build_codex_writing_packet


def _web_game_story() -> StoryState:
    return StoryState(
        story_id="s-governance",
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


def test_first_chapter_governance_separates_intent_context_and_rule_stack():
    story = _web_game_story()
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="第1章 灰烬村的登录者",
        body="",
        next_outline="第2章继续确认任务和补给成本。",
        updated_story=story,
    )

    governance = build_chapter_governance(story, bundle, chapter_number=1)

    assert governance["schema_version"] == "chapter-governance/v1"
    assert governance["chapter_intent"]["chapter_number"] == 1
    assert "现实压力" in "、".join(governance["chapter_intent"]["must_include"])
    assert "交易行" in "、".join(governance["chapter_intent"]["must_avoid"])
    assert governance["runtime_context"]["protagonist"]["real_name"] == "苏叶"
    assert governance["runtime_context"]["protagonist"]["game_id"] == "夜烬"
    assert any("怪物统一为灰鼠" in item for item in governance["rule_stack"]["hard_facts"])
    assert "爽点" in "、".join(governance["rule_stack"]["diagnostic_only"])


def test_writing_packet_embeds_governance_without_mixing_diagnostic_terms_into_hard_locks():
    story = _web_game_story()
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="第1章 灰烬村的登录者",
        body="",
        next_outline="第2章继续确认任务和补给成本。",
        updated_story=story,
    )

    packet = build_codex_writing_packet(story, bundle)

    assert "governance" in packet
    assert packet["governance"]["rule_stack"]["diagnostic_only"]
    assert not any("爽点" in item for item in packet["hard_locks"])
    assert any("爽点" in item for item in packet["governance"]["rule_stack"]["diagnostic_only"])


def test_later_chapter_governance_uses_latest_context_without_first_chapter_bans():
    story = _web_game_story()
    story.current_chapter = 2
    bundle = ChapterBundle(
        chapter_number=2,
        chapter_title="第2章 第一瓶小法力药",
        body="",
        next_outline="夜烬确认补给成本。",
        updated_story=story,
        event_plan={"next_focus": "确认补给成本和任务回报。"},
    )

    governance = build_chapter_governance(story, bundle, chapter_number=2)

    assert governance["chapter_intent"]["chapter_number"] == 2
    assert any("承接上一章" in item for item in governance["chapter_intent"]["must_include"])
    assert not any("第一章禁止" in item for item in governance["chapter_intent"]["must_avoid"])
    assert governance["runtime_context"]["next_focus"] == "确认补给成本和任务回报。"
