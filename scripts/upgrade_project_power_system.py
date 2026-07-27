from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TARGET_PROJECT_ID = "p-gou-webgame-restored"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.p_gou_power_system_data import build_power_system_spec  # noqa: E402
from packages.story_core.power_systems import (  # noqa: E402
    legacy_power_summary,
    validate_power_system_spec,
)
from packages.story_core.world_blueprint_context import (  # noqa: E402
    MANAGED_MARKER,
    render_power_markdown,
)


class FilesystemContainmentError(ValueError):
    pass


def _validate_target_project(root: Path, project: dict[str, Any] | None = None) -> None:
    if root.name != TARGET_PROJECT_ID:
        raise ValueError(
            "this migration only supports project directory "
            f"'{TARGET_PROJECT_ID}', got '{root.name}'"
        )
    if project is None or "project_id" not in project:
        return
    project_id = project["project_id"]
    if project_id != TARGET_PROJECT_ID:
        raise ValueError(
            f"project.json project_id must be '{TARGET_PROJECT_ID}', got {project_id!r}"
        )


class FilesystemTransactionError(RuntimeError):
    def __init__(
        self,
        *,
        primary_error: Exception | None,
        rollback_errors: list[tuple[Path, Exception]],
        cleanup_errors: list[tuple[Path, Exception]],
        residual_temp_paths: list[Path],
        changed: bool,
        canonical_valid: bool,
    ) -> None:
        self.primary_error = primary_error
        self.rollback_errors = tuple(rollback_errors)
        self.cleanup_errors = tuple(cleanup_errors)
        self.residual_temp_paths = tuple(residual_temp_paths)
        self.rollback_failed = bool(rollback_errors)
        self.cleanup_failed = bool(cleanup_errors)
        self.changed = changed
        self.canonical_valid = canonical_valid
        if primary_error is not None:
            message = f"primary failure: {type(primary_error).__name__}: {primary_error}"
        else:
            message = "canonical commit succeeded but temporary-file cleanup failed"
        super().__init__(message)


def _build_power_system_spec() -> dict[str, Any]:
    return build_power_system_spec()


_LEVEL_TWENTY = re.compile(r"(?i)(?:lv\.?\s*20|20\s*级)")
_CONTRADICTORY_LEVEL_TWENTY = re.compile(
    r"第二次\s*(?:职业)?(?:转职|晋升|进阶)|再次\s*(?:职业)?转职|二次\s*(?:职业)?转职|二转|第二职业\s*(?:晋升|进阶)"
)
_LEVEL_TEN = re.compile(r"(?i)(?:lv\.?\s*10|10\s*级)")
_OUTLINE_NARRATIVE_FIELDS = frozenset(
    {
        "action",
        "beat",
        "close_route",
        "continue_route",
        "current_strategy",
        "description",
        "end_state",
        "ending_contract",
        "ending_direction",
        "ending_hook",
        "game_line_payoff",
        "goal",
        "growth_path",
        "key_event",
        "main_conflict",
        "obstacle",
        "payoff",
        "progression",
        "progression_path",
        "protagonist_goal",
        "reality_line_payoff",
        "stage_antagonist",
        "story",
        "summary",
        "synopsis",
        "title",
        "turn",
    }
)
_OUTLINE_DICT_CONTAINERS = frozenset(
    {"extension_gate", "overall", "outline", "progression", "summary"}
)
_OUTLINE_LIST_CONTAINERS = frozenset(
    {
        "arc_beats",
        "arcs",
        "beats",
        "chapter_beats",
        "chapters",
        "events",
        "key_events",
        "plot_beats",
        "progression_beats",
        "summaries",
    }
)
_OUTLINE_EXCLUDED_KEY_PARTS = (
    "note",
    "author",
    "dialogue",
    "quote",
    "excerpt",
    "instruction",
    "constraint",
    "rule",
    "raw",
    "source",
)
_FIRST_CHAPTER_LEVEL_UP = "【等级提升至Lv.2。】"
_FIRST_CHAPTER_ATTRIBUTE_SCENE = (
    "\n\n等级提示刚落，角色面板又弹出一行：【获得5点自由属性。】"
    "夜烬现在靠火球术刷怪，没必要把点数分散到别处，便把五点全加到了智力上。"
    "\n\n他点下确认，两行新的提示随即跳了出来：【智力：5→10。】【可用属性点：0。】"
)
_ATTRIBUTE_ALLOCATION_REASON = "强化基础火球术"
_CHAPTER_NINE_GOAL = "验证后续构筑效率，比较技能学习与强化后的火球术循环。"
_CHAPTER_NINE_RESOURCE_BOUNDARY = (
    "属性点已在升级时获得，可保留或分配；技能点用于技能学习或强化，不直接投进智力。"
)
_CHAPTER_NINE_TURN = "后续构筑效率验证：在有限资源下比较火球术学习与强化的实际收益。"
_CHAPTER_NINE_PAYOFF = "用技能点强化基础火球术，建立可复用的构筑效率记录。"
_FIRST_CHAPTER_ATTRIBUTE_MARKERS = (
    "【获得5点自由属性。】",
    "把五点全加到了智力上",
    "他点下确认",
    "【智力：5→10。】",
    "【可用属性点：0。】",
)
_LEGACY_CHAPTER_NINE_TERMS = (
    "首次智力加点",
    "技能点全投智力",
    "智力加点比速度加点",
)
_DETAIL_CHAPTER_HEADING = re.compile(
    r"^(?P<level>#{2,4})\s*第\s*(?P<number>\d+)\s*章(?:\s*[：:].*)?(?:\r?\n)?$"
)
_DETAIL_MARKDOWN_HEADING = re.compile(r"^(?P<level>#{1,4})(?:\s|$)")
_FIRST_CHAPTER_FILENAME = re.compile(
    r"^(?:0*1(?:$|[-_\s.].*)|第\s*0*1\s*章(?:$|[-_\s.].*))$"
)


