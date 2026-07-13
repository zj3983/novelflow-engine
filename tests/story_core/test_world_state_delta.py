from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import (
    _sanitize_chapter_output,
    _soften_repeated_paragraph_openers,
    apply_simulated_state_deltas,
)


def test_apply_simulated_state_deltas_merges_world_event_and_scene_card_state():
    story = StoryState(
        story_id="s-delta",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="leveling",
        characters=[CharacterState(name="Su Ye", role="protagonist", game_id="Night Ember")],
        progression_ledger={
            "protagonist": {"level": 1, "class_path": "Element Mage Apprentice", "exp": "0/100"},
            "economy": {"currency": "0 copper", "inventory": {"venom_gland": 0}},
        },
    )
    world_events = [
        {
            "event_id": "gain",
            "state_delta": {
                "economy": {"inventory": {"venom_gland": 36}},
                "pressure": {"market_trace": "low"},
            },
        }
    ]
    scene_cards = [
        {
            "scene_id": "panel",
            "state_delta": {
                "protagonist": {"level": 2, "exp": "35/100", "hp": "88/100", "mp": "42/80"},
                "economy": {"currency": "190 copper"},
            },
        }
    ]

    apply_simulated_state_deltas(story, world_events=world_events, scene_cards=scene_cards, chapter_number=1)

    assert story.progression_ledger["protagonist"]["level"] == 2
    assert story.progression_ledger["protagonist"]["hp"] == "88/100"
    assert story.progression_ledger["economy"]["inventory"]["venom_gland"] == 36
    assert story.progression_ledger["economy"]["currency"] == "190 copper"
    assert story.progression_ledger["pressure"]["market_trace"] == "low"
    panel = story.characters[0].game_panel
    assert panel.level == 2
    assert panel.hp == "88/100"
    assert panel.inventory["venom_gland"] == 36


def test_apply_simulated_state_deltas_ignores_empty_values():
    story = StoryState(
        story_id="s-delta-empty",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="leveling",
        progression_ledger={"economy": {"currency": "50 copper"}},
    )
    world_events = [{"state_delta": {"economy": {"currency": ""}}}]

    apply_simulated_state_deltas(story, world_events=world_events, scene_cards=[], chapter_number=1)

    assert story.progression_ledger["economy"]["currency"] == "50 copper"


def test_apply_simulated_state_deltas_persists_systemic_ledger_delta():
    story = StoryState(
        story_id="s-systemic-delta",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="systemic",
        characters=[CharacterState(name="Su Ye", role="protagonist", game_id="Night Ember")],
        progression_ledger={
            "economy": {"inventory": {"wolf_pelt": 1}},
            "market": {"newbie_materials": {"supply": 34}},
            "systems": {"chaos_seed": {"anomaly_score": 0}},
        },
    )
    scene_cards = [
        {
            "state_delta": {
                "game_world_simulation": {
                    "ledger_delta": {
                        "clock_minutes": 24,
                        "inventory_delta": {"wolf_pelt": 5, "venom_gland": 8},
                        "cost_delta": {"hp": -54, "mp": -60, "durability": -6},
                        "market_delta": {"material_supply": 13, "price_copper": 5},
                        "hidden_system_delta": {"chaos_seed_anomaly_score": 7},
                        "next_pressure": ["repair_weapon", "find_market_route"],
                    }
                }
            }
        }
    ]

    apply_simulated_state_deltas(story, world_events=[], scene_cards=scene_cards, chapter_number=1)

    assert story.progression_ledger["economy"]["inventory"] == {"wolf_pelt": 6, "venom_gland": 8}
    assert story.progression_ledger["protagonist"]["cost_delta"] == {"hp": -54, "mp": -60, "durability": -6}
    assert story.progression_ledger["market"]["newbie_materials"]["supply"] == 47
    assert story.progression_ledger["market"]["newbie_materials"]["price_copper"] == 5
    assert story.progression_ledger["systems"]["chaos_seed"]["anomaly_score"] == 7
    assert story.progression_ledger["pressure"]["next"] == ["repair_weapon", "find_market_route"]
    assert story.characters[0].game_panel.inventory["wolf_pelt"] == 6


