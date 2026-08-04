import json
from collections import UserDict
from copy import deepcopy

from packages.story_core.engine import ChapterBundle
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import _normalize_event_plan
from packages.story_core.power_systems import power_system_prompt_slice
from packages.story_core.writing_packet import build_codex_writing_packet, power_system_context_for_state


def test_power_system_prompt_selects_nearest_shared_transfer_tiers_and_path_tree() -> None:
    spec = {
        "name": "Class system",
        "class_advancement_tiers": [
            {"level": 10, "name": "Class", "purpose": "Choose class", "common_requirements": ["Trial"], "failure_rule": "Retry"},
            {"level": 30, "name": "Branch", "purpose": "Choose branch", "common_requirements": ["Branch trial"], "failure_rule": "Delay"},
            {"level": 60, "name": "Legacy", "purpose": "Claim legacy", "common_requirements": ["Legacy trial"], "failure_rule": "Repair"},
        ],
        "paths": [{
            "name": "Mage",
            "branches": ["Fire", "Ice"],
            "advancement_tree": [
                {"level": level, "tier_name": tier, "options": [{"name": tier, "transfer_task": f"{tier} task", "ability_changes": [f"{tier} power"]}]}
                for level, tier in ((10, "Class"), (30, "Branch"), (60, "Legacy"))
            ],
        }],
    }

    result = power_system_prompt_slice(spec, stage_hint=12, path_hint="Fire")

    assert [tier["level"] for tier in result["class_advancement_tiers"]] == [10, 30]
    assert [node["level"] for node in result["paths"][0]["advancement_tree"]] == [10, 30]


def _packet_power_spec() -> dict:
    return {
        "name": "神域职业体系",
        "origin": ["职业权能来自试炼"],
        "stages": [
            {"name": "见习者", "level": 1, "entry": "创建角色", "change": "通用能力", "failure": "重新建号"},
            {"name": "正式职业", "level": 10, "entry": "转职任务", "change": "职业资源", "failure": "任务冷却"},
            {"name": "专精", "level": 20, "entry": "专精试炼", "change": "强化方向", "failure": "材料损失"},
            {"name": "进阶职业", "level": 30, "entry": "分支任务", "change": "分支能力", "failure": "晋升延期"},
            {"name": "传承", "level": 60, "entry": "传承试炼", "change": "职业权柄", "failure": "传承反噬"},
        ],
        "paths": [
            {"name": "法师", "branches": ["元素法师", "秘术法师"], "role": "远程输出", "advancement": ["元素核心试炼"]},
            {"name": "战士", "branches": ["盾战士", "狂战士"], "role": "近战承伤", "advancement": ["战团试炼"]},
        ],
        "skills": ["技能必须通过导师、技能书或试炼获得"],
        "equipment": ["装备必须来自掉落、制作或交易"],
        "resources": ["法力通过休息与药剂恢复"],
        "advancement": ["晋升同时需要等级、任务和材料"],
        "costs": ["透支会造成虚弱"],
        "counters": ["沉默克制持续施法"],
        "boundaries": ["不得无条件跨越两个阶段"],
        "continuity_ledger": ["level", "class_path", "skills", "equipment", "resources", "conditions"],
    }


def _power_story(*, ledger: dict | None = None, characters: list[CharacterState] | None = None) -> StoryState:
    return StoryState(
        story_id="s-power-packet",
        outline="职业成长",
        genre="网游",
        style="白描",
        progression_ledger=ledger or {},
        characters=characters or [],
        world_context={"power_system_spec": _packet_power_spec()},
    )


def _attribute_packet_story(*, ledger: dict | None = None) -> StoryState:
    spec = _packet_power_spec()
    spec["attribute_allocation"] = {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {"智力": 5, "力量": 5},
        "allow_carry": True,
        "respec_rule": "主城洗点",
    }
    return StoryState(
        story_id="attribute-packet",
        outline="属性点测试",
        genre="网游",
        style="白描",
        progression_ledger=ledger or {"protagonist": {"level": "Lv.1", "unallocated_attribute_points": 0}},
        world_context={"power_system_spec": spec},
    )


