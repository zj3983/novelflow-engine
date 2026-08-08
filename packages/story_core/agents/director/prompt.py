"""Director prompt assembly for the modular agent.

The director prompt is built only from the typed
``DirectorContext`` (Task 3) — no project root, no orchestrator
state, no legacy ``StoryState`` reach-around. The renderer
covers the eight questions every chapter plan must answer:
chapter goal, opening state, ordered scene beats, cause and
effect, character decisions, information boundaries, ending
state, hook, and entity requirements.
"""

from __future__ import annotations

from typing import Any

from ..contracts import DirectorArtifact, EntityRequirement, SceneBeat
from ...context.director_context import DirectorContext


def _render_volume(context: DirectorContext) -> str:
    if not context.volume:
        return ""
    return (
        f"## 当前卷\n"
        f"卷 {context.volume.get('id', '?')} · {context.volume.get('title', '?')}\n"
        f"章节范围：{context.volume.get('chapter_range', [])}\n"
        f"卷摘要：{context.volume.get('summary', '')}"
    )


def _render_nearby_outline(context: DirectorContext) -> str:
    if not context.nearby_outline:
        return ""
    boundary_lines: list[str] = []
    target_lines: list[str] = []
    for entry in context.nearby_outline:
        number = entry.get("number", "?")
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        goal = entry.get("goal", "")
        obstacle = entry.get("obstacle", "")
        action = entry.get("action", "")
        line = f"- 第{number}章 {title}：{summary}"
        detail = " · ".join(
            part for part in (goal, obstacle, action) if isinstance(part, str) and part.strip()
        )
        if detail:
            line = f"{line}（{detail}）"
        if int(number or 0) == int(context.chapter_number or 0):
            target_lines.append(line)
        else:
            boundary_lines.append(line)
    sections: list[str] = []
    if target_lines:
        sections.append(
            "## 本章细纲（必须展开为可执行场景计划，不得照抄为标题或正文）\n"
            + "\n".join(target_lines)
        )
    if boundary_lines:
        sections.append("## 相邻章节边界\n" + "\n".join(boundary_lines))
    return "\n".join(sections)


def _render_previous_handoff(context: DirectorContext) -> str:
    if not context.previous_chapter_summary and not context.continuity_ledger:
        return ""
    sections: list[str] = []
    if context.previous_chapter_summary:
        sections.append(f"## 上章总结\n{context.previous_chapter_summary}")
    if context.continuity_ledger:
        facts = "\n".join(
            f"- {fact.get('subject', '?')} · {fact.get('field', '?')}：{fact.get('value', '?')}"
            for fact in context.continuity_ledger
        )
        sections.append(f"## 连续性事实\n{facts}")
    return "\n".join(sections)


def _render_foreshadowing(context: DirectorContext) -> str:
    if not context.foreshadowing:
        return ""
    items = "\n".join(
        f"- {item.get('text', '?')}"
        + (f"（埋设于第{item.get('planted_chapter')}章）" if item.get("planted_chapter") else "")
        for item in context.foreshadowing
    )
    return f"## 待兑现伏笔\n{items}"


def _render_character_cards(context: DirectorContext) -> str:
    if not context.character_cards:
        return ""
    lines = ["## 候选角色（仅活动角色）"]
    for card in context.character_cards:
        name = card.get("name", "未命名")
        role = card.get("role", "")
        location = card.get("location", "")
        state = card.get("current_state", "")
        lines.append(f"- {name}（{role or '?'}）· 位置：{location or '?'} · 状态：{state or '?'}")
    return "\n".join(lines)