def test_apply_simulated_state_deltas_does_not_persist_raw_game_world_simulation():
    story = StoryState(
        story_id="s-systemic-raw-skip",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="systemic",
        progression_ledger={"protagonist": {"level": "Lv.1"}},
    )
    world_events = [
        {
            "state_delta": {
                "protagonist": {"exp": "30/100"},
                "game_world_simulation": {
                    "schema_version": "game-world-simulation/v1",
                    "ledger_delta": {"next_pressure": ["repair_weapon"]},
                },
            }
        }
    ]

    apply_simulated_state_deltas(story, world_events=world_events, scene_cards=[], chapter_number=2)

    assert story.progression_ledger["protagonist"]["exp"] == "30/100"
    assert story.progression_ledger["pressure"]["next"] == ["repair_weapon"]
    assert "game_world_simulation" not in story.progression_ledger


def test_apply_simulated_state_deltas_replaces_legacy_string_system_slots():
    story = StoryState(
        story_id="s-systemic-legacy-slots",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="systemic",
        progression_ledger={
            "market": "quiet",
            "systems": {"chaos_seed": "未解析"},
        },
    )
    scene_cards = [
        {
            "state_delta": {
                "game_world_simulation": {
                    "ledger_delta": {
                        "market_delta": {"material_supply": 3, "price_copper": 2},
                        "hidden_system_delta": {"chaos_seed_anomaly_score": 4},
                    }
                }
            }
        }
    ]

    apply_simulated_state_deltas(story, world_events=[], scene_cards=scene_cards, chapter_number=2)

    assert story.progression_ledger["market"]["newbie_materials"]["supply"] == 3
    assert story.progression_ledger["market"]["newbie_materials"]["price_copper"] == 2
    assert story.progression_ledger["systems"]["chaos_seed"]["anomaly_score"] == 4


def test_apply_simulated_state_deltas_applies_currency_and_final_set_delta():
    story = StoryState(
        story_id="s-systemic-final-set",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="systemic",
        progression_ledger={
            "protagonist": {"level": "Lv.1", "exp": "30/100"},
            "currency": "0铜",
            "inventory": "灰狼毒腺0份，粗糙狼皮7张，基础法力药水2瓶",
            "economy": {
                "game_currency": "0铜",
                "inventory": {"灰狼毒腺": 8, "粗糙狼皮": 7},
            },
            "equipment": {"weapon": "新手法杖", "durability": "4/10"},
        },
    )
    scene_cards = [
        {
            "state_delta": {
                "game_world_simulation": {
                    "ledger_delta": {
                        "inventory_delta": {"灰狼毒腺": -8, "初级法力药水": 2},
                        "currency_delta": {"铜": 5},
                        "set_delta": {
                            "protagonist": {"exp": "45/100", "mp": "30/60"},
                            "economy": {
                                "game_currency": "5铜",
                                "inventory": {"灰狼毒腺": 0, "粗糙狼皮": 7, "初级法力药水": 2},
                            },
                            "equipment": {"durability": "10/10"},
                        },
                    }
                }
            }
        }
    ]

    apply_simulated_state_deltas(story, world_events=[], scene_cards=scene_cards, chapter_number=2)

    assert story.progression_ledger["protagonist"]["exp"] == "45/100"
    assert story.progression_ledger["protagonist"]["mp"] == "30/60"
    assert story.progression_ledger["economy"]["game_currency"] == "5铜"
    assert story.progression_ledger["economy"]["inventory"]["灰狼毒腺"] == 0
    assert story.progression_ledger["economy"]["inventory"]["初级法力药水"] == 2
    assert "currency" not in story.progression_ledger["economy"]
    assert story.progression_ledger["equipment"]["durability"] == "10/10"


def test_repeated_paragraph_opener_softener_does_not_add_banned_time_crutches():
    body = "\n\n".join(
        [
            "夜烬看了一眼面板。",
            "夜烬把背包扣上。",
            "夜烬走到柜台前。",
            "夜烬递出材料。",
            "夜烬退回队伍边。",
            "夜烬摸了摸法杖。",
            "夜烬往村口走。",
        ]
    )

    softened = _soften_repeated_paragraph_openers(body)

    for token in ("这一次，", "下一刻，", "很快，", "片刻后，", "转眼，", "眼前，"):
        assert token not in softened


