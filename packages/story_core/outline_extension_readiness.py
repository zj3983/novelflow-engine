"""Local-only prerequisite checks for extending the detailed outline."""

from __future__ import annotations

from typing import Any

from packages.story_core.elastic_outline import outline_window_status


def _text(value: Any) -> str:
    return str(value or "").strip()


def _issue(code: str, message: str, section: str, *, names: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "section": section,
    }
    if names:
        payload["names"] = names
    return payload


def _is_protagonist(card: Any) -> bool:
    if not isinstance(card, dict):
        return False
    role = _text(card.get("character_tier") or card.get("role")).lower()
    return role in {"protagonist", "main", "lead", "主角"}


def _world_context_ready(project: dict[str, Any], state: dict[str, Any]) -> bool:
    blueprint = project.get("world_blueprint")
    if not isinstance(blueprint, dict):
        blueprint = {}
    premise = _text(
        blueprint.get("premise")
        or project.get("world_summary")
        or state.get("outline")
    )
    rules = blueprint.get("world_rules")
    has_rules = isinstance(rules, list) and any(_text(item) for item in rules)
    power = blueprint.get("power_system")
    has_power = (
        isinstance(power, list) and any(_text(item) for item in power)
    ) or bool(
        isinstance(blueprint.get("power_system_spec"), dict)
        and blueprint["power_system_spec"]
    )
    return bool(premise and (has_rules or has_power))


def _arc_covers(arc: Any, chapter_number: int) -> bool:
    if not isinstance(arc, dict):
        return False
    start = arc.get("start_chapter")
    end = arc.get("end_chapter")
    return (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and start <= chapter_number <= end
    )


def _arc_is_actionable(arc: dict[str, Any]) -> bool:
    return all(_text(arc.get(field)) for field in ("goal", "obstacle", "payoff"))


def _card_is_complete(card: dict[str, Any]) -> bool:
    identity = card.get("identity_profile")
    drive = card.get("story_drive")
    if not isinstance(identity, dict) or not isinstance(drive, dict):
        return False
    return all(
        _text(value)
        for value in (
            identity.get("origin"),
            identity.get("current_identity"),
            drive.get("immediate_goal"),
            drive.get("failure_stakes"),
        )
    )


def inspect_outline_extension_readiness(
    *,
    project: dict[str, Any],
    state: dict[str, Any],
    outline: dict[str, Any],
) -> dict[str, Any]:
    """Return blockers and warnings without invoking a model or mutating files."""

    current_chapter = int(state.get("current_chapter") or 0)
    window = outline_window_status(outline, current_chapter=current_chapter)
    target_numbers = list(window["next_chapter_numbers"])
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    overall = outline.get("overall") if isinstance(outline.get("overall"), dict) else {}
    core_fields = (
        "story",
        "protagonist_goal",
        "main_conflict",
        "growth_path",
        "ending_direction",
    )
    if any(not _text(overall.get(field)) for field in core_fields):
        blockers.append(
            _issue(
                "overall_core_required",
                "总纲核心信息不完整，请先补全故事、主角目标、核心冲突、成长路线和结局方向。",
                "overall",
            )
        )

    arcs = outline.get("arcs") if isinstance(outline.get("arcs"), list) else []
    uncovered = [
        number
        for number in target_numbers
        if not any(
            _arc_covers(arc, number) and _arc_is_actionable(arc)
            for arc in arcs
            if isinstance(arc, dict)
        )
    ]
    if uncovered:
        blockers.append(
            _issue(
                "stage_arc_required",
                f"阶段大纲没有完整覆盖第{uncovered[0]}至第{uncovered[-1]}章，请先补全阶段目标、阻力和兑现。",
                "arcs",
            )
        )

    cards = [
        item
        for item in [
            *(project.get("character_profiles") if isinstance(project.get("character_profiles"), list) else []),
            *(state.get("characters") if isinstance(state.get("characters"), list) else []),
        ]
        if isinstance(item, dict)
    ]
    if not any(_is_protagonist(card) for card in cards):
        blockers.append(
            _issue(
                "protagonist_card_required",
                "缺少主角角色卡，请先补全主角身份、目标和当前状态。",
                "characters",
            )
        )

    if not _world_context_ready(project, state):
        blockers.append(
            _issue(
                "world_context_required",
                "世界观缺少背景和可执行规则，请先补全世界背景以及世界规则或力量体系。",
                "world",
            )
        )

    incomplete_names = sorted(
        {
            _text(card.get("name"))
            for card in cards
            if _text(card.get("name"))
            and not _is_protagonist(card)
            and not _card_is_complete(card)
        }
    )
    if incomplete_names:
        warnings.append(
            _issue(
                "supporting_cards_incomplete",
                "部分已有角色卡缺少来历、当前身份、眼前目标或失败代价。",
                "characters",
                names=incomplete_names[:12],
            )
        )

    summaries = state.get("chapter_summaries")
    has_current_summary = isinstance(summaries, list) and any(
        isinstance(item, dict)
        and item.get("chapter_number") == current_chapter
        and _text(item.get("summary"))
        for item in summaries
    )
    if current_chapter > 0 and not has_current_summary:
        warnings.append(
            _issue(
                "recent_summary_missing",
                f"第{current_chapter}章缺少有效摘要，后续细纲可能接不准上一章。",
                "chapters",
            )
        )

    return {
        "schema_version": "outline-extension-readiness/v1",
        "ready": not blockers,
        "current_chapter": current_chapter,
        "next_chapter_numbers": target_numbers,
        "blockers": blockers,
        "warnings": warnings,
    }