def build_director_prompt(context: DirectorContext) -> str:
    """Render the director's request prompt from a context view.

    The output covers the eight questions every chapter plan
    must answer: chapter goal, opening state, ordered scene
    beats, cause and effect, character decisions, information
    boundaries, ending state, hook, and entity requirements.
    """
    sections: list[str] = [
        "你是小说导演。只能返回 JSON；不要输出任何额外文字。",
        "",
        _render_volume(context),
    ]
    nearby = _render_nearby_outline(context)
    if nearby:
        sections.append(nearby)
    handoff = _render_previous_handoff(context)
    if handoff:
        sections.append(handoff)
    foreshadowing = _render_foreshadowing(context)
    if foreshadowing:
        sections.append(foreshadowing)
    characters = _render_character_cards(context)
    if characters:
        sections.append(characters)
    sections.extend(
        [
            "## 必须回答的 8 个问题",
            "1. 本章目标（chapter_goal）",
            "2. 开场状态（opening_state）",
            "3. 顺序的场景节拍（scene_beats），每条包含 order/location/action/result",
            "4. 因果关系（scene_beats 之间的 result 链）",
            "5. 关键角色在每个节拍中的决定（action 字段）",
            "6. 信息边界（角色之间不能相互知道的事，写入 scene 描述或备注）",
            "7. 收尾状态（ending_state）",
            "8. 章末钩子（hook）",
            "",
            "## 实体要求（entity_requirements）",
            "列出本章新出现或需要卡片支持的角色/物品/装备/技能/地点/组织/任务/怪物，"
            "kind 仅限：character / item / equipment / technique / location / organization / quest / monster / rule。",
            "",
            "## 章节标题（chapter_title）",
            "给一句不超过 20 字的章节标题，"
            "不得把整段细纲当标题；标题应与 scene_beats 共同表达这一章的关键变化。",
            "输出简短 chapter_title、2 至 5 个有因果结果的 scene_beats；"
            "不得把整段细纲作为 chapter_goal 或标题。",
        ]
    )
    return "\n\n".join(section for section in sections if section)


def parse_director_response(payload: Any) -> DirectorArtifact:
    """Parse a structured director response into a ``DirectorArtifact``."""
    if not isinstance(payload, dict):
        raise ValueError("director_response_not_dict")
    chapter_number = int(payload.get("chapter_number", 0))
    if chapter_number < 1:
        raise ValueError(f"director_response_missing_chapter_number: {payload!r}")
    beats_in = payload.get("scene_beats") or []
    if not isinstance(beats_in, list) or not beats_in:
        raise ValueError("director_response_missing_scene_beats")
    beats: list[SceneBeat] = []
    for index, beat in enumerate(beats_in):
        if not isinstance(beat, dict):
            continue
        beats.append(
            SceneBeat(
                order=int(beat.get("order", index + 1)),
                location=str(beat.get("location") or ""),
                action=str(beat.get("action") or ""),
                result=str(beat.get("result") or ""),
            )
        )
    requirements_in = payload.get("entity_requirements") or []
    if not isinstance(requirements_in, list):
        requirements_in = []
    requirements: list[EntityRequirement] = []
    for requirement in requirements_in:
        if not isinstance(requirement, dict):
            continue
        kind = str(requirement.get("kind") or "")
        if kind not in {
            "character",
            "item",
            "equipment",
            "technique",
            "location",
            "organization",
            "quest",
            "monster",
            "rule",
        }:
            continue
        requirements.append(
            EntityRequirement(
                kind=kind,  # type: ignore[arg-type]
                name=str(requirement.get("name") or ""),
                importance=int(requirement.get("importance", 5) or 5),
                inline_minor=bool(requirement.get("inline_minor", False)),
                notes=str(requirement.get("notes") or ""),
            )
        )
    return DirectorArtifact(
        chapter_number=chapter_number,
        chapter_title=str(payload.get("chapter_title") or ""),
        chapter_goal=str(payload.get("chapter_goal") or ""),
        opening_state=str(payload.get("opening_state") or ""),
        scene_beats=beats,
        ending_state=str(payload.get("ending_state") or ""),
        hook=str(payload.get("hook") or ""),
        entity_requirements=requirements,
    )


__all__ = ["build_director_prompt", "parse_director_response"]