def test_packet_uses_ledger_level_and_branch_to_select_current_next_stage_and_path():
    story = _power_story(ledger={"protagonist": {"level": "Lv.12", "class_path": "元素法师"}})
    source = deepcopy(story.world_context["power_system_spec"])

    packet = build_codex_writing_packet(story, chapter_number=3)

    power = packet["power_system"]
    assert [stage["level"] for stage in power["stages"]] == [10, 20]
    assert [path["name"] for path in power["paths"]] == ["法师"]
    assert power["paths"][0]["role"] == "远程输出"
    assert {"costs", "boundaries", "continuity_ledger"} <= set(power)
    assert len(json.dumps(power, ensure_ascii=False, separators=(",", ":"))) <= 5000
    power["stages"][0]["name"] = "外部修改"
    assert story.world_context["power_system_spec"] == source


def test_packet_includes_only_compact_free_attribute_context_and_chapter_decision() -> None:
    story = _attribute_packet_story(
        ledger={
            "protagonist": {
                "level": "Lv.1",
                "attributes": {"智力": 5, "力量": 5},
                "unallocated_attribute_points": 0,
                "attribute_allocations": [{"chapter": 1, "allocations": {"智力": 2}, "remaining": 3}],
            }
        }
    )
    bundle = ChapterBundle(
        chapter_number=2,
        body="",
        next_outline="继续升级",
        updated_story=story,
        event_plan={
            "level": "Lv.2",
            "attribute_allocation_decision": {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 0},
        },
    )

    packet = build_codex_writing_packet(story, bundle)

    assert packet["attribute_allocation"] == {
        "mode": "free",
        "points_per_level": 5,
        "attributes": {"智力": 5, "力量": 5},
        "available_points": 0,
        "latest_allocations": [{"chapter": 1, "allocations": {"智力": 2}, "remaining": 3}],
        "chapter_decision": {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 0},
    }
    assert "allow_carry" not in str(packet["attribute_allocation"])
    assert any("attribute points" in line for line in packet["prose_renderer"]["body_contract"])


def test_packet_omits_attribute_context_without_free_rule() -> None:
    packet = build_codex_writing_packet(_power_story(), chapter_number=1)

    assert "attribute_allocation" not in packet


def test_normalized_level_target_preserves_decision_through_writing_packet() -> None:
    story = _attribute_packet_story()
    raw_event_plan = {
        "state_delta": {"protagonist": {"level": "Lv.2"}},
        "attribute_allocation_decision": {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 0},
    }
    event_plan = _normalize_event_plan(raw_event_plan, chapter_number=2, story=story)
    bundle = ChapterBundle(chapter_number=2, body="", next_outline="继续升级", updated_story=story, event_plan=event_plan)

    packet = build_codex_writing_packet(story, bundle)

    assert event_plan["attribute_allocation_level_target"] == 2
    assert packet["attribute_allocation"]["chapter_decision"] == {
        "mode": "allocate",
        "allocations": {"智力": 5},
        "remaining": 0,
    }
    assert any("attribute points" in line for line in packet["prose_renderer"]["body_contract"])


def test_direct_event_plan_level_preserves_decision_through_writing_packet() -> None:
    story = _attribute_packet_story()
    raw_event_plan = {
        "level": "Lv.2",
        "attribute_allocation_decision": {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 0},
    }
    event_plan = _normalize_event_plan(raw_event_plan, chapter_number=2, story=story)
    bundle = ChapterBundle(chapter_number=2, body="", next_outline="继续升级", updated_story=story, event_plan=event_plan)

    packet = build_codex_writing_packet(story, bundle)

    assert event_plan["attribute_allocation_level_target"] == 2
    assert packet["attribute_allocation"]["chapter_decision"]["allocations"] == {"智力": 5}
    assert any("attribute points" in line for line in packet["prose_renderer"]["body_contract"])


def test_writing_packet_does_not_apply_previous_bundle_decision_to_next_chapter() -> None:
    story = _attribute_packet_story()
    story.current_chapter = 1
    story.progression_ledger["protagonist"]["unallocated_attribute_points"] = 5
    bundle = ChapterBundle(
        chapter_number=1,
        body="",
        next_outline="继续探索",
        updated_story=story,
        event_plan={"attribute_allocation_decision": {"mode": "carry", "remaining": 5, "reason": "留给转职"}},
    )

    packet = build_codex_writing_packet(story, bundle, chapter_number=2)

    assert packet["attribute_allocation"]["available_points"] == 5
    assert "chapter_decision" not in packet["attribute_allocation"]


def test_packet_uses_character_world_state_aliases_and_respects_stage_boundaries():
    protagonist = CharacterState(
        name="苏叶",
        role="主角",
        game_state={"current": {"current_level": "20级", "profession": "秘术法师"}},
    )
    packet = build_codex_writing_packet(_power_story(characters=[protagonist]), chapter_number=4)

    assert [stage["level"] for stage in packet["power_system"]["stages"]] == [20, 30]
    assert [path["name"] for path in packet["power_system"]["paths"]] == ["法师"]


