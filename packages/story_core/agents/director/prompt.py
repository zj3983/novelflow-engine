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

from ..contracts import (
    DirectorArtifact,
    EntityRequirement,
    OutlineExecutionContract,
    SceneBeat,
)
from ...context.director_context import DirectorContext


def _parse_outline_chapter_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        try:
            number = int(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if number > 0 else None


def outline_chapter_number(entry: dict[str, Any]) -> int | None:
    number = _parse_outline_chapter_number(entry.get("number"))
    if number is not None:
        return number
    return _parse_outline_chapter_number(entry.get("chapter_number"))


def _outline_chapter_title(entry: dict[str, Any]) -> str:
    for key in ("title", "chapter_title"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def planned_chapter_title(context: DirectorContext) -> str:
    """Return the last valid title planned for the target chapter."""
    selected = ""
    for entry in context.nearby_outline:
        if not isinstance(entry, dict):
            continue
        if outline_chapter_number(entry) != context.chapter_number:
            continue
        title = _outline_chapter_title(entry)
        if title:
            selected = title
    return selected


def _outline_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _outline_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _outline_text_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item.strip()
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str) and item.strip()
    }


def build_outline_execution_contract(
    context: DirectorContext,
) -> OutlineExecutionContract | None:
    """Build the target chapter's contract from the trusted outline view.

    The last valid target entry wins, matching the title-lock behavior.  The
    runtime response is intentionally not involved: missing fields simply
    remain empty for old outlines.
    """

    selected: dict[str, Any] | None = None
    for entry in context.nearby_outline:
        if isinstance(entry, dict) and outline_chapter_number(entry) == context.chapter_number:
            selected = entry
    if selected is None:
        return None

    chapter_sop = selected.get("chapter_sop")
    if not isinstance(chapter_sop, dict):
        chapter_sop = {}
    return OutlineExecutionContract(
        chapter_number=context.chapter_number,
        core_conflict=_outline_text(selected.get("core_conflict"))
        or _outline_text(selected.get("obstacle")),
        gain=_outline_text(selected.get("gain")) or _outline_text(selected.get("payoff")),
        cost=_outline_text(selected.get("cost")) or _outline_text(selected.get("turn")),
        state_delta=_outline_text(selected.get("state_delta")),
        # ``chapter_sop.ending_hook`` is the formal chapter-contract field.
        # Top-level values remain legacy fallbacks for older rolling outlines.
        planned_hook=_outline_text(chapter_sop.get("ending_hook"))
        or _outline_text(selected.get("hook"))
        or _outline_text(selected.get("ending_hook")),
        opening_carry=_outline_text(chapter_sop.get("opening_carry")),
        mid_feedback=_outline_text(chapter_sop.get("mid_feedback")),
        planned_turn=_outline_text(chapter_sop.get("turn")),
        payoff_contract=_outline_text_map(selected.get("payoff_contract")),
        must_not_write=_outline_text_list(selected.get("must_not_write")),
    )


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
        if not isinstance(entry, dict):
            continue
        number = outline_chapter_number(entry)
        if number is None:
            continue
        title = _outline_chapter_title(entry)
        summary = _outline_text(entry.get("summary"))
        goal = _outline_text(entry.get("goal"))
        obstacle = _outline_text(entry.get("obstacle"))
        action = _outline_text(entry.get("action"))
        line = f"- 第{number}章 {title}：{summary}"
        detail = " · ".join(
            part for part in (goal, obstacle, action) if isinstance(part, str) and part.strip()
        )
        if detail:
            line = f"{line}（{detail}）"
        if number == context.chapter_number:
            target_lines.append(line)
        else:
            compact: list[str] = []
            state_delta = _outline_text(entry.get("state_delta"))
            opening_carry = _outline_text(entry.get("opening_carry"))
            chapter_sop = entry.get("chapter_sop")
            if isinstance(chapter_sop, dict):
                opening_carry = _outline_text(chapter_sop.get("opening_carry")) or opening_carry
            chapter_sop_ending_hook = ""
            if isinstance(chapter_sop, dict):
                chapter_sop_ending_hook = _outline_text(chapter_sop.get("ending_hook"))
            ending_hook = chapter_sop_ending_hook or _outline_text(entry.get("ending_hook"))
            hook = _outline_text(entry.get("hook"))
            for label, value in (
                ("状态变化", state_delta),
                ("承接", opening_carry),
                ("章末钩子", ending_hook or hook),
            ):
                if value:
                    compact.append(f"{label}：{value}")
            if compact:
                line += "｜" + "；".join(compact)
            boundary_lines.append(line)
    sections: list[str] = []
    if target_lines:
        target_contract = build_outline_execution_contract(context)
        target_section = [
            "## 本章细纲（正文内容必须展开为可执行场景计划，不得整段照抄）",
            *target_lines,
        ]
        if target_contract is not None:
            target_section.extend(
                [
                    "",
                    "## 本章上游执行合同（以此约束 Director 与 Writer）",
                    f"核心冲突：{target_contract.core_conflict or '（未提供）'}",
                    f"本章收益：{target_contract.gain or '（未提供）'}",
                    f"本章代价：{target_contract.cost or '（未提供）'}",
                    f"目标状态变化：{target_contract.state_delta or '（未提供）'}",
                    f"开场承接：{target_contract.opening_carry or '（未提供）'}",
                    f"中段反馈：{target_contract.mid_feedback or '（未提供）'}",
                    f"计划转折：{target_contract.planned_turn or '（未提供）'}",
                    f"计划章末钩子：{target_contract.planned_hook or '（未提供）'}",
                ]
            )
            if target_contract.payoff_contract:
                target_section.append(
                    "收益合同："
                    + "；".join(
                        f"{key}={value}"
                        for key, value in target_contract.payoff_contract.items()
                    )
                )
            if target_contract.must_not_write:
                target_section.append(
                    "禁止提前写：" + "；".join(target_contract.must_not_write)
                )
        sections.append("\n".join(target_section))
    if boundary_lines:
        sections.append("## 相邻章节边界\n" + "\n".join(boundary_lines))
    return "\n".join(sections)


