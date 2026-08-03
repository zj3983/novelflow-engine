from types import SimpleNamespace

from packages.story_core.models import StoryState
from packages.story_core.pipeline.simulation_stage import prepare_simulation_stage


class PassthroughProfile:
    def prepare_scene_cards(self, context):
        return context.scene_cards


def _story() -> StoryState:
    return StoryState(
        story_id="simulation-stage",
        outline="主角调查旧城。",
        genre="都市",
        style="轻松",
    )


def test_simulation_stage_skips_world_event_generation_without_external_effect():
    result = prepare_simulation_stage(
        _story(),
        2,
        event_plan={},
        memory_constraints={},
        planning_profile=PassthroughProfile(),
        attach_trope_contract=lambda plan, seed: plan,
        simulate_events=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not simulate")),
    )

    assert result.run_world_simulation is False
    assert result.world_events == []
    assert result.simulation_plan["world_simulation_reason"] == "no_visible_external_effect"


def test_simulation_stage_returns_world_events_scene_cards_and_style_guidance():
    result = prepare_simulation_stage(
        _story(),
        2,
        event_plan={"external_effect": True},
        memory_constraints={},
        planning_profile=PassthroughProfile(),
        attach_trope_contract=lambda plan, seed: plan,
        simulation_decider=lambda *args, **kwargs: {"run": True, "reason": "test", "triggers": ["effect"]},
        simulate_events=lambda *args, **kwargs: [SimpleNamespace(model_dump=lambda: {"event": "停电"})],
        select_cards=lambda *args, **kwargs: [SimpleNamespace(model_dump=lambda: {"scene": "旧城"})],
        style_builder=lambda **kwargs: {"tone": "紧张"},
        performance_enricher=lambda cards, guidance: [*cards, {"guidance": guidance["tone"]}],
    )

    assert result.run_world_simulation is True
    assert result.world_events == [{"event": "停电"}]
    assert result.scene_cards == [{"scene": "旧城"}, {"guidance": "紧张"}]
    assert result.style_guidance == {"tone": "紧张"}