def test_mapping_characters_choose_explicit_protagonist_after_leading_npc():
    characters = [
        UserDict({"name": "守门人", "role": "NPC", "level": 60, "class_path": "战士"}),
        UserDict({"name": "夜烬", "role": "main", "level": "Lv.12", "class_path": "元素法师学徒"}),
    ]

    power = power_system_context_for_state(_packet_power_spec(), characters=characters)

    assert [stage["level"] for stage in power["stages"]] == [10, 20]
    assert [path["name"] for path in power["paths"]] == ["法师"]


def test_mapping_characters_skip_frozen_protagonist_for_later_active_lead():
    characters = [
        UserDict(
            {
                "name": "Archived Lead",
                "role": "protagonist",
                "frozen": True,
                "level": 60,
                "class_path": "战士",
            }
        ),
        UserDict(
            {
                "name": "Active Lead",
                "role": "main",
                "lifecycle_state": "active",
                "level": "Lv.12",
                "class_path": "元素法师学徒",
            }
        ),
    ]

    power = power_system_context_for_state(_packet_power_spec(), characters=characters)

    assert [stage["level"] for stage in power["stages"]] == [10, 20]
    assert [path["name"] for path in power["paths"]] == ["法师"]


def test_mapping_characters_require_active_protagonist_lifecycle():
    active = UserDict(
        {
            "name": "Active Lead",
            "role": "main",
            "lifecycle_state": "active",
            "level": 12,
            "class_path": "元素法师学徒",
        }
    )

    for lifecycle_state in ("proposed", "rejected"):
        pending = UserDict(
            {
                "name": "Pending Lead",
                "role": "protagonist",
                "lifecycle_state": lifecycle_state,
                "level": 60,
                "class_path": "战士",
            }
        )
        power = power_system_context_for_state(
            _packet_power_spec(),
            characters=[pending, active],
        )

        assert [stage["level"] for stage in power["stages"]] == [10, 20]
        assert [path["name"] for path in power["paths"]] == ["法师"]


def test_character_objects_require_active_protagonist_lifecycle():
    active = CharacterState(
        name="Active Lead",
        role="main",
        lifecycle_state="active",
        game_state={"current": {"level": 12, "class_path": "元素法师学徒"}},
    )

    for lifecycle_state in ("proposed", "rejected"):
        pending = CharacterState(
            name="Pending Lead",
            role="protagonist",
            lifecycle_state=lifecycle_state,
            game_state={"current": {"level": 60, "class_path": "战士"}},
        )
        power = power_system_context_for_state(
            _packet_power_spec(),
            characters=[pending, active],
        )

        assert [stage["level"] for stage in power["stages"]] == [10, 20]
        assert [path["name"] for path in power["paths"]] == ["法师"]


def test_mapping_characters_skip_inactive_role_tagged_leads():
    inactive_states = [
        {"lifecycle_state": "inactive"},
        {"lifecycle_state": "retired"},
        {"lifecycle_state": "dead"},
        {"lifecycle_state": "frozen"},
        {"status": "inactive"},
        {"status": "proposed"},
        {"status": "rejected"},
        {"status": "retired"},
        {"status": "dead"},
        {"status": "frozen"},
    ]
    active = UserDict(
        {
            "name": "Active Lead",
            "role": "main",
            "lifecycle_state": "active",
            "level": 12,
            "class_path": "元素法师学徒",
        }
    )

    for state in inactive_states:
        inactive = UserDict(
            {
                "name": "Inactive Lead",
                "role": "protagonist",
                "level": 60,
                "class_path": "战士",
                **state,
            }
        )
        power = power_system_context_for_state(
            _packet_power_spec(),
            characters=[inactive, active],
        )

        assert [stage["level"] for stage in power["stages"]] == [10, 20]
        assert [path["name"] for path in power["paths"]] == ["法师"]


def test_authoritative_ledger_power_hints_override_character_mapping_state():
    characters = [
        UserDict({"name": "夜烬", "role": "主角", "level": 12, "class_path": "元素法师学徒"}),
    ]

    power = power_system_context_for_state(
        _packet_power_spec(),
        progression_ledger={"protagonist": {"level": 20, "class_path": "战士"}},
        characters=characters,
    )

    assert [stage["level"] for stage in power["stages"]] == [20, 30]
    assert [path["name"] for path in power["paths"]] == ["战士"]


