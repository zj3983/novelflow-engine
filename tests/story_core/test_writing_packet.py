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
    assert packet["prose_renderer"]["skill"] == "chinese-novelist"
    assert packet["prose_renderer"]["role"] == "prose_renderer_only"
    assert "world_simulation" in packet["prose_renderer"]["do_not_use_for"]
    assert "review_verdicts" in packet["prose_renderer"]["do_not_use_for"]
    assert any("少用比喻和形容词" in rule for rule in packet["style_rules"])
    assert any("番茄爆款网文" in rule for rule in packet["style_rules"])
    assert any("rhetoric sparse" in rule for rule in packet["prose_renderer"]["body_contract"])
    assert any("Tomato-style webnovel language" in rule for rule in packet["prose_renderer"]["body_contract"])
    assert packet["title_contract"]["style"] == "tomato_concrete_short_title"
    assert any("真实章节目录" in rule for rule in packet["title_contract"]["rules"])
    assert "清道夫委托" in packet["title_contract"]["examples"]
    assert any("现实姓名：苏叶" in item for item in packet["hard_locks"])
    assert any("1金币=100银币=10000铜币" in item for item in packet["hard_locks"])
    assert any(card["id"] == "validation" for card in packet["scene_cards"])
    assert packet["whole_chapter_contract"]["mode"] == "whole_body_only"
    assert "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子" in packet["whole_chapter_contract"]["beat_map"]
    assert any("白描" in item for item in packet["whole_chapter_contract"]["style"])
    assert any("自然对话" in item for item in packet["whole_chapter_contract"]["dialogue"])
    assert any("谜语式" in item for item in packet["whole_chapter_contract"]["avoid"])
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
                "pov": "夜烬",
                "purpose": "确认价格而不暴露身份",
                "conflict": "人多眼杂",
                "must_show": ["匿名寄售规则"],
                "must_not_explain": ["精准暴露身份"],
                "ending_pressure": "下一笔交易必须更谨慎。",
                "state_delta": {"economy": {"inventory_hint": "保留材料"}},
            }
        ],
    )

    packet = build_codex_writing_packet(story, bundle)

    assert packet["scene_cards"] == [
        {
            "index": 1,
            "id": "market-check",
            "location": "交易行门口",
            "pov": "夜烬",
            "purpose": "确认价格而不暴露身份",
            "conflict": "人多眼杂",
            "must_show": ["匿名寄售规则"],
            "avoid": ["精准暴露身份"],
            "ending_pressure": "下一笔交易必须更谨慎。",
            "state_delta": {"economy": {"inventory_hint": "保留材料"}},
            "sensory_anchors": [],
            "subtext": "",
            "rhythm_hint": "",
        }
    ]


def test_packet_exposes_governance_quality_gate():
    story = StoryState(story_id="s-gate-packet", outline="网游开服。", genre="网游", style="升级流")
    bundle = ChapterBundle(chapter_number=1, body="", next_outline="继续验证。", updated_story=story)

    packet = build_codex_writing_packet(story, bundle)

    assert packet["governance_gate"]["reviewer"] == "chapter_governance_gate/v1"
    assert packet["governance_gate"]["pass"] is True
    assert packet["governance_gate"]["next_action"] == "write_or_revise_chapter"


def test_packet_exposes_director_wow_hook_and_reality_bridge():
    story = StoryState(story_id="s-packet-director", outline="网游开服，千倍爆率。", genre="网游", style="番茄升级流")
    bundle = ChapterBundle(
        chapter_number=1,
        body="",
        next_outline="继续验证材料去向。",
        updated_story=story,
        event_plan={
            "wow_beat": "wow_beat: 千倍爆率用一次稀有掉落兑现，不要只有2-8倍。",
            "explicit_chapter_end_hook": "explicit_chapter_end_hook: 下一章去找散人收购渠道。",
            "reality_game_bridge": "reality_game_bridge: 游戏材料价格第一次指向现实催租压力。",
        },
    )

    packet = build_codex_writing_packet(story, bundle)

    assert packet["event_plan"]["wow_beat"].startswith("wow_beat")
    assert "下一章" in packet["event_plan"]["explicit_chapter_end_hook"]
    assert "现实" in packet["event_plan"]["reality_game_bridge"]
