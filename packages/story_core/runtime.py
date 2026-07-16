from __future__ import annotations

from packages.story_core.models import StageRuntimeEntry, StoryState


def stage_runtime_label(stage: str) -> str:
    labels = {
        "planner": "规划阶段",
        "writer": "写作阶段",
        "memory": "记忆阶段",
    }
    return labels.get(stage, stage)


def record_stage_runtime(
    story: StoryState,
    stage: str,
    source: str,
    provider: str,
    model: str,
    chapter_number: int,
    fallback_reason: str = "",
) -> None:
    if stage not in {"planner", "writer", "memory"}:
        raise ValueError(f"unknown runtime stage: {stage}")
    entry = StageRuntimeEntry(
        source=source,  # type: ignore[arg-type]
        provider=provider,
        model=model,
        fallback_reason=fallback_reason,
        last_run_chapter=chapter_number,
    )
    setattr(story.agent_runtime, stage, entry)
    source_label = {
        "idle": "空闲",
        "llm": "模型",
        "fallback": "回退",
    }.get(source, source)
    event = f"{stage_runtime_label(stage)}：{source_label}，第 {chapter_number} 章"
    if fallback_reason:
        event = f"{event}（{fallback_reason}）"
    story.agent_runtime.recent_events.append(event)
    story.agent_runtime.recent_events = story.agent_runtime.recent_events[-8:]


def record_agent_runtime(*args, **kwargs) -> None:
    """Compatibility no-op for retired standalone agent runtime reporting."""
