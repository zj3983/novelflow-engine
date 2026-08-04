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


def test_simulation_stage_defers_external_world_updates_and_only_prepares_director_context():
    simulated = []

    result = prepare_simulation_stage(
        _story(),
        2,
        event_plan={
            "external_effect": True,
            "scene_chain": [
                {
                    "location": "旧城",
                    "pov": "林舟",
                    "goal": "找到证人",
                    "obstacle": "街区停电",
                    "action": "摸黑进入值班室",
                    "change": "发现备用电源被人拆走",
                    "next": "追查搬运记录",
                }
            ],
        },
        memory_constraints={},
        planning_profile=PassthroughProfile(),
        attach_trope_contract=lambda plan, seed: plan,
        simulation_decider=lambda *args, **kwargs: {"run": True, "reason": "test", "triggers": ["effect"]},
        simulate_events=lambda *args, **kwargs: simulated.append((args, kwargs)),
        select_cards=lambda *args, **kwargs: [SimpleNamespace(model_dump=lambda: {"scene": "旧城"})],
        style_builder=lambda **kwargs: {"tone": "紧张"},
        performance_enricher=lambda cards, guidance: [*cards, {"guidance": guidance["tone"]}],
    )

    assert simulated == []
    assert result.run_world_simulation is False
    assert result.world_events == []
    assert result.simulation_plan["world_update_deferred"] is True
    assert result.simulation_plan["world_update_reason"] == "test"
    assert result.simulation_plan["world_update_triggers"] == ["effect"]
    assert result.scene_cards == [{"scene": "旧城"}, {"guidance": "紧张"}]
    assert result.style_guidance == {"tone": "紧张"}