def _clean_outline_text(value: str) -> tuple[str, bool]:
    cleaned = value
    if _LEVEL_TWENTY.search(cleaned):
        cleaned = _CONTRADICTORY_LEVEL_TWENTY.sub("职业专精", cleaned)
    if _LEVEL_TEN.search(cleaned) and "正式法系职业" in cleaned:
        cleaned = cleaned.replace("正式法系职业", "元素法师")
    return cleaned, cleaned != value


def _outline_key(key: Any) -> str:
    return str(key).strip().casefold()


def _outline_key_is_excluded(key: str) -> bool:
    return any(part in key for part in _OUTLINE_EXCLUDED_KEY_PARTS)


def _clean_outline_list(value: list[Any]) -> tuple[list[Any], bool]:
    result: list[Any] = []
    changed = False
    for item in value:
        if isinstance(item, dict):
            cleaned, item_changed = _clean_outline_mapping(item)
        elif isinstance(item, list):
            cleaned, item_changed = _clean_outline_list(item)
        elif isinstance(item, str):
            cleaned, item_changed = _clean_outline_text(item)
        else:
            cleaned, item_changed = item, False
        result.append(cleaned)
        changed = changed or item_changed
    return result, changed


def _clean_outline_mapping(value: dict[Any, Any]) -> tuple[dict[Any, Any], bool]:
    result: dict[Any, Any] = {}
    changed = False
    for key, item in value.items():
        normalized_key = _outline_key(key)
        item_changed = False
        if _outline_key_is_excluded(normalized_key):
            cleaned = item
        elif isinstance(item, str) and normalized_key in _OUTLINE_NARRATIVE_FIELDS:
            cleaned, item_changed = _clean_outline_text(item)
        elif isinstance(item, dict) and normalized_key in _OUTLINE_DICT_CONTAINERS:
            cleaned, item_changed = _clean_outline_mapping(item)
        elif isinstance(item, list) and normalized_key in _OUTLINE_LIST_CONTAINERS:
            cleaned, item_changed = _clean_outline_list(item)
        else:
            cleaned = item
        result[key] = cleaned
        changed = changed or item_changed
    return result, changed


def _clean_outline_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        return _clean_outline_mapping(value)
    if isinstance(value, list):
        result: list[Any] = []
        changed = False
        for item in value:
            if isinstance(item, dict):
                cleaned, item_changed = _clean_outline_mapping(item)
            else:
                cleaned, item_changed = item, False
            result.append(cleaned)
            changed = changed or item_changed
        return result, changed
    return value, False


def _chapter_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(?:第\s*)?(\d+)\s*(?:章)?\s*", value)
        if match:
            return int(match.group(1))
    return None


def _is_chapter_nine(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        _chapter_number(value.get(key)) == 9
        for key in ("chapter_number", "chapter", "number", "序号")
    )


def _replace_chapter_nine_terms(value: str) -> str:
    return (
        value.replace("首次智力加点", "后续构筑效率验证")
        .replace("技能点全投智力", "技能点用于技能学习或强化")
        .replace("智力加点比速度加点", "后续构筑效率验证")
    )


def _dominant_newline(text: str) -> str:
    crlf_count = text.count("\r\n")
    lf_count = text.count("\n") - crlf_count
    return "\r\n" if crlf_count and crlf_count >= lf_count else "\n"


def _migrate_chapter_nine_outline(value: Any) -> tuple[Any, bool]:
    if not isinstance(value, dict):
        return value, False
    chapters = value.get("chapters")
    if not isinstance(chapters, list):
        return value, False
    migrated = deepcopy(value)
    changed = False
    for index, chapter in enumerate(chapters):
        if not _is_chapter_nine(chapter):
            continue
        updated = deepcopy(chapter)
        for key, item in tuple(updated.items()):
            if isinstance(item, str):
                replacement = _replace_chapter_nine_terms(item)
                if replacement != item:
                    updated[key] = replacement
                    changed = True
        updates = {
            "goal": _CHAPTER_NINE_GOAL,
            "obstacle": _CHAPTER_NINE_RESOURCE_BOUNDARY,
            "turn": _CHAPTER_NINE_TURN,
            "payoff": _CHAPTER_NINE_PAYOFF,
        }
        for key, replacement in updates.items():
            if updated.get(key) != replacement:
                updated[key] = replacement
                changed = True
        migrated["chapters"][index] = updated
    return migrated, changed


