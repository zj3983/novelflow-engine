from packages.story_core.models import CharacterState, StoryState
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events


def _story() -> StoryState:
    return StoryState(
        story_id="s-plot-sim",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率。",
        genre="网游",
        style="白描升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["低调验证千倍爆率", "把游戏收益变成现实喘息空间"],
            )
        ],
        progression_ledger={
            "protagonist": {"level": "Lv.1", "exp": "30/100", "hp": "42/100", "mp": "0/60"},
            "economy": {"game_currency": "空", "inventory": {"灰狼毒腺": 8, "粗糙狼皮": 7}},
            "equipment": {"durability": "4/10"},
            "quests": {"清道夫委托": "未接取；未提交；奖励未到账"},
        },
    )


def test_game_simulation_plan_carries_plot_simulation_for_writing():
    plan = build_chapter_simulation_plan(_story(), 2).model_dump()
    plot = plan["plot_simulation"]

    assert plot["mode"] == "plot-first"
    assert "读者" in plot["reader_hook"]
    assert "夜烬" in plot["chapter_desire"]
    assert len(plot["obstacle_chain"]) >= 3
    assert plot["choice_point"]
    assert plot["payoff"]
    assert plot["cost"]
    assert plot["emotional_turn"]
    assert plot["outsider_misread"]
    assert plot["ending_hook"]
    assert plan["longform_plot_contract"]["mode"] == "longform-plot-first"
    assert plan["longform_plot_contract"]["pace_contract"]["must_payoff"]
    assert "必须兑现" in plot["payoff_requirement"] or plot["payoff_requirement"]


def test_game_simulation_plan_has_longform_snowball_contract():
    plan = build_chapter_simulation_plan(_story(), 4).model_dump()
    contract = plan["longform_plot_contract"]

    assert contract["arc_window"]["name"] == "新手村滚雪球"
    assert "每章至少让一项账本向前滚" in contract["payoff_requirement"]
    assert any("苟不是不拿好处" in item for item in contract["snowball_logic"])
    assert any("低等级不能硬开高等级转职线" in item for item in contract["webgame_satisfaction"])


def test_scene_cards_use_plot_simulation_as_writing_spine():
    story = _story()
    plan = build_chapter_simulation_plan(story, 2).model_dump()
    events = simulate_world_events(story, 2, simulation_plan=plan)

    scene_cards = select_scene_cards(events, simulation_plan=plan)

    joined_purpose = "\n".join(card.purpose for card in scene_cards)
    joined_conflict = "\n".join(card.conflict for card in scene_cards)
    joined_must_show = "\n".join("\n".join(card.must_show) for card in scene_cards)

    assert "导演计划" in joined_purpose
    assert plan["plot_simulation"]["chapter_desire"] in joined_must_show
    assert plan["plot_simulation"]["choice_point"] in joined_conflict
    assert plan["plot_simulation"]["ending_hook"] in joined_must_show


def test_scene_cards_drop_blank_and_none_plot_values():
    story = _story()
    plan = build_chapter_simulation_plan(
        story,
        2,
        event_plan={"turn": "完成低级任务"},
        plot_authority="director",
    ).model_dump()
    cards = select_scene_cards([], chapter_seed={"chapter_number": 2, "genre_plugins": ["game_webnovel"]}, simulation_plan=plan)

    assert cards
    assert all(item not in {"", "None", "null"} for item in cards[0].must_show)
