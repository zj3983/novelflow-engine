from __future__ import annotations

import json
import hashlib
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from packages.story_core.persistence.snapshot_store import SnapshotStore
from packages.story_core.volume_outline import (
    MIN_VOLUME_CHAPTERS,
    STORY_NODE_INTERVAL,
    validate_volume_structure,
)


_TEXT_FIELDS = (
    "title",
    "pacing_stage_id",
    "goal",
    "obstacle",
    "payoff",
    "emotional_curve",
    "hook_plan",
    "irreversible_change",
    "end_state",
    "stage_antagonist",
    "game_line_payoff",
    "reality_line_payoff",
    "core_loop",
    "midpoint_turn",
    "climax",
    "next_arc_entry",
)
_LIST_FIELDS = (
    "key_results",
    "long_term_antagonist_traces",
    "active_long_term_lines",
    "escalations",
    "relationship_changes",
    "foreshadowing_in",
    "foreshadowing_out",
)
DEFAULT_BACKUP_ROOT = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "migration-backups"
    / "volume-outline"
)


def _read_json(path: Path, default: Any) -> Any:
    return SnapshotStore().read_json(path, default)


def _read_outline_with_hash(path: Path) -> tuple[Any, str]:
    content = path.read_bytes()
    return (
        json.loads(content.decode("utf-8-sig")),
        hashlib.sha256(content).hexdigest(),
    )


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _ordered_unique(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _merge_text(arcs: list[dict[str, Any]], field: str) -> str:
    return "；".join(_ordered_unique(arc.get(field) for arc in arcs))


def _merge_list(arcs: list[dict[str, Any]], field: str) -> list[str]:
    return _ordered_unique(
        item
        for arc in arcs
        for item in (
            arc.get(field) if isinstance(arc.get(field), list) else []
        )
    )


def _volume_range(arc: Mapping[str, Any]) -> list[int]:
    return [int(arc["start_chapter"]), int(arc["end_chapter"])]


def _overlap_count(arcs: list[dict[str, Any]]) -> int:
    ordered = sorted(
        arcs,
        key=lambda arc: (
            int(arc.get("start_chapter") or 0),
            int(arc.get("end_chapter") or 0),
            _clean_text(arc.get("id")),
        ),
    )
    return sum(
        int(current.get("start_chapter") or 0)
        <= int(previous.get("end_chapter") or 0)
        for previous, current in zip(ordered, ordered[1:])
    )


def _validate_legacy_ranges(arcs: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if not arcs:
        return ["volume_missing"]
    first_start = int(arcs[0].get("start_chapter") or 0)
    if first_start != 1:
        blockers.append(f"volume_gap:1:{max(1, first_start - 1)}")
    covered_end = 0
    for arc in arcs:
        start = int(arc.get("start_chapter") or 0)
        end = int(arc.get("end_chapter") or 0)
        if start < 1 or end < start:
            blockers.append(f"invalid_volume_range:{_clean_text(arc.get('id'))}")
            continue
        if start > covered_end + 1:
            blockers.append(f"volume_gap:{covered_end + 1}:{start - 1}")
        covered_end = max(covered_end, end)
    return _ordered_unique(blockers)


def _select_groups(arcs: list[dict[str, Any]], final_end: int) -> list[list[dict[str, Any]]]:
    """Merge whole legacy arcs; every new cut is an existing arc end.

    Chapter summaries never influence these boundaries. They are consumed
    later only to populate story-node descriptions inside the selected range.
    """
    groups: list[list[dict[str, Any]]] = []
    index = 0
    covered_end = 0
    while index < len(arcs):
        group: list[dict[str, Any]] = []
        group_start = covered_end + 1
        group_end = covered_end
        while index < len(arcs):
            arc = arcs[index]
            group.append(arc)
            group_end = max(group_end, int(arc["end_chapter"]))
            index += 1
            if group_end - group_start + 1 < MIN_VOLUME_CHAPTERS:
                continue
            if (
                index < len(arcs)
                and int(arcs[index]["start_chapter"]) <= group_end
            ):
                continue
            break
        groups.append(group)
        covered_end = group_end
    return groups


def _summary_index(state: Mapping[str, Any]) -> dict[int, str]:
    summaries: dict[int, str] = {}
    values = state.get("chapter_summaries")
    if not isinstance(values, list):
        return summaries
    for item in values:
        if not isinstance(item, Mapping):
            continue
        try:
            number = int(item.get("chapter_number") or 0)
        except (TypeError, ValueError):
            continue
        text = _clean_text(item.get("summary") or item.get("chapter_title"))
        if number > 0 and text and number not in summaries:
            summaries[number] = text
    return summaries


def _chapter_detail_index(outline: Mapping[str, Any]) -> dict[int, str]:
    details: dict[int, str] = {}
    chapters = outline.get("chapters")
    if not isinstance(chapters, list):
        return details
    for item in chapters:
        if not isinstance(item, Mapping):
            continue
        try:
            number = int(item.get("chapter_number") or 0)
        except (TypeError, ValueError):
            continue
        text = _clean_text(
            item.get("payoff")
            or item.get("title")
            or item.get("ending_hook")
        )
        if number > 0 and text and number not in details:
            details[number] = text
    return details


def _node_text(
    summaries: Mapping[int, str],
    details: Mapping[int, str],
    number: int,
    fallback: str,
) -> str:
    return summaries.get(number) or details.get(number) or fallback


def _story_nodes(
    start: int,
    end: int,
    *,
    summaries: Mapping[int, str],
    details: Mapping[int, str],
    fallback_arc: Mapping[str, Any],
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    node_start = start
    while node_start <= end:
        node_end = min(end, node_start + STORY_NODE_INTERVAL - 1)
        midpoint = node_start + (node_end - node_start) // 2
        next_chapter = min(end, node_end + 1)
        fallback_goal = _clean_text(fallback_arc.get("goal")) or f"推进第{node_start}-{node_end}章目标"
        fallback_pressure = _clean_text(fallback_arc.get("obstacle")) or fallback_goal
        fallback_turn = _clean_text(fallback_arc.get("midpoint_turn")) or fallback_pressure
        fallback_payoff = _clean_text(fallback_arc.get("payoff")) or fallback_goal
        fallback_next = _clean_text(fallback_arc.get("next_arc_entry")) or fallback_payoff
        nodes.append(
            {
                "start_chapter": node_start,
                "end_chapter": node_end,
                "objective": _node_text(summaries, details, node_start, fallback_goal),
                "pressure": _node_text(summaries, details, midpoint, fallback_pressure),
                "turn": _node_text(summaries, details, min(node_end, midpoint + 1), fallback_turn),
                "payoff": _node_text(summaries, details, node_end, fallback_payoff),
                "next_effect": _node_text(summaries, details, next_chapter, fallback_next),
            }
        )
        node_start = node_end + 1
    return nodes


def _merge_group(
    group: list[dict[str, Any]],
    *,
    start: int,
    end: int,
    index: int,
    is_final: bool,
    summaries: Mapping[int, str],
    details: Mapping[int, str],
) -> dict[str, Any]:
    first = deepcopy(group[0])
    first["id"] = _clean_text(first.get("id")) or f"volume-{index}"
    first["start_chapter"] = start
    first["end_chapter"] = end
    first["is_final_arc"] = is_final
    first["trope_id"] = next(
        (_clean_text(arc.get("trope_id")) for arc in group if _clean_text(arc.get("trope_id"))),
        None,
    )
    first["extension_gate"] = deepcopy(
        next(
            (arc.get("extension_gate") for arc in reversed(group) if isinstance(arc.get("extension_gate"), Mapping)),
            {},
        )
    )
    for field in _TEXT_FIELDS:
        first[field] = _merge_text(group, field)
    for field in _LIST_FIELDS:
        first[field] = _merge_list(group, field)
    first["story_nodes"] = _story_nodes(
        start,
        end,
        summaries=summaries,
        details=details,
        fallback_arc=first,
    )
    return first


def _migrated_outline(
    outline: Mapping[str, Any],
    state: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    raw_arcs = outline.get("arcs")
    if not isinstance(raw_arcs, list):
        return deepcopy(dict(outline)), ["volume_missing"]
    invalid_entries = [
        f"invalid_volume_entry:{index}"
        for index, arc in enumerate(raw_arcs)
        if not isinstance(arc, Mapping)
    ]
    if invalid_entries:
        return deepcopy(dict(outline)), invalid_entries
    arcs = [deepcopy(dict(arc)) for arc in raw_arcs]
    arcs.sort(
        key=lambda arc: (
            int(arc.get("start_chapter") or 0),
            int(arc.get("end_chapter") or 0),
            _clean_text(arc.get("id")),
        )
    )
    blockers = _validate_legacy_ranges(arcs)
    if blockers:
        return deepcopy(dict(outline)), blockers

    final_end = max(int(arc["end_chapter"]) for arc in arcs)
    overall = outline.get("overall")
    if not isinstance(overall, Mapping):
        return deepcopy(dict(outline)), ["invalid_core_ending_chapter"]
    configured_end = overall.get("core_ending_chapter")
    if (
        not isinstance(configured_end, int)
        or isinstance(configured_end, bool)
        or configured_end < 1
    ):
        return deepcopy(dict(outline)), ["invalid_core_ending_chapter"]
    if configured_end != final_end:
        return (
            deepcopy(dict(outline)),
            [f"core_ending_mismatch:{configured_end}:{final_end}"],
        )

    groups = _select_groups(arcs, final_end)
    summaries = _summary_index(state)
    details = _chapter_detail_index(outline)
    migrated_arcs: list[dict[str, Any]] = []
    start = 1
    for index, group in enumerate(groups, start=1):
        end = max(int(arc["end_chapter"]) for arc in group)
        if index == len(groups):
            end = final_end
        migrated_arcs.append(
            _merge_group(
                group,
                start=start,
                end=end,
                index=index,
                is_final=index == len(groups),
                summaries=summaries,
                details=details,
            )
        )
        start = end + 1

    migrated = deepcopy(dict(outline))
    migrated["arcs"] = migrated_arcs
    migrated_overall = migrated.get("overall")
    if not isinstance(migrated_overall, dict):
        migrated_overall = {}
        migrated["overall"] = migrated_overall
    migrated_overall["core_ending_chapter"] = final_end
    migrated_overall["planned_arc_count"] = len(migrated_arcs)
    validate_volume_structure(migrated_arcs, core_ending_chapter=final_end)
    return migrated, []


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def migrate_project_volume_outline(
    project_root: str | Path,
    *,
    apply: bool = False,
    timestamp: str | None = None,
    backup_root: str | Path = DEFAULT_BACKUP_ROOT,
    expected_outline_hash: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    outline_path = root / ".webnovel" / "outline.json"
    state_path = root / ".webnovel" / "state.json"
    outline, outline_hash = _read_outline_with_hash(outline_path)
    state = _read_json(state_path, {})
    if not isinstance(outline, Mapping):
        outline = {}
    if not isinstance(state, Mapping):
        state = {}
    raw_old_arcs = outline.get("arcs", [])
    old_arcs = (
        [dict(arc) for arc in raw_old_arcs if isinstance(arc, Mapping)]
        if isinstance(raw_old_arcs, list)
        else []
    )
    migrated, blockers = _migrated_outline(outline, state)
    new_arcs = [
        dict(arc)
        for arc in migrated.get("arcs", [])
        if isinstance(arc, Mapping)
    ]
    changed = not blockers and dict(outline) != migrated
    status = (
        "skipped"
        if blockers == ["volume_missing"]
        else "blocked"
        if blockers
        else "pending"
        if changed
        else "unchanged"
    )
    report: dict[str, Any] = {
        "project_id": root.name,
        "project_root": str(root),
        "status": status,
        "old_volume_ranges": [_volume_range(arc) for arc in old_arcs],
        "new_volume_ranges": [_volume_range(arc) for arc in new_arcs],
        "overlap_count_before": _overlap_count(old_arcs),
        "overlap_count_after": _overlap_count(new_arcs),
        "blockers": blockers,
        "changed_files": [".webnovel/outline.json"] if changed else [],
        "backup_path": None,
        "outline_hash": outline_hash,
        "boundary_policy": "legacy_arc_ends_only",
        "summary_policy": "story_nodes_only",
        "legacy_boundary_ends": sorted(
            {int(arc["end_chapter"]) for arc in old_arcs}
        ),
    }
    if expected_outline_hash is not None and outline_hash != expected_outline_hash:
        report["status"] = "blocked"
        report["blockers"] = ["concurrent_outline_change"]
        report["changed_files"] = []
        return report
    if not apply or blockers or not changed:
        return report

    if _file_hash(outline_path) != outline_hash:
        report["status"] = "blocked"
        report["blockers"] = ["concurrent_outline_change"]
        report["changed_files"] = []
        return report
    stamp = timestamp or _timestamp()
    backup = (
        Path(backup_root).resolve()
        / stamp
        / root.name
        / ".webnovel"
        / "outline.json"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(outline_path, backup)
    SnapshotStore().write_json_atomic(outline_path, migrated)
    report["status"] = "applied"
    report["backup_path"] = str(backup)
    return report


__all__ = ["DEFAULT_BACKUP_ROOT", "migrate_project_volume_outline"]
