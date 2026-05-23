from packages.story_core.game_world_simulator import simulate_game_world
from packages.story_core.models import CharacterState, StoryState


def _game_story() -> StoryState:
    return StoryState(
        story_id="s-game-sandbox",
        outline="网游开服，苏叶以夜烬身份低调验证混沌之种。",
        genre="网游",
        style="番茄升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["确认混沌之种的边界和代价"],
            )
        ],
        progression_ledger={
            "protagonist": {
                "level": 1,
                "class_path": "元素法师学徒",
                "exp": "0/100",
            },
            "economy": {"currency": "0铜", "inventory": {}},
            "equipment": {"weapon": "新手法杖", "durability": "10/10"},
        },
    )


def test_game_world_simulator_rolls_concrete_opening_ticks():
    result = simulate_game_world(_game_story(), 1)

    assert result["aggregate"]["hp"] == "46/100"
    assert result["aggregate"]["mp"] == "0/60"
    assert result["aggregate"]["weapon_durability"] == "4/10"
    assert result["aggregate"]["currency"] == "0铜"
    assert result["aggregate"]["inventory"] == {"灰狼毒腺": 8, "粗糙狼皮": 5}
    assert result["external_attention"]["guild"] == 0

    kill_ticks = [tick for tick in result["ticks"] if tick["kind"] == "combat"]
    assert len(kill_ticks) == 5
    assert kill_ticks[0]["drop_roll"]["actual"] == {"灰狼毒腺": 2, "粗糙狼皮": 1}
    assert kill_ticks[0]["visible_to"] == ["夜烬", "附近普通玩家"]
    assert "公会" not in "".join(kill_ticks[0]["visible_to"])
    assert kill_ticks[-1]["cost"]["mp"] == -8
    assert kill_ticks[-1]["cost"]["hp"] == -6


def test_game_world_simulator_records_npc_boundary_without_overreaction():
    result = simulate_game_world(_game_story(), 1)

    npc_tick = next(tick for tick in result["ticks"] if tick["kind"] == "npc_service")
    assert npc_tick["actor"] == "洛婶"
    assert npc_tick["knowledge_scope"] == ["药材数量", "委托规则", "药剂库存"]
    assert npc_tick["cannot_know"] == ["混沌之种", "现实身份", "完整刷怪路线", "公会内部消息"]
    assert result["observability"]["guild_signal"] == "none"
    assert result["observability"]["market_signal"] == "none"


def test_game_world_simulator_exports_systemic_state_and_visibility_layers():
    result = simulate_game_world(_game_story(), 1)

    systemic = result["systemic_simulation"]
    assert systemic["schema_version"] == "systemic-simulation/v1"
    assert result["world_state"]["systems"]["chaos_seed"]["anomaly_score"] > 0
    assert "hidden_system_tracks_private_anomaly" in result["systemic_rules"]
    assert any("combat_tick" in item for item in result["causal_chain"])
    assert result["ledger_delta"]["clock_minutes"] > 0
    assert result["ledger_delta"]["inventory_delta"] == result["aggregate"]["inventory"]
    assert result["visibility_layers"]["npc"]
    assert result["visibility_layers"]["guild"]
    assert any("cannot know hidden talent" in item for item in result["visibility_layers"]["npc"])


def test_game_world_simulator_exports_novel_simulation_ticks_not_plot_rules():
    result = simulate_game_world(_game_story(), 1)

    ticks = result["simulation_ticks"]

    assert ticks
    assert all({"actor", "action", "cost", "result", "visible_to", "hidden_delta", "next_pressure"} <= set(tick) for tick in ticks)
    assert any(tick["cost"].get("mp") for tick in ticks)
    assert any(tick["result"].get("inventory_delta") for tick in ticks)
    assert any(tick["hidden_delta"].get("chaos_seed_anomaly_score") for tick in ticks)
    serialized = " ".join(str(tick) for tick in ticks)
    assert "爽点" not in serialized
    assert "钩子" not in serialized
    assert "节奏" not in serialized


def test_game_world_simulator_gives_chapter_two_concrete_quest_loop():
    story = _game_story()
    story.progression_ledger = {
        "protagonist": {
            "game_id": "夜烬",
            "class_path": "元素法师学徒",
            "level": "Lv.1",
            "exp": "30/100",
            "hp": "42/100",
            "mp": "0/60",
        },
        "economy": {
            "game_currency": "0铜",
            "inventory": {"灰狼毒腺": 8, "粗糙狼皮": 7},
        },
        "equipment": {"weapon": "新手法杖", "durability": "4/10"},
    }

    result = simulate_game_world(story, 2)
    surface = " ".join(str(tick) for tick in result["simulation_ticks"])

    assert "补打一只灰狼" in surface
    assert "递交十份灰狼毒腺" in surface
    assert "短剑" not in surface
    assert "新手法杖" in surface
    assert result["ledger_delta"]["inventory_delta"]["灰狼毒腺"] == -8
    assert result["ledger_delta"]["inventory_delta"]["初级法力药水"] == 2
    assert result["ledger_delta"]["currency_delta"] == {"铜": 5}
    assert any("路线熟或运气好" in item for item in result["ledger_delta"]["next_pressure"])


def test_game_world_simulator_rotates_opening_variant():
    result = simulate_game_world(
        _game_story(),
        1,
        chapter_seed={"simulation_variant": {"id": "boundary-durability-route"}},
    )

    npc_tick = next(tick for tick in result["ticks"] if tick["kind"] == "npc_service")
    assert result["simulation_variant"] == "boundary-durability-route"
    assert npc_tick["actor"] == "修理匠老葛"
    assert result["aggregate"]["weapon_durability"] == "2/10"
    assert "修理" in result["chapter_pressure"] or "boundary-durability-route" in result["chapter_pressure"]
