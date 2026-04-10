from __future__ import annotations

from packages.story_core.models import AgentRuntimeEntry, StoryState


def _entry_attr(agent_name: str) -> str:
    mapping = {
        "CharacterAgent": "character_agent",
        "DirectorAgent": "director_agent",
        "WriterAgent": "writer_agent",
        "MemoryAgent": "memory_agent",
    }
    return mapping[agent_name]


def record_agent_runtime(
    story: StoryState,
    agent_name: str,
    mode: str,
    source: str,
    chapter_number: int,
    fallback_reason: str = "",
) -> None:
    entry = AgentRuntimeEntry(
        mode=mode,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        fallback_reason=fallback_reason,
        last_run_chapter=chapter_number,
    )
    setattr(story.agent_runtime, _entry_attr(agent_name), entry)
    event = f"{agent_name}: {source} at chapter {chapter_number}"
    if fallback_reason:
        event = f"{event} ({fallback_reason})"
    story.agent_runtime.recent_events.append(event)
    story.agent_runtime.recent_events = story.agent_runtime.recent_events[-8:]