def test_second_chapter_sanitizer_does_not_add_outsider_or_emotion_scenes():
    body = "\n\n".join(
        [
            "夜烬走到任务柜台前，把材料递过去。",
            "他收起钱袋，转身去修理铺。",
            "他又买了两瓶初级法力药水。",
            "夜烬把背包扣上，准备回灰狼坡。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[])

    assert cleaned == body
    assert "路线挺熟" not in cleaned
    assert "运气好" not in cleaned
    assert "公共频道" not in cleaned
    assert "二十七块六" not in cleaned
    assert "获得：灰狼毒腺×2" not in cleaned


def test_second_chapter_sanitizer_does_not_insert_retroactive_venom_after_turn_in():
    body = "\n\n".join(
        [
            "夜烬把十份灰狼毒腺放在柜台上。",
            "洛婶数完材料，在册子上划了一笔。系统提示：清道夫委托已完成。铜币+30。",
            "他转身去修理铺，准备修杖买药。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[])

    assert "回村前，夜烬只在坡口补打一只灰狼" not in cleaned
    assert cleaned.count("清道夫委托") == 1


def test_second_chapter_sanitizer_normalizes_guide_terms_without_adding_npc_scene():
    body = "\n\n".join(
        [
            "夜烬把法杖横在身前，等灰狼的仇恨值转过来。",
            "群聚区的AI规矩和散怪完全不同，仇恨连锁会把人拖死。",
            "他回村修装备，又买了两瓶药。",
            "夜烬把背包扣上，准备去后坡。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[])

    assert "仇恨值" not in cleaned
    assert "AI规矩" not in cleaned
    assert "仇恨连锁" not in cleaned
    assert "灰狼的注意" in cleaned
    assert "灰狼互相呼应" in cleaned
    assert "修理铺" not in cleaned
    assert "十五铜" not in cleaned
    assert "只看裂纹和耐久" not in cleaned


def test_second_chapter_sanitizer_does_not_complete_partial_npc_boundary():
    body = "\n\n".join(
        [
            "夜烬去了修理铺，老葛说价格按牌子来。",
            "夜烬买完药，准备去后坡。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[])

    assert cleaned == body
    assert "只看裂纹和耐久" not in cleaned
    assert "不问夜烬从哪儿弄来的毒腺" not in cleaned


def test_second_chapter_sanitizer_does_not_add_luoshen_service_boundary():
    body = "\n\n".join(
        [
            "夜烬到药剂铺买药，洛婶把药瓶放在柜台上。",
            "夜烬收起药瓶，准备离开。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[])

    assert cleaned == body
    assert "洛婶只按清单收钱拿药" not in cleaned
    assert "不理会他刚交完委托又买药" not in cleaned


def test_second_chapter_sanitizer_removes_stale_webgame_terms_and_prices():
    body = "\n\n".join(
        [
            "夜烬看见灰鼠头顶飘出仇恨标识，旁边还有 footing（落脚点）不稳定的提示。",
            "每秒0.16点的恢复速率，从零到满需要整整六分钟。毒腺掉率基础值15%，受幸运值影响浮动。",
            "提示框弹出来：【后坡探路登记。条件未满足。需火球熟练度达到Lv.1，或携带高级法力药水×1。】",
            "铁匠说：三块铜。修完十成。钱袋里少了三枚铜币。洛婶说：十五铜一瓶。两瓶二十八，省两铜。夜烬数出二十八枚铜币，钱袋里只剩两枚铜币。",
            "夜烬准备继续。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[])

    assert "仇恨标识" not in cleaned
    assert "灰鼠" not in cleaned
    assert "灰狼" in cleaned
    assert "footing" not in cleaned
    assert "每秒0.16" not in cleaned
    assert "掉率基础值15%" not in cleaned
    assert "熟练度" not in cleaned
    assert "清道夫委托" not in cleaned
    assert "十五铜" in cleaned
    assert "五铜一瓶，两瓶十铜" in cleaned
    assert "钱袋里还剩五枚铜币" in cleaned
    assert "他把这一趟在心里过了一遍" not in cleaned