def _migrate_first_chapter_outline(value: Any, *, points_per_level: int) -> tuple[Any, bool]:
    if not isinstance(value, dict) or not isinstance(value.get("chapters"), list):
        return value, False
    chapters = value["chapters"]
    first_index = next(
        (index for index, chapter in enumerate(chapters) if isinstance(chapter, dict) and _chapter_number(chapter.get("chapter_number")) == 1),
        None,
    )
    if first_index is None or not isinstance(chapters[first_index], dict):
        return value, False
    migrated = deepcopy(value)
    chapter = migrated["chapters"][first_index]
    updates = {
        "chapter_number": 1,
        "level_target": "Lv.2",
        "attribute_allocation_decision": {
            "mode": "allocate",
            "allocations": {"智力": points_per_level},
            "remaining": 0,
            "reason": _ATTRIBUTE_ALLOCATION_REASON,
        },
    }
    changed = any(chapter.get(key) != item for key, item in updates.items())
    chapter.update(deepcopy(updates))
    return migrated, changed


def _chapter_nine_detail_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    in_chapter_nine = False
    chapter_level = 0
    result: list[str] = []
    for line in lines:
        match = _DETAIL_CHAPTER_HEADING.match(line)
        if match and int(match.group("number")) == 9:
            in_chapter_nine = True
            chapter_level = len(match.group("level"))
        elif in_chapter_nine:
            next_chapter = _DETAIL_CHAPTER_HEADING.match(line)
            next_heading = _DETAIL_MARKDOWN_HEADING.match(line)
            next_level = len(next_heading.group("level")) if next_heading else None
            if next_chapter or (next_level is not None and next_level <= chapter_level):
                break
        if in_chapter_nine:
            result.append(line)
    return "".join(result)


def _append_resource_boundary(result: list[str], newline: str) -> None:
    if result and not result[-1].endswith(("\n", "\r")):
        result.append(newline)
    result.append(f"- 资源边界: {_CHAPTER_NINE_RESOURCE_BOUNDARY}{newline}")