def test_packet_uses_conservative_power_fallback_without_progression_state():
    packet = build_codex_writing_packet(_power_story(), chapter_number=1)

    assert [stage["level"] for stage in packet["power_system"]["stages"]] == [1, 10, 20]
    assert packet["power_system"]["paths"] == [
        {"name": "法师", "branches": ["元素法师", "秘术法师"]},
        {"name": "战士", "branches": ["盾战士", "狂战士"]},
    ]


def test_packet_omits_power_system_for_absent_and_legacy_world_context():
    absent = StoryState(story_id="s-none", outline="现实故事", genre="都市", style="白描")
    legacy = StoryState(
        story_id="s-legacy",
        outline="旧项目",
        genre="网游",
        style="白描",
        world_context={"power_system": ["旧版职业规则"]},
    )

    assert "power_system" not in build_codex_writing_packet(absent, chapter_number=1)
    assert "power_system" not in build_codex_writing_packet(legacy, chapter_number=1)


def test_file_project_legacy_prompt_preview_has_exactly_no_power_system_key():
    store = object.__new__(FileProjectStore)

    preview = store._compact_prompt_preview_packet(
        {
            "schema_version": "file-writing-packet/v1",
            "target_chapter": 2,
            "scene_kind": "reality",
            "state": {"story_id": "legacy", "genre": "都市", "style": "白描"},
        }
    )

    assert "power_system" not in preview


def test_first_chapter_packet_contains_contract():
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
    assert any("人物行动、选择和结果要接得上" in rule for rule in packet["style_rules"])
    assert all("番茄爆款网文" not in rule for rule in packet["style_rules"])
    assert any("sentences complete" in rule for rule in packet["prose_renderer"]["body_contract"])
    assert all("Tomato-style" not in rule for rule in packet["prose_renderer"]["body_contract"])
    assert packet["title_contract"]["style"] == "tomato_concrete_short_title"
    assert any("真实章节目录" in rule for rule in packet["title_contract"]["rules"])
    assert "清道夫委托" in packet["title_contract"]["examples"]
    assert any("现实姓名：苏叶" in item for item in packet["hard_locks"])
    assert any("1金币=100银币=10000铜币" in item for item in packet["hard_locks"])
    assert any(card["id"] == "validation" for card in packet["scene_cards"])
    assert packet["whole_chapter_contract"]["mode"] == "whole_body_only"
    assert "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子" in packet["whole_chapter_contract"]["beat_map"]
    assert any("句子要完整" in item for item in packet["whole_chapter_contract"]["style"])
    assert any("自然对话" in item for item in packet["whole_chapter_contract"]["dialogue"])
    assert any("谜语式" in item for item in packet["whole_chapter_contract"]["avoid"])


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
    assert any("首次达到升级阈值" in rule for rule in packet["style_rules"])
    assert any("总额减手续费等于净到账" in rule for rule in packet["style_rules"])
    assert any("不得额外赠送开局属性点" in rule for rule in packet["style_rules"])


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


