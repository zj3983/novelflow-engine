"""Stable stage vocabulary for chapter generation and workbench tracing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from packages.story_core.workflow_steps import build_workflow_step_event


_STEP_PIPELINE_STAGE = {
    "read_outline": "context",
    "read_characters": "context",
    "read_world_state": "context",
    "director_plan": "plan",
    "prepare_scenes": "simulation",
    "write_body": "writing",
    "review_body": "quality_gate",
    "write_memory": "candidate_output",
    "candidate_output": "candidate_output",
}

BundleT = TypeVar("BundleT")


class ChapterPipeline:
    """Compatibility pipeline around the existing bundle generator.

    Stage implementations can move behind this facade one at a time while
    callers keep receiving the same chapter bundle.
    """

    def run(self, story: Any, *, generate_bundle: Callable[[Any], BundleT]) -> BundleT:
        bundle = generate_bundle(story)
        simulation_plan = getattr(bundle, "simulation_plan", {})
        ran_simulation = bool(
            isinstance(simulation_plan, dict) and simulation_plan.get("world_simulation_ran")
        )
        setattr(
            bundle,
            "pipeline_stages",
            chapter_pipeline_stage_order(run_world_simulation=ran_simulation),
        )
        return bundle


def chapter_pipeline_stage_order(*, run_world_simulation: bool) -> list[str]:
    stages = ["context", "plan"]
    if run_world_simulation:
        stages.append("simulation")
    return [*stages, "writing", "quality_gate", "candidate_output"]


def build_chapter_pipeline_event(
    step_id: str,
    label: str,
    *,
    status: str = "running",
    source: str = "orchestrator",
    used_modules: list[str] | None = None,
    reads: list[str] | None = None,
    outputs: dict[str, Any] | None = None,
    provider: str = "",
    model: str = "",
) -> dict[str, object]:
    event = build_workflow_step_event(
        step_id,
        label,
        status=status,
        source=source,
        used_modules=used_modules,
        reads=reads,
        outputs=outputs,
    )
    artifact = event["artifact"]
    workflow_step = artifact["workflow_step"]
    workflow_step["pipeline_stage"] = _STEP_PIPELINE_STAGE.get(step_id, step_id)
    model_call = {key: value for key, value in {"provider": provider, "model": model}.items() if value}
    if model_call:
        artifact["model_call"] = model_call
    return event
