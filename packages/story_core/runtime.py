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


def _agent_label(agent_name: str) -> str:
    labels = {
        "CharacterAgent": "角色代理",
        "DirectorAgent": "导演代理",
        "WriterAgent": "写作代理",
        "MemoryAgent": "记忆代理",
    }
    return labels.get(agent_name, agent_name)


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
    source_label = {
        "idle": "空闲",
        "rule-based": "规则",
        "llm": "模型",
        "fallback": "回退",
    }.get(source, source)
    event = f"{_agent_label(agent_name)}：{source_label}，第 {chapter_number} 章"
    if fallback_reason:
        event = f"{event}（{fallback_reason}）"
    story.agent_runtime.recent_events.append(event)
    story.agent_runtime.recent_events = story.agent_runtime.recent_events[-8:]
