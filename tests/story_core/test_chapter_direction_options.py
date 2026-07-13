from packages.story_core.chapter_direction import build_chapter_direction_options
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.simulation import build_chapter_simulation_plan


def _webgame_story() -> StoryState:
    return StoryState(
        story_id="s-direction-options",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率和混沌之种。",
        genre="网游",
        style="番茄升级流",
        current_chapter=1,
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
        world_facts=["现实催租压力未解决。", "低级收益不能直接触发公会追杀。"],
        progression_ledger={
            "protagonist": {"level": "Lv.1", "hp": "46/100", "mp": "0/60"},
            "economy": {"game_currency": "0铜", "inventory": {"灰狼毒腺": 8, "粗糙狼皮": 5}},
            "equipment": {"weapon": "新手法杖", "durability": "4/10"},
            "quests": {"清道夫委托": "未完成，还差2份毒腺"},
        },
    )


def test_build_chapter_direction_options_offers_reader_meaningful_branches():
    options = build_chapter_direction_options(_webgame_story(), 2)

    assert options["schema_version"] == "chapter-direction-options/v1"
    assert options["chapter_number"] == 2
    assert options["recommended_id"] == "trade-bridge"
    assert [item["id"] for item in options["options"]] == [
        "trade-bridge",
        "chaos-seed-trace",
        "guild-ecology",
    ]
    trade = options["options"][0]
    assert "现实" in trade["reader_promise"]
    assert "提现" in trade["ending_hook"] or "收购" in trade["ending_hook"]
    for item in options["options"]:
        assert item["chapter_goal"]
        assert item["wow_beat"]
        assert item["ending_hook"]
        assert item["main_scenes"]
        assert item["risk"]


def test_selected_chapter_direction_enters_simulation_plan_required_beats():
    story = _webgame_story()
    choices = build_chapter_direction_options(story, 2)
    selected = next(item for item in choices["options"] if item["id"] == "chaos-seed-trace")

    plan = build_chapter_simulation_plan(
        story,
        2,
        chapter_seed={"selected_chapter_direction": selected},
    )

    assert plan.chapter_goal == selected["chapter_goal"]
    assert plan.simulation_variant["chapter_direction"]["id"] == "chaos-seed-trace"
    assert any(selected["wow_beat"] in beat for beat in plan.required_beats)
    assert any(selected["ending_hook"] in beat for beat in plan.required_beats)
