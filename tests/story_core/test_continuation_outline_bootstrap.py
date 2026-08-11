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
    ContinuationOutlineBootstrapper,
    validate_continuation_bootstrap,
)
from packages.story_core.outline_rolling_store import RollingOutlineStore


CHAPTER_CONTRACT = {
    "payoff_contract": {
        "need": "林修必须拿到替换镜芯",
        "pressure": "买家只给他一夜验货",
        "hidden_advantage": "他能恢复物品上次完整运行状态",
        "concrete_reward": "修复订单并获得父亲失踪线索",
    },
    "chapter_sop": {
        "opening_carry": "接上铜镜第一次亮起",
        "mid_feedback": "镜面恢复一段旧影像",
        "turn": "影像中的人认出了林修",
        "ending_hook": "镜中人叫出林修父亲的名字",
    },
}


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

    # The continuation-analysis.json is written by the import
    # baseline; the bootstrapper reads it to compute the
    # input fingerprint and to confirm the source analysis.
    _write_json(
        root / ".story-system" / "continuation-analysis.json",
        {
            "story_overview": "林修承接万修传承，闯荡万界",
            "needs_confirmation": [],
        },
    )

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


def test_rolling_batch_from_generated_window_preserves_chapter_contracts() -> None:
    from packages.story_core.continuation_outline_bootstrap import (
        rolling_batch_from_generated_window,
    )

    chapter = detailed_chapter(148)
    chapter.update(CHAPTER_CONTRACT)

    row = rolling_batch_from_generated_window(
        chapters=[chapter],
        character_cards=[character_card(chapter["cast"][0], "protagonist")],
        volume_range=(148, 160),
        require_shuangwen_contracts=True,
    )[0]

    assert row["payoff_contract"] == chapter["payoff_contract"]
    assert row["chapter_sop"] == chapter["chapter_sop"]


def test_disabled_rolling_conversion_drops_partial_model_contracts() -> None:
    from packages.story_core.continuation_outline_bootstrap import (
        rolling_batch_from_generated_window,
    )

    chapter = detailed_chapter(148)
    chapter["payoff_contract"] = {"need": "模型恶意夹带的局部字段"}

    row = rolling_batch_from_generated_window(
        chapters=[chapter],
        character_cards=[character_card("林修", "protagonist")],
        volume_range=(148, 160),
        require_shuangwen_contracts=False,
    )[0]

    assert "payoff_contract" not in row
    assert "chapter_sop" not in row


def test_enabled_rolling_conversion_rejects_partial_contracts() -> None:
    from packages.story_core.continuation_outline_bootstrap import (
        rolling_batch_from_generated_window,
    )

    chapter = detailed_chapter(148)
    chapter["payoff_contract"] = {"need": "林修必须拿到替换镜芯"}

    with pytest.raises(ValueError, match="chapter_contract_missing"):
        rolling_batch_from_generated_window(
            chapters=[chapter],
            character_cards=[character_card("林修", "protagonist")],
            volume_range=(148, 160),
            require_shuangwen_contracts=True,
        )


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
                        {
                            **detailed_chapter(148),
                            "cast": ["林修"],
                            "payoff_contract": {"need": "恶意夹带"},
                        },
                        {
                            **detailed_chapter(149),
                            "cast": ["林修"],
                            "chapter_sop": {"turn": "恶意夹带"},
                        },
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
        require_shuangwen_contracts=False,
    )
    assert [row["chapter_number"] for row in rows] == [148, 149]
    assert len(captured) == 1
    assert captured[0]["stage"] == "planner"
    serialized_request = json.dumps(captured[0]["messages"], ensure_ascii=False)
    assert "payoff_contract" not in serialized_request
    assert "chapter_sop" not in serialized_request
    assert all("payoff_contract" not in row for row in rows)
    assert all("chapter_sop" not in row for row in rows)
    # The generator never touches the filesystem; it just
    # produces the rolling rows.
    assert all(isinstance(row["scenes"], list) and len(row["scenes"]) >= 2 for row in rows)


