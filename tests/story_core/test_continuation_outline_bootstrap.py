"""Tests for continuation import outline bootstrap.

Task 1 (readiness contracts) — these tests describe the pure
``validate_continuation_bootstrap`` contract: a freshly imported
project must have a future arc covering the next chapter, rolling
detail for the next chapter, the foundation layers, and a current
chapter that matches the committed chapters. Tests deliberately
stay on disk to keep the validator honest.

Task 3 (rolling-compatible chapter windows) — these tests
describe the conversion path from a planner-stage chapter window
to the independent rolling schema. The conversion is
deterministic and never touches disk; the bootstrapper owns disk
writes.
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


# ---------------------------------------------------------------------------
# Task 3: rolling-compatible chapter windows
# ---------------------------------------------------------------------------


def detailed_chapter(chapter_number: int) -> dict[str, Any]:
    """Return a planner-stage detailed chapter for ``chapter_number``.

    The fixture mirrors what
    :class:`LLMOutlinePlanningGenerator` returns from its chapter
    window: a ``ChapterPlan``-compatible payload plus the
    rolling-only fields ``core_conflict``, ``gain``, ``cost``,
    ``foreshadowing``, ``state_delta_summary`` and ``scene_chain``.
    """

    return {
        "chapter_number": chapter_number,
        "title": f"第{chapter_number}章 续写推进",
        "goal": f"推进主线并完成第{chapter_number}章的阶段目标",
        "obstacle": "现有资源不足以支撑下一阶段行动",
        "action": "林修重新调配资源并制定下一步计划",
        "turn": "行动暴露新的限制",
        "payoff": "确立下一阶段的资源基础",
        "ending_hook": f"为第{chapter_number + 1}章埋下新冲突",
        "cast": ["林修"],
        "core_conflict": "林修面对新出现的阻力并尝试化解",
        "gain": f"完成第{chapter_number}章的核心任务，建立下一步的合理性",
        "cost": "消耗部分灵材库存",
        "foreshadowing": ["万修之墓的线索"],
        "state_delta_summary": "林修灵材库存减少",
        "scene_chain": [
            {
                "location": "万修坊",
                "pov": "林修",
                "goal": "评估当前资源",
                "obstacle": "灵材库存不足",
                "action": "清点现有灵材",
                "change": "确认库存后调整计划",
                "next": "前往下一处任务地点",
                "state_delta": {"灵材": -1},
            },
            {
                "location": "维修铺",
                "pov": "林修",
                "goal": "为下一步准备工具",
                "obstacle": "工具老旧",
                "action": "整修并替换关键工具",
                "change": "工具恢复可用状态",
                "next": "开启第{0}章的任务".format(chapter_number),
                "state_delta": {"工具": 1},
            },
        ],
    }


def character_card(name: str, role: str) -> dict[str, Any]:
    return {
        "name": name,
        "role": role,
        "character_tier": "protagonist" if role == "protagonist" else "supporting",
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


def test_rolling_batch_from_generated_window_happy_path() -> None:
    """The conversion must project the planner-stage chapter
    window into the rolling schema, then validate it as a batch.
    """

    from packages.story_core.continuation_outline_bootstrap import (
        rolling_batch_from_generated_window,
    )
    from packages.story_core.outline_rolling import validate_rolling_batch

    batch = rolling_batch_from_generated_window(
        chapters=[detailed_chapter(148), detailed_chapter(149)],
        character_cards=[character_card("林修", "protagonist")],
        volume_range=(148, 160),
    )
    assert [row["chapter_number"] for row in batch] == [148, 149]
    validate_rolling_batch(
        batch,
        expected_chapter_numbers=[148, 149],
        volume_range=(148, 160),
    )

    # Field mapping is deterministic: the rolling rows are the
    # rolling schema, not the planner schema. Generation-only
    # fields like ``state_delta_summary`` and ``scene_chain`` must
    # not leak into the rolling payload.
    first = batch[0]
    assert first["chapter_goal"].startswith("推进主线")
    assert first["hook"].startswith("为第149章")
    assert first["state_delta"] == "林修灵材库存减少"
    assert first["gain"].startswith("完成第148章")
    assert "scene_chain" not in first
    assert "state_delta_summary" not in first


def test_rolling_batch_rejects_blank_gain_or_cost() -> None:
    from packages.story_core.continuation_outline_bootstrap import (
        rolling_batch_from_generated_window,
    )

    blank_gain = detailed_chapter(148)
    blank_gain["gain"] = ""
    with pytest.raises(ValueError):
        rolling_batch_from_generated_window(
            chapters=[blank_gain, detailed_chapter(149)],
            character_cards=[character_card("林修", "protagonist")],
            volume_range=(148, 160),
        )

    blank_cost = detailed_chapter(148)
    blank_cost["cost"] = "   "
    with pytest.raises(ValueError):
        rolling_batch_from_generated_window(
            chapters=[detailed_chapter(148), blank_cost],
            character_cards=[character_card("林修", "protagonist")],
            volume_range=(148, 160),
        )


def test_rolling_batch_rejects_too_few_scenes() -> None:
    from packages.story_core.continuation_outline_bootstrap import (
        rolling_batch_from_generated_window,
    )

    short_scene = detailed_chapter(148)
    short_scene["scene_chain"] = short_scene["scene_chain"][:1]
    with pytest.raises(ValueError):
        rolling_batch_from_generated_window(
            chapters=[short_scene, detailed_chapter(149)],
            character_cards=[character_card("林修", "protagonist")],
            volume_range=(148, 160),
        )


def test_rolling_batch_rejects_unknown_cast() -> None:
    from packages.story_core.continuation_outline_bootstrap import (
        rolling_batch_from_generated_window,
    )

    unknown_cast = detailed_chapter(148)
    unknown_cast["cast"] = ["林修", "陌生人"]
    with pytest.raises(ValueError):
        rolling_batch_from_generated_window(
            chapters=[unknown_cast, detailed_chapter(149)],
            character_cards=[character_card("林修", "protagonist")],
            volume_range=(148, 160),
        )


def test_rolling_batch_rejects_wrong_chapter_numbers() -> None:
    from packages.story_core.continuation_outline_bootstrap import (
        rolling_batch_from_generated_window,
    )

    # The second slot must be 149; declaring 150 in slot 1 is a
    # wrong chapter number and the conversion must reject it.
    wrong_number = detailed_chapter(150)
    wrong_number["chapter_number"] = 150
    with pytest.raises(ValueError):
        rolling_batch_from_generated_window(
            chapters=[detailed_chapter(148), wrong_number],
            character_cards=[character_card("林修", "protagonist")],
            volume_range=(148, 160),
        )


def test_llm_rolling_window_generator_makes_one_planner_call() -> None:
    """``LLMRollingWindowGenerator.generate`` must make exactly
    one planner call for the full window and validate the result
    before returning.
    """

    from packages.story_core.continuation_outline_bootstrap import (
        LLMRollingWindowGenerator,
    )

    captured: list[dict[str, Any]] = []

    class _FakeGateway:
        def complete_stage(self, stage: str, request):  # type: ignore[no-untyped-def]
            captured.append({"stage": stage, "messages": list(request.messages)})
            content = json.dumps(
                {
                    "chapters": [
                        {**detailed_chapter(148), "cast": ["林修"]},
                        {**detailed_chapter(149), "cast": ["林修"]},
                    ]
                },
                ensure_ascii=False,
            )
            from packages.story_core.model_gateway import ModelResponse

            return ModelResponse.success(
                request,
                text=content,
            )

    generator = LLMRollingWindowGenerator(gateway=_FakeGateway())  # type: ignore[arg-type]
    rows = generator.generate(
        context={"current_arc": "续写主线"},
        chapter_numbers=[148, 149],
        volume_range=(148, 160),
        character_cards=[character_card("林修", "protagonist")],
    )
    assert [row["chapter_number"] for row in rows] == [148, 149]
    assert len(captured) == 1
    assert captured[0]["stage"] == "planner"
    # The generator never touches the filesystem; it just
    # produces the rolling rows.
    assert all(isinstance(row["scenes"], list) and len(row["scenes"]) >= 2 for row in rows)