def _render_previous_handoff(context: DirectorContext) -> str:
    if (
        not context.previous_chapter_summary
        and not context.previous_chapter_tail
        and not context.continuity_ledger
    ):
        return ""
    sections: list[str] = []
    if context.previous_chapter_summary:
        sections.append(f"## 上章总结\n{context.previous_chapter_summary}")
    if context.previous_chapter_tail:
        sections.append(f"## 上章实际收尾\n{context.previous_chapter_tail}")
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


def build_director_prompt(
    context: DirectorContext,
) -> str:
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
    if context.rewrite_guidance.strip():
        sections.append(
            "## 本次写作指导（必须落实到场景计划）\n"
            + context.rewrite_guidance.strip()
        )
    locked_title = planned_chapter_title(context)
    if locked_title:
        title_instruction = (
            "## 章节标题（chapter_title）\n"
            "JSON schema 仍需包含 chapter_title。"
            "本章细纲标题已经锁定，原样复制，不得重命名："
            f"{locked_title}"
        )
        output_instruction = (
            "输出 chapter_title 字段、2 至 5 个有因果结果的 scene_beats；"
            "chapter_title 只能复制上述锁定值。"
        )
    else:
        title_instruction = (
            "## 章节标题（chapter_title）\n"
            "给一句不超过 20 字的章节标题，不得把整段细纲当标题；"
            "标题应与 scene_beats 共同表达这一章的关键变化。"
        )
        output_instruction = (
            "输出简短 chapter_title、2 至 5 个有因果结果的 scene_beats；"
            "不得把整段细纲作为 chapter_goal 或标题。"
        )
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
            "每项都要填写 notes，用一两句写清本章身份、用途、已知效果或场景作用；不要只给名称。",
            "",
            title_instruction,
            output_instruction,
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


__all__ = [
    "build_outline_execution_contract",
    "build_director_prompt",
    "outline_chapter_number",
    "parse_director_response",
    "planned_chapter_title",
]
