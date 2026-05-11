from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events


def _story() -> StoryState:
    return StoryState(
        story_id="s-world-sandbox-bridge",
        outline="网游开服，苏叶以夜烬身份低调验证混沌之种。",
        genre="网游",
        style="番茄升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )


def test_world_events_include_concrete_game_simulation_ticks():
    story = _story()
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()

    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)
    verify_event = next(event for event in events if event.event_id == "c1-small-verify")

    sandbox = verify_event.state_delta.get("game_world_simulation")
    assert sandbox
    assert sandbox["aggregate"]["inventory"]["灰狼毒腺"] == 8
    assert sandbox["aggregate"]["weapon_durability"] == "4/10"
    assert sandbox["external_attention"]["guild"] == 0
    assert len([tick for tick in sandbox["ticks"] if tick["kind"] == "combat"]) == 5


def test_scene_cards_surface_game_ticks_as_writeable_facts():
    story = _story()
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)

    cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)
    verify_card = next(card for card in cards if card.template_id == "small_verification")
    surface = " ".join(verify_card.must_show)

    assert "第1只灰狼" in surface
    assert "灰狼毒腺x2" in surface
    assert "最终：生命46/100，法力0/60，法杖4/10，毒腺8，狼皮5，0铜" in surface
    assert "公会注意力0" in surface