def test_llm_rolling_window_generator_requires_enabled_contracts() -> None:
    from packages.story_core.continuation_outline_bootstrap import (
        LLMRollingWindowGenerator,
    )

    captured: list[dict[str, Any]] = []

    class _FakeGateway:
        def complete_stage(self, stage: str, request):  # type: ignore[no-untyped-def]
            captured.append({"stage": stage, "messages": list(request.messages)})
            chapter = {**detailed_chapter(148), **CHAPTER_CONTRACT, "cast": ["林修"]}
            from packages.story_core.model_gateway import ModelResponse

            return ModelResponse.success(
                request,
                text=json.dumps({"chapters": [chapter]}, ensure_ascii=False),
            )

    rows = LLMRollingWindowGenerator(gateway=_FakeGateway()).generate(  # type: ignore[arg-type]
        context={"current_arc": "续写主线"},
        chapter_numbers=[148],
        volume_range=(148, 160),
        character_cards=[character_card("林修", "protagonist")],
        require_shuangwen_contracts=True,
        enabled_skill_ids=["commercial-shuangwen"],
        enabled_skill_module_ids=[
            "commercial-shuangwen::chapter-sop",
            "commercial-shuangwen::genre-examples",
        ],
        genre_id="xuanhuan",
    )

    serialized_request = json.dumps(captured[0]["messages"], ensure_ascii=False)
    assert "payoff_contract" in serialized_request
    assert "chapter_sop" in serialized_request
    assert "chapter-sop" in serialized_request
    assert "genre-examples" in serialized_request
    assert "周执事押上长老担保" in serialized_request
    assert "公会押上声望封锁副本" not in serialized_request
    assert "review-checklist" not in serialized_request
    assert rows[0]["payoff_contract"] == CHAPTER_CONTRACT["payoff_contract"]
    assert rows[0]["chapter_sop"] == CHAPTER_CONTRACT["chapter_sop"]


def test_llm_rolling_window_generator_can_load_genre_examples_without_chapter_sop() -> None:
    from packages.story_core.continuation_outline_bootstrap import (
        LLMRollingWindowGenerator,
    )

    captured: list[dict[str, Any]] = []

    class _FakeGateway:
        def complete_stage(self, stage: str, request):  # type: ignore[no-untyped-def]
            captured.append({"stage": stage, "messages": list(request.messages)})
            chapter = {**detailed_chapter(148), "cast": ["林修"]}
            from packages.story_core.model_gateway import ModelResponse

            return ModelResponse.success(
                request,
                text=json.dumps({"chapters": [chapter]}, ensure_ascii=False),
            )

    rows = LLMRollingWindowGenerator(gateway=_FakeGateway()).generate(  # type: ignore[arg-type]
        context={"current_arc": "续写主线"},
        chapter_numbers=[148],
        volume_range=(148, 160),
        character_cards=[character_card("林修", "protagonist")],
        require_shuangwen_contracts=False,
        enabled_skill_ids=["commercial-shuangwen"],
        enabled_skill_module_ids=["commercial-shuangwen::genre-examples"],
        genre_id="xuanhuan",
    )

    serialized_request = json.dumps(captured[0]["messages"], ensure_ascii=False)
    assert "genre-examples" in serialized_request
    assert "周执事押上长老担保" in serialized_request
    assert "chapter-sop" not in serialized_request
    assert "payoff_contract" not in serialized_request
    assert "chapter_sop" not in serialized_request
    assert "payoff_contract" not in rows[0]
    assert "chapter_sop" not in rows[0]