def test_file_writer_character_cards_use_generic_state_for_non_game_story():
    store = object.__new__(FileProjectStore)
    cards = store._writer_character_cards(
        {
            "characters": [
                {
                    "name": "沈墨",
                    "role": "主角",
                    "current_state": {"current": {"location": "祖祠"}},
                    "real_state": {"current": {"location": "旧住处"}},
                }
            ]
        },
        {"chapter": {"cast": ["沈墨"]}},
        scene_kind="reality",
        is_game_story=False,
    )

    assert cards[0]["state_context"] == {
        "current_state": {
            "current": {"location": "祖祠"},
            "recent_changes": [],
        }
    }


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
        "world_blueprint": {
            "genre_plugin_ids": ["game_webnovel"],
            "power_system_spec": _packet_power_spec(),
        },
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
        "progression_ledger": {"protagonist": {"level": 12, "class_path": "元素法师"}},
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
    (root / ".webnovel" / "story_core.json").write_text(
        json.dumps(
            {
                "schema_version": "story-core/v1",
                "title": "双状态测试",
                "logline": "苏叶进入神域后必须靠游戏收益解决现实困境，否则会失去唯一住处。",
                "protagonist_profile": "谨慎的失业青年。",
                "inciting_incident": "他获得异常掉落能力。",
                "protagonist_goal": "在游戏中站稳并解决现实困境。",
                "main_conflict": "游戏规则和现实压力同时逼近。",
                "failure_stakes": "失去住处和翻身机会。",
                "growth_path": "从只求自保变成掌握规则的人。",
                "excitement_point": "游戏能力逐步影响现实。",
                "target_audience": "喜欢网游升级的读者。",
                "reader_promise": "每章都有可见成长或现实回报。",
                "ending_direction": "主角掌握神域规则并改变现实。",
                "core_advantage": {
                    "name": "异常掉落",
                    "type": "概率优势",
                    "ability": "提高符合当前等级怪物的有效掉落。",
                    "growth_rule": "完成阶段验证后开放新的掉落类别。",
                    "limits": "不能绕过等级差和任务条件。",
                    "early_payoff": "用第一批材料换到启动资金。",
                },
                "central_mystery": {
                    "surface_anomaly": "掉落记录偶尔出现未知校验信息。",
                    "hidden_truth": "神域正在筛选能够承受现实反馈的玩家。",
                    "reality_impact": "游戏属性会分阶段反馈现实。",
                    "reveal_path": ["异常校验", "属性反馈", "筛选真相"],
                },
                "initial_drive": {
                    "immediate_need": "先挣到稳定生活费。",
                    "trigger": "现实工作中断后进入神域。",
                    "short_term_goal": "靠第一批材料解决住处问题。",
                    "failure_stakes": "失去住处和继续游戏的条件。",
                    "long_term_transition": "从打金转向追查神域异常。",
                },
                "source_direction_id": "direction-1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = FileProjectStore(root)
    packet = store.writing_packet(1)
    preview = store.prompt_preview(1)
    prompts = {item["key"]: item for item in preview["prompts"]}
    character_module = next(item for item in preview["modules"] if item["key"] == "character_context")
    core_module = next(item for item in preview["modules"] if item["key"] == "core_context")

    assert packet["scene_kind"] == "game"
    assert "story_core" not in packet
    assert packet["outline_context"]["overall"]["story"] == "双状态测试"
    assert packet["outline_context"]["overall"]["positioning"]["reader_promise"] == (
        "每章都有可见成长或现实回报。"
    )
    assert packet["outline_context"]["overall"]["core_advantage"]["name"] == "异常掉落"
    assert not (root / ".webnovel" / "story_core.json").exists()
    assert (root / ".webnovel" / "story_core.legacy.json").exists()
    assert "神域正在筛选" not in json.dumps(packet, ensure_ascii=False)
    assert "pacing_stages" not in json.dumps(packet, ensure_ascii=False)
    assert [stage["level"] for stage in packet["power_system"]["stages"]] == [10, 20]
    assert [path["name"] for path in packet["power_system"]["paths"]] == ["法师"]
    assert '"power_system"' in preview["modules"][-1]["content"]
    assert "神域职业体系" in prompts["writer_body"]["content"]
    assert "每章都有可见成长或现实回报" in core_module["content"]
    assert "喜欢网游升级的读者" not in prompts["writer_body"]["content"]
    assert '"scene_kind": "game"' in preview["modules"][-1]["content"]
    assert '"game_state"' in character_module["content"]
    assert '"real_state"' not in character_module["content"]

    generic_root = tmp_path / "generic-file-project"
    (generic_root / ".story-system" / "chapters").mkdir(parents=True)
    (generic_root / ".story-system" / "reviews").mkdir(parents=True)
    (generic_root / ".webnovel").mkdir(parents=True)
    (generic_root / "chapters").mkdir(parents=True)
    generic_project = deepcopy(project)
    generic_project["project_id"] = "p-generic-dual"
    generic_project["world_blueprint"]["genre_plugin_ids"] = ["suspense"]
    generic_state = deepcopy(state)
    generic_state["story_id"] = "s-generic-dual"
    generic_state["genre"] = "suspense"
    (generic_root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps({"project": generic_project}, ensure_ascii=False), encoding="utf-8"
    )
    (generic_root / ".webnovel" / "project.json").write_text(
        json.dumps(generic_project, ensure_ascii=False), encoding="utf-8"
    )
    (generic_root / ".webnovel" / "state.json").write_text(
        json.dumps(generic_state, ensure_ascii=False), encoding="utf-8"
    )
    (generic_root / ".webnovel" / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False), encoding="utf-8"
    )

    generic_preview = FileProjectStore(generic_root).prompt_preview(1)
    generic_character_module = next(
        item for item in generic_preview["modules"] if item["key"] == "character_context"
    )
    assert '"game_state"' not in generic_character_module["content"]
    assert "游戏状态：" in prompts["writer_body"]["content"]
    assert "现实状态：" not in prompts["writer_body"]["content"]
