import json

from packages.story_core.engine import ChapterBundle
from packages.story_core.file_project_store import FileProjectStore
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


def test_non_game_packet_does_not_leak_webgame_terms():
    story = StoryState(
        story_id="s-xianxia-packet",
        outline="林照被分去祖祠看守断香炉，残香里藏着宗门旧账。",
        genre="修仙",
        style="白描、现代中文",
        current_chapter=0,
        author_constraints=["不要写游戏面板、背包、铜币、掉落、任务牌或玩家生态。"],
    )
    bundle = ChapterBundle(chapter_number=1, body="", next_outline="掀开第三块青砖。", updated_story=story)

    packet = build_codex_writing_packet(story, bundle)
    text = str(packet)

    assert "UI panels" not in text
    assert "service counters" not in text
    assert "UI state" not in text
    assert "NPC服务点" not in text
    assert "委托名" not in text
    assert "铜币账目" not in text
    assert "清道夫委托" not in packet["title_contract"]["examples"]


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


def test_game_packet_requires_fast_visible_progression():
    story = StoryState(story_id="s-fast-growth", outline="网游开服。", genre="网游", style="升级流")
    bundle = ChapterBundle(chapter_number=5, body="", next_outline="继续验证。", updated_story=story)

    packet = build_codex_writing_packet(story, bundle)

    assert any("前10章节奏要快" in rule for rule in packet["style_rules"])
    assert any("连续两章不能只拿线索不给成长" in rule for rule in packet["style_rules"])
    assert any("等级、经验大幅推进、技能、装备、货币补给或任务权限" in rule for rule in packet["style_rules"])


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


def test_file_writer_character_cards_project_only_selected_state_line():
    store = object.__new__(FileProjectStore)
    state = {
        "characters": [
            {
                "name": "苏叶",
                "role": "主角",
                "real_state": {"current": {"balance": "27.60", "real_secret": "现实秘密"}},
                "game_state": {"current": {"level": "Lv.2", "game_secret": "游戏秘密"}},
            }
        ]
    }

    for scene_kind, expected in (
        ("game", {"game_state"}),
        ("reality", {"real_state"}),
        ("transition", {"real_state", "game_state"}),
    ):
        cards = store._writer_character_cards(
            state,
            {"chapter": {"cast": ["苏叶"]}},
            scene_kind=scene_kind,
        )
        assert set(cards[0]["state_context"]) == expected
        assert "real_secret" not in str(cards[0]["state_context"] if scene_kind == "game" else {})
        assert "game_secret" not in str(cards[0]["state_context"] if scene_kind == "reality" else {})


def test_writer_scene_kind_uses_all_scene_card_text_and_mixes_lines():
    store = object.__new__(FileProjectStore)

    assert store._writer_scene_kind(
        [{"location": "出租屋", "purpose": "核对银行余额"}],
        is_game_story=True,
    ) == "reality"
    assert store._writer_scene_kind(
        [{"location": "副本入口", "purpose": "领取任务"}],
        is_game_story=False,
    ) == "reality"
    assert store._writer_scene_kind(
        [
            {"title": "出租屋催租", "line": "reality"},
            {"title": "副本入口", "line": "game"},
        ],
        is_game_story=True,
    ) == "transition"


def test_common_writing_packet_projects_character_state_by_scene_kind():
    story = StoryState(
        story_id="s-common-dual",
        outline="网游开服，现实压力同步推进。",
        genre="网游",
        style="升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                game_panel={"game_id": "夜烬", "level": "Lv.2", "currency": "99金币"},
                real_state={"current": {"balance": "27.60", "real_secret": "现实秘密"}},
                game_state={"current": {"level": "Lv.2", "game_secret": "游戏秘密"}},
            )
        ],
    )
    def build_packet(line: str) -> dict:
        return build_codex_writing_packet(
            story,
            ChapterBundle(
                chapter_number=2,
                body="",
                next_outline="继续推进。",
                updated_story=story,
                scene_cards=[{"location": "副本入口", "purpose": "领取任务", "line": line}],
            ),
        )

    game_packet = build_packet("game")
    game_card = game_packet["character_cards"][0]
    assert game_packet["scene_kind"] == "game"
    assert set(game_card["state_context"]) == {"game_state"}
    assert "real_secret" not in str(game_card["state_context"])
    assert "game_panel" not in game_card
    assert "game_panel" not in game_card.get("continuity_locks", {})

    reality_packet = build_packet("reality")
    reality_card = reality_packet["character_cards"][0]
    assert reality_packet["scene_kind"] == "reality"
    assert set(reality_card["state_context"]) == {"real_state"}
    assert "Lv.2" not in str(reality_card)
    assert "99金币" not in str(reality_card)
    assert "game_panel" not in reality_card.get("continuity_locks", {})

    transition_packet = build_packet("transition")
    transition_card = transition_packet["character_cards"][0]
    assert transition_packet["scene_kind"] == "transition"
    assert set(transition_card["state_context"]) == {"real_state", "game_state"}
    assert "game_panel" not in transition_card.get("continuity_locks", {})


def test_file_project_packet_and_prompt_preview_share_scene_kind_and_state_context(tmp_path):
    root = tmp_path / "file-project"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    project = {
        "project_id": "p-dual",
        "title": "双状态测试",
        "active_story_id": "s-dual",
        "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        "character_profiles": [
            {
                "name": "苏叶",
                "role": "主角",
                "character_tier": "protagonist",
                "game_id": "夜烬",
                "real_state": {"current": {"balance": "27.60", "real_secret": "现实秘密"}},
                "game_state": {"current": {"level": "Lv.2", "game_secret": "游戏秘密"}},
            }
        ],
    }
    state = {
        "story_id": "s-dual",
        "current_chapter": 0,
        "genre": "网游",
        "style": "升级流",
        "outline": "双状态测试",
        "characters": project["character_profiles"],
        "world_facts": [],
    }
    outline = {
        "overall": {"story": "双状态测试"},
        "arcs": [],
        "chapters": [
            {
                "chapter_number": 1,
                "title": "副本入口",
                "goal": "进入副本",
                "action": "进入副本领取任务",
                "cast": ["苏叶"],
            }
        ],
    }
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps({"project": project}, ensure_ascii=False), encoding="utf-8"
    )
    (root / ".webnovel" / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    (root / ".webnovel" / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    (root / ".webnovel" / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    store = FileProjectStore(root)
    packet = store.writing_packet(1)
    preview = store.prompt_preview(1)
    prompts = {item["key"]: item for item in preview["prompts"]}
    character_module = next(item for item in preview["modules"] if item["key"] == "character_context")

    assert packet["scene_kind"] == "game"
    assert '"scene_kind": "game"' in preview["modules"][-1]["content"]
    assert '"game_state"' in character_module["content"]
    assert '"real_state"' not in character_module["content"]
    assert "游戏状态：" in prompts["writer_body"]["content"]
    assert "现实状态：" not in prompts["writer_body"]["content"]