def test_llm_rolling_window_generator_normalizes_common_cli_shape() -> None:
    """CLI models may omit ordered chapter ids and emit scene strings."""

    from packages.story_core.continuation_outline_bootstrap import (
        LLMRollingWindowGenerator,
    )

    class _FakeGateway:
        def complete_stage(self, stage: str, request):  # type: ignore[no-untyped-def]
            chapter = detailed_chapter(148)
            chapter.pop("chapter_number")
            chapter["cast"] = ["林修"]
            chapter["scene_chain"] = ["林修检查炉火。", "林修确认新的异常。"]
            from packages.story_core.model_gateway import ModelResponse

            return ModelResponse.success(
                request,
                text=json.dumps({"chapters": [chapter]}, ensure_ascii=False),
            )

    rows = LLMRollingWindowGenerator(gateway=_FakeGateway()).generate(  # type: ignore[arg-type]
        context={"current_arc": "续写主线"},
        chapter_numbers=[148],
        volume_range=(148, 160),
        character_cards=[character_card("林修", "protagonist")],
        require_shuangwen_contracts=False,
    )

    assert rows[0]["chapter_number"] == 148
    assert rows[0]["scenes"][0]["action"] == "林修检查炉火。"


# ---------------------------------------------------------------------------
# Task 4: Resumable bootstrap orchestrator
# ---------------------------------------------------------------------------


def _seed_legacy_approved_project(
    tmp_path: Path,
    *,
    current_chapter: int = 147,
) -> Path:
    """Seed a project whose overall/arcs/characters are already
    approved. The bootstrapper must NOT call the full planning
    generator; it must call the rolling-only generator for the
    next five chapters and seed the rolling outline file.
    """

    root = seed_imported_project(
        tmp_path,
        future_arc=True,
        rolling=False,
        current_chapter=current_chapter,
    )
    outline_path = root / ".webnovel" / "outline.json"
    outline = _read_json(outline_path)
    future_arc = outline["arcs"][-1]
    future_arc.update(
        {
            "stage_antagonist": "负责阻断万修传承的巡界使",
            "core_loop": "接单、诊断、维修、承担代价并得到新的线索",
            "escalations": [
                "维修对象从民用器物升级为宗门法器",
                "维修结果开始改变各方势力关系",
                "巡界使亲自封锁万修传承",
            ],
            "midpoint_turn": "林修发现故障并非自然形成，而是有人主动制造",
            "climax": "林修修复关键仙器并迫使巡界使暴露",
            "active_long_term_lines": ["万修传承的来历", "幕后故障制造者"],
            "relationship_changes": ["林修与盟友从交易关系转为共同承担风险"],
            "foreshadowing_in": ["早期异常维修单"],
            "foreshadowing_out": ["上界巡查体系"],
            "next_arc_entry": "修复结果惊动更高层的巡界机构",
        }
    )
    _write_json(outline_path, outline)
    return root


def test_bootstrapper_rejects_sparse_future_arc_shell(tmp_path: Path) -> None:
    """A title/range/goal shell is not a usable stage outline."""

    root = seed_imported_project(
        tmp_path,
        future_arc=True,
        rolling=False,
        current_chapter=147,
    )
    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=object(),
        rolling_generator=object(),
    )

    assert bootstrapper.outline_foundation_needs_refresh()


def test_refresh_ready_checkpoint_lists_all_available_rolling_chapters(
    tmp_path: Path,
) -> None:
    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    rolling_path = (
        root
        / ".story-system"
        / "outline-generation"
        / "rolling_outline.json"
    )
    _write_json(
        rolling_path,
        {
            "schema_version": "rolling-outline/v1",
            "chapters": [
                {"chapter_number": number, "title": f"Chapter {number}"}
                for number in range(148, 154)
            ],
        },
    )
    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=object(),
        rolling_generator=object(),
    )
    payload = {
        "schema_version": "continuation-bootstrap/v1",
        "input_fingerprint": "fingerprint",
        "status": "ready",
        "phases": [
            {
                "id": phase,
                "status": "completed",
                "artifact": {"written_chapter_numbers": [148, 149]},
                "error": "",
            }
            for phase in BOOTSTRAP_PHASES
        ],
    }

    refreshed = bootstrapper.refresh_ready_checkpoint(payload)

    chapter_phase = next(
        phase
        for phase in refreshed["phases"]
        if phase["id"] == "chapter_window"
    )
    assert chapter_phase["artifact"]["written_chapter_numbers"] == [148, 149]
    assert chapter_phase["artifact"]["available_chapter_numbers"] == [
        148,
        149,
        150,
        151,
        152,
        153,
    ]