def _migrate_detailed_outline(text: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    in_chapter_nine = False
    chapter_level = 0
    changed = False
    result: list[str] = []
    saw_resource_boundary = False
    newline = _dominant_newline(text)
    for line in lines:
        match = _DETAIL_CHAPTER_HEADING.match(line)
        if match and int(match.group("number")) == 9:
            in_chapter_nine = True
            chapter_level = len(match.group("level"))
            updated_heading = _replace_chapter_nine_terms(line)
            changed = changed or updated_heading != line
            line = updated_heading
        elif in_chapter_nine:
            next_chapter = _DETAIL_CHAPTER_HEADING.match(line)
            next_heading = _DETAIL_MARKDOWN_HEADING.match(line)
            next_level = len(next_heading.group("level")) if next_heading else None
            if next_chapter or (next_level is not None and next_level <= chapter_level):
                if not saw_resource_boundary:
                    _append_resource_boundary(result, newline)
                    saw_resource_boundary = True
                    changed = True
                in_chapter_nine = False
                chapter_level = 0
        if not in_chapter_nine:
            result.append(line)
            continue

        field = re.match(r"^(?P<prefix>\s*-\s*[^:：]+)(?P<separator>[:：])(?P<current>.*)$", line)
        prefix = field.group("prefix") if field else ""
        separator = field.group("separator") if field else ""
        current = field.group("current") if field else ""
        replacement: str | None = None
        if separator and prefix.strip() in {"- 目标", "- 章节目标"}:
            replacement = _CHAPTER_NINE_GOAL
        elif separator and prefix.strip() in {"- 障碍", "- 资源边界"}:
            replacement = _CHAPTER_NINE_RESOURCE_BOUNDARY
            saw_resource_boundary = True
        elif separator and prefix.strip() in {"- 爽点", "- 转折"}:
            replacement = _CHAPTER_NINE_TURN
        elif separator and prefix.strip() in {"- 本章变化", "- 收益"}:
            replacement = _CHAPTER_NINE_PAYOFF
        if replacement is None:
            result.append(line)
            continue
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        leading_space = current[: len(current) - len(current.lstrip(" \t"))]
        updated = f"{prefix}{separator}{leading_space}{replacement}{ending}"
        result.append(updated)
        changed = changed or updated != line
    if in_chapter_nine and not saw_resource_boundary:
        _append_resource_boundary(result, newline)
        changed = True
    migrated = "".join(result)
    unresolved = [
        term for term in _LEGACY_CHAPTER_NINE_TERMS if term in _chapter_nine_detail_block(migrated)
    ]
    if unresolved:
        raise ValueError("unmigratable chapter 9 wording: " + ", ".join(unresolved))
    return migrated, changed


def _decode_text(raw: bytes) -> str:
    return raw.decode("utf-8-sig")


def _encode_text(text: str, source: bytes) -> bytes:
    encoded = text.encode("utf-8")
    return b"\xef\xbb\xbf" + encoded if source.startswith(b"\xef\xbb\xbf") else encoded


def _find_first_chapter(root: Path) -> tuple[Path, bytes]:
    chapters = root / "chapters"
    _require_contained_path(root, chapters, "chapters_directory")
    if not chapters.is_dir():
        raise FileNotFoundError("chapters directory is required for this migration")
    candidates = [
        path
        for path in sorted(chapters.glob("*.md"))
        if _FIRST_CHAPTER_FILENAME.fullmatch(path.stem)
    ]
    if len(candidates) != 1:
        raise ValueError("could not identify a unique first chapter file")
    path = candidates[0]
    _require_contained_path(root, path, "first_chapter_markdown")
    raw = path.read_bytes()
    if _FIRST_CHAPTER_LEVEL_UP in _decode_text(raw):
        return path, raw
    raise ValueError("first chapter level-up marker is missing")


def _find_workbench_first_chapter(root: Path) -> tuple[Path, bytes] | None:
    story_system = root / ".story-system"
    if not os.path.lexists(story_system):
        return None
    if story_system.is_symlink() and not story_system.exists():
        raise ValueError("workbench path is a broken symbolic link")
    _require_contained_path(root, story_system, "workbench_directory")
    if not story_system.is_dir():
        raise ValueError("workbench path must be a directory")
    chapters = root / ".story-system" / "chapters"
    if not os.path.lexists(chapters):
        raise FileNotFoundError("workbench chapters directory is required")
    if chapters.is_symlink() and not chapters.exists():
        raise ValueError("workbench chapters path is a broken symbolic link")
    _require_contained_path(root, chapters, "workbench_chapters_directory")
    if not chapters.is_dir():
        raise FileNotFoundError("workbench chapters directory is required")
    path = chapters / "0001.json"
    _require_contained_path(root, path, "workbench_first_chapter_json")
    if not path.is_file():
        raise FileNotFoundError("workbench first chapter JSON is required")
    candidates = [
        candidate
        for candidate in sorted(chapters.glob("*.json"))
        if _FIRST_CHAPTER_FILENAME.fullmatch(candidate.stem)
    ]
    if len(candidates) != 1:
        raise ValueError("could not identify a unique workbench first chapter JSON")
    raw = path.read_bytes()
    try:
        chapter = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("workbench first chapter JSON is invalid") from exc
    if not isinstance(chapter, dict):
        raise ValueError("workbench first chapter JSON must contain a JSON object")
    body = chapter.get("body")
    if not isinstance(body, str):
        raise ValueError("workbench first chapter body must be a string")
    if _FIRST_CHAPTER_LEVEL_UP not in body:
        raise ValueError("first chapter level-up marker is missing")
    return path, raw


def _migrate_first_chapter_body(text: str) -> tuple[str, bool]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    level_up_count = normalized.count(_FIRST_CHAPTER_LEVEL_UP)
    canonical_scene_count = normalized.count(_FIRST_CHAPTER_ATTRIBUTE_SCENE)
    canonical_fragment_count = normalized.count(
        _FIRST_CHAPTER_LEVEL_UP + _FIRST_CHAPTER_ATTRIBUTE_SCENE
    )
    marker_counts = [normalized.count(marker) for marker in _FIRST_CHAPTER_ATTRIBUTE_MARKERS]
    if (
        level_up_count == 1
        and canonical_scene_count == 1
        and canonical_fragment_count == 1
        and all(count == 1 for count in marker_counts)
    ):
        return text, False
    if level_up_count != 1 or canonical_scene_count or any(marker_counts):
        raise ValueError(
            "invalid first chapter attribute scene: expected one level-up marker followed by one canonical scene"
        )
    marker_index = text.find(_FIRST_CHAPTER_LEVEL_UP)
    if marker_index < 0:
        raise ValueError("first chapter level-up marker is missing")
    insert_at = marker_index + len(_FIRST_CHAPTER_LEVEL_UP)
    scene = _FIRST_CHAPTER_ATTRIBUTE_SCENE.replace("\n", _dominant_newline(text))
    return text[:insert_at] + scene + text[insert_at:], True


def _migrate_first_chapter(raw: bytes) -> tuple[bytes, bool]:
    text = _decode_text(raw)
    migrated, changed = _migrate_first_chapter_body(text)
    if not changed:
        return raw, False
    return _encode_text(migrated, raw), True


def _migrate_workbench_first_chapter(raw: bytes) -> tuple[bytes, bool]:
    try:
        chapter = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("workbench first chapter JSON is invalid") from exc
    if not isinstance(chapter, dict):
        raise ValueError("workbench first chapter JSON must contain a JSON object")
    body = chapter.get("body")
    if not isinstance(body, str):
        raise ValueError("workbench first chapter body must be a string")
    migrated_body, changed = _migrate_first_chapter_body(body)
    if not changed:
        return raw, False
    migrated = deepcopy(chapter)
    migrated["body"] = migrated_body
    return _encode_json(migrated, raw), True


def _protagonist_cards(state: dict[str, Any]) -> list[dict[str, Any]]:
    cards = state.get("characters")
    if not isinstance(cards, list):
        return []
    return [
        card
        for card in cards
        if isinstance(card, dict) and card.get("role") in {"protagonist", "主角"}
    ]


def _level_number(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value > 0 else None
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(?:lv\.?\s*)?(\d+)(?:\s*级)?\s*", value, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _is_initial_attribute_snapshot(state: dict[str, Any], protagonist: dict[str, Any]) -> bool:
    chapter = _chapter_number(state.get("current_chapter"))
    level = _level_number(protagonist.get("level"))
    return (chapter if chapter is not None else 1) <= 1 and (level if level is not None else 1) <= 2


def _stable_history(items: list[Any]) -> list[Any]:
    indexed = list(enumerate(items))
    indexed.sort(
        key=lambda entry: (
            _chapter_number(entry[1].get("chapter"))
            if isinstance(entry[1], dict) and _chapter_number(entry[1].get("chapter")) is not None
            else 1_000_000,
            _level_number(entry[1].get("level"))
            if isinstance(entry[1], dict) and _level_number(entry[1].get("level")) is not None
            else 1_000_000,
            entry[0],
        )
    )
    return [item for _, item in indexed]


def _migrate_state(state: Any, spec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not isinstance(state, dict):
        raise ValueError("state.json must contain a JSON object")
    rule = spec.get("attribute_allocation")
    if not isinstance(rule, dict) or not isinstance(rule.get("base_attributes"), dict):
        raise ValueError("power system must define attribute allocation")
    migrated = deepcopy(state)
    ledger = migrated.get("progression_ledger")
    if not isinstance(ledger, dict):
        ledger = {}
        migrated["progression_ledger"] = ledger
    protagonist = ledger.get("protagonist")
    if not isinstance(protagonist, dict):
        protagonist = {}
        ledger["protagonist"] = protagonist

    award = {"level": 2, "points": rule["points_per_level"], "chapter": 1}
    awards = protagonist.get("attribute_point_awards")
    award_history = deepcopy(awards) if isinstance(awards, list) else []
    award_history = [
        item
        for item in award_history
        if not (
            isinstance(item, dict)
            and _chapter_number(item.get("chapter")) == 1
            and _chapter_number(item.get("level")) == 2
        )
    ]
    protagonist["attribute_point_awards"] = _stable_history([*award_history, award])

    allocation = {
        "chapter": 1,
        "allocations": {"智力": rule["points_per_level"]},
        "remaining": 0,
        "reason": _ATTRIBUTE_ALLOCATION_REASON,
    }
    allocations = protagonist.get("attribute_allocations")
    allocation_history = deepcopy(allocations) if isinstance(allocations, list) else []
    allocation_history = [
        item
        for item in allocation_history
        if not (
            isinstance(item, dict) and _chapter_number(item.get("chapter")) == 1
        )
    ]
    protagonist["attribute_allocations"] = _stable_history([*allocation_history, allocation])

    history_sync = {
        "attribute_point_awards": deepcopy(protagonist["attribute_point_awards"]),
        "attribute_allocations": deepcopy(protagonist["attribute_allocations"]),
    }
    if not _is_initial_attribute_snapshot(migrated, protagonist):
        for card in _protagonist_cards(migrated):
            panel = card.get("game_panel")
            if not isinstance(panel, dict):
                panel = {}
                card["game_panel"] = panel
            panel.update(deepcopy(history_sync))
            game_state = card.get("game_state")
            if not isinstance(game_state, dict):
                game_state = {}
                card["game_state"] = game_state
            current = game_state.get("current")
            if not isinstance(current, dict):
                current = {}
                game_state["current"] = current
            current.update(deepcopy(history_sync))
        return migrated, migrated != state

    base_attributes = deepcopy(rule["base_attributes"])
    attributes = protagonist.get("attributes")
    attributes = deepcopy(attributes) if isinstance(attributes, dict) else {}
    attributes.update(base_attributes)
    attributes["智力"] = base_attributes["智力"] + rule["points_per_level"]
    protagonist["attributes"] = attributes
    protagonist["unallocated_attribute_points"] = 0

    synchronized = {
        "attributes": deepcopy(attributes),
        "unallocated_attribute_points": 0,
        "attribute_point_awards": deepcopy(protagonist["attribute_point_awards"]),
        "attribute_allocations": deepcopy(protagonist["attribute_allocations"]),
    }
    for card in _protagonist_cards(migrated):
        panel = card.get("game_panel")
        if not isinstance(panel, dict):
            panel = {}
            card["game_panel"] = panel
        panel.update(deepcopy(synchronized))
        game_state = card.get("game_state")
        if not isinstance(game_state, dict):
            game_state = {}
            card["game_state"] = game_state
        current = game_state.get("current")
        if not isinstance(current, dict):
            current = {}
            game_state["current"] = current
        current.update(deepcopy(synchronized))
    return migrated, migrated != state


def _read_json(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), raw


def _serialization_style(raw: bytes) -> tuple[int | str | None, str, bool, bool]:
    decoded = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in decoded else "\n"
    match = re.search(r"(?:\r?\n)([ \t]+)\"", decoded)
    indent: int | str | None
    if match:
        whitespace = match.group(1)
        indent = "\t" if "\t" in whitespace else len(whitespace)
    else:
        indent = None
    return indent, newline, decoded.endswith(("\n", "\r")), raw.startswith(b"\xef\xbb\xbf")


def _encode_json(value: Any, source: bytes) -> bytes:
    indent, newline, trailing_newline, bom = _serialization_style(source)
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    if newline != "\n":
        text = text.replace("\n", newline)
    if trailing_newline:
        text += newline
    encoded = text.encode("utf-8")
    return (b"\xef\xbb\xbf" + encoded) if bom else encoded


def _is_managed_markdown(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return handle.readline().rstrip("\r\n") == MANAGED_MARKER
    except UnicodeDecodeError:
        return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _require_contained_path(root: Path, path: Path, label: str) -> None:
    resolved_parent = path.parent.resolve(strict=False)
    resolved_target = path.resolve(strict=False)
    if not _is_relative_to(resolved_parent, root) or not _is_relative_to(
        resolved_target, root
    ):
        raise FilesystemContainmentError(f"path_escape: {label}")


def _stage_write(root: Path, path: Path, content: bytes) -> Path:
    _require_contained_path(root, path.parent, "staging_parent")
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_contained_path(root, path.parent, "staging_parent")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        _require_contained_path(root, temporary, "staging_file")
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except Exception as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        setattr(exc, "_migration_temp_path", temporary)
        raise


def _capture_targets(writes: list[tuple[Path, bytes]]) -> dict[Path, tuple[bool, bytes]]:
    originals: dict[Path, tuple[bool, bytes]] = {}
    for path, _ in writes:
        existed = path.exists()
        originals[path] = (existed, path.read_bytes() if existed else b"")
    return originals


def _targets_differ(originals: dict[Path, tuple[bool, bytes]]) -> bool:
    for path, (existed, original) in originals.items():
        try:
            current_exists = path.exists()
            if current_exists != existed:
                return True
            if current_exists and path.read_bytes() != original:
                return True
        except OSError:
            return True
    return False


def _transactional_write(
    root: Path,
    writes: list[tuple[Path, bytes]],
    originals: dict[Path, tuple[bool, bytes]],
) -> None:
    if set(originals) != {path for path, _ in writes}:
        raise ValueError("transaction originals do not match write targets")
    staged: list[tuple[Path, Path]] = []
    temporary_paths: list[Path] = []
    replaced: list[Path] = []
    primary_error: Exception | None = None
    rollback_errors: list[tuple[Path, Exception]] = []
    canonical_valid = False

    try:
        for path, content in writes:
            temporary = _stage_write(root, path, content)
            staged.append((path, temporary))
            temporary_paths.append(temporary)
    except Exception as staging_error:
        primary_error = staging_error
        failed_temp = getattr(staging_error, "_migration_temp_path", None)
        if isinstance(failed_temp, Path):
            temporary_paths.append(failed_temp)

    if primary_error is None:
        try:
            for path, temporary in staged:
                os.replace(temporary, path)
                replaced.append(path)
            canonical_valid = True
        except Exception as commit_error:
            primary_error = commit_error
            for path in reversed(replaced):
                existed, original = originals[path]
                try:
                    if existed:
                        restoration = _stage_write(root, path, original)
                        temporary_paths.append(restoration)
                        os.replace(restoration, path)
                    else:
                        path.unlink(missing_ok=True)
                except Exception as rollback_error:
                    failed_temp = getattr(
                        rollback_error, "_migration_temp_path", None
                    )
                    if isinstance(failed_temp, Path):
                        temporary_paths.append(failed_temp)
                    rollback_errors.append((path, rollback_error))

    cleanup_errors: list[tuple[Path, Exception]] = []
    for temporary in dict.fromkeys(temporary_paths):
        try:
            temporary.unlink(missing_ok=True)
        except Exception as cleanup_error:
            cleanup_errors.append((temporary, cleanup_error))

    residual_temp_paths: list[Path] = []
    for temporary in dict.fromkeys(temporary_paths):
        try:
            if temporary.exists():
                residual_temp_paths.append(temporary)
        except OSError:
            residual_temp_paths.append(temporary)

    changed = _targets_differ(originals)
    if primary_error is not None or cleanup_errors:
        raise FilesystemTransactionError(
            primary_error=primary_error,
            rollback_errors=rollback_errors,
            cleanup_errors=cleanup_errors,
            residual_temp_paths=residual_temp_paths,
            changed=changed,
            canonical_valid=canonical_valid,
        ) from primary_error


def _write_fsynced_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _backup_relative_path(root: Path, metadata_dir: Path, path: Path) -> Path:
    if path.parent == metadata_dir:
        return Path(path.name)
    return path.relative_to(root)


def _backup(
    root: Path,
    metadata_dir: Path,
    originals: dict[Path, tuple[bool, bytes]],
) -> Path:
    backups_parent = metadata_dir / "backups"
    _require_contained_path(root, backups_parent, "backups_parent")
    backups_parent.mkdir(parents=True, exist_ok=True)
    _require_contained_path(root, backups_parent, "backups_parent")
    staging = Path(
        tempfile.mkdtemp(
            prefix=".power-system-", suffix=".tmp", dir=backups_parent
        )
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = backups_parent / f"power-system-{stamp}"
    try:
        _require_contained_path(root, staging, "backup_staging")
        _require_contained_path(root, destination, "backup_destination")
        for path, (existed, content) in originals.items():
            if not existed:
                continue
            relative = _backup_relative_path(root, metadata_dir, path)
            target = staging / relative
            _require_contained_path(root, target, "backup_target")
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_fsynced_file(target, content)
        os.replace(staging, destination)
        return destination
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def upgrade_project(
    project_dir: str | Path, *, check: bool = False, backup: bool = True
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "changed": False,
        "valid": False,
        "backup_path": None,
        "changes": [],
    }
    transaction_originals: dict[Path, tuple[bool, bytes]] | None = None
    try:
        root = Path(project_dir).resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(f"project root is not a directory: {root}")
        _validate_target_project(root)
        metadata = root / ".webnovel"
        project_path = metadata / "project.json"
        outline_path = metadata / "outline.json"
        state_path = metadata / "state.json"
        power_path = root / "设定集" / "力量体系.md"
        detail_path = root / "大纲" / "第1卷-详细大纲.md"
        _require_contained_path(root, project_path, "project_json")
        _require_contained_path(root, outline_path, "outline_json")
        _require_contained_path(root, state_path, "state_json")
        _require_contained_path(root, power_path, "power_markdown")
        if backup:
            _require_contained_path(root, metadata / "backups", "backups_parent")
        project, project_bytes = _read_json(project_path)
        if not isinstance(project, dict):
            raise ValueError("project.json must contain a JSON object")
        _validate_target_project(root, project)
        outline, outline_bytes = _read_json(outline_path)
        if not isinstance(outline, (dict, list)):
            raise ValueError("project.json and outline.json must contain JSON objects or arrays")
        state, state_bytes = _read_json(state_path)
        if not isinstance(state, dict):
            raise ValueError("state.json must contain a JSON object")
        chapter_path, chapter_bytes = _find_first_chapter(root)
        workbench_chapter = _find_workbench_first_chapter(root)
        detail_bytes: bytes | None = None
        if detail_path.exists():
            _require_contained_path(root, detail_path, "detailed_outline")
            detail_bytes = detail_path.read_bytes()

        migrated_project = deepcopy(project)
        blueprint = migrated_project.setdefault("world_blueprint", {})
        if not isinstance(blueprint, dict):
            raise ValueError("project.json world_blueprint must be an object")
        spec = _build_power_system_spec()
        blueprint["power_system_spec"] = spec
        blueprint["power_system"] = legacy_power_summary(spec)
        validate_power_system_spec(blueprint["power_system_spec"], novel_type_id="game_webnovel")

        migrated_outline, outline_changed = _clean_outline_value(outline)
        migrated_outline, chapter_nine_changed = _migrate_chapter_nine_outline(
            migrated_outline
        )
        migrated_outline, first_chapter_changed = _migrate_first_chapter_outline(
            migrated_outline,
            points_per_level=spec["attribute_allocation"]["points_per_level"],
        )
        outline_changed = outline_changed or chapter_nine_changed or first_chapter_changed
        migrated_state, state_changed = _migrate_state(state, spec)
        expected_chapter_bytes, chapter_changed = _migrate_first_chapter(chapter_bytes)
        workbench_chapter_path: Path | None = None
        expected_workbench_chapter_bytes: bytes | None = None
        workbench_chapter_changed = False
        if workbench_chapter is not None:
            workbench_chapter_path, workbench_chapter_bytes = workbench_chapter
            (
                expected_workbench_chapter_bytes,
                workbench_chapter_changed,
            ) = _migrate_workbench_first_chapter(workbench_chapter_bytes)
        expected_detail_bytes = detail_bytes
        detail_changed = False
        if detail_bytes is not None:
            migrated_detail, detail_changed = _migrate_detailed_outline(
                _decode_text(detail_bytes)
            )
            if detail_changed:
                expected_detail_bytes = _encode_text(migrated_detail, detail_bytes)
        expected_project_bytes = _encode_json(migrated_project, project_bytes)
        expected_outline_bytes = (
            _encode_json(migrated_outline, outline_bytes) if outline_changed else outline_bytes
        )
        expected_state_bytes = (
            _encode_json(migrated_state, state_bytes) if state_changed else state_bytes
        )
        project_changed = expected_project_bytes != project_bytes
        outline_file_changed = expected_outline_bytes != outline_bytes
        state_file_changed = expected_state_bytes != state_bytes

        expected_power = render_power_markdown(project.get("title"), blueprint).encode("utf-8")
        power_exists = power_path.exists()
        power_managed = power_exists and _is_managed_markdown(power_path)
        current_power = power_path.read_bytes() if power_exists else None
        power_changed = (not power_exists or power_managed) and current_power != expected_power

        changes: list[str] = []
        if project_changed:
            changes.append("project.json: power system upgraded")
        if outline_file_changed:
            changes.append("outline.json: contradictory progression wording updated")
        if state_file_changed:
            changes.append("state.json: protagonist attribute allocation synchronized")
        if chapter_changed:
            changes.append("chapters: first level-up attribute allocation inserted")
        if workbench_chapter_changed:
            changes.append(
                ".story-system/chapters/0001.json: first level-up attribute allocation inserted"
            )
        if detail_changed:
            changes.append("大纲/第1卷-详细大纲.md: chapter 9 build wording updated")
        if power_changed:
            changes.append(
                "设定集/力量体系.md: refreshed" if power_exists else "设定集/力量体系.md: created"
            )
        elif power_exists and not power_managed:
            changes.append("设定集/力量体系.md: skipped unmanaged")

        will_write = (
            project_changed
            or outline_file_changed
            or state_file_changed
            or power_changed
            or chapter_changed
            or workbench_chapter_changed
            or detail_changed
        )
        result.update(changed=will_write, valid=True, changes=changes)
        if check or not will_write:
            return result

        writes: list[tuple[Path, bytes]] = []
        if project_changed:
            writes.append((project_path, expected_project_bytes))
        if outline_file_changed:
            writes.append((outline_path, expected_outline_bytes))
        if state_file_changed:
            writes.append((state_path, expected_state_bytes))
        if power_changed:
            writes.append((power_path, expected_power))
        if chapter_changed:
            writes.append((chapter_path, expected_chapter_bytes))
        if (
            workbench_chapter_changed
            and workbench_chapter_path is not None
            and expected_workbench_chapter_bytes is not None
        ):
            writes.append((workbench_chapter_path, expected_workbench_chapter_bytes))
        if detail_changed and expected_detail_bytes is not None:
            writes.append((detail_path, expected_detail_bytes))
        transaction_originals = _capture_targets(writes)
        if backup:
            backup_path = _backup(root, metadata, transaction_originals)
            result["backup_path"] = str(backup_path)
        _transactional_write(root, writes, transaction_originals)
        return result
    except Exception as exc:
        transaction_error = (
            exc if isinstance(exc, FilesystemTransactionError) else None
        )
        persistent_change = (
            transaction_error.changed
            if transaction_error is not None
            else _targets_differ(transaction_originals)
            if transaction_originals is not None
            else False
        )
        rollback_failed = bool(
            transaction_error and transaction_error.rollback_failed
        )
        cleanup_failed = bool(
            transaction_error and transaction_error.cleanup_failed
        )
        rollback_errors = (
            [
                f"{path}: {type(error).__name__}: {error}"
                for path, error in transaction_error.rollback_errors
            ]
            if transaction_error is not None
            else []
        )
        cleanup_errors = (
            [
                f"{path}: {type(error).__name__}: {error}"
                for path, error in transaction_error.cleanup_errors
            ]
            if transaction_error is not None
            else []
        )
        residual_temp_paths = (
            [str(path) for path in transaction_error.residual_temp_paths]
            if transaction_error is not None
            else []
        )
        return {
            "changed": persistent_change,
            "valid": bool(transaction_error and transaction_error.canonical_valid),
            "backup_path": result.get("backup_path"),
            "changes": [f"error: {type(exc).__name__}: {exc}"],
            "rollback_failed": rollback_failed,
            "cleanup_failed": cleanup_failed,
            "rollback_errors": rollback_errors,
            "cleanup_errors": cleanup_errors,
            "residual_temp_paths": residual_temp_paths,
            "state": (
                "indeterminate"
                if rollback_failed
                else "changed"
                if persistent_change
                else "unchanged"
            ),
        }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Upgrade a legacy file project's power system")
    parser.add_argument("project_dir")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args(argv)
    result = upgrade_project(args.project_dir, check=args.check, backup=not args.no_backup)
    print(json.dumps(result, ensure_ascii=False))
    return (
        0
        if result["valid"]
        and not result.get("rollback_failed")
        and not result.get("cleanup_failed")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
