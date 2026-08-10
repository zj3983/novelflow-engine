"""Tests for continuation import outline bootstrap.

Task 1 (readiness contracts) — these tests describe the pure
``validate_continuation_bootstrap`` contract: a freshly imported
project must have a future arc covering the next chapter, rolling
detail for the next chapter, the foundation layers, and a current
chapter that matches the committed chapters. Tests deliberately
stay on disk to keep the validator honest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packages.story_core.continuation_outline_bootstrap import (
    BootstrapPhaseId,
    BootstrapReadiness,
    BOOTSTRAP_PHASES,
    validate_continuation_bootstrap,
)
from packages.story_core.outline_rolling_store import RollingOutlineStore


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _rolling_chapter_payload(chapter_number: int) -> dict[str, Any]:
    return {
        "chapter_number": chapter_number,
        "title": f"第{chapter_number}章 待生成",
        "chapter_goal": f"推进主线并完成第{chapter_number}章的阶段目标",
        "core_conflict": "林修面对新出现的阻力并尝试化解",
        "cast": [
            {
                "name": "林修",
                "role": "protagonist",
                "character_tier": "protagonist",
            }
        ],
        "scenes": [
            {
                "location": "万修坊",
                "action": "林修确认炉子状态并准备下一步",
                "result": "确认炉子恢复稳定",
            },
            {
                "location": "维修铺",
                "action": "林修与同伴商讨下一步",
                "result": "确定前往下一个任务地点",
            },
        ],
        "gain": "完成一个维修委托，建立下一步出发的合理性",
        "cost": "消耗部分灵材",
        "foreshadowing": ["万修之墓的线索"],
        "hook": "新的异常订单出现",
        "state_delta": "林修灵材库存减少",
    }


def _seed_outline_payload(*, include_future_arc: bool) -> dict[str, Any]:
    overall = {
        "story": "林修承接万修传承，走出万修坊",
        "theme_statement": "以维修工作展现主角匠人本色",
        "protagonist_goal": "成为顶级万修师",
        "main_conflict": "传承与多方势力的拉扯",
        "growth_path": "维修技艺从家电到仙器",
        "ending_direction": "完成万修传承",
        "primary_trope_id": None,
        "core_ending_chapter": 300,
        "extension_ceiling_chapter": 300,
        "current_strategy": "observe",
        "ending_contract": "完成万修传承",
    }
    arcs: list[dict[str, Any]] = [
        {
            "id": "imported-history-1-147",
            "title": "原著已发生",
            "start_chapter": 1,
            "end_chapter": 147,
            "goal": "承接原著既定主线",
            "obstacle": "既有势力的围堵",
            "payoff": "推进至第147章的既定状态",
            "end_state": "炉火初定",
        }
    ]
    if include_future_arc:
        arcs.append(
            {
                "id": "continuation-148-300",
                "title": "续写阶段：承接万修传承",
                "start_chapter": 148,
                "end_chapter": 300,
                "goal": "推进续写主线直至全书结尾",
                "obstacle": "万修传承与多方围堵",
                "payoff": "完成续写目标",
                "end_state": "主角成为顶级万修师",
            }
        )
    return {
        "schema_version": "project-outline/v1",
        "overall": overall,
        "arcs": arcs,
        "chapters": [],
    }


def _seed_project_payload(*, current_chapter: int) -> dict[str, Any]:
    return {
        "project_id": "p-continuation-bootstrap-test",
        "title": "万界维修工",
        "current_chapter": current_chapter,
        "status": "draft",
        "pipeline_stage": "outline_bootstrapping",
        "world_blueprint": {
            "genre_plugin_ids": ["generic_webnovel"],
            "premise": "林修以维修技艺闯荡万界",
            "current_arc": "承接原著余波",
            "world_rules": ["万修以灵材为核心", "墨契需要以记忆为代价"],
            "power_system": ["筑基阶段以灵识驱动维修"],
            "locations": [],
            "factions": [],
        },
        "character_profiles": [
            {
                "name": "林修",
                "role": "protagonist",
                "character_tier": "protagonist",
                "identity_profile": {
                    "age": 19,
                    "origin": "万修坊",
                    "current_identity": "万修学徒",
                    "occupation": "万修学徒",
                },
                "current_life_profile": {
                    "authority_scope": "万修坊学徒",
                    "immediate_problem": "需要完成下一份维修委托",
                },
                "story_drive": {
                    "immediate_goal": "完成第一份维修委托",
                    "long_term_goal": "成为顶级万修师",
                    "motivation": "让万修坊重新运转",
                    "failure_stakes": "炉火熄灭",
                },
            }
        ],
        "continuation": {
            "schema_version": "continuation-project/v1",
            "start_after_chapter": current_chapter,
            "branch_point": current_chapter,
        },
    }


def _seed_state_payload(*, current_chapter: int) -> dict[str, Any]:
    return {
        "schema_version": "story-state/v1",
        "current_chapter": current_chapter,
        "characters": [
            {
                "name": "林修",
                "identity_profile": {
                    "age": 19,
                    "origin": "万修坊",
                    "current_identity": "万修学徒",
                    "occupation": "万修学徒",
                },
                "current_state": {
                    "current": {"realm": "筑基初期"},
                },
                "memory": ["承接万修坊的第一份委托"],
            }
        ],
        "foreshadowing": [
            {
                "text": "万修之墓",
                "first_chapter": 1,
                "last_touched_chapter": current_chapter,
                "status": "open",
            }
        ],
        "world_facts": ["万修以灵材为核心", "墨契需要以记忆为代价"],
    }


def _write_imported_chapter(
    root: Path, chapter_number: int, title: str = "已写章节"
) -> None:
    payload = {
        "schema_version": "imported-continuation-chapter/v1",
        "chapter_number": chapter_number,
        "chapter_title": title,
        "body": "正文",
        "chapter_summary": "正文摘要",
    }
    _write_json(
        root / ".story-system" / "chapters" / f"{chapter_number:04d}.json",
        payload,
    )


def seed_imported_project(
    tmp_path: Path,
    *,
    future_arc: bool = True,
    rolling: bool = True,
    current_chapter: int = 147,
) -> Path:
    """Seed a minimal imported project on disk for readiness tests.

    The fixture mirrors the files ``continuation_project`` writes
    during baseline import: ``.webnovel/{project,state,outline}.json``
    and ``.story-system/chapters/{number:04d}.json`` for each imported
    chapter. The rolling outline lives in
    ``.story-system/outline-generation/rolling_outline.json``.
    """

    root = tmp_path / "p-continuation-bootstrap-test"
    (root / ".webnovel").mkdir(parents=True, exist_ok=True)
    (root / ".story-system" / "chapters").mkdir(parents=True, exist_ok=True)

    _write_json(root / ".webnovel" / "outline.json", _seed_outline_payload(include_future_arc=future_arc))
    _write_json(root / ".webnovel" / "project.json", _seed_project_payload(current_chapter=current_chapter))
    _write_json(root / ".webnovel" / "state.json", _seed_state_payload(current_chapter=current_chapter))
    _write_imported_chapter(root, current_chapter)
    _write_imported_chapter(root, current_chapter - 1, title="上一章")

    if rolling:
        store = RollingOutlineStore(root)
        store.apply_rolling_batch(
            chapters=[_rolling_chapter_payload(current_chapter + 1)],
            expected_chapter_numbers=[current_chapter + 1],
            volume_range=(current_chapter + 1, current_chapter + 10),
        )
    return root


def test_bootstrap_phases_list_matches_plan() -> None:
    """Plan requires six phases in the documented order."""

    assert BOOTSTRAP_PHASES == (
        "source_analysis",
        "outline_foundation",
        "character_roster",
        "world_context",
        "chapter_window",
        "readiness_check",
    )
    assert all(isinstance(phase, str) for phase in BOOTSTRAP_PHASES)
    # Sanity: BootstrapPhaseId must be usable as a typed alias.
    declared: BootstrapPhaseId = "readiness_check"
    assert declared in BOOTSTRAP_PHASES


def test_readiness_requires_future_arc_covering_next_chapter(tmp_path: Path) -> None:
    root = seed_imported_project(tmp_path, future_arc=False, rolling=True)
    result = validate_continuation_bootstrap(root)
    assert isinstance(result, BootstrapReadiness)
    assert not result.ready
    assert "import_future_arc_required" in result.errors
    assert result.next_chapter == 148


def test_readiness_requires_rolling_target_chapter(tmp_path: Path) -> None:
    root = seed_imported_project(tmp_path, future_arc=True, rolling=False)
    result = validate_continuation_bootstrap(root)
    assert not result.ready
    assert "import_chapter_window_required:148" in result.errors
    assert result.next_chapter == 148


def test_readiness_accepts_complete_import(tmp_path: Path) -> None:
    root = seed_imported_project(tmp_path, future_arc=True, rolling=True)
    result = validate_continuation_bootstrap(root)
    assert result.ready
    assert result.errors == []
    assert result.next_chapter == 148