def _fake_planning_generator(
    *,
    chapters: list[dict[str, Any]] | None = None,
    error: str = "",
):
    """Return a stub LLMOutlinePlanningGenerator-like object
    that records its calls. The test asserts the bootstrapper
    does NOT call it for legacy-approved projects.
    """

    calls: list[dict[str, Any]] = []

    class _Stub:
        def generate(self, brief: Any, *, mode: str, guidance: str = "", **kwargs: Any) -> Any:  # type: ignore[no-untyped-def]
            calls.append({"mode": mode, "guidance": guidance})
            if error:
                raise ValueError(error)
            from packages.story_core.outline_planning_generation import (
                GeneratedOutlinePlan,
            )

            raise AssertionError("planning generator must not be called for legacy-approved projects")

    return _Stub(), calls


def _fake_rolling_generator(
    chapters: list[dict[str, Any]] | None = None,
    *,
    error: str = "",
):
    """Return a stub LLMRollingWindowGenerator-like object
    that records its calls. The default fixture returns the
    chapters from the ``chapters`` argument.
    """

    captured: list[dict[str, Any]] = []

    class _Stub:
        def generate(
            self,
            *,
            context: dict[str, Any],
            chapter_numbers: list[int],
            volume_range: tuple[int, int],
            character_cards: list[dict[str, Any]],
            require_shuangwen_contracts: bool,
            enabled_skill_ids: list[str],
            enabled_skill_module_ids: list[str] | None,
            genre_id: str,
        ) -> list[dict[str, Any]]:
            captured.append(
                {
                    "context": context,
                    "chapter_numbers": list(chapter_numbers),
                    "volume_range": tuple(volume_range),
                    "character_cards": list(character_cards),
                    "require_shuangwen_contracts": require_shuangwen_contracts,
                    "enabled_skill_ids": list(enabled_skill_ids),
                    "enabled_skill_module_ids": (
                        None
                        if enabled_skill_module_ids is None
                        else list(enabled_skill_module_ids)
                    ),
                    "genre_id": genre_id,
                }
            )
            if error:
                raise ValueError(error)
            if chapters is not None:
                return chapters
            return [
                {
                    "chapter_number": number,
                    "title": f"第{number}章 续写推进",
                    "chapter_goal": f"推进主线并完成第{number}章的阶段目标",
                    "core_conflict": "林修面对新出现的阻力并尝试化解",
                    "cast": [{"name": "林修", "role": "protagonist", "character_tier": "protagonist"}],
                    "scenes": [
                        {"location": "万修坊", "action": "林修确认炉子状态", "result": "确认炉子恢复稳定"},
                        {"location": "维修铺", "action": "林修准备下一步", "result": "确定下一步任务"},
                    ],
                    "gain": f"完成第{number}章的维修委托",
                    "cost": "消耗部分灵材",
                    "foreshadowing": ["万修之墓的线索"],
                    "hook": f"新的异常订单出现（第{number}章）",
                    "state_delta": f"林修灵材库存减少（第{number}章）",
                }
                for number in chapter_numbers
            ]

    return _Stub(), captured


def test_bootstrapper_full_run_reaches_ready(tmp_path: Path) -> None:
    """A full bootstrap run on a legacy-approved baseline
    reaches readiness and writes the rolling outline.

    The plan rule: the bootstrapper owns the rolling window.
    When the three-level outline is already valid, the
    bootstrapper must adopt the foundation/character layers
    and only call the rolling-only generator.
    """

    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    rolling_stub, rolling_calls = _fake_rolling_generator()

    def planning_generate(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "planning generator must not be called for legacy-approved"
        )

    from packages.story_core.continuation_outline_bootstrap import (
        ContinuationOutlineBootstrapper,
    )

    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=planning_generate,
        rolling_generator=rolling_stub,
    )
    result = bootstrapper.run()
    assert result.ready
    assert result.errors == []
    assert len(rolling_calls) == 1

    # Rolling outline was written for chapters 148..152.
    from packages.story_core.outline_rolling_store import RollingOutlineStore

    rolling = RollingOutlineStore(root)
    numbers = [
        chapter["chapter_number"]
        for chapter in rolling.read_rolling_outline()["chapters"]
    ]
    assert numbers == [148, 149, 150, 151, 152]


