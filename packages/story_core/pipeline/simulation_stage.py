"""Director-plan projection and deterministic writing-context preparation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.genre_stages.base import SceneCardContext
from packages.story_core.models import StoryState
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.style_coach import build_style_guidance, enrich_performance_cards
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events
from packages.story_core.world_simulation_gate import world_simulation_decision


@dataclass(frozen=True)
class SimulationStageResult:
    chapter_seed: dict[str, Any]
    simulation_plan: dict[str, Any]
    world_events: list[dict[str, Any]]
    scene_cards: list[dict[str, Any]]
    style_guidance: dict[str, Any]
    run_world_simulation: bool
    decision: dict[str, Any]


def prepare_simulation_stage(
    story: StoryState,
    chapter_number: int,
    *,
    event_plan: dict[str, Any],
    memory_constraints: dict[str, Any],
    planning_profile: Any,
    attach_trope_contract: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None],
    simulation_decider: Callable[..., dict[str, Any]] = world_simulation_decision,
    simulate_events: Callable[..., list[Any]] = simulate_world_events,
    select_cards: Callable[..., list[Any]] = select_scene_cards,
    style_builder: Callable[..., dict[str, Any]] = build_style_guidance,
    performance_enricher: Callable[[list[dict[str, Any]], dict[str, Any]], list[dict[str, Any]]] = enrich_performance_cards,
) -> SimulationStageResult:
    chapter_seed = build_chapter_seed(story, chapter_number)
    simulation_plan = build_chapter_simulation_plan(
        story,
        chapter_number,
        event_plan=event_plan,
        memory_constraints=memory_constraints,
        chapter_seed=chapter_seed,
        plot_authority="director",
    ).model_dump()
    simulation_plan = attach_trope_contract(simulation_plan, chapter_seed) or {}
    continuity_interface = (
        story.outline_context.get("continuity_interface")
        if isinstance(story.outline_context, dict)
        and isinstance(story.outline_context.get("continuity_interface"), dict)
        else {}
    )
    if continuity_interface:
        simulation_plan["continuity_interface"] = deepcopy(continuity_interface)

    decision = simulation_decider(
        story,
        chapter_number,
        event_plan=event_plan,
        chapter_seed=chapter_seed,
    )
    world_update_required = bool(decision.get("run"))
    run_world_simulation = False
    world_events: list[dict[str, Any]] = []
    simulation_plan["world_simulation_ran"] = False
    simulation_plan["world_simulation_reason"] = decision.get("reason", "")
    simulation_plan["world_simulation_triggers"] = decision.get("triggers", [])
    simulation_plan["world_update_deferred"] = world_update_required
    simulation_plan["world_update_reason"] = decision.get("reason", "")
    simulation_plan["world_update_triggers"] = decision.get("triggers", [])

    scene_cards = [
        card.model_dump()
        for card in select_cards(
            [],
            chapter_seed=chapter_seed,
            simulation_plan=simulation_plan,
        )
    ]
    scene_cards = planning_profile.prepare_scene_cards(
        context=SceneCardContext(
            story=story,
            chapter_number=chapter_number,
            scene_cards=scene_cards,
            world_facts=[*story.world_facts, *story.author_constraints],
        )
    )
    style_guidance = style_builder(
        genre=story.genre,
        style=story.style,
        chapter_number=chapter_number,
        world_events=world_events,
        scene_cards=scene_cards,
    )
    scene_cards = performance_enricher(scene_cards, style_guidance)
    simulation_plan = {**simulation_plan, "style_guidance": style_guidance}
    return SimulationStageResult(
        chapter_seed=chapter_seed,
        simulation_plan=simulation_plan,
        world_events=world_events,
        scene_cards=scene_cards,
        style_guidance=style_guidance,
        run_world_simulation=run_world_simulation,
        decision=decision,
    )
