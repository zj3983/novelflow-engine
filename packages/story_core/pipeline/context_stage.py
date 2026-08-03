"""Deterministic chapter-context assembly for the generation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.story_core.agent_base import compact_text
from packages.story_core.context.context_builder import build_context_package
from packages.story_core.context.context_package import ContextPackage
from packages.story_core.models import StoryState
from packages.story_core.pipeline.chapter_pipeline import build_chapter_pipeline_event


@dataclass(frozen=True)
class PreparedChapterContext:
    chapter_number: int
    director_context: dict[str, Any]
    planning_character_cards: dict[str, Any]
    outline_snapshot: str
    world_context: dict[str, Any]
    context_package: ContextPackage
    outline_reads: list[str]
    character_names: list[str]
    outline_context_keys: list[str]
    world_sections: list[str]
    world_fact_count: int
    ledger_sections: list[str]


def planning_character_names(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    names: list[str] = []
    cards = payload.get("cards")
    if isinstance(cards, list):
        for card in cards:
            identity = card.get("identity") if isinstance(card, dict) else None
            name = str(identity.get("name") or "").strip() if isinstance(identity, dict) else ""
            if name and name not in names:
                names.append(name)
    if names:
        return names
    envelope_keys = {"selection", "requested_names", "cards"}
    direct_names = [str(name).strip() for name in payload if name not in envelope_keys]
    if direct_names:
        return sorted(name for name in direct_names if name)
    requested = payload.get("requested_names")
    if isinstance(requested, list):
        return [str(name).strip() for name in requested if str(name).strip()]
    return []


def _dump_recent(items: list[Any]) -> list[Any]:
    return [item.model_dump() if hasattr(item, "model_dump") else item for item in items[-2:]]


def prepare_chapter_context(
    story: StoryState,
    chapter_number: int,
    director_context: dict[str, Any],
) -> PreparedChapterContext:
    character_cards = (
        director_context.get("character_cards")
        if isinstance(director_context.get("character_cards"), dict)
        else {}
    )
    world_context = story.world_context if isinstance(story.world_context, dict) else {}
    outline_reads = ["总纲", f"第{chapter_number}章细纲"]
    if chapter_number > 1:
        outline_reads.append("上一章摘要与结尾")
    context_package = build_context_package(
        {
            "outline": {"outline": story.outline, "outline_context": story.outline_context},
            "adjacent_chapters": {
                "chapter_summaries": _dump_recent(story.chapter_summaries),
                "timeline": _dump_recent(story.timeline),
            },
            "characters": character_cards,
            "relationships": director_context.get("relationship_graph", {}),
            "foreshadowings": director_context.get("foreshadowing", []),
            "world": world_context,
            "genre": {"genre": story.genre, "style": story.style},
            "long_term_memory": director_context.get("memory_index", []),
            "author_request": story.author_constraints,
        },
        chapter_number=chapter_number,
    )
    return PreparedChapterContext(
        chapter_number=chapter_number,
        director_context=director_context,
        planning_character_cards=character_cards,
        outline_snapshot=compact_text(story.outline, 220),
        world_context=world_context,
        context_package=context_package,
        outline_reads=outline_reads,
        character_names=planning_character_names(character_cards),
        outline_context_keys=sorted((story.outline_context or {}).keys()),
        world_sections=sorted(world_context.keys()),
        world_fact_count=len(story.world_facts),
        ledger_sections=sorted((story.progression_ledger or {}).keys()),
    )


def build_context_stage_events(prepared: PreparedChapterContext) -> list[dict[str, object]]:
    return [
        build_chapter_pipeline_event(
            "read_outline",
            "读取大纲",
            status="done",
            source="context_loader",
            used_modules=["outline_agent", "memory_retrieval"],
            reads=prepared.outline_reads,
            outputs={
                "outline_preview": prepared.outline_snapshot,
                "chapter_context_keys": prepared.outline_context_keys,
            },
        ),
        build_chapter_pipeline_event(
            "read_characters",
            "读取角色卡",
            status="done",
            source="context_loader",
            used_modules=["character_agent"],
            reads=[f"角色卡：{name}" for name in prepared.character_names] or ["本章没有匹配到角色卡"],
            outputs={
                "character_count": len(prepared.character_names),
                "characters": prepared.character_names,
            },
        ),
        build_chapter_pipeline_event(
            "read_world_state",
            "读取世界观与连续性",
            status="done",
            source="context_loader",
            used_modules=["world_context", "continuity_state", "progression_ledger"],
            reads=["本章相关世界规则", "当前任务与资源账本", "已确认事实", "未解决线索"],
            outputs={
                "world_sections": prepared.world_sections,
                "world_fact_count": prepared.world_fact_count,
                "ledger_sections": prepared.ledger_sections,
                "context_snapshot_id": prepared.context_package.snapshot_id,
                "excluded_sections": prepared.context_package.excluded_sections,
            },
        ),
    ]