def test_disabled_bootstrap_drops_partial_contracts_before_persisting(
    tmp_path: Path,
) -> None:
    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    chapters = []
    for number in range(148, 153):
        chapter = _rolling_chapter_payload(number)
        chapter["payoff_contract"] = {"need": "模型恶意夹带的局部字段"}
        chapters.append(chapter)
    rolling_stub, rolling_calls = _fake_rolling_generator(chapters=chapters)

    result = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=object(),
        rolling_generator=rolling_stub,
    ).run()

    assert result.ready
    assert rolling_calls[0]["require_shuangwen_contracts"] is False
    assert rolling_calls[0]["enabled_skill_ids"] == []
    assert rolling_calls[0]["enabled_skill_module_ids"] is None
    persisted = RollingOutlineStore(root).read_rolling_outline()
    assert all("payoff_contract" not in row for row in persisted["chapters"])
    assert all("chapter_sop" not in row for row in persisted["chapters"])


def test_enabled_bootstrap_requires_and_persists_full_contracts(
    tmp_path: Path,
) -> None:
    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    project_path = root / ".webnovel" / "project.json"
    project = _read_json(project_path)
    project["enabled_skill_ids"] = ["commercial-shuangwen"]
    project["world_blueprint"] = {
        **project.get("world_blueprint", {}),
        "genre_plugin_ids": ["xuanhuan"],
    }
    project["enabled_skill_module_ids"] = [
        "commercial-shuangwen::chapter-sop",
        "commercial-shuangwen::genre-examples",
    ]
    _write_json(project_path, project)
    chapters = [
        {**_rolling_chapter_payload(number), **CHAPTER_CONTRACT}
        for number in range(148, 153)
    ]
    rolling_stub, rolling_calls = _fake_rolling_generator(chapters=chapters)

    result = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=object(),
        rolling_generator=rolling_stub,
    ).run()

    assert result.ready
    assert rolling_calls[0]["require_shuangwen_contracts"] is True
    assert rolling_calls[0]["enabled_skill_ids"] == ["commercial-shuangwen"]
    assert rolling_calls[0]["enabled_skill_module_ids"] == [
        "commercial-shuangwen::chapter-sop",
        "commercial-shuangwen::genre-examples",
    ]
    assert rolling_calls[0]["genre_id"] == "xuanhuan"
    persisted = RollingOutlineStore(root).read_rolling_outline()
    assert persisted["chapters"][0]["payoff_contract"] == CHAPTER_CONTRACT["payoff_contract"]
    assert persisted["chapters"][0]["chapter_sop"] == CHAPTER_CONTRACT["chapter_sop"]


def test_bootstrapper_real_import_baseline_generates_future_arc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real import baseline has history only, so planning must run.

    This guards against treating any non-empty arc list as a complete
    continuation foundation.  The production planner is passed to
    ``FileProjectStore.generate_outline_plan`` rather than called as a
    facade itself.
    """

    root = seed_imported_project(
        tmp_path,
        future_arc=False,
        rolling=False,
        current_chapter=147,
    )
    rolling_stub, rolling_calls = _fake_rolling_generator()
    planning_calls: list[object] = []

    class PlannerLikeProduction:
        def generate(self, brief: Any, **kwargs: Any) -> Any:
            raise AssertionError("store adapter owns this call")

    planner = PlannerLikeProduction()

    from packages.story_core.file_project_store import FileProjectStore

    def generate_outline_plan(
        store: FileProjectStore,
        generator: object,
        **kwargs: Any,
    ) -> dict[str, Any]:
        planning_calls.append(generator)
        outline = store.project_outline()
        outline["arcs"].append(
            {
                "id": "continuation-148-300",
                "title": "续写阶段",
                "start_chapter": 148,
                "end_chapter": 300,
                "goal": "推进续写主线",
                    "obstacle": "既有冲突继续升级",
                    "payoff": "完成续写目标",
                    "end_state": "主角完成阶段成长",
                    "stage_antagonist": "阻断万修传承的巡界使",
                    "core_loop": "接单、诊断、维修、承担代价并获得线索",
                    "escalations": ["维修宗门法器", "维修结果改变势力关系"],
                    "midpoint_turn": "林修确认故障是人为制造",
                    "climax": "林修修复关键仙器并逼出幕后对手",
                    "active_long_term_lines": ["万修传承的来历"],
                }
        )
        store.update_project_outline(outline)
        return {
            "outline_foundation": {"overall": outline["overall"], "arcs": outline["arcs"]},
            "character_roster": store.project()["character_profiles"],
        }

    monkeypatch.setattr(FileProjectStore, "generate_outline_plan", generate_outline_plan)

    result = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=planner,
        rolling_generator=rolling_stub,
    ).run()

    assert result.ready
    assert planning_calls == [planner]
    assert rolling_calls[0]["chapter_numbers"] == [148, 149, 150, 151, 152]


def test_bootstrapper_unexpected_model_error_persists_failed_phase(
    tmp_path: Path,
) -> None:
    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    rolling_stub, _ = _fake_rolling_generator(error="provider_unavailable")

    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=lambda *args, **kwargs: None,
        rolling_generator=rolling_stub,
    )
    result = bootstrapper.run()
    checkpoint = bootstrapper.read_checkpoint()

    assert not result.ready
    assert checkpoint["status"] == "failed"
    failed = [phase for phase in checkpoint["phases"] if phase["status"] == "failed"]
    assert failed == [
        {
            "id": "chapter_window",
            "status": "failed",
            "artifact": {},
            "error": "provider_unavailable",
        }
    ]


def test_bootstrapper_legacy_approved_uses_rolling_only(tmp_path: Path) -> None:
    """When the three-level outline is already valid, the
    bootstrapper must not call the planning generator.
    """

    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    rolling_stub, rolling_calls = _fake_rolling_generator()

    planning_called = {"count": 0}

    def planning_generate(*args: Any, **kwargs: Any) -> Any:
        planning_called["count"] += 1
        raise AssertionError("planning generator must not be called for legacy-approved")

    from packages.story_core.continuation_outline_bootstrap import (
        ContinuationOutlineBootstrapper,
    )

    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=planning_generate,
        rolling_generator=rolling_stub,
    )
    result = bootstrapper.run()

    assert result.ready
    assert planning_called["count"] == 0
    assert len(rolling_calls) == 1
    assert rolling_calls[0]["chapter_numbers"] == [148, 149, 150, 151, 152]


def test_bootstrapper_preserves_manual_rolling_chapters(tmp_path: Path) -> None:
    """A user-edited rolling chapter (source="manual") must
    survive a fresh bootstrap run.
    """

    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    from packages.story_core.outline_rolling_store import RollingOutlineStore

    store = RollingOutlineStore(root)
    manual_chapter = {
        "chapter_number": 148,
        "title": "用户自定义章节",
        "chapter_goal": "用户手动填写的目标",
        "core_conflict": "用户手动填写的冲突",
        "cast": [{"name": "林修", "role": "protagonist", "character_tier": "protagonist"}],
        "scenes": [
            {"location": "万修坊", "action": "用户填写的场景", "result": "用户填写的结果"},
            {"location": "维修铺", "action": "用户填写的场景二", "result": "用户填写的结果二"},
        ],
        "gain": "用户填写的收获",
        "cost": "用户填写的代价",
        "foreshadowing": [],
        "hook": "用户填写的钩子",
        "state_delta": "用户填写的状态变化",
        "source": "manual",
    }
    store.apply_rolling_batch(
        chapters=[manual_chapter],
        expected_chapter_numbers=[148],
        volume_range=(148, 160),
    )

    rolling_stub, rolling_calls = _fake_rolling_generator()

    from packages.story_core.continuation_outline_bootstrap import (
        ContinuationOutlineBootstrapper,
    )

    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("planning must not be called for legacy-approved")
        ),
        rolling_generator=rolling_stub,
    )
    result = bootstrapper.run()
    assert result.ready

    # The rolling generator was called only for the missing
    # chapters (149-152), not for 148 (already manual).
    assert rolling_calls[0]["chapter_numbers"] == [149, 150, 151, 152]

    # The manual chapter's title survived.
    rolling = RollingOutlineStore(root).read_rolling_outline()
    chapter_148 = next(
        chapter
        for chapter in rolling["chapters"]
        if chapter["chapter_number"] == 148
    )
    assert chapter_148["title"] == "用户自定义章节"
    assert chapter_148["source"] == "manual"


def test_bootstrapper_invalid_chapter_batch_writes_nothing(tmp_path: Path) -> None:
    """A bad rolling batch (blank gain) must leave the rolling
    outline file byte-identical to the pre-call state.
    """

    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    from packages.story_core.outline_rolling_store import RollingOutlineStore

    bad_chapter = {
        "chapter_number": 148,
        "title": "错误章节",
        "chapter_goal": "错误目标",
        "core_conflict": "错误冲突",
        "cast": [{"name": "林修", "role": "protagonist", "character_tier": "protagonist"}],
        "scenes": [
            {"location": "万修坊", "action": "测试", "result": "测试结果"},
            {"location": "维修铺", "action": "测试二", "result": "测试结果二"},
        ],
        "gain": "",  # invalid
        "cost": "错误代价",
        "foreshadowing": [],
        "hook": "错误钩子",
        "state_delta": "错误状态",
    }
    rolling_stub, _ = _fake_rolling_generator(chapters=[bad_chapter])
    from packages.story_core.continuation_outline_bootstrap import (
        ContinuationOutlineBootstrapper,
    )

    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("planning must not be called for legacy-approved")
        ),
        rolling_generator=rolling_stub,
    )
    result = bootstrapper.run()
    assert not result.ready
    assert any("import_chapter_window_required" in err for err in result.errors)
    # The rolling outline file was never created.
    assert not (root / ".story-system" / "outline-generation" / "rolling_outline.json").is_file()


def test_bootstrapper_resumes_from_persisted_checkpoints(tmp_path: Path) -> None:
    """A re-run with the same input fingerprint must reuse
    completed phases and skip the model call.
    """

    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    rolling_stub, rolling_calls = _fake_rolling_generator()
    planning_calls: list[None] = []

    def planning_generate(*args: Any, **kwargs: Any) -> Any:
        planning_calls.append(None)
        raise AssertionError("planning must not be called for legacy-approved")

    from packages.story_core.continuation_outline_bootstrap import (
        ContinuationOutlineBootstrapper,
    )

    first = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=planning_generate,
        rolling_generator=rolling_stub,
    )
    result = first.run()
    assert result.ready
    assert len(rolling_calls) == 1

    # A second run with the same input must not call the
    # rolling generator again.
    second = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=planning_generate,
        rolling_generator=rolling_stub,
    )
    result = second.run()
    assert result.ready
    assert len(rolling_calls) == 1  # no new call
    assert planning_calls == []


def test_bootstrapper_preserves_legacy_vs_explicit_empty_module_selection(tmp_path: Path) -> None:
    root = _seed_legacy_approved_project(tmp_path, current_chapter=147)
    project_path = root / ".webnovel" / "project.json"
    project = _read_json(project_path)
    project["enabled_skill_ids"] = ["commercial-shuangwen"]
    project.pop("enabled_skill_module_ids", None)
    _write_json(project_path, project)
    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=lambda *args, **kwargs: None,
        rolling_generator=lambda *args, **kwargs: None,
    )

    legacy_fingerprint = bootstrapper._compute_fingerprint({})

    assert bootstrapper._enabled_skill_module_ids() is None
    assert bootstrapper._require_shuangwen_contracts() is True

    project["enabled_skill_module_ids"] = []
    _write_json(project_path, project)

    assert bootstrapper._enabled_skill_module_ids() == []
    assert bootstrapper._require_shuangwen_contracts() is False
    assert bootstrapper._compute_fingerprint({}) != legacy_fingerprint
