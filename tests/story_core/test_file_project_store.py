import json
import importlib
import importlib.util
import os
import re
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import packages.story_core.file_project_store as file_project_store_module

from packages.story_core.file_project_store import (
    ChapterQualityError,
    FileProjectStore,
    _assert_auto_chapter_quality,
    _assert_auto_chapter_length,
    _chapter_outline_title,
    _chapter_length_review,
    _manual_chapter_quality_report,
    _project_legacy_review,
    _regeneration_quality_blocking,
)
from packages.story_core.outline_planning_generation import GeneratedChapterWindow
from packages.story_core.project_outline import ArcOutline
from packages.story_core.outline_rolling_store import RollingOutlineStore
from packages.story_core.volume_detail_checkpoints import VolumeDetailCheckpointStore


def _seed_generation_outline(root: Path, chapter_number: int) -> None:
    volume_start = ((chapter_number - 1) // 50) * 50 + 1
    volume_end = volume_start + 49
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    base_arc = dict(outline["arcs"][0])
    base_arc.update(
        {
            "id": f"volume-{volume_start}",
            "start_chapter": volume_start,
            "end_chapter": volume_end,
            "is_final_arc": False,
            "story_nodes": _story_nodes(volume_start, volume_end),
        }
    )
    outline["arcs"] = [base_arc]
    outline["chapters"] = []
    outline_path = root / ".webnovel" / "outline.json"
    outline_path.write_text(
        json.dumps(outline, ensure_ascii=False),
        encoding="utf-8",
    )
    path = root / ".story-system" / "outline-generation" / "rolling_outline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "rolling-outline/v1",
                "chapters": [
                    {
                        "chapter_number": number,
                        "title": f"Chapter {number}",
                        "chapter_goal": "Advance the test chapter.",
                        "core_conflict": "Resolve the test conflict.",
                        "cast": [{"name": "Lead", "role": "protagonist", "this_chapter_role": "act"}],
                        "scenes": [{"location": "test", "action": "advance", "result": "complete"}],
                        "gain": "progress",
                        "cost": "effort",
                        "foreshadowing": [],
                        "hook": "continue",
                        "state_delta": "test state advances",
                        "source": "manual",
                    }
                    for number in range(volume_start, volume_end + 1)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_manual_quality_report_passes_explicit_genre_context_to_style_review(monkeypatch):
    captured = {}

    def fake_style(body, *, genre_context=None):
        captured["genre_context"] = genre_context
        return {"pass": True, "scores": {}, "issues": [], "revision_plan": []}

    monkeypatch.setattr(file_project_store_module, "review_prose_style", fake_style)

    _manual_chapter_quality_report(
        {
            "chapter_number": 1,
            "chapter_title": "test",
            "body": "plain body",
            "next_outline": "continue",
            "chapter_summary": {"summary": "test", "facts": []},
            "updated_story": {"timeline": [], "chapter_summaries": []},
        },
        genre_context={"genre_plugin_ids": ["game_webnovel"]},
    )

    assert captured["genre_context"] == {"genre_plugin_ids": ["game_webnovel"]}


def test_world_state_load_projects_legacy_dynamic_fields_without_mutating_files(tmp_path):
    root = tmp_path / "legacy-world-context"
    webnovel = root / ".webnovel"
    webnovel.mkdir(parents=True)
    project = {
        "project_id": "legacy-world-context",
        "title": "Legacy",
        "current_focus": "守住神殿入口。",
        "world_blueprint": {
            "premise": "灵气依赖地脉。",
            "current_arc": "雪山神殿封锁。",
            "continuity_state": {"running_facts": ["林修负伤。"]},
        },
    }
    state = {
        "story_id": "legacy-world-context",
        "outline": "",
        "genre": "xuanhuan",
        "style": "",
        "current_chapter": 147,
        "world_facts": ["第147章事实：林修负伤。", "第147章摘要：长摘要不应进入事实。"],
        "characters": [],
    }
    (webnovel / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    (webnovel / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    visible = FileProjectStore(root).state()

    assert visible["world_snapshot"]["current_arc"] == "雪山神殿封锁。"
    assert visible["continuity_facts"] == [
        {
            "text": "林修负伤。",
            "source_chapter": 147,
            "status": "active",
            "updated_chapter": 147,
        }
    ]
    assert "world_snapshot" not in json.loads((webnovel / "state.json").read_text(encoding="utf-8"))


def test_sync_state_writes_continuity_facts_without_copying_summary_to_world_facts(tmp_path):
    root = tmp_path / "new-world-context"
    webnovel = root / ".webnovel"
    webnovel.mkdir(parents=True)
    (webnovel / "project.json").write_text(
        json.dumps(
            {
                "project_id": "new-world-context",
                "title": "New",
                "world_blueprint": {"premise": "灵气依赖地脉。"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = FileProjectStore(root)
    synced = store._sync_state_after_chapter(
        {"story_id": "new-world-context", "world_facts": ["世界前提：灵气依赖地脉。"]},
        {
            "chapter_number": 1,
            "chapter_title": "神殿封门",
            "body": "林修退到门边。",
            "next_outline": "守住入口。",
            "chapter_summary": {
                "chapter_number": 1,
                "chapter_title": "神殿封门",
                "summary": "林修负伤后封住神殿入口。",
                "facts": ["林修负伤。", "神殿入口已经封死。"],
                "unresolved_threads": [],
                "resolved_threads": [],
                "next_focus": "守住入口。",
            },
        },
    )

    assert [item["text"] for item in synced["continuity_facts"]] == [
        "林修负伤。",
        "神殿入口已经封死。",
    ]
    assert synced["world_facts"] == ["世界前提：灵气依赖地脉。"]
    assert all("摘要" not in str(item) for item in synced["world_facts"])


def test_manual_quality_report_forwards_genre_context_and_reuses_cold_reader_report(monkeypatch):
    """The manual write/rewrite path should call the deterministic
    cold-reader reviewer exactly once, forward the supplied
    ``genre_context`` unchanged, and emit a canonical
    ``review-result/v2`` payload — no longer routing through the three
    legacy agent reviews (reader/editor/reviewer).
    """
    genre_context = {"genre": "玄幻", "genre_plugin_ids": ["xuanhuan"]}
    captured = {"cold_reader_calls": 0}
    cold_reader_report = {
        "reviewer": "cold_reader/v1",
        "pass": True,
        "scores": {},
        "issues": [],
        "revision_plan": [],
        "previous_summary_used": True,
    }

    def fake_cold_reader(body, *, previous_summary="", genre_context=None):
        captured["cold_reader_calls"] += 1
        captured["genre_context"] = genre_context
        return cold_reader_report

    monkeypatch.setattr(file_project_store_module, "review_cold_reader_experience", fake_cold_reader)

    report = _manual_chapter_quality_report(
        {
            "chapter_number": 1,
            "chapter_title": "test",
            "body": "plain body",
            "next_outline": "continue",
            "event_plan": {"summary": "previous"},
            "chapter_summary": {"summary": "test", "facts": []},
            "updated_story": {"timeline": [], "chapter_summaries": []},
        },
        genre_context=genre_context,
    )

    assert captured["cold_reader_calls"] == 1
    assert captured["genre_context"] is genre_context
    # The 3 legacy agent review fields are gone — the manual path now
    # exposes the canonical v2 contract instead.
    for legacy_key in ("reader_agent_review", "editor_agent_review", "reviewer_agent_review"):
        assert legacy_key not in report
        assert legacy_key not in report.get("writing_review", {})
    review_result = report.get("review_result")
    assert isinstance(review_result, dict)
    assert review_result.get("schema_version") == "review-result/v2"
    assert review_result.get("status") in {"passed", "warning", "blocked"}


def test_auto_quality_gate_allows_advisory_review_and_records_warning():
    report = {
        "ok": False,
        "issues": ["writing_review"],
        "writing_review": {"pass": False, "issues": ["对话仍不自然。"]},
        "simplified_review": {"has_hard_errors": False, "needs_revision": True},
    }

    _assert_auto_chapter_quality(report, operation="regenerate")

    assert report["quality_warning"]["needs_revision"] is True


def test_auto_chapter_length_rejects_body_above_hard_max():
    body = "正文" * 2851  # 5702 non-whitespace characters

    review = _chapter_length_review(body)

    assert review["pass"] is False
    assert review["max_chars"] == 5500
    assert review["hard_max_chars"] == 5700
    with pytest.raises(ValueError, match="硬上限5700字"):
        _assert_auto_chapter_length(body, operation="generate")


def test_shared_chapter_length_policy_is_the_single_source():
    module_name = "packages.story_core.chapter_length_policy"
    assert importlib.util.find_spec(module_name) is not None
    policy = importlib.import_module(module_name)

    assert policy.CHAPTER_HARD_MIN_CHARS == 3800
    assert policy.CHAPTER_TARGET_MIN_CHARS == 4200
    assert policy.CHAPTER_TARGET_MAX_CHARS == 5500
    assert policy.CHAPTER_HARD_MAX_CHARS == 5700
    assert file_project_store_module.FILE_CHAPTER_MIN_CHARS == policy.CHAPTER_HARD_MIN_CHARS
    assert file_project_store_module.FILE_CHAPTER_TARGET_MIN_CHARS == policy.CHAPTER_TARGET_MIN_CHARS
    assert file_project_store_module.FILE_CHAPTER_MAX_CHARS == policy.CHAPTER_TARGET_MAX_CHARS
    assert file_project_store_module.FILE_CHAPTER_HARD_MAX_CHARS == policy.CHAPTER_HARD_MAX_CHARS


def test_file_project_state_normalizes_all_inventory_views(tmp_path):
    root = tmp_path / "inventory-project"
    state_path = root / ".webnovel" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "genre": "网游",
                "genre_plugin_ids": ["game_webnovel"],
                "characters": [
                    {
                        "name": "苏叶",
                        "role": "protagonist",
                        "game_state": {
                            "current": {
                                "inventory": {
                                    "里静静堆叠着【灰狼毒腺": 7,
                                    "】与【粗糙狼皮": 7,
                                }
                            }
                        },
                    }
                ],
                "progression_ledger": {
                    "economy": {
                        "inventory": {
                            "背包里还剩【灰狼毒腺": 7,
                            "】与【粗糙狼皮": 7,
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    state = FileProjectStore(root).state()

    assert state["characters"][0]["game_state"]["current"]["inventory"] == {
        "灰狼毒腺": 7,
        "粗糙狼皮": 7,
    }
    assert state["progression_ledger"]["economy"]["inventory"] == {
        "灰狼毒腺": 7,
        "粗糙狼皮": 7,
    }


def test_project_legacy_review_synthesizes_v2_envelope_for_v1_payload():
    """A persisted v1 review payload (saved before the v2 contract
    existed) must keep its simplified-review/v1 envelope under
    ``simplified_review`` AND expose a real ``review-result/v2`` shape
    under ``review_result`` — never the v1 dict in the v2 slot.
    """
    payload = {
        "issues": ["时间线冲突", "对白过长"],
        "revision_plan": ["修复时间线顺序", "缩短对白"],
        "pass": False,
        "has_hard_errors": True,
    }

    projected = _project_legacy_review(payload)

    # The v1 dict is still kept under simplified_review for backward
    # compat with the front-end fallback and historical read paths.
    assert isinstance(projected.get("simplified_review"), dict)
    assert "reader_agent_review" not in projected["simplified_review"]  # build_simplified_review normalizes

    # The v2 contract is a real review-result/v2 payload, not a copy
    # of the v1 dict.
    review_result = projected["review_result"]
    assert isinstance(review_result, dict)
    assert review_result["schema_version"] == "review-result/v2"
    assert review_result["status"] in {"passed", "warning", "blocked"}
    assert review_result["has_hard_errors"] is True
    assert review_result["needs_revision"] is True
    # Each v1 issue becomes a structured ReviewFinding dict.
    assert len(review_result["issues"]) == 2
    first_issue = review_result["issues"][0]
    assert first_issue["message"] == "时间线冲突"
    # Paired revision_plan[i] becomes the suggestion.
    assert first_issue["suggestion"] == "修复时间线顺序"
    # The second issue also gets its paired plan.
    second_issue = review_result["issues"][1]
    assert second_issue["suggestion"] == "缩短对白"


def test_project_legacy_review_preserves_existing_v2_payload():
    """If a payload already has a real v2 ``review_result``, the
    projection must not clobber it; it should only ensure a
    ``simplified_review`` mirror exists.
    """
    payload = {
        "review_result": {
            "schema_version": "review-result/v2",
            "status": "passed",
            "pass": True,
            "has_hard_errors": False,
            "issues": [],
        },
        "issues": ["stale v1 issue"],
    }

    projected = _project_legacy_review(payload)

    assert projected["review_result"]["schema_version"] == "review-result/v2"
    assert projected["review_result"]["status"] == "passed"
    # simplified_review mirrors the v2 payload (not the stale v1 issue).
    assert projected["simplified_review"] == projected["review_result"]
from packages.story_core.models import ChapterSummary, StoryState, TimelineEvent
from packages.story_core.outline_planning import GeneratedOutlinePlan
from packages.story_core.skill_packs import import_skill_pack_from_path
from packages.story_core.orchestrator import (
    _failed_bundle,
    _render_compression_length_prompt,
    _render_expansion_length_prompt,
)
from packages.story_core.prompt_templates import prompt_template_scope
from packages.story_core.world_blueprint_context import flatten_selected_rules
from packages.story_core.web_game_economy import (
    normalize_legacy_economy_prompt_value,
    opening_market_exchange_flow_lines,
)


def _long_test_body(label: str = "Night Ember keeps the chapter grounded.") -> str:
    unit = label + " He checks the task, pays a visible cost, gains a result, and leaves a next step.\n"
    unit_chars = max(1, len("".join(unit.split())))
    return unit * max(1, 4500 // unit_chars)


def test_first_chapter_regeneration_removes_post_chapter_character_states(tmp_path):
    store = FileProjectStore(tmp_path)
    reset = store._conservative_regeneration_state(
        {
            "current_chapter": 1,
            "world_facts": [
                "《神域》是全沉浸网游。",
                "夜烬已完成灰石裂缝外沿复查，获得灰石二段通行记录。",
                "寄售功能将于开服次日夜间开放测试，提现规则将同步公示。",
            ],
            "characters": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "game_id": "夜烬",
                    "real_state": {"current": {"balance": "312.60元"}},
                    "game_state": {"current": {"level": "Lv.1"}},
                    "memory": ["现实急账已在第一章解决，余额312.60元。"],
                }
            ],
        }
    )

    assert reset["characters"] == []
    assert reset["world_facts"] == []
    assert reset["current_chapter"] == 0


def test_first_chapter_regeneration_keeps_structured_portrait_from_visible_state(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "rewrite-character-portrait",
        project={
            "project_id": "p-rewrite-character-portrait",
            "title": "Repair Shop",
            "character_profiles": [
                {
                    "name": "Shen Chuan",
                    "role": "watch shop owner",
                    "motivation": "Keep the shop open",
                    "personality": "Reserved and exacting",
                    "speech_style": "Speaks briefly",
                }
            ],
        },
        state={
            "story_id": "s-rewrite-character-portrait",
            "outline": "A father and son investigate an old watch.",
            "genre": "urban",
            "style": "",
            "current_chapter": 1,
            "characters": [
                {
                    "name": "Shen Chuan",
                    "role": "watch shop owner",
                    "story_drive": {
                        "immediate_goal": "Identify the old watch",
                        "long_term_goal": "Repair the family relationship",
                        "motivation": "Protect the shop and learn why his son returned",
                    },
                    "performance_profile": {
                        "speech_style": "Reserved, but answers in complete sentences",
                        "action_style": "Checks physical evidence before deciding",
                    },
                    "current_emotion": "CHAPTER1_EMOTION",
                    "location": "CHAPTER1_LOCATION",
                    "memory": ["CHAPTER1_MEMORY"],
                }
            ],
        },
    )

    reset = store._conservative_regeneration_state(store.state())
    character = reset["characters"][0]

    assert character["story_drive"]["motivation"] == "Protect the shop and learn why his son returned"
    assert character["performance_profile"]["speech_style"] == "Reserved, but answers in complete sentences"
    assert "current_emotion" not in character
    assert "location" not in character
    assert "memory" not in character


def test_first_chapter_regeneration_drops_null_character_profile_fields(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "rewrite-null-profile",
        project={
            "project_id": "p-rewrite-null-profile",
            "title": "Repair Shop",
            "character_profiles": [
                {
                    "name": "沈川",
                    "role": "protagonist",
                    "character_type": None,
                    "core_motivation": None,
                    "poison_points": None,
                    "social_profile": None,
                }
            ],
        },
        state={
            "story_id": "s-rewrite-null-profile",
            "current_chapter": 1,
            "characters": [
                {
                    "name": "沈川",
                    "role": "protagonist",
                    "current_life_profile": {
                        "economic_state": None,
                        "immediate_problem": None,
                    },
                    "story_drive": {"immediate_goal": None},
                }
            ],
        },
    )

    base_state = store._conservative_regeneration_state(store.state())
    payload = store._story_state_payload_for_direction(base_state, store.project(), 1)

    StoryState.model_validate(payload)
    assert "character_type" not in base_state["characters"][0]
    assert "poison_points" not in base_state["characters"][0]
    assert "current_life_profile" not in payload["characters"][0]
    assert "story_drive" not in payload["characters"][0]


def test_visible_character_card_softens_professional_checklist_speech(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "natural-professional-speech",
        project={"project_id": "p-natural-professional-speech", "title": "Repair Shop"},
        state={
            "story_id": "s-natural-professional-speech",
            "outline": "A son investigates a redevelopment project.",
            "genre": "urban",
            "style": "",
            "characters": [
                {
                    "name": "Shen Yu",
                    "role": "supporting",
                    "performance_profile": {
                        "speech_style": "说话像在核对条款，常用流程、数据和时间节点压人。"
                    },
                }
            ],
        },
    )

    speech = store.state()["characters"][0]["performance_profile"]["speech_style"]

    assert "追问具体依据" in speech
    assert "不连续罗列术语或材料" in speech
    assert "像在核对条款" not in speech


def test_chapter_outline_title_uses_matching_detailed_outline_title():
    outline_context = {
        "chapter": {
            "chapter_number": 1,
            "title": "灰狼坡的第一笔到账",
        }
    }

    assert _chapter_outline_title(outline_context, 1) == "灰狼坡的第一笔到账"
    assert _chapter_outline_title(outline_context, 2) is None


def test_regeneration_gate_blocks_missing_first_chapter_core_scene_fact():
    writing_review = {
        "issues": [
            "第一章外部压力过早：公会信息提前介入。",
            "场景卡必写内容缺失：缺少现实职业/技能来源。",
            "现代中文对话不自然：存在清单式短句。",
        ],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }

    assert _regeneration_quality_blocking({"issues": ["writing_review"]}, writing_review) is True


def test_regeneration_gate_blocks_missing_first_monster_panel():
    writing_review = {
        "issues": ["首次与怪物交战前缺少简洁怪物面板。"],
        "critical_review": {
            "hard_issues": ["首次与怪物交战前缺少简洁怪物面板。"],
            "severity_summary": {"has_hard_violation": True},
        },
    }

    assert _regeneration_quality_blocking({"issues": ["writing_review"]}, writing_review) is True


def test_chapter_sync_persists_equipment_cards_to_world_blueprint(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "equipment-sync",
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "world_blueprint": {"equipment_cards": []},
        },
    )
    card = {
        "name": "Dusk Verdict",
        "equipment_type": "weapon",
        "rarity": "epic",
        "current_owner": "Night Ember",
    }

    store._sync_after_chapter(
        {"chapter_number": 8, "chapter_title": "Vault", "body": "body"},
        {
            "story_id": "s-file",
            "genre": "game_webnovel",
            "genre_plugin_ids": ["game_webnovel"],
            "equipment_cards": [card],
        },
    )

    persisted = store.project()["world_blueprint"]["equipment_cards"]
    assert len(persisted) == 1
    assert persisted[0]["name"] == "Dusk Verdict"


def test_writing_packet_selects_relevant_equipment_cards(tmp_path):
    project = {
        "project_id": "p-file",
        "title": "File Novel",
        "active_story_id": "s-file",
        "current_focus": "Find Dusk Verdict in Ashen Hall",
        "world_blueprint": {
            "genre_plugin_ids": ["game_webnovel"],
            "equipment_cards": [
                {"name": "Dusk Verdict", "equipment_type": "weapon", "current_owner": "Night Ember"},
                {"name": "Tide Ring", "equipment_type": "accessory", "current_owner": "Tide Priest"},
            ],
        },
    }
    store = _make_minimal_file_project(
        tmp_path / "equipment-context",
        project=project,
        state={
            "story_id": "s-file",
            "genre": "game_webnovel",
            "genre_plugin_ids": ["game_webnovel"],
            "style": "commercial",
            "current_chapter": 0,
            "characters": [{"name": "Night Ember", "role": "protagonist"}],
        },
    )

    packet, is_game_story, _ = store._build_writing_packet(1)
    story_payload = store._story_state_payload_for_direction(store.state(), store.project(), 1)

    assert is_game_story is True
    assert [item["name"] for item in packet["equipment_cards"]] == ["Dusk Verdict"]
    assert packet["project"]["world_blueprint"]["equipment_cards"] == packet["equipment_cards"]
    assert [item["name"] for item in story_payload["equipment_cards"]] == ["Dusk Verdict", "Tide Ring"]


def test_writing_packet_separates_static_world_snapshot_and_continuity_facts(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "world-context-packet",
        project={
            "project_id": "world-context-packet",
            "title": "World Context",
            "current_focus": "守住神殿入口。",
            "world_blueprint": {
                "genre_plugin_ids": ["xuanhuan"],
                "premise": "灵气依赖地脉。",
                "current_arc": "雪山神殿封锁。",
                "continuity_state": {
                    "running_facts": ["林修负伤。"],
                    "chapter_facts": [{"chapter_number": 147, "facts": ["林修负伤。"]}],
                },
            },
        },
        state={
            "story_id": "world-context-packet",
            "genre": "xuanhuan",
            "style": "",
            "current_chapter": 147,
            "characters": [{"name": "林修", "role": "protagonist"}],
            "world_facts": [
                "世界前提：灵气依赖地脉。",
                "第147章事实：林修负伤。",
                "第147章摘要：林修在雪山神殿与敌人周旋。",
            ],
        },
    )

    packet = store.writing_packet(148)

    assert packet["project"]["world_blueprint"].get("premise") == "灵气依赖地脉。"
    assert "current_arc" not in packet["project"]["world_blueprint"]
    assert "continuity_state" not in packet["project"]["world_blueprint"]
    assert packet["state"]["world_snapshot"]["current_arc"] == "雪山神殿封锁。"
    assert [item["text"] for item in packet["state"]["continuity_facts"]] == ["林修负伤。"]
    assert "world_facts" not in packet["state"]
    assert "林修在雪山神殿与敌人周旋" not in json.dumps(packet, ensure_ascii=False)


def _make_minimal_file_project(root, *, state=None, project=None):
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": project or {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(project or {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(state or {"story_id": "s-file", "current_chapter": 0, "world_facts": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return FileProjectStore(root)


def _manual_shuangwen_report():
    return {
        "schema_version": "skill-review/v1",
        "skill_id": "commercial-shuangwen",
        "executed": True,
        "status": "warning",
        "summary": "The payoff needs one observable result.",
        "checks": {
            "goal": [],
            "pressure": [],
            "information_gap": [],
            "counterattack": [],
            "payoff": ["The order result is not visible."],
            "reaction": [],
            "ending_hook": [],
            "cliches": [],
        },
        "issues": ["Show whether the order was credited."],
        "runtime": "test-runtime",
        "model": "test-reviewer",
        "trace_id": "trace-store-review",
    }


def _seed_manual_shuangwen_chapter(store):
    chapter = {
        "chapter_number": 1,
        "chapter_title": "Receipt",
        "body": "Lin Xiu presents the archived receipt.",
        "quality_report": {"ok": True, "issues": []},
    }
    chapter_path = store.story_system_dir / "chapters" / "0001.json"
    review_path = store.story_system_dir / "reviews" / "0001.json"
    store._write_json(chapter_path, chapter)
    store._write_json(review_path, chapter["quality_report"])
    return chapter, chapter_path, review_path


def _store_manual_shuangwen_report(store, chapter, chapter_path, report):
    from hashlib import sha256

    return store._store_shuangwen_review(
        chapter_number=1,
        report=report,
        expected_artifact_hash=sha256(chapter_path.read_bytes()).hexdigest(),
        expected_body_hash=sha256(chapter["body"].encode("utf-8")).hexdigest(),
        expected_candidate_hash=store._candidate_artifacts_hash(),
    )


def test_manual_shuangwen_review_synchronizes_chapter_sidecar_and_latest_review(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "manual-review-sidecar",
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": []},
    )
    chapter, chapter_path, _review_path = _seed_manual_shuangwen_chapter(store)
    report = _manual_shuangwen_report()

    _store_manual_shuangwen_report(store, chapter, chapter_path, report)

    chapter_report = store.chapter(1)["quality_report"]["skill_reviews"]["commercial-shuangwen"]
    sidecar_report = store.review(1)["skill_reviews"]["commercial-shuangwen"]
    latest_report = store.writing_packet(2)["latest_review"]["skill_reviews"]["commercial-shuangwen"]
    assert chapter_report == report
    assert sidecar_report == report
    assert latest_report == report


def test_manual_shuangwen_review_rolls_back_both_files_when_second_replace_fails(
    tmp_path,
    monkeypatch,
):
    store = _make_minimal_file_project(
        tmp_path / "manual-review-sidecar-rollback",
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": []},
    )
    chapter, chapter_path, review_path = _seed_manual_shuangwen_chapter(store)
    chapter_before = chapter_path.read_bytes()
    review_before = review_path.read_bytes()
    original_replace = store.snapshot_store._replace_file
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second review write failure")
        return original_replace(source, target)

    monkeypatch.setattr(store.snapshot_store, "_replace_file", fail_second_replace)

    with pytest.raises(OSError, match="injected second review write failure"):
        _store_manual_shuangwen_report(
            store,
            chapter,
            chapter_path,
            _manual_shuangwen_report(),
        )

    assert chapter_path.read_bytes() == chapter_before
    assert review_path.read_bytes() == review_before
    assert "skill_reviews" not in store.chapter(1)["quality_report"]
    assert "skill_reviews" not in store.review(1)
    assert "skill_reviews" not in store.writing_packet(2)["latest_review"]


@pytest.mark.parametrize(
    ("changed_artifact", "expected_error"),
    [
        ("chapter", "shuangwen_review_chapter_changed"),
        ("body", "shuangwen_review_body_changed"),
        ("candidate", "shuangwen_review_candidate_changed"),
    ],
)
def test_manual_shuangwen_review_checks_all_hashes_before_persisting(
    tmp_path,
    monkeypatch,
    changed_artifact,
    expected_error,
):
    from hashlib import sha256

    store = _make_minimal_file_project(
        tmp_path / f"manual-review-{changed_artifact}-conflict",
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": []},
    )
    body = "Lin Xiu presents the archived receipt."
    markdown_path = store.root / "chapters" / "0001-Receipt.md"
    markdown_path.write_text(body, encoding="utf-8")
    chapter = {
        "chapter_number": 1,
        "chapter_title": "Receipt",
        "body_path": "chapters/0001-Receipt.md",
        "body_sha256": sha256(body.encode("utf-8")).hexdigest(),
        "quality_report": {"ok": True, "issues": []},
    }
    chapter_path = store.story_system_dir / "chapters" / "0001.json"
    review_path = store.story_system_dir / "reviews" / "0001.json"
    store._write_json(chapter_path, chapter)
    store._write_json(review_path, chapter["quality_report"])
    expected_artifact_hash = sha256(chapter_path.read_bytes()).hexdigest()
    expected_body_hash = sha256(body.encode("utf-8")).hexdigest()
    expected_candidate_hash = store._candidate_artifacts_hash()

    if changed_artifact == "chapter":
        chapter["chapter_title"] = "Changed receipt"
        store._write_json(chapter_path, chapter)
    elif changed_artifact == "body":
        markdown_path.write_text("Concurrent body edit.", encoding="utf-8")
    else:
        store.candidate_store.directory.mkdir(parents=True, exist_ok=True)
        (store.candidate_store.directory / "concurrent.json").write_text(
            "{}",
            encoding="utf-8",
        )

    def forbidden_transaction(_payloads):
        raise AssertionError("conflict reached persistent write")

    monkeypatch.setattr(store, "_replace_json_transaction", forbidden_transaction)

    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        store._store_shuangwen_review(
            chapter_number=1,
            report=_manual_shuangwen_report(),
            expected_artifact_hash=expected_artifact_hash,
            expected_body_hash=expected_body_hash,
            expected_candidate_hash=expected_candidate_hash,
        )

    assert "skill_reviews" not in store.review(1)


def test_manual_shuangwen_review_does_not_raise_conflict_after_successful_commit(
    tmp_path,
    monkeypatch,
):
    store = _make_minimal_file_project(
        tmp_path / "manual-review-post-commit",
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": []},
    )
    chapter, chapter_path, _review_path = _seed_manual_shuangwen_chapter(store)
    original_transaction = store._replace_json_transaction

    def commit_then_create_candidate(payloads):
        original_transaction(payloads)
        store.candidate_store.directory.mkdir(parents=True, exist_ok=True)
        (store.candidate_store.directory / "after-commit.json").write_text(
            "{}",
            encoding="utf-8",
        )

    monkeypatch.setattr(store, "_replace_json_transaction", commit_then_create_candidate)

    result = _store_manual_shuangwen_report(
        store,
        chapter,
        chapter_path,
        _manual_shuangwen_report(),
    )

    assert result == _manual_shuangwen_report()
    assert (
        store.review(1)["skill_reviews"]["commercial-shuangwen"]
        == _manual_shuangwen_report()
    )


def test_direction_payload_keeps_opening_chapter_facts_when_regeneration_rolls_back_state(tmp_path):
    project = {
        "project_id": "p-file",
        "title": "File Novel",
        "active_story_id": "s-file",
        "world_blueprint": {
            "opening_arc": {
                "golden_three_chapters": {
                    "1": {
                        "must_include": [
                            "现实余额从46.83元开始。",
                            "官方兑换实际到账1764.00元。",
                            "底层协议校验、掉落判定×1000、混沌之种未解析。",
                        ]
                    }
                }
            }
        },
    }
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project=project,
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )

    payload = store._story_state_payload_for_direction(store.state(), store.project(), 1)

    assert payload["world_facts"] == project["world_blueprint"]["opening_arc"]["golden_three_chapters"]["1"]["must_include"]


def test_saved_outline_does_not_mix_legacy_opening_facts_into_direction_payload(tmp_path):
    project = {
        "project_id": "p-file",
        "title": "File Novel",
        "active_story_id": "s-file",
        "world_blueprint": {
            "opening_arc": {
                "golden_three_chapters": {
                    "1": {"must_include": ["旧计划：第一章不要升级。"]}
                }
            }
        },
    }
    store = _make_minimal_file_project(
        tmp_path / "saved-outline",
        project=project,
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    (store.webnovel_dir / "outline.json").write_text(
        json.dumps(
            {
                "schema_version": "project-outline/v1",
                "overall": {"story": "新大纲"},
                "arcs": [],
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "第一章",
                        "goal": "本章升到二级",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = store._story_state_payload_for_direction(store.state(), store.project(), 1)

    assert "旧计划：第一章不要升级。" not in payload["world_facts"]


def test_direction_payload_merges_full_project_character_profile_into_story_state(tmp_path):
    project = {
        "project_id": "p-character-sync",
        "title": "修表铺的冬天",
        "active_story_id": "s-character-sync",
        "character_profiles": [
            {
                "name": "沈川",
                "role": "修表铺店主",
                "character_tier": "protagonist",
                "story_drive": {
                    "motivation": "保住修表铺。",
                    "immediate_goal": "确认旧表来历。",
                },
                "performance_profile": {
                    "speech_style": "回应会把原因和决定说清楚。",
                    "action_style": "先查痕迹再判断。",
                },
                "dialogue_examples": ["你先告诉我这块表是从哪里拿到的。"],
            }
        ],
    }
    store = _make_minimal_file_project(
        tmp_path / "character-sync",
        project=project,
        state={
            "story_id": "s-character-sync",
            "genre": "都市",
            "current_chapter": 0,
            "characters": [{"name": "沈川", "role": "protagonist"}],
        },
    )

    payload = store._story_state_payload_for_direction(store.state(), store.project(), 1)
    character = payload["characters"][0]

    assert character["story_drive"]["motivation"] == "保住修表铺。"
    assert character["performance_profile"]["speech_style"] == "回应会把原因和决定说清楚。"
    assert character["dialogue_examples"] == ["你先告诉我这块表是从哪里拿到的。"]
    assert character["goals"] == ["确认旧表来历。"]


def test_summary_reads_chapter_metadata_without_hydrating_full_chapters(tmp_path, monkeypatch):
    store = _make_minimal_file_project(tmp_path / "novel")
    chapters_dir = store.story_system_dir / "chapters"
    for number in range(1, 4):
        (chapters_dir / f"{number:04d}.json").write_text(
            json.dumps(
                {
                    "chapter_number": number,
                    "chapter_title": f"Chapter {number}",
                    "body": "body",
                }
            ),
            encoding="utf-8",
        )

    read_counts: dict[str, int] = {}
    original_read_json = store._read_json

    def counting_read_json(path, default=None):
        if path.parent == chapters_dir and path.suffix == ".json":
            read_counts[path.name] = read_counts.get(path.name, 0) + 1
        return original_read_json(path, default)

    def fail_if_hydrated(_chapter_number=None):
        raise AssertionError("summary must not hydrate full chapter payloads")

    monkeypatch.setattr(store, "chapter", fail_if_hydrated)
    monkeypatch.setattr(store, "_read_json", counting_read_json)

    summary = store.summary()

    assert summary["current_chapter"] == 3
    assert summary["chapter_count"] == 3
    assert summary["chapters"][-1] == {"chapter_number": 3, "chapter_title": "Chapter 3"}
    assert read_counts == {"0001.json": 1, "0002.json": 1, "0003.json": 1}


def test_summary_uses_master_setting_project_metadata_without_project_json(tmp_path, monkeypatch):
    store = _make_minimal_file_project(tmp_path / "novel")
    project_json = store.webnovel_dir / "project.json"
    project_json.unlink()
    (store.story_system_dir / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {
                    "project_id": "p-master",
                    "title": "Master Title",
                    "active_story_id": "s-master",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chapters_dir = store.story_system_dir / "chapters"
    (chapters_dir / "0001.json").write_text(
        json.dumps(
            {
                "chapter_number": 1,
                "body": "body",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    read_counts: dict[str, int] = {}
    original_read_json = store._read_json

    def counting_read_json(path, default=None):
        if path.parent == chapters_dir and path.suffix == ".json":
            read_counts[path.name] = read_counts.get(path.name, 0) + 1
        return original_read_json(path, default)

    monkeypatch.setattr(store, "_read_json", counting_read_json)

    summary = store.summary()

    assert summary["project_id"] == "p-master"
    assert summary["title"] == "Master Title"
    assert summary["active_story_id"] == "s-master"
    assert summary["chapter_count"] == 1
    assert read_counts == {"0001.json": 1}


def test_chapter_index_and_summary_use_chinese_fallback_for_untitled_chapters(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    chapters_dir = store.story_system_dir / "chapters"
    (chapters_dir / "0001.json").write_text(
        json.dumps(
            {
                "chapter_number": 1,
                "body": "body",
                "chapter_summary": {"summary": "Untitled summary.", "next_focus": "continue"},
                "next_outline": "continue",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    index = store.chapter_index()
    summary = store.summary()

    assert index == [
        {
            "chapter_number": 1,
            "chapter_title": "第1章",
            "body_chars": len("body"),
            "summary": "Untitled summary.",
            "next_focus": "continue",
            "has_quality_report": False,
            "has_simulation": False,
        }
    ]
    assert summary["chapters"] == [{"chapter_number": 1, "chapter_title": "第1章"}]


def test_chapter_index_reads_each_file_once_without_display_hydration(tmp_path, monkeypatch):
    store = _make_minimal_file_project(tmp_path / "novel")
    chapters_dir = store.story_system_dir / "chapters"
    long_summary = "Summary one " + ("A" * 500)
    long_next_focus = "Next focus one " + ("B" * 500)
    chapter_payloads = [
        (
            1,
            {
                "chapter_number": 1,
                "chapter_title": "Chapter 1",
                "body": "First draft body.\nWith whitespace.",
                "chapter_summary": {"summary": long_summary, "next_focus": "Carry on."},
                "next_outline": long_next_focus,
                "simulation_status": {"status": "simulated"},
                "quality_report": {"writing_review": {"pass": True, "issues": []}},
            },
        ),
        (
            2,
            {
                "chapter_number": 2,
                "chapter_title": "Chapter 2",
                "body": "Second draft body.",
                "chapter_summary": {"summary": "Second summary.", "next_focus": "Keep moving."},
                "next_outline": "Keep moving.",
                "simulation_status": "legacy truthy",
                "quality_report": {"writing_review": {"pass": True, "issues": []}},
            },
        ),
    ]
    for number, payload in chapter_payloads:
        (chapters_dir / f"{number:04d}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    read_counts: dict[str, int] = {}
    original_read_json = store._read_json

    def counting_read_json(path, default=None):
        if path.parent == chapters_dir and path.suffix == ".json":
            read_counts[path.name] = read_counts.get(path.name, 0) + 1
        return original_read_json(path, default)

    monkeypatch.setattr(
        store,
        "chapter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("chapter_index must not hydrate full chapters")),
    )
    monkeypatch.setattr(store, "_read_json", counting_read_json)

    index = store.chapter_index()

    assert index == [
        {
            "chapter_number": 1,
            "chapter_title": "Chapter 1",
            "body_chars": len("Firstdraftbody.Withwhitespace."),
            "summary": long_summary[:320] + "...",
            "next_focus": long_next_focus[:220] + "...",
            "has_quality_report": True,
            "has_simulation": True,
        },
        {
            "chapter_number": 2,
            "chapter_title": "Chapter 2",
            "body_chars": len("Seconddraftbody."),
            "summary": "Second summary.",
            "next_focus": "Keep moving.",
            "has_quality_report": True,
            "has_simulation": False,
        },
    ]
    assert read_counts == {"0001.json": 1, "0002.json": 1}


def test_story_overview_data_matches_state_character_synthesis_in_one_chapter_pass(
    tmp_path,
    monkeypatch,
):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "genre": "网游",
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "genre": "网游",
            "genre_plugin_ids": ["game_webnovel"],
            "world_facts": [],
            "characters": [],
            "progression_ledger": {
                "protagonist": {
                    "real_name": "苏叶",
                    "game_id": "夜烬",
                    "level": "Lv.3",
                    "exp": "196/300",
                },
                "economy": {"game_currency": "39铜币", "inventory": {"灰狼毒腺": 11}},
            },
        },
    )
    chapters_dir = store.story_system_dir / "chapters"
    (chapters_dir / "0001.json").write_text(
        json.dumps(
            {
                "chapter_number": 1,
                "chapter_title": "药剂铺窗口",
                "body": "夜烬走进药剂铺。灰头巾老妇人抬头，药剂师只按十份一批收货。",
                "chapter_summary": {
                    "summary": "夜烬向药剂师提交材料。",
                    "next_focus": "返回灰狼坡。",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (store.webnovel_dir / "project.json").unlink()
    expected_state = store.state()
    read_counts: dict[str, int] = {}
    original_read_json = store._read_json

    def counting_read_json(path, default=None):
        if path.parent == chapters_dir and path.suffix == ".json":
            read_counts[path.name] = read_counts.get(path.name, 0) + 1
        return original_read_json(path, default)

    monkeypatch.setattr(store, "_read_json", counting_read_json)
    monkeypatch.setattr(
        store,
        "chapter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("story overview must not hydrate chapters")
        ),
    )

    overview = store.story_overview_data()

    assert overview["project"]["project_id"] == "p-file"
    assert overview["state"]["characters"] == expected_state["characters"]
    assert {card["name"] for card in overview["state"]["characters"]} >= {
        "苏叶",
        "药剂师洛婶",
    }
    assert overview["chapters"][0]["chapter_title"] == "药剂铺窗口"
    assert read_counts == {"0001.json": 1}


def test_explicit_chapter_access_does_not_enumerate_chapter_numbers(tmp_path, monkeypatch):
    store = _make_minimal_file_project(tmp_path / "novel")
    (store.story_system_dir / "chapters" / "0002.json").write_text(
        json.dumps(
            {
                "chapter_number": 2,
                "chapter_title": "Direct chapter",
                "body": "Loaded directly.",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        store,
        "chapter_numbers",
        lambda: (_ for _ in ()).throw(
            AssertionError("explicit chapter access must not enumerate chapters")
        ),
    )

    chapter = store.chapter(2)

    assert chapter["chapter_number"] == 2
    assert chapter["body"] == "Loaded directly."


def test_chapter_without_number_preserves_latest_and_no_chapters_semantics(
    tmp_path,
    monkeypatch,
):
    empty_store = _make_minimal_file_project(tmp_path / "empty")
    with pytest.raises(FileNotFoundError, match="no_chapters"):
        empty_store.chapter()
    monkeypatch.setattr(
        empty_store,
        "chapter_numbers",
        lambda: (_ for _ in ()).throw(
            AssertionError("explicit missing chapter must not enumerate chapter numbers")
        ),
    )
    with pytest.raises(FileNotFoundError, match="no_chapters"):
        empty_store.chapter(1)

    store = _make_minimal_file_project(tmp_path / "novel")
    chapters_dir = store.story_system_dir / "chapters"
    for number in (1, 2):
        (chapters_dir / f"{number:04d}.json").write_text(
            json.dumps(
                {
                    "chapter_number": number,
                    "chapter_title": f"Chapter {number}",
                    "body": f"Body {number}",
                }
            ),
            encoding="utf-8",
        )

    assert store.chapter()["chapter_number"] == 2
    with pytest.raises(FileNotFoundError, match="chapter_not_found:999"):
        store.chapter(999)


def _file_snapshot(root) -> dict:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _planning_card(name: str, tier: str, *, age: int = 30) -> dict:
    return {
        "name": name,
        "role": tier,
        "character_tier": tier,
        "first_appearance": 0 if tier == "long_term_antagonist" else 1,
        "identity_profile": {
            "age": age,
            "origin": "青石镇",
            "current_identity": "宗门中人",
            "occupation": "处理宗门差事",
        },
        "background_profile": {},
        "current_life_profile": {},
        "story_drive": {"immediate_goal": "控制祖祠", "failure_stakes": "失去位置"},
        "performance_profile": {},
        "dialogue_examples": ["先把事情说清楚。", "这件事要按规矩处理。"],
        "relationship_notes": [],
    }


def _story_nodes(start: int, end: int) -> list[dict]:
    return [
        {
            "start_chapter": node_start,
            "end_chapter": min(node_start + 14, end),
            "objective": f"Advance the volume from chapter {node_start}.",
            "pressure": "Opposition closes in.",
            "turn": "A decisive clue changes the route.",
            "payoff": "The current objective is resolved.",
            "next_effect": "The result drives the next node.",
        }
        for node_start in range(start, end + 1, 15)
    ]


def _generated_opening_plan() -> GeneratedOutlinePlan:
    return GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "overall": {
                    "story": "林照追查祖祠旧案。",
                    "theme_statement": "守住事实，比赢下一次争斗更重要。",
                    "foreground_story": "林照从祖祠异动查到宗门旧案。",
                    "background_story": "多年前有人借封档重分宗门权力。",
                    "book_objective": "公开旧案证据并改变封档规则。",
                    "ending_image": "旧名册在议事堂当众展开。",
                    "protagonist_goal": "查清旧案。",
                    "main_conflict": "有人销毁证据。",
                    "growth_path": "逐步取得调查旧档的权力。",
                    "ending_direction": "旧案公开。",
                    "primary_trope_id": "low_status_reversal",
                    "core_ending_chapter": 150,
                    "extension_ceiling_chapter": 150,
                },
                "arcs": [
                    {
                        "id": "opening",
                        "title": "祖祠旧案",
                        "start_chapter": 1,
                        "end_chapter": 150,
                        "is_final_arc": True,
                        "story_nodes": _story_nodes(1, 150),
                        "goal": "找到换名册的人",
                        "obstacle": "赵衡控制清点权",
                        "payoff": "取得查档资格",
                        "emotional_curve": "受压查证，抓住破绽，取得主动。",
                        "key_results": ["保住证据", "取得查档资格", "锁定换册人"],
                        "hook_plan": "缺失的一页指向宗门高层。",
                        "irreversible_change": "赵衡失去对祖祠的独占控制。",
                        "trope_id": "low_status_reversal",
                        "end_state": "祖祠不再由赵衡独占",
                        "stage_antagonist": "赵衡",
                        "long_term_antagonist_traces": ["旧名册被换过"],
                    }
                ],
                "chapters": [
                    {
                        "chapter_number": number,
                        "title": f"第{number}步",
                        "goal": "查清祖祠异动",
                        "obstacle": "赵衡阻拦",
                        "action": "林照留下证据",
                        "turn": "旧名册出现矛盾",
                        "payoff": "得到可验证线索",
                        "ending_hook": "有人提前来过",
                        "trope_beat": "低位压力" if number == 1 else None,
                        "cast": ["林照", "赵衡"],
                    }
                    for number in range(1, 11)
                ],
            },
            "characters": [
                _planning_card("林照", "protagonist", age=19),
                _planning_card("赵衡", "stage_antagonist"),
                _planning_card("周满", "supporting"),
                _planning_card("顾长老", "long_term_antagonist"),
            ],
        }
    )


def test_save_generated_outline_rejects_non_final_short_volume_without_writes(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "short-volume"
    store = _make_minimal_file_project(root)
    payload = _generated_opening_plan().model_dump(mode="json")
    payload["outline"]["overall"].update(
        core_ending_chapter=10,
        extension_ceiling_chapter=10,
    )
    payload["outline"]["arcs"][0].update(
        end_chapter=10,
        is_final_arc=False,
        story_nodes=_story_nodes(1, 10),
    )
    plan = GeneratedOutlinePlan.model_validate(payload)
    before = _file_snapshot(root)
    monkeypatch.setattr(
        file_project_store_module,
        "validate_generated_opening_plan",
        lambda candidate, **_kwargs: GeneratedOutlinePlan.model_validate(candidate),
    )

    with pytest.raises(ValueError, match="^volume_too_short:opening$"):
        store.save_generated_outline_plan(plan, mode="initial")

    assert _file_snapshot(root) == before


def _plan_with_short_final_volume() -> GeneratedOutlinePlan:
    payload = _generated_opening_plan().model_dump(mode="json")
    opening = payload["outline"]["arcs"][0]
    opening.update(
        end_chapter=50,
        is_final_arc=False,
        story_nodes=_story_nodes(1, 50),
    )
    final = deepcopy(opening)
    final.update(
        id="ending",
        title="Ending",
        start_chapter=51,
        end_chapter=70,
        is_final_arc=True,
        story_nodes=_story_nodes(51, 70),
    )
    payload["outline"]["arcs"] = [opening, final]
    payload["outline"]["overall"].update(
        core_ending_chapter=70,
        extension_ceiling_chapter=70,
    )
    return GeneratedOutlinePlan.model_validate(payload)


def _bypass_generated_volume_validation(monkeypatch) -> None:
    monkeypatch.setattr(
        file_project_store_module,
        "validate_generated_opening_plan",
        lambda candidate, **_kwargs: GeneratedOutlinePlan.model_validate(candidate),
    )


def test_save_generated_outline_allows_short_final_volume(
    tmp_path,
    monkeypatch,
) -> None:
    store = _make_minimal_file_project(tmp_path / "short-final-volume")
    _bypass_generated_volume_validation(monkeypatch)

    saved = store.save_generated_outline_plan(
        _plan_with_short_final_volume(),
        mode="initial",
    )

    assert saved["outline"]["arcs"][-1]["end_chapter"] == 70


@pytest.mark.parametrize(
    ("invalidity", "error"),
    [
        ("overlap", "volume_overlap:opening:ending"),
        ("gap", "volume_gap:opening:ending"),
        ("node_gap", "story_node_gap:opening"),
    ],
)
def test_save_generated_outline_rejects_invalid_volume_structure_without_writes(
    tmp_path,
    monkeypatch,
    invalidity: str,
    error: str,
) -> None:
    root = tmp_path / invalidity
    store = _make_minimal_file_project(root)
    payload = _plan_with_short_final_volume().model_dump(mode="json")
    if invalidity == "overlap":
        payload["outline"]["arcs"][1].update(
            start_chapter=50,
            story_nodes=_story_nodes(50, 70),
        )
    elif invalidity == "gap":
        payload["outline"]["arcs"][1].update(
            start_chapter=52,
            story_nodes=_story_nodes(52, 70),
        )
    else:
        payload["outline"]["arcs"][0]["story_nodes"].pop()
    plan = GeneratedOutlinePlan.model_validate(payload)
    before = _file_snapshot(root)
    _bypass_generated_volume_validation(monkeypatch)

    with pytest.raises(ValueError, match=f"^{error}$"):
        store.save_generated_outline_plan(plan, mode="initial")

    assert _file_snapshot(root) == before


@pytest.mark.parametrize(
    ("invalidity", "error"),
    [
        ("short_non_final", "volume_too_short:opening"),
        ("node_gap", "story_node_gap:opening"),
    ],
)
def test_save_generated_outline_foundation_rejects_invalid_volume_without_writes(
    tmp_path,
    invalidity: str,
    error: str,
) -> None:
    root = tmp_path / f"foundation-{invalidity}"
    store = _make_minimal_file_project(root)
    payload = _generated_opening_plan().model_dump(mode="json")
    if invalidity == "short_non_final":
        payload["outline"]["overall"].update(
            core_ending_chapter=10,
            extension_ceiling_chapter=10,
        )
        payload["outline"]["arcs"][0].update(
            end_chapter=10,
            is_final_arc=False,
            story_nodes=_story_nodes(1, 10),
        )
    else:
        payload["outline"]["arcs"][0]["story_nodes"].pop()
    plan = GeneratedOutlinePlan.model_validate(payload)
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match=f"^{error}$"):
        store._save_generated_outline_foundation(plan, mode="regenerate")

    assert _file_snapshot(root) == before


def _shenyu_world_blueprint() -> dict:
    return {
        "premise": "神域中的稀缺资源可以通过受限渠道影响现实生活。",
        "world_rules": ["世界规则一。", "世界规则二。"],
        "power_system": ["转职必须满足等级与技能条件。"],
        "progression_rules": ["升级必须来自可验证经验。", "转职必须留下职业记录。"],
        "economy_rules": ["交易价格取决于真实稀缺性。", "寄售必须支付手续费。"],
        "quest_rules": ["委托必须先登记再提交。", "巡查任务必须记录路线。"],
        "reality_bridge_rules": ["现实到账必须经过官方结算。", "房租支付必须保留账单。"],
        "quest_network": {
            "active_chains": [
                {
                    "name": "灰烬村异常链",
                    "stages": ["提交清道夫委托", "开启后坡巡查"],
                },
                {
                    "name": "黑水沼泽异常链",
                    "stages": ["提交毒腺委托", "调查黑水沼泽"],
                },
            ]
        },
        "locations": [{"name": "灰烬村"}, {"name": "黑水沼泽"}],
        "factions": [{"name": "灰烬村守卫队"}, {"name": "沼泽猎团"}],
        "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
        "server_runtime": {"online": True},
        "current_arc": "开服篇",
        "opening_arc": {"goal": "完成开服验证"},
        "volume_plan": {"volume_title": "新手村"},
        "longform_framework": {"progression_ladder": ["Lv.1-5"]},
        "chapter_formula": ["目标-代价-收益-钩子"],
        "forbidden_breaks": ["不得跳过章节大纲。"],
    }


def _store_with_shenyu_world(
    tmp_path,
    *,
    chapter_number: int,
    chapter_update: dict,
    current_chapter: int = 0,
    current_focus: str = "",
) -> FileProjectStore:
    project = {
        "project_id": "p-shenyu",
        "title": "苟在网游里成神",
        "active_story_id": "s-shenyu",
        "current_focus": current_focus,
        "world_blueprint": _shenyu_world_blueprint(),
    }
    state = {
        "story_id": "s-shenyu",
        "current_chapter": current_chapter,
        "current_focus": current_focus,
        "world_facts": [],
    }
    store = _make_minimal_file_project(tmp_path / "shenyu", project=project, state=state)
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][chapter_number - 1].update(chapter_update)
    (store.webnovel_dir / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False),
        encoding="utf-8",
    )
    return store


def test_save_generated_plan_updates_outline_project_and_state_together(tmp_path):
    root = tmp_path / "novel"
    project = {
        "project_id": "p-file",
        "title": "断香炉",
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "character_profiles": [
            {"name": "林照", "role": "protagonist", "identity_profile": {"age": 21, "occupation": "守祠杂役"}}
        ],
    }
    state = {"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": []}
    store = _make_minimal_file_project(root, project=project, state=state)

    saved = store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")

    assert saved["outline"]["chapters"][0]["chapter_number"] == 1
    assert store.project()["pipeline_stage"] == "world_ready"
    assert store.project()["character_profiles"][0]["identity_profile"]["age"] == 21
    assert store.project()["character_profiles"][0]["identity_profile"]["occupation"] == "守祠杂役"
    assert store.state()["characters"][0]["identity_profile"]["age"] == 21
    assert list((root / ".story-system" / "plans").glob("*-initial.json"))


def test_unstarted_full_outline_generation_replaces_stale_character_roster_and_graph(
    tmp_path,
) -> None:
    project = {
        "project_id": "p-file",
        "title": "断香炉",
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "character_profiles": [
            {
                "name": "林照",
                "role": "protagonist",
                "current_state": {"current": {"summary": "已经进入后续危机"}},
            },
            {"name": "底层执行者", "role": "stage_antagonist"},
            {"name": "幕后黑手", "role": "long_term_antagonist"},
        ],
        "relationship_graph": [
            {"source": "林照", "target": "底层执行者", "relation_type": "旧关系"}
        ],
    }
    state = {
        "story_id": "s-file",
        "current_chapter": 0,
        "world_facts": [],
        "characters": project["character_profiles"],
    }
    store = _make_minimal_file_project(tmp_path / "initial", project=project, state=state)

    saved = store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")

    names = {card["name"] for card in saved["characters"]}
    assert "底层执行者" not in names
    assert "幕后黑手" not in names
    protagonist = next(card for card in saved["characters"] if card["name"] == "林照")
    assert "current_state" not in protagonist
    assert all(
        edge["source"] in names and edge["target"] in names
        for edge in store.project()["relationship_graph"]
    )


def test_unstarted_regeneration_replaces_stale_character_roster(tmp_path) -> None:
    project = {
        "project_id": "p-file",
        "title": "断香炉",
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "character_profiles": [
            {"name": "林照", "role": "protagonist"},
            {"name": "底层执行者", "role": "stage_antagonist"},
        ],
    }
    state = {
        "story_id": "s-file",
        "current_chapter": 0,
        "world_facts": [],
        "characters": project["character_profiles"],
    }
    store = _make_minimal_file_project(
        tmp_path / "regenerate",
        project=project,
        state=state,
    )

    saved = store.save_generated_outline_plan(
        _generated_opening_plan(),
        mode="regenerate",
    )

    assert "底层执行者" not in {card["name"] for card in saved["characters"]}


def test_save_generated_plan_revalidates_tropes_before_writes(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "Fake Trope Bypass",
            "active_story_id": "s-file",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    payload = _generated_opening_plan().model_dump(mode="json")
    payload["outline"]["overall"]["primary_trope_id"] = "not-a-candidate"
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^invalid_primary_trope_id$"):
        store.save_generated_outline_plan(GeneratedOutlinePlan.model_validate(payload), mode="initial")

    assert _file_snapshot(root) == before


def test_save_initial_allows_generated_primary_when_no_existing_lock(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "Direct Initial",
            "active_story_id": "s-file",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )

    saved = store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")

    assert saved["outline"]["overall"]["primary_trope_id"] == "low_status_reversal"
    assert saved["outline"]["arcs"][0]["trope_id"] == "low_status_reversal"


def test_save_generated_plan_builds_canonical_relationship_graph(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    payload = _generated_opening_plan().model_dump(mode="json")
    payload["characters"][0]["relationship_notes"] = [
        {
            "target": payload["characters"][1]["name"],
            "relation_type": "上下级",
            "current_attitude": "彼此提防",
            "shared_interest_or_conflict": "旧名册",
        }
    ]

    store.save_generated_outline_plan(payload, mode="initial")

    graph = store.project()["relationship_graph"]
    assert len(graph) == 1
    assert graph[0]["source"] == payload["characters"][0]["name"]
    assert graph[0]["target"] == payload["characters"][1]["name"]
    assert graph[0]["relation_type"] == "上下级"
    assert graph[0]["id"].startswith("rel-")


def test_project_derives_legacy_character_relations_without_writing_file(tmp_path):
    project = {
        "project_id": "p-file",
        "title": "Legacy",
        "character_profiles": [
            {
                "name": "Lin Zhao",
                "role": "protagonist",
                "relationship_notes": [{"target": "Zhao Heng", "relation_type": "rivals"}],
            }
        ],
    }
    store = _make_minimal_file_project(tmp_path / "novel", project=project)
    project_path = store.webnovel_dir / "project.json"
    before = project_path.read_text(encoding="utf-8")

    loaded = store.project()

    assert loaded["relationship_graph"][0]["relation_type"] == "rivals"
    assert project_path.read_text(encoding="utf-8") == before

    store.update_project({"relationship_graph": []})

    assert store.project()["relationship_graph"] == []


def test_update_project_normalizes_relationship_graph(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")

    updated = store.update_project(
        {"relationship_graph": [{"source": "Lin Zhao", "target": "Zhao Heng", "bond": "rivals", "trust": 140}]}
    )

    assert updated["relationship_graph"][0]["id"].startswith("rel-")
    assert updated["relationship_graph"][0]["relation_type"] == "rivals"
    assert updated["relationship_graph"][0]["trust"] == 100


def test_update_project_shallow_merges_independent_world_blueprint_patches(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "world_blueprint": {
                "genre_plugin_ids": ["game_webnovel"],
                "premise": "旧前提",
                "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
            },
        },
    )

    store.update_project({"world_blueprint": {"world_rules": ["新规则"]}})
    updated = store.update_project(
        {
            "world_blueprint": {
                "locations": [{"name": "新港"}],
                "monster_profiles": [{"id": "wolf", "name": "灰狼", "hp": "90"}],
            }
        }
    )

    assert updated["world_blueprint"] == {
        "genre_plugin_ids": ["game_webnovel"],
        "premise": "旧前提",
        "world_rules": ["新规则"],
        "locations": [{"name": "新港"}],
        "monster_profiles": [{"id": "wolf", "name": "灰狼", "hp": "90"}],
    }


def test_update_project_syncs_canonical_blueprint_to_master_and_markdown(tmp_path):
    root = tmp_path / "novel"
    project = {
        "project_id": "p-shenyu",
        "title": "旧书名",
        "active_story_id": "s-shenyu",
        "world_blueprint": {
            "premise": "旧世界背景。",
            "economy_rules": ["铜币价格必须有锚点。"],
            "quest_rules": ["任务必须先登记，再执行和提交。"],
            "power_system": ["所有玩家统一为见习者。"],
        },
    }
    store = _make_minimal_file_project(root, project=project)
    master_path = root / ".story-system" / "MASTER_SETTING.json"
    master_path.write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "editor_notes": {"owner": "保留我"},
                "world_blueprint": {"premise": "顶层旧镜像"},
                "project": {
                    "project_id": "p-shenyu",
                    "title": "旧书名",
                    "custom_master_field": "不得删除",
                    "world_blueprint": {"premise": "项目旧镜像"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    updated = store.update_project(
        {
            "game_title": "神域",
            "world_blueprint": {"premise": "新世界背景。"},
        }
    )

    saved_project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    saved_master = json.loads(master_path.read_text(encoding="utf-8"))
    canonical = saved_project["world_blueprint"]
    assert updated["game_title"] == "神域"
    assert canonical["premise"] == "新世界背景。"
    assert canonical["economy_rules"] == ["铜币价格必须有锚点。"]
    assert saved_master["world_blueprint"] == canonical
    assert saved_master["project"]["world_blueprint"] == canonical
    assert saved_master["project"]["game_title"] == "神域"
    assert saved_master["project"]["title"] == "旧书名"
    assert saved_master["editor_notes"] == {"owner": "保留我"}
    assert saved_master["project"]["custom_master_field"] == "不得删除"

    world_markdown = (root / "设定集" / "世界观.md").read_text(encoding="utf-8")
    power_markdown = (root / "设定集" / "力量体系.md").read_text(encoding="utf-8")
    assert world_markdown.startswith("<!-- managed: world-blueprint/v1 -->")
    assert "# 《神域》世界观" in world_markdown
    assert "## 经济体系" in world_markdown
    assert "## 任务体系" in world_markdown
    assert "所有玩家统一为见习者。" in power_markdown


@pytest.mark.parametrize(
    ("include_master_project", "master_project"),
    [(False, None), (True, ["legacy-project"])],
    ids=["missing", "non-dict"],
)
def test_update_project_creates_master_project_blueprint_mirror(
    tmp_path,
    include_master_project,
    master_project,
):
    root = tmp_path / "novel"
    project = {
        "project_id": "p-mirror",
        "active_story_id": "s-mirror",
        "title": "镜像测试",
        "game_title": "镜像游戏名",
        "world_blueprint": {
            "premise": "旧前提",
            "economy_rules": ["经济规则不能丢。"],
        },
    }
    store = _make_minimal_file_project(root, project=project)
    master_path = root / ".story-system" / "MASTER_SETTING.json"
    master_payload = {
        "schema_version": "story-system-master-setting/v1",
        "custom_master_field": {"preserved": True},
        "world_blueprint": {"premise": "旧顶层镜像"},
    }
    if include_master_project:
        master_payload["project"] = master_project
    master_path.write_text(
        json.dumps(master_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    store.update_project({"world_blueprint": {"premise": "新前提"}})

    saved_project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    saved_master = json.loads(master_path.read_text(encoding="utf-8"))
    canonical = saved_project["world_blueprint"]
    assert canonical["economy_rules"] == ["经济规则不能丢。"]
    assert saved_master["world_blueprint"] == canonical
    assert saved_master["project"]["world_blueprint"] == canonical
    for key in ("project_id", "active_story_id", "title", "game_title"):
        assert saved_master["project"][key] == saved_project[key]
    assert saved_master["custom_master_field"] == {"preserved": True}


@pytest.mark.parametrize(
    ("project", "expected_title"),
    [
        (
            {"project_id": "p-game-title", "title": "作品标题", "game_title": "游戏标题"},
            "游戏标题",
        ),
        ({"project_id": "p-title", "title": "作品标题"}, "作品标题"),
        ({"project_id": "p-untitled"}, "未命名作品"),
    ],
    ids=["game-title", "title", "fallback"],
)
def test_update_project_uses_title_priority_for_world_markdown(
    tmp_path,
    project,
    expected_title,
):
    root = tmp_path / "novel"
    project = {
        **project,
        "world_blueprint": {
            "premise": "标题优先级测试。",
            "power_system": ["力量规则。"],
        },
    }
    store = _make_minimal_file_project(root, project=project)

    store.update_project({"world_blueprint": {"world_rules": ["触发同步。"]}})

    world_markdown = (root / "设定集" / "世界观.md").read_text(encoding="utf-8")
    power_markdown = (root / "设定集" / "力量体系.md").read_text(encoding="utf-8")
    assert f"# 《{expected_title}》世界观" in world_markdown
    assert f"# 《{expected_title}》力量体系" in power_markdown


def test_update_project_without_world_blueprint_does_not_refresh_world_markdown(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "旧标题",
            "world_blueprint": {"premise": "项目背景"},
        },
    )
    settings_dir = root / "设定集"
    settings_dir.mkdir()
    world_path = settings_dir / "世界观.md"
    power_path = settings_dir / "力量体系.md"
    world_path.write_text("<!-- managed: world-blueprint/v1 -->\n保留世界文档\n", encoding="utf-8")
    power_path.write_text("<!-- managed: world-blueprint/v1 -->\n保留力量文档\n", encoding="utf-8")

    updated = store.update_project({"title": "新标题", "game_title": "新游戏名"})

    assert updated["title"] == "新标题"
    assert updated["game_title"] == "新游戏名"
    assert world_path.read_text(encoding="utf-8") == "<!-- managed: world-blueprint/v1 -->\n保留世界文档\n"
    assert power_path.read_text(encoding="utf-8") == "<!-- managed: world-blueprint/v1 -->\n保留力量文档\n"


def test_update_project_keeps_saved_json_when_world_markdown_sync_fails(
    tmp_path,
    monkeypatch,
    caplog,
):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "故障降级测试",
            "world_blueprint": {
                "premise": "旧前提",
                "economy_rules": ["经济规则保留。"],
            },
        },
    )

    def fail_sync(*args, **kwargs):
        raise OSError("markdown unavailable")

    monkeypatch.setattr(
        "packages.story_core.file_project_store.sync_world_markdown",
        fail_sync,
    )

    with caplog.at_level("WARNING"):
        updated = store.update_project(
            {"world_blueprint": {"premise": "JSON 已保存的新前提"}}
        )

    saved_project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    saved_master = json.loads(
        (root / ".story-system" / "MASTER_SETTING.json").read_text(encoding="utf-8")
    )
    assert updated["world_blueprint"]["premise"] == "JSON 已保存的新前提"
    assert saved_project["world_blueprint"] == updated["world_blueprint"]
    assert saved_master["world_blueprint"] == updated["world_blueprint"]
    assert saved_master["project"]["world_blueprint"] == updated["world_blueprint"]
    assert "world blueprint markdown sync failed" in caplog.text


def test_update_project_serializes_concurrent_instances_for_same_root(tmp_path):
    root = tmp_path / "novel"
    store_a = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "world_blueprint": {"monster_profiles": [{"id": "wolf", "name": "灰狼"}]},
        },
    )
    store_b = FileProjectStore(root)
    read_barrier = threading.Barrier(2)
    start_barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def synchronize_project_read(store):
        original = store.project

        def read_project():
            project = original()
            try:
                read_barrier.wait(timeout=0.25)
            except threading.BrokenBarrierError:
                pass
            return project

        store.project = read_project

    synchronize_project_read(store_a)
    synchronize_project_read(store_b)

    def update(store, patch):
        try:
            start_barrier.wait()
            store.update_project({"world_blueprint": patch})
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors.append(exc)

    threads = [
        threading.Thread(target=update, args=(store_a, {"world_rules": ["并发规则"]})),
        threading.Thread(target=update, args=(store_b, {"locations": [{"name": "并发新港"}]})),
    ]
    for thread in threads:
        thread.start()
    start_barrier.wait()
    for thread in threads:
        thread.join()

    assert errors == []
    assert FileProjectStore(root).project()["world_blueprint"] == {
        "world_rules": ["并发规则"],
        "locations": [{"name": "并发新港"}],
        "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
    }


def test_chapter_reality_events_update_real_state_only(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {
            "protagonist": {"level": "Lv.1"},
            "economy": {"game_currency": "0铜币"},
        },
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {
                    "current": {"balance": "27.60元"},
                    "recent_changes": [],
                },
                "game_state": {
                    "current": {"level": "Lv.1", "currency": "0铜币"},
                    "recent_changes": [],
                },
                "game_panel": {"game_id": "夜烬", "level": "Lv.1", "currency": "0铜币"},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 2,
            "body": "现实线里兼职收入到账，随后支付房租。",
            "state_changes": [
                {
                    "line": "reality",
                    "change": {
                        "current": {"balance": "32.60元", "income": "5.00元"},
                        "fact": "兼职收入到账",
                    },
                },
                {
                    "line": "reality",
                    "change": {
                        "current": {"balance": "30.60元", "rent": "2.00元"},
                        "fact": "支付房租",
                    },
                },
            ],
        },
    )

    character = synced["characters"][0]
    assert character["real_state"]["current"] == {
        "balance": "30.60元",
        "income": "5.00元",
        "rent": "2.00元",
    }
    assert character["real_state"]["recent_changes"] == [
        {"chapter": 2, "fact": "兼职收入到账"},
        {"chapter": 2, "fact": "支付房租"},
    ]
    assert character["game_state"] == {
        "current": {"level": "Lv.1", "currency": "0铜币"},
        "recent_changes": [],
    }


def test_body_ledger_sync_uses_final_panel_and_real_balance(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "Web Game",
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
    )
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {
            "real": {"start_balance": "27.60元", "end_balance": "27.60元"},
            "protagonist": {"level": "Lv.3", "exp": "80/100"},
            "panel": {"level": "Lv.3", "exp": "80/100"},
            "economy": {"inventory": {}},
        },
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "game_id": "夜烬",
                "game_panel": {"level": "Lv.3", "exp": "80/100"},
            }
        ],
    }
    body = (
        "银行卡可用余额：27.60元。\n"
        "【急账代付已通过】【可用余额：312.60元】\n"
        "【等级：Lv.1】【经验：20/100】【生命：82/100】【法力：36/60】\n"
        "【新手法杖 9/10】【钱袋：空】【背包：灰狼毒腺×16，粗糙狼皮×10（2/20）】"
    )

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 1, "chapter_title": "夜烬", "body": body},
    )

    ledger = synced["progression_ledger"]
    assert ledger["real"]["end_balance"] == "312.60元"
    assert ledger["protagonist"]["level"] == "Lv.1"
    assert ledger["panel"]["level"] == "Lv.1"
    assert synced["characters"][0]["game_panel"]["level"] == "Lv.1"
    facts = synced["chapter_summaries"][0]["facts"]
    assert "苏叶现实余额312.60元" in facts
    assert "苏叶现实余额27.60元未变" not in facts


def test_body_ledger_sync_reads_compact_protagonist_level_panel(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "Web Game",
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
    )
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {
            "protagonist": {"level": "Lv.1"},
            "panel": {"level": "Lv.1"},
        },
    }

    body = (
        "路边有一只Lv.2灰狼。\n"
        "【灰狼；等级：Lv.1；生命82/82；攻击方式：扑咬】\n"
        "【夜烬；Lv.3见习者　经验40/420；生命100/100；法力60/60】"
    )

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 2, "chapter_title": "升级", "body": body},
    )

    assert synced["progression_ledger"]["protagonist"]["level"] == "Lv.3"
    assert synced["progression_ledger"]["panel"]["level"] == "Lv.3"


def test_update_project_can_replace_world_blueprint_after_genre_enrichment(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-replace-world",
            "title": "Realistic Novel",
            "world_blueprint": {
                "genre_plugin_ids": ["urban"],
                "premise": "Old premise",
                "power_system": ["stale generated field"],
                "panel_rules": ["stale generated field"],
            },
        },
    )

    updated = store.update_project(
        {
            "world_blueprint": {
                "genre_plugin_ids": ["urban"],
                "premise": "New premise",
            }
        },
        replace_world_blueprint=True,
    )

    assert updated["world_blueprint"] == {
        "genre_plugin_ids": ["urban"],
        "premise": "New premise",
    }


def test_game_character_sync_mirrors_complete_attribute_ledger(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    awards = [
        {"level": 2, "points": 5, "chapter": 1},
        {"level": 3, "points": 5, "chapter": 4},
    ]
    allocations = [
        {"chapter": 1, "allocations": {"Intelligence": 5}, "remaining": 0},
        {"chapter": 4, "allocations": {"Constitution": 2}, "remaining": 3},
    ]
    character = {"name": "Ari", "role": "protagonist"}
    ledger = {
        "protagonist": {
            "attributes": {"Intelligence": 10, "Constitution": 7},
            "unallocated_attribute_points": 3,
            "attribute_point_awards": awards,
            "attribute_allocations": allocations,
        }
    }

    store._sync_game_character_from_ledger(character, ledger, chapter_number=4)

    for state_slice in (character["game_state"]["current"], character["game_panel"]):
        assert state_slice["attributes"] == {"Intelligence": 10, "Constitution": 7}
        assert state_slice["unallocated_attribute_points"] == 3
        assert state_slice["attribute_point_awards"] == awards
        assert state_slice["attribute_allocations"] == allocations


@pytest.mark.parametrize("invalid_points", ["oops", -1, True])
def test_game_character_sync_ignores_invalid_attribute_ledger_values(tmp_path, invalid_points):
    store = _make_minimal_file_project(tmp_path / "novel")
    existing = {
        "attributes": {"Intelligence": 10},
        "unallocated_attribute_points": 3,
        "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 1}],
        "attribute_allocations": [
            {"chapter": 1, "allocations": {"Intelligence": 5}, "remaining": 0}
        ],
    }
    character = {
        "name": "Ari",
        "role": "protagonist",
        "game_state": {"current": deepcopy(existing)},
        "game_panel": deepcopy(existing),
    }
    ledger = {
        "protagonist": {
            "attributes": None,
            "unallocated_attribute_points": invalid_points,
            "attribute_point_awards": {},
            "attribute_allocations": [{"chapter": 2}, "not-a-record"],
        }
    }

    store._sync_game_character_from_ledger(character, ledger, chapter_number=2)

    for state_slice in (character["game_state"]["current"], character["game_panel"]):
        for field, value in existing.items():
            assert state_slice[field] == value


def test_opening_ledger_derives_latest_project_balance_instead_of_fixed_amount(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    chapters = [
        {
            "chapter_number": 1,
            "body": "登录前，银行卡可用余额43.18元。收到转账并付完急账后，账户余额286.41元。",
            "chapter_summary": {},
        }
    ]

    ledger = store._derive_opening_progression_ledger(chapters, {})

    assert ledger["economy"]["real_balance"] == "286.41元"
    assert "27.60" not in str(ledger)


def test_chapter_ledger_does_not_copy_monster_level_and_hp_to_protagonist(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {"protagonist": {"level": "Lv.1", "hp": "100/100"}},
        "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
    }
    body = (
        "苏叶打开角色面板，等级Lv.1，生命100/100，法力60/60。"
        "任务结算后，系统提示等级提升至Lv.2，生命110/110，法力66/66。"
        "系统弹出信息：裂纹狼（精英），等级Lv.5，生命320/320，攻击方式为撕咬。"
        "夜烬击杀了裂纹狼。"
    )

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 1, "chapter_title": "第一笔到账", "body": body},
    )

    protagonist = synced["progression_ledger"]["protagonist"]
    assert protagonist["level"] == "Lv.2"
    assert protagonist["hp"] == "110/110"
    assert protagonist["mp"] == "66/66"


def test_chapter_ledger_ignores_compact_monster_panel_and_keeps_latest_quest_inventory(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {"protagonist": {"level": "Lv.1", "hp": "100/100"}},
        "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
    }
    body = (
        "【普通任务：清道夫；收集灰狼毒腺：0/16】"
        "【灰狼；等级：Lv.1；生命：82/82；攻击方式：短距离扑咬】"
        "【背包：灰狼毒腺×8，粗糙狼皮×7，裂纹狼心×1；占用3/20】"
        "裂纹狼心从背包消失。清道夫任务仍停在8/16，尚未提交。"
    )

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 1, "chapter_title": "裂纹狼心", "body": body},
    )

    ledger = synced["progression_ledger"]
    assert ledger["protagonist"]["hp"] == "100/100"
    assert ledger["quests"]["active"] == "清道夫：8/16；未提交"
    assert ledger["economy"]["inventory"] == {"灰狼毒腺": 8, "粗糙狼皮": 7}
    assert ledger["economy"]["backpack"] == "2/20"


def test_default_protagonist_speech_profile_does_not_request_explanatory_dialogue(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    card = store._protagonist_character_card(
        {
            "current_chapter": 0,
            "progression_ledger": {"protagonist": {"real_name": "苏叶", "game_id": "夜烬"}},
        }
    )

    speech_style = card["performance_profile"]["speech_style"]
    assert "解释选择时把原因说清" not in speech_style
    assert "只说当下会说的话" in speech_style


def test_character_merge_migrates_only_the_legacy_explanatory_speech_template(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    merged = store._merge_character_cards(
        [
            {
                "name": "苏叶",
                "role": "protagonist",
                "performance_profile": {
                    "speech_style": "白话、完整、少装腔；解释选择时把原因说清。",
                    "action_style": "保留用户动作风格",
                },
            }
        ],
        [
            {
                "name": "苏叶",
                "role": "protagonist",
                "performance_profile": {
                    "speech_style": "白话、完整、少装腔；只说当下会说的话，理由藏在语气、动作和必要回答里。",
                    "action_style": "新的默认动作风格",
                },
            }
        ],
    )

    profile = merged[0]["performance_profile"]
    assert "解释选择时把原因说清" not in profile["speech_style"]
    assert "只说当下会说的话" in profile["speech_style"]
    assert profile["action_style"] == "保留用户动作风格"


def test_project_and_state_loading_migrate_the_legacy_explanatory_speech_template(tmp_path):
    legacy_card = {
        "name": "苏叶",
        "role": "protagonist",
        "game_id": "夜烬",
        "performance_profile": {
            "speech_style": "白话、完整、少装腔；解释选择时把原因说清。",
            "action_style": "保留动作风格",
        },
    }
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "Web Game",
            "genre": "game_webnovel",
            "character_profiles": [legacy_card],
        },
        state={
            "story_id": "s-file",
            "genre": "game_webnovel",
            "characters": [legacy_card],
        },
    )

    project_profile = store.project()["character_profiles"][0]["performance_profile"]
    state_profile = store.state()["characters"][0]["performance_profile"]
    assert "解释选择时把原因说清" not in project_profile["speech_style"]
    assert "解释选择时把原因说清" not in state_profile["speech_style"]
    assert project_profile["action_style"] == "保留动作风格"


def test_update_project_saves_and_clears_optional_writing_style(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-style",
            "title": "Style Novel",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={"story_id": "s-style", "style": "白描、现代中文", "world_facts": []},
    )

    selected = store.update_project({"world_blueprint": {"writing_style": "幽默"}})

    assert selected["world_blueprint"]["writing_style"] == "幽默"
    assert store.state()["style"] == "幽默"

    cleared = store.update_project({"world_blueprint": {"writing_style": ""}})

    assert cleared["world_blueprint"]["writing_style"] == ""
    assert store.state()["style"] == ""


def test_update_project_rejects_unknown_writing_style(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")

    with pytest.raises(ValueError, match="invalid_writing_style"):
        store.update_project({"world_blueprint": {"writing_style": "通用白描"}})


def test_chapter_ledger_scopes_weapon_durability_and_quantity_backpack_lines(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {"economy": {"inventory": {}}},
        "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
    }
    body = (
        "夜烬装备灰狼护腕，防御+2，耐久8/8。"
        "铁匠修好新手法杖，耐久回到10/10。"
        "背包里还剩灰狼毒腺×2、粗糙狼皮×4、狼牙×1、灰狼护腕×1。"
        "下线后，他还在想该怎么解释背包里的东西。"
    )

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 1, "chapter_title": "第一笔到账", "body": body},
    )

    ledger = synced["progression_ledger"]
    assert ledger["equipment"]["durability"] == "10/10"
    assert ledger["economy"]["inventory"] == {
        "灰狼毒腺": 2,
        "粗糙狼皮": 4,
        "狼牙": 1,
        "灰狼护腕": 1,
    }


def test_chapter_ledger_parses_only_remaining_inventory_and_prose_real_balance(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {"economy": {"inventory": {}}, "real": {}},
        "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
    }
    body = (
        "背包里只剩灰狼毒腺×8和粗糙狼皮×7，占用两个材料格。"
        "苏叶付清房租和信用卡最低还款以后，现实账户余额停在332.60元。"
    )

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 1, "chapter_title": "裂纹狼心", "body": body},
    )

    ledger = synced["progression_ledger"]
    assert ledger["economy"]["inventory"] == {"灰狼毒腺": 8, "粗糙狼皮": 7}
    assert ledger["real"]["end_balance"] == "332.60元"
    assert synced["characters"][0]["real_state"]["current"]["balance"] == "332.60元"


def test_chapter_ledger_normalizes_bracketed_inventory_prose(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {"economy": {"inventory": {}}},
        "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
    }
    body = "夜烬清点背包，背包里静静堆叠着【灰狼毒腺×7】与【粗糙狼皮×7】。"

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 1, "chapter_title": "裂纹狼心", "body": body},
    )

    assert synced["progression_ledger"]["economy"]["inventory"] == {
        "灰狼毒腺": 7,
        "粗糙狼皮": 7,
    }


def test_body_ledger_summary_preserves_confirmed_next_focus(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    chapter = {
        "chapter_number": 1,
        "chapter_title": "夜烬",
        "chapter_summary": {
            "next_focus": "用现有材料登记并完成清道夫委托，优先拿任务经验。"
        },
    }
    ledger = {
        "protagonist": {"level": "Lv.1", "exp": "20/100"},
        "economy": {"inventory": {"灰狼毒腺": 16}, "game_currency": "空"},
        "quests": {"清道夫委托": "未接取；未提交；奖励未到账"},
    }

    summary = store._chapter_body_ledger_summary(chapter, ledger)

    assert summary["next_focus"] == "用现有材料登记并完成清道夫委托，优先拿任务经验。"


def test_generation_state_reconciles_saved_chapter_before_planning(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "genre": "game_webnovel",
            "current_chapter": 1,
            "world_facts": [],
            "progression_ledger": {
                "real": {"end_balance": "27.60元"},
                "protagonist": {"level": "Lv.3", "exp": "80/100"},
                "panel": {"level": "Lv.3"},
            },
            "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
        },
        project={
            "project_id": "p-file",
            "title": "Web Game",
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "夜烬",
        "body": (
            "银行卡可用余额：27.60元。后来急账代付通过。"
            "【可用余额：312.60元】【等级：Lv.1】【经验：20/100】"
            "【生命：82/100】【法力：36/60】【新手法杖 9/10】【钱袋：空】"
        ),
        "chapter_summary": {"chapter_number": 1, "facts": ["旧摘要误写Lv.3"]},
    }
    (store.story_system_dir / "chapters" / "0001.json").write_text(
        json.dumps(chapter, ensure_ascii=False), encoding="utf-8"
    )

    reconciled = store._generation_state(store.state())

    ledger = reconciled["progression_ledger"]
    assert ledger["real"]["end_balance"] == "312.60元"
    assert ledger["protagonist"]["level"] == "Lv.1"
    assert ledger["panel"]["level"] == "Lv.1"


def test_state_before_next_chapter_prefers_current_state_over_stale_embedded_snapshot(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "progression_ledger": {
                "real": {"start_balance": "27.60元", "end_balance": "312.60元"},
                "economy": {"real_balance": "312.60元"},
            },
            "chapter_summaries": [
                {
                    "chapter_number": 1,
                    "summary": "急账已经付清。",
                    "facts": ["苏叶现实余额312.60元"],
                }
            ],
        },
    )
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "updated_story": {
                "story_id": "s-file",
                "current_chapter": 1,
                "progression_ledger": {
                    "real": {"start_balance": "27.60元", "end_balance": "27.60元"},
                    "economy": {"real_balance": "27.60元"},
                },
                "chapter_summaries": [
                    {
                        "chapter_number": 1,
                        "summary": "急账尚未解决。",
                        "facts": ["苏叶现实余额27.60元未变"],
                    }
                ],
            },
        },
    )
    (store.root / "chapters" / "0001-第一章.md").write_text("第一章正文", encoding="utf-8")

    before = store._state_before_chapter(2)

    assert before["progression_ledger"]["real"]["end_balance"] == "312.60元"
    assert before["chapter_summaries"][-1]["facts"] == ["苏叶现实余额312.60元"]


def test_state_before_current_chapter_uses_previous_chapter_snapshot(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "current_chapter": 2,
            "progression_ledger": {"quests": {"清道夫委托": "已提交"}},
        },
    )
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "updated_story": {
                "story_id": "s-file",
                "current_chapter": 1,
                "progression_ledger": {"quests": {"清道夫委托": "进行中 8/16"}},
            },
        },
    )

    before = store._state_before_chapter(2)

    assert before["current_chapter"] == 1
    assert before["progression_ledger"]["quests"]["清道夫委托"] == "进行中 8/16"


def test_story_payload_uses_project_constraints_and_preserves_character_lifecycle(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "outline": "夜烬推进新手任务。",
            "genre": "网游",
            "style": "白描",
            "author_constraints": ["stale english constraint"],
            "timeline": [
                {"chapter_number": 1, "summary": "完成首章。", "impact": "继续任务。"},
                {"chapter_number": 2, "summary": "旧稿。", "impact": "不应提前读取。"},
            ],
            "chapter_summaries": [
                {"chapter_number": 1, "chapter_title": "首章", "summary": "完成首章。", "next_focus": "继续任务。"},
                {"chapter_number": 2, "chapter_title": "旧稿", "summary": "旧稿。", "next_focus": "不应提前读取。"},
            ],
            "characters": [
                {"name": "苏叶", "role": "protagonist", "game_id": "夜烬", "lifecycle_state": "active"},
                {
                    "name": "白河仓库收购方",
                    "role": "收购方NPC",
                    "lifecycle_state": "proposed",
                    "last_approved_chapter": 0,
                },
            ],
        },
        project={
            "project_id": "p-file",
            "title": "Web Game",
            "author_constraints": ["游戏内使用夜烬。"],
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
    )

    payload = store._story_state_payload_for_direction(store.state(), store.project(), 2)

    assert payload["author_constraints"] == ["游戏内使用夜烬。"]
    assert [character["name"] for character in payload["characters"]] == ["苏叶"]
    assert [item["chapter_number"] for item in payload["timeline"]] == [1]
    assert [item["chapter_number"] for item in payload["chapter_summaries"]] == [1]


def test_generation_context_does_not_repeat_chapter_specific_rules_as_global_constraints(tmp_path):
    chapter_rule = "第一章必须完成旧表交易并付清欠款。"
    global_rule = "人物对话要使用完整、自然的现代中文。"
    store = _make_minimal_file_project(
        tmp_path / "scoped-author-constraints",
        project={
            "project_id": "p-scoped-rules",
            "title": "Repair Shop",
            "active_story_id": "s-scoped-rules",
            "author_constraints": [chapter_rule, global_rule],
        },
        state={"story_id": "s-scoped-rules", "current_chapter": 1, "world_facts": []},
    )

    payload = store._story_state_payload_for_direction(store.state(), store.project(), 2)
    packet = store.writing_packet(2)

    assert payload["author_constraints"] == [global_rule]
    assert packet["state"]["author_constraints"] == [global_rule]
    assert packet["project"]["author_constraints"] == [global_rule]


def test_director_story_payload_contains_progression_and_scoped_quest_context(tmp_path):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=2,
        chapter_update={
            "title": "升级与巡查",
            "goal": "升级转职后提交清道夫委托，开启后坡巡查",
            "action": "返回灰烬村登记任务并提交记录",
            "payoff": "获得新职业与巡查权限",
        },
    )

    payload = store._story_state_payload_for_direction(store.state(), store.project(), 2)
    world_context = payload["world_context"]

    assert world_context["progression_rules"]
    assert world_context["quest_rules"]
    assert [
        chain["name"]
        for chain in world_context["quest_network"]["active_chains"]
    ] == ["灰烬村异常链"]
    assert "server_runtime" not in world_context
    assert "monster_profiles" not in world_context
    assert payload["monster_profiles"] == [{"id": "wolf", "name": "灰狼"}]


def test_world_relevance_text_uses_explicit_current_chapter_snapshot(tmp_path, monkeypatch):
    focus = "下一章交易材料并支付现实房租"
    store = FileProjectStore(tmp_path / "novel")
    monkeypatch.setattr(
        store,
        "chapter_numbers",
        lambda: (_ for _ in ()).throw(AssertionError("helper must not rescan chapters")),
    )
    outline_context = {"chapter": {"title": "灰狼坡", "goal": "击败灰狼"}}
    state = {"current_focus": focus}
    project = {"current_focus": focus}

    rewrite_text = store._world_relevance_text(
        state,
        project,
        2,
        outline_context,
        current_chapter=2,
    )
    future_text = store._world_relevance_text(
        state,
        project,
        3,
        outline_context,
        current_chapter=2,
    )

    assert focus not in rewrite_text
    assert focus in future_text


def test_writing_packet_passes_existing_current_chapter_to_relevance_helper(tmp_path, monkeypatch):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={"title": "灰狼坡", "goal": "击败灰狼"},
        current_chapter=3,
        current_focus="下一章交易材料",
    )
    captured = {}

    def capture_relevance(
        state,
        project,
        target_chapter,
        outline_context,
        scene_cards=None,
        *,
        current_chapter,
    ):
        captured["target_chapter"] = target_chapter
        captured["current_chapter"] = current_chapter
        return "灰狼"

    monkeypatch.setattr(store, "_world_relevance_text", capture_relevance)

    store.writing_packet(1)

    assert captured == {"target_chapter": 1, "current_chapter": 3}


def test_director_payload_scans_chapters_once_and_passes_current_snapshot(tmp_path, monkeypatch):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=2,
        chapter_update={"title": "后坡巡查", "goal": "提交清道夫委托"},
        current_chapter=1,
        current_focus="开启后坡巡查",
    )
    state = store.state()
    project = store.project()
    original = store.chapter_numbers
    calls = 0
    captured = {}

    def counted_chapter_numbers():
        nonlocal calls
        calls += 1
        return original()

    def capture_relevance(
        state,
        project,
        target_chapter,
        outline_context,
        scene_cards=None,
        *,
        current_chapter,
    ):
        captured["target_chapter"] = target_chapter
        captured["current_chapter"] = current_chapter
        return "提交清道夫委托"

    monkeypatch.setattr(store, "chapter_numbers", counted_chapter_numbers)
    monkeypatch.setattr(store, "_world_relevance_text", capture_relevance)

    store._story_state_payload_for_direction(state, project, 2)

    assert calls == 1
    assert captured == {"target_chapter": 2, "current_chapter": 1}


def test_transition_reality_change_does_not_fallback_to_game_change(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
                "game_panel": {"game_id": "夜烬", "level": "Lv.1"},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 3,
            "body": "从现实回到游戏。",
            "state_changes": [
                {
                    "line": "transition",
                    "real_change": {
                        "current": {"balance": "32.60元"},
                        "fact": "现实收入到账",
                    },
                }
            ],
        },
    )

    character = synced["characters"][0]
    assert character["real_state"]["current"]["balance"] == "32.60元"
    assert character["game_state"] == {
        "current": {"level": "Lv.1"},
        "recent_changes": [],
    }


def test_state_event_with_unknown_target_updates_no_character(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
            },
            {
                "name": "林照",
                "role": "supporting",
                "real_state": {"current": {"balance": "10.00元"}, "recent_changes": []},
            },
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 4,
            "body": "现实线出现一笔明确收入。",
            "state_changes": [
                {
                    "line": "reality",
                    "target": "不存在的人",
                    "change": {"current": {"balance": "99.00元"}, "fact": "错误目标"},
                }
            ],
        },
    )

    assert synced["characters"][0]["real_state"]["current"]["balance"] == "27.60元"
    assert synced["characters"][1]["real_state"]["current"]["balance"] == "10.00元"


def test_plain_money_in_game_body_without_state_changes_does_not_change_real_state(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {"chapter_number": 5, "body": "他摸了摸口袋里的钱，随后继续登录游戏。"},
    )

    character = synced["characters"][0]
    assert character["real_state"] == {"current": {"balance": "27.60元"}, "recent_changes": []}


def test_web_game_english_body_updates_game_state(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "web game",
        "progression_ledger": {},
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_panel": {"game_id": "Night Ember"},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 6,
            "body": (
                "Level: 2\nExperience: 20/200\nHP: 80/100\nMP: 40/60\n"
                "Inventory: wolf fang x3\nCurrency: 30 coins\nQuest: patrol\nDurability: 90/100"
            ),
        },
    )

    character = synced["characters"][0]
    current = character["game_state"]["current"]
    assert current["level"] == "Lv.2"
    assert current["exp"] == "20/200"
    assert current["hp"] == "80/100"
    assert current["mp"] == "40/60"
    assert current["inventory"] == {"wolf fang": 3}
    assert current["currency"] == "30 coins"


def test_explicit_game_event_wins_over_chapter_ledger(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {},
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
                "game_panel": {"game_id": "夜烬"},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 7,
            "body": "Level: 2 Experience: 20/200",
            "state_changes": [
                {
                    "line": "game",
                    "change": {
                        "current": {"level": "Lv.5"},
                        "fact": "事件确认等级",
                    },
                }
            ],
        },
    )

    character = synced["characters"][0]
    assert character["game_state"]["current"]["level"] == "Lv.5"
    assert character["game_panel"]["level"] == "Lv.5"


def test_full_chapter_sync_applies_game_state_event_once(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "progression_ledger": {},
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
                "game_panel": {"game_id": "夜烬", "level": "Lv.1"},
            }
        ],
    }

    synced = store._sync_after_chapter(
        {
            "chapter_number": 8,
            "chapter_title": "回到副本",
            "body": "现实线结束，夜烬重新登录。",
            "state_changes": [
                {
                    "line": "game",
                    "change": {
                        "current": {"level": "Lv.2"},
                        "fact": "重新登录后等级确认",
                    },
                }
            ],
        },
        state,
    )

    changes = synced["characters"][0]["game_state"]["recent_changes"]
    assert changes == [{"chapter": 8, "fact": "重新登录后等级确认"}]


def test_english_prose_question_questing_and_coins_do_not_create_ledger_updates(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "web game",
        "characters": [{"name": "苏叶", "role": "protagonist"}],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 9,
            "body": "He questioned the questing route while coins glittered in the prose.",
        },
    )

    assert synced.get("progression_ledger", {}) == {}
    assert "game_state" not in synced["characters"][0]


def test_reality_line_with_only_game_namespace_does_not_fallback_to_generic_change(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 12,
            "body": "现实线没有账本变化。",
            "state_changes": [
                {
                    "line": "reality",
                    "change": {
                        "current": {"balance": "99.00元"},
                        "game_state": {"current": {"level": "Lv.9"}},
                    },
                }
            ],
        },
    )

    character = synced["characters"][0]
    assert character["real_state"]["current"]["balance"] == "27.60元"
    assert character["game_state"]["current"]["level"] == "Lv.1"


def test_game_line_with_only_reality_namespace_does_not_fallback_to_generic_change(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    state = {
        "genre": "game_webnovel",
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
                "game_state": {"current": {"level": "Lv.1"}, "recent_changes": []},
            }
        ],
    }

    synced = store._sync_ledger_from_chapter_body(
        state,
        {
            "chapter_number": 13,
            "body": "游戏线没有账本变化。",
            "state_changes": [
                {
                    "line": "game",
                    "change": {
                        "current": {"level": "Lv.9"},
                        "real_state": {"current": {"balance": "99.00元"}},
                    },
                }
            ],
        },
    )

    character = synced["characters"][0]
    assert character["game_state"]["current"]["level"] == "Lv.1"
    assert character["real_state"]["current"]["balance"] == "27.60元"


def test_generated_plan_transaction_restores_old_files_on_replace_failure(tmp_path, monkeypatch):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root)
    outline_path = root / ".webnovel" / "outline.json"
    outline_path.write_text(json.dumps({"schema_version": "project-outline/v1", "overall": {}, "arcs": [], "chapters": []}), encoding="utf-8")
    before = {
        path: path.read_bytes()
        for path in (root / ".webnovel" / "project.json", root / ".webnovel" / "state.json", outline_path)
    }
    import packages.story_core.file_project_store as module

    real_replace = module.os.replace
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")

    assert {path: path.read_bytes() for path in before} == before


def test_generated_plan_failed_transaction_does_not_rollback_concurrent_success(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "novel"
    failing_store = _make_minimal_file_project(root)
    successful_store = FileProjectStore(root)
    first_replace_finished = threading.Event()
    successful_save_finished = threading.Event()
    errors: dict[str, BaseException] = {}
    results: dict[str, dict] = {}
    import packages.story_core.file_project_store as module

    real_replace = module.os.replace
    failing_replace_calls = 0

    def coordinated_replace(source, target):
        nonlocal failing_replace_calls
        if threading.current_thread().name != "failing-outline-save":
            return real_replace(source, target)
        failing_replace_calls += 1
        if failing_replace_calls == 1:
            result = real_replace(source, target)
            first_replace_finished.set()
            successful_save_finished.wait(timeout=0.5)
            return result
        if failing_replace_calls == 2:
            raise OSError("simulated concurrent replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", coordinated_replace)

    def fail_save() -> None:
        try:
            failing_store.save_generated_outline_plan(
                _generated_opening_plan(),
                mode="initial",
            )
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors["failing"] = exc

    def succeed_save() -> None:
        try:
            results["successful"] = successful_store.save_generated_outline_plan(
                _generated_opening_plan(),
                mode="initial",
            )
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors["successful"] = exc
        finally:
            successful_save_finished.set()

    failing_thread = threading.Thread(target=fail_save, name="failing-outline-save")
    failing_thread.start()
    assert first_replace_finished.wait(timeout=2)
    successful_thread = threading.Thread(target=succeed_save, name="successful-outline-save")
    successful_thread.start()
    failing_thread.join(timeout=3)
    successful_thread.join(timeout=3)

    assert not failing_thread.is_alive()
    assert not successful_thread.is_alive()
    assert isinstance(errors.get("failing"), OSError)
    assert "successful" not in errors
    assert results["successful"]["outline"]["chapters"]
    assert len(FileProjectStore(root).project_outline()["chapters"]) == 10


def test_manual_outline_update_waits_for_failed_generated_transaction(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "novel"
    generated_store = _make_minimal_file_project(root)
    manual_store = FileProjectStore(root)
    manual_outline = _generated_opening_plan().outline.model_dump(mode="json")
    manual_outline["overall"]["ending_direction"] = "Manual ending after rollback."
    generated_paused = threading.Event()
    release_generated = threading.Event()
    manual_started = threading.Event()
    manual_write_entered = threading.Event()
    errors: dict[str, BaseException] = {}
    import packages.story_core.file_project_store as module

    real_replace = module.os.replace
    generated_replace_calls = 0

    def coordinated_replace(source, target):
        nonlocal generated_replace_calls
        if threading.current_thread().name != "failing-generated-save":
            return real_replace(source, target)
        generated_replace_calls += 1
        if generated_replace_calls == 1:
            result = real_replace(source, target)
            generated_paused.set()
            assert release_generated.wait(timeout=2)
            return result
        if generated_replace_calls == 2:
            raise OSError("simulated generated save failure")
        return real_replace(source, target)

    original_manual_write = manual_store._write_json_atomic

    def tracked_manual_write(path, payload):
        manual_write_entered.set()
        return original_manual_write(path, payload)

    monkeypatch.setattr(module.os, "replace", coordinated_replace)
    monkeypatch.setattr(manual_store, "_write_json_atomic", tracked_manual_write)

    def save_generated() -> None:
        try:
            generated_store.save_generated_outline_plan(
                _generated_opening_plan(),
                mode="initial",
            )
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors["generated"] = exc

    def update_manually() -> None:
        manual_started.set()
        try:
            manual_store.update_project_outline(manual_outline)
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors["manual"] = exc

    generated_thread = threading.Thread(
        target=save_generated,
        name="failing-generated-save",
    )
    generated_thread.start()
    assert generated_paused.wait(timeout=2)
    manual_thread = threading.Thread(target=update_manually, name="manual-outline-update")
    manual_thread.start()
    assert manual_started.wait(timeout=2)
    manual_entered_while_generated_paused = manual_write_entered.wait(timeout=0.25)
    release_generated.set()
    generated_thread.join(timeout=3)
    manual_thread.join(timeout=3)

    assert not generated_thread.is_alive()
    assert not manual_thread.is_alive()
    assert manual_entered_while_generated_paused is False
    assert isinstance(errors.get("generated"), OSError)
    assert "manual" not in errors
    assert FileProjectStore(root).project_outline()["overall"]["ending_direction"] == (
        "Manual ending after rollback."
    )


def test_manual_outline_update_waits_for_successful_generated_transaction(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "novel"
    generated_store = _make_minimal_file_project(root)
    manual_store = FileProjectStore(root)
    plan = _generated_opening_plan()
    manual_outline = plan.outline.model_dump(mode="json")
    manual_outline["overall"]["ending_direction"] = "Manual ending after generation."
    generated_paused = threading.Event()
    release_generated = threading.Event()
    manual_started = threading.Event()
    manual_write_entered = threading.Event()
    errors: dict[str, BaseException] = {}
    import packages.story_core.file_project_store as module

    real_replace = module.os.replace
    generated_replace_calls = 0

    def coordinated_replace(source, target):
        nonlocal generated_replace_calls
        if threading.current_thread().name != "successful-generated-save":
            return real_replace(source, target)
        generated_replace_calls += 1
        result = real_replace(source, target)
        if generated_replace_calls == 1:
            generated_paused.set()
            assert release_generated.wait(timeout=2)
        return result

    original_manual_write = manual_store._write_json_atomic

    def tracked_manual_write(path, payload):
        manual_write_entered.set()
        return original_manual_write(path, payload)

    monkeypatch.setattr(module.os, "replace", coordinated_replace)
    monkeypatch.setattr(manual_store, "_write_json_atomic", tracked_manual_write)

    def save_generated() -> None:
        try:
            generated_store.save_generated_outline_plan(plan, mode="initial")
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors["generated"] = exc

    def update_manually() -> None:
        manual_started.set()
        try:
            manual_store.update_project_outline(manual_outline)
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors["manual"] = exc

    generated_thread = threading.Thread(
        target=save_generated,
        name="successful-generated-save",
    )
    generated_thread.start()
    assert generated_paused.wait(timeout=2)
    manual_thread = threading.Thread(target=update_manually, name="manual-outline-update")
    manual_thread.start()
    assert manual_started.wait(timeout=2)
    manual_entered_while_generated_paused = manual_write_entered.wait(timeout=0.25)
    release_generated.set()
    generated_thread.join(timeout=3)
    manual_thread.join(timeout=3)

    assert not generated_thread.is_alive()
    assert not manual_thread.is_alive()
    assert manual_entered_while_generated_paused is False
    assert errors == {}
    saved = FileProjectStore(root)
    outline = saved.project_outline()
    project = saved.project()
    state = saved.state()
    assert outline["overall"]["ending_direction"] == "Manual ending after generation."
    assert len(outline["chapters"]) == 10
    assert project["pipeline_stage"] == "world_ready"
    assert state["outline"] == outline["overall"]["story"]
    assert [
        (card["name"], card["role"])
        for card in project["character_profiles"]
    ] == [
        (card["name"], card["role"])
        for card in state["characters"]
    ]


def _prepare_synced_markdown_outline(root: Path, outline: dict) -> Path:
    from packages.story_core.outline_markdown_sync import export_outline_to_markdown

    baseline = deepcopy(outline)
    baseline["overall"]["ending_direction"] = "Baseline markdown ending."
    (root / ".webnovel" / "outline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    outline_dir = root / "大纲"
    outline_dir.mkdir(parents=True, exist_ok=True)
    overview_path = outline_dir / "总纲.md"
    overview_path.write_text(
        """# 总纲

## 故事一句话
Baseline story.

## 核心主线
- **主线目标**：Baseline goal.
- **主要阻力**：Baseline conflict.

## 主角成长线
- **关键跃迁节点**：Baseline growth.
- **终局定位**：Baseline ending.

## 分卷纲要
""",
        encoding="utf-8",
    )
    assert export_outline_to_markdown(root, baseline) == "ok"
    assert "Baseline markdown ending." in overview_path.read_text(encoding="utf-8")
    return overview_path


@pytest.mark.parametrize("generated_fails", [True, False])
def test_markdown_newer_sync_waits_for_generated_outline_transaction(
    tmp_path,
    monkeypatch,
    generated_fails: bool,
) -> None:
    root = tmp_path / "novel"
    generated_store = _make_minimal_file_project(root)
    reader_store = FileProjectStore(root)
    plan = _generated_opening_plan()
    overview_path = _prepare_synced_markdown_outline(
        root,
        plan.outline.model_dump(mode="json"),
    )
    generated_paused = threading.Event()
    release_generated = threading.Event()
    reader_started = threading.Event()
    markdown_sync_write_entered = threading.Event()
    errors: dict[str, BaseException] = {}
    results: dict[str, dict] = {}
    import packages.story_core.file_project_store as store_module
    import packages.story_core.outline_markdown_sync as sync_module

    real_replace = store_module.os.replace
    generated_replace_calls = 0

    def coordinated_replace(source, target):
        nonlocal generated_replace_calls
        if threading.current_thread().name != "generated-outline-save":
            return real_replace(source, target)
        generated_replace_calls += 1
        result = real_replace(source, target)
        if generated_replace_calls == 1:
            generated_paused.set()
            assert release_generated.wait(timeout=2)
        elif generated_fails and generated_replace_calls == 2:
            raise OSError("simulated generated save failure")
        return result

    real_sync_write = sync_module._write_json_atomic

    def tracked_sync_write(path, payload):
        if threading.current_thread().name == "markdown-outline-reader":
            markdown_sync_write_entered.set()
        return real_sync_write(path, payload)

    monkeypatch.setattr(store_module.os, "replace", coordinated_replace)
    monkeypatch.setattr(sync_module, "_write_json_atomic", tracked_sync_write)

    def save_generated() -> None:
        try:
            results["generated"] = generated_store.save_generated_outline_plan(
                plan,
                mode="initial",
            )
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors["generated"] = exc

    def read_outline() -> None:
        reader_started.set()
        try:
            results["reader"] = reader_store.project_outline()
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors["reader"] = exc

    generated_thread = threading.Thread(
        target=save_generated,
        name="generated-outline-save",
    )
    generated_thread.start()
    assert generated_paused.wait(timeout=2)

    overview_text = overview_path.read_text(encoding="utf-8")
    overview_path.write_text(
        overview_text.replace(
            "Baseline markdown ending.",
            "Concurrent markdown ending.",
        ),
        encoding="utf-8",
    )
    assert "Concurrent markdown ending." in overview_path.read_text(encoding="utf-8")
    json_path = root / ".webnovel" / "outline.json"
    newer_mtime = max(overview_path.stat().st_mtime, json_path.stat().st_mtime) + 100
    os.utime(overview_path, (newer_mtime, newer_mtime))

    reader_thread = threading.Thread(target=read_outline, name="markdown-outline-reader")
    reader_thread.start()
    assert reader_started.wait(timeout=2)
    sync_entered_while_generated_paused = markdown_sync_write_entered.wait(timeout=0.25)
    release_generated.set()
    generated_thread.join(timeout=3)
    reader_thread.join(timeout=3)

    assert not generated_thread.is_alive()
    assert not reader_thread.is_alive()
    assert sync_entered_while_generated_paused is False
    assert "reader" not in errors
    if generated_fails:
        assert isinstance(errors.get("generated"), OSError)
        assert "generated" not in results
    else:
        assert "generated" not in errors
        assert results["generated"]["outline"]["chapters"]
    assert results["reader"]["overall"]["ending_direction"] == (
        "Concurrent markdown ending."
    )
    final_outline = json.loads(json_path.read_text(encoding="utf-8"))
    assert final_outline["overall"]["ending_direction"] == "Concurrent markdown ending."


def test_update_outline_rejects_core_ending_before_current_chapter(tmp_path) -> None:
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root, state={"current_chapter": 21})
    before = store.project_outline()
    invalid = deepcopy(before)
    invalid["overall"]["core_ending_chapter"] = 20
    invalid["overall"]["extension_ceiling_chapter"] = 30

    with pytest.raises(ValueError, match="core_ending_before_current_chapter"):
        store.update_project_outline(invalid)

    assert store.project_outline() == before


def test_generate_outline_plan_uses_compact_brief_and_one_time_guidance(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "seed_outline": "林照看守断香炉。",
            "current_focus": "查清第三块青砖。",
            "author_constraints": ["对白完整。"],
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
            "enabled_skill_ids": ["commercial-shuangwen"],
            "enabled_skill_module_ids": [
                "commercial-shuangwen::genre-examples",
                "commercial-shuangwen::plot-engine",
            ],
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": []},
    )
    calls = []

    class RecordingGenerator:
        def generate(self, brief, *, mode, guidance):
            calls.append((brief, mode, guidance))
            return _generated_opening_plan()

    (store.webnovel_dir / "opening_directions.json").write_text(
        json.dumps(
            {
                "schema_version": "opening-directions/v1",
                "directions": [
                    {
                        "id": "direction-1",
                        "title": "方向一",
                        "hook": "林照看守断香炉。",
                        "protagonist_goal": "守住香火。",
                        "main_conflict": "有人想毁掉旧案。",
                        "growth_path": "从守住现场开始掌握宗门规则。",
                        "opening_promise": "每次解决具体问题都会换来一条可验证线索。",
                        "primary_trope_id": "selected-trope",
                    },
                    {
                        "id": "direction-2",
                        "title": "方向二",
                        "hook": "另一条方向。",
                        "protagonist_goal": "另一目标。",
                        "main_conflict": "另一冲突。",
                        "growth_path": "另一成长。",
                        "opening_promise": "另一承诺。",
                        "primary_trope_id": "unused-trope",
                    },
                    {
                        "id": "direction-3",
                        "title": "方向三",
                        "hook": "第三条方向。",
                        "protagonist_goal": "第三目标。",
                        "main_conflict": "第三冲突。",
                        "growth_path": "第三成长。",
                        "opening_promise": "第三承诺。",
                        "primary_trope_id": "backup-trope",
                    },
                ],
                "selected_id": "direction-1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store.generate_outline_plan(RecordingGenerator(), mode="initial", guidance="  对手有现实利益  ")

    brief, mode, guidance = calls[0]
    assert mode == "initial"
    assert guidance == "对手有现实利益"
    assert brief.novel_type_id == "xuanhuan"
    assert brief.opening_direction.hook == "林照看守断香炉。"
    assert brief.opening_direction.primary_trope_id == "selected-trope"
    assert brief.existing_characters == []
    assert brief.existing_character_names == []
    assert brief.enabled_skill_ids == ["commercial-shuangwen"]
    assert brief.enabled_skill_module_ids == [
        "commercial-shuangwen::genre-examples",
        "commercial-shuangwen::plot-engine",
    ]
    secret = "对手有现实利益".encode("utf-8")
    assert all(secret not in path.read_bytes() for path in store.root.rglob("*") if path.is_file())


def test_outline_planning_brief_respects_explicit_project_module_disable(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "title": "照夜行",
            "seed_outline": "林照从断香炉查出宗门旧案。",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "enabled_skill_ids": ["commercial-shuangwen"],
            "enabled_skill_module_ids": [],
        },
        state={
            "current_chapter": 0,
            "enabled_skill_ids": ["legacy-pack"],
            "enabled_skill_module_ids": ["commercial-shuangwen::plot-engine"],
        },
    )

    brief = store._planning_brief()

    assert brief.enabled_skill_ids == ["commercial-shuangwen"]
    assert brief.enabled_skill_module_ids == []


@pytest.mark.parametrize(
    ("module_selection", "expected"),
    [
        (None, None),
        ([], []),
        (
            ["commercial-shuangwen::writer-execution"],
            ["commercial-shuangwen::writer-execution"],
        ),
    ],
)
def test_store_preserves_three_state_skill_module_selection(
    tmp_path,
    module_selection,
    expected,
):
    project = {
        "project_id": "p-module-selection",
        "title": "石碑第九纹",
        "seed_outline": "沈砚参加宗门石碑试炼。",
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "enabled_skill_ids": ["commercial-shuangwen"],
    }
    if module_selection is not None:
        project["enabled_skill_module_ids"] = module_selection
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project=project,
        state={"story_id": "s-module-selection", "current_chapter": 0},
    )

    direction = store._story_state_payload_for_direction(
        store.state(),
        store.project(),
        1,
    )
    brief = store._planning_brief()

    assert direction["enabled_skill_module_ids"] == expected
    assert brief.enabled_skill_module_ids == expected


def test_generate_outline_plan_resumes_from_persisted_phase_checkpoints(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "seed_outline": "林照看守断香炉。",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": []},
    )
    (store.webnovel_dir / "opening_directions.json").write_text(
        json.dumps(
            {
                "schema_version": "opening-directions/v1",
                "directions": [{
                    "id": f"direction-{index}",
                    "title": f"方向{index}",
                    "hook": "林照看守断香炉。",
                    "protagonist_goal": "守住香火。",
                    "main_conflict": "有人要毁掉旧案。",
                    "growth_path": "从守住现场开始掌握宗门规则。",
                    "opening_promise": "每次解决问题都会得到线索。",
                } for index in range(1, 4)],
                "selected_id": "direction-1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class CheckpointGenerator:
        def __init__(self):
            self.calls = 0
            self.received = []

        def generate(self, brief, *, mode, guidance, phase_payloads, phase_callback):
            self.calls += 1
            self.received.append(set(phase_payloads))
            if self.calls == 1:
                phase_callback("outline_foundation", "running", None, "")
                phase_callback("outline_foundation", "completed", {"outline": {}}, "")
                phase_callback("character_roster", "running", None, "")
                phase_callback("character_roster", "completed", {"characters": []}, "")
                phase_callback("chapter_window", "running", None, "")
                phase_callback("chapter_window", "failed", None, "chapter timeout")
                raise ValueError("outline_planning_generation_failed")
            phase_callback("chapter_window", "running", None, "")
            phase_callback("chapter_window", "completed", {"chapters": []}, "")
            return _generated_opening_plan()

    generator = CheckpointGenerator()
    with pytest.raises(ValueError, match="outline_planning_generation_failed"):
        store.generate_outline_plan(generator, mode="initial")

    failed_status = store.outline_generation_checkpoints()
    assert [item["status"] for item in failed_status["phases"]] == [
        "completed", "completed", "failed"
    ]

    store.generate_outline_plan(generator, mode="initial")

    assert generator.received == [set(), {"outline_foundation", "character_roster"}]
    assert [item["status"] for item in store.outline_generation_checkpoints()["phases"]] == [
        "completed", "completed", "completed"
    ]


def test_planning_brief_falls_back_to_saved_overall_primary_trope_id(tmp_path) -> None:
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "Fallback Trope",
            "seed_outline": "Seed outline",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": []},
    )
    (store.webnovel_dir / "outline.json").write_text(
        json.dumps(
            {
                "schema_version": "project-outline/v1",
                "overall": {
                    "story": "Saved hook",
                    "protagonist_goal": "Saved goal",
                    "main_conflict": "Saved conflict",
                    "growth_path": "Saved growth",
                    "ending_direction": "Saved promise",
                    "primary_trope_id": "saved-overall-trope",
                },
                "arcs": [],
                "chapters": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    brief = store._planning_brief()

    assert brief.opening_direction.primary_trope_id == "saved-overall-trope"


def test_planning_brief_keeps_all_character_names_while_limiting_detailed_cards(tmp_path) -> None:
    project_cards = [
        _planning_card(f"已有角色{number}", "supporting")
        for number in range(1, 8)
    ]
    state_cards = [project_cards[0], _planning_card("状态角色8", "supporting")]
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "角色清单",
            "character_profiles": project_cards,
        },
        state={
            "story_id": "s-file",
            "current_chapter": 0,
            "world_facts": [],
            "characters": state_cards,
        },
    )

    brief = store._planning_brief()

    assert len(brief.existing_characters) == 6
    assert brief.existing_character_names == [
        *[f"已有角色{number}" for number in range(1, 8)],
        "状态角色8",
    ]


def test_continuation_planning_brief_loads_all_imported_history_summaries(tmp_path) -> None:
    store = _make_minimal_file_project(
        tmp_path / "continuation",
        project={
            "project_id": "p-continuation",
            "title": "万界维修工",
            "continuation": {"start_after_chapter": 141},
        },
        state={
            "story_id": "s-continuation",
            "current_chapter": 145,
            "world_facts": [],
            "characters": [],
            "chapter_summaries": [{"chapter_number": 145, "summary": "最近摘要"}],
        },
    )
    chapter_dir = store.story_system_dir / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    for number, title in ((1, "维修铺"), (141, "雪山神殿"), (142, "续写章")):
        (chapter_dir / f"{number:04d}.json").write_text(
            json.dumps(
                {
                    "chapter_number": number,
                    "chapter_title": title,
                    "chapter_summary": {"summary": f"第{number}章摘要"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    brief = store._planning_brief()

    assert brief.continuation_start_chapter == 141
    assert brief.historical_chapter_summaries == [
        {"chapter_number": 1, "title": "维修铺", "summary": "第1章摘要"},
        {"chapter_number": 141, "title": "雪山神殿", "summary": "第141章摘要"},
    ]


def test_generated_protagonist_upgrades_supporting_import_placeholder(tmp_path) -> None:
    existing = _planning_card("Lin Xiu", "supporting")
    generated = _planning_card("Lin Xiu", "protagonist")
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={"character_profiles": [existing]},
        state={"characters": [existing]},
    )

    merged = store._merge_generated_character_cards([generated])

    assert merged[0]["role"] == "protagonist"
    assert merged[0]["character_tier"] == "protagonist"


def test_generated_character_merge_normalizes_import_analysis_relationships(tmp_path) -> None:
    existing = {
        **_planning_card("Lin Xiu", "supporting"),
        "relationships": [
            {"claim": "Lin Xiu and Xiao Le are allies", "confidence": "confirmed"}
        ],
    }
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={"character_profiles": [existing]},
        state={"characters": []},
    )

    merged = store._merge_generated_character_cards(
        [_planning_card("Lin Xiu", "protagonist")]
    )

    assert merged[0]["relationships"] == {}


def _prepare_extendable_outline(tmp_path, *, locked_inner_arc: bool = False):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root)
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 10
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    if locked_inner_arc:
        current_outline["overall"].update(
            core_ending_chapter=60,
            extension_ceiling_chapter=500,
        )
        current_outline["arcs"][0].update(
            end_chapter=10,
            is_final_arc=False,
            story_nodes=[],
        )
        current_outline["arcs"].append(
            {
                **current_outline["arcs"][0],
                "id": "locked-inner",
                "title": "Locked inner",
                "start_chapter": 11,
                "end_chapter": 60,
                "trope_id": "golden_finger_first_test",
                "goal": "Test the anomaly",
                "is_final_arc": True,
                "story_nodes": _story_nodes(11, 60),
            }
        )
    store.update_project_outline(current_outline)
    prepared = store.project_outline()
    prepared.pop("source", None)
    return root, store, prepared


def _extension_plan(
    current_outline: dict,
    *,
    arcs: list[dict] | None = None,
    first_trope_beat=None,
) -> GeneratedOutlinePlan:
    return GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "overall": current_outline["overall"],
                "arcs": current_outline["arcs"] if arcs is None else arcs,
                "chapters": [
                    {
                        "chapter_number": number,
                        "goal": "继续追查旧案",
                        "obstacle": "旧档房封门",
                        "action": "林照争取查档资格",
                        "turn": "发现新的经手人",
                        "payoff": "锁定下一条线索",
                        "ending_hook": "经手人已经离宗",
                        "trope_beat": first_trope_beat if number == 11 else None,
                        "cast": ["林照", "New"],
                    }
                    for number in range(11, 21)
                ],
            },
            "characters": [_planning_card("New", "supporting")],
        }
    )


def test_extend_allows_unchanged_committed_legacy_short_volume(tmp_path) -> None:
    _, store, current_outline = _prepare_extendable_outline(tmp_path)
    current_outline["arcs"][0].update(
        end_chapter=10,
        is_final_arc=False,
        story_nodes=[],
    )
    store.update_project_outline(current_outline)
    legacy_outline = store.project_outline()
    legacy_outline.pop("source", None)

    saved = store.save_generated_outline_plan(
        _extension_plan(legacy_outline),
        mode="extend",
    )

    assert saved["outline"]["arcs"][0]["end_chapter"] == 10
    assert saved["outline"]["arcs"][0]["story_nodes"] == []


def _volume_detail_generated_chapter(chapter_number: int) -> dict:
    return {
        "chapter_number": chapter_number,
        "title": f"Detail {chapter_number}",
        "goal": f"Advance {chapter_number}",
        "obstacle": "Evidence is sealed.",
        "action": "The protagonist verifies the seal.",
        "turn": "A second signature appears.",
        "payoff": "The next witness is identified.",
        "ending_hook": "The witness has vanished.",
        "trope_beat": None,
        "cast": ["Lin Xiu"],
        "core_conflict": "The archive closes before the proof is copied.",
        "gain": "A verifiable signature.",
        "cost": "The keeper notices the search.",
        "foreshadowing": ["The second signature"],
        "state_delta_summary": "The investigation moves to the missing witness.",
        "scene_chain": [
            {
                "location": "Archive",
                "pov": "Lin Xiu",
                "goal": "Copy the proof.",
                "obstacle": "The archive is closing.",
                "action": "Compare the seals.",
                "change": "Find the second signature.",
                "next": "Question the witness.",
                "state_delta": {"clue": 1},
            },
            {
                "location": "Courtyard",
                "pov": "Lin Xiu",
                "goal": "Find the witness.",
                "obstacle": "The witness is gone.",
                "action": "Check the departure register.",
                "change": "Learn the witness left early.",
                "next": "Follow the route.",
                "state_delta": {"lead": 1},
            },
        ],
    }


def _prepare_volume_detail_project(tmp_path):
    store = _make_minimal_file_project(tmp_path / "volume-detail")
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["overall"].update(
        core_ending_chapter=60,
        extension_ceiling_chapter=60,
    )
    outline["arcs"] = [
        {
            **outline["arcs"][0],
            "id": "v3",
            "start_chapter": 1,
            "end_chapter": 60,
            "goal": "Finish the repair hearing.",
            "obstacle": "The guild seals the evidence.",
            "payoff": "Win archive access.",
            "climax": "Expose the forged seal.",
            "is_final_arc": True,
            "story_nodes": _story_nodes(1, 60),
        }
    ]
    outline["chapters"] = []
    store.update_project_outline(outline)
    return store


class _RecordingVolumeDetailGenerator:
    def __init__(self, *, fail_batch_start: int | None = None):
        self.calls: list[tuple[int, ...]] = []
        self.contexts: list[dict] = []
        self.fail_batch_start = fail_batch_start
        self.failed = False

    def generate_chapter_batch(
        self,
        brief,
        *,
        volume,
        chapter_numbers,
        previous_batches,
        adjacent_chapters=None,
        committed_context=None,
        guidance="",
    ):
        self.calls.append(tuple(chapter_numbers))
        self.contexts.append(
            {
                "previous_batches": previous_batches,
                "adjacent_chapters": adjacent_chapters or [],
                "committed_context": committed_context or {},
            }
        )
        if self.fail_batch_start == chapter_numbers[0] and not self.failed:
            self.failed = True
            raise ValueError("temporary model failure")
        return GeneratedChapterWindow.model_validate(
            {
                "chapters": [
                    _volume_detail_generated_chapter(number)
                    for number in chapter_numbers
                ]
            }
        )


def test_generate_volume_detail_calls_model_once_per_fifteen_chapter_batch(tmp_path) -> None:
    store = _prepare_volume_detail_project(tmp_path)
    generator = _RecordingVolumeDetailGenerator()

    result = store.generate_volume_detail(generator, volume_id="v3")

    assert generator.calls == [
        tuple(range(1, 16)),
        tuple(range(16, 31)),
        tuple(range(31, 46)),
        tuple(range(46, 61)),
    ]
    assert result["schema_version"] == "volume-detail-generation/v1"
    assert result["detail_status"] == "complete"
    assert result["completed_chapters"] == result["total_chapters"] == 60
    rolling = RollingOutlineStore(store.root).read_rolling_outline()
    assert [chapter["chapter_number"] for chapter in rolling["chapters"]] == list(range(1, 61))


def test_failed_second_batch_keeps_first_and_retry_starts_at_second(
    tmp_path,
    monkeypatch,
) -> None:
    store = _prepare_volume_detail_project(tmp_path)
    generator = _RecordingVolumeDetailGenerator(fail_batch_start=16)
    publish_calls: list[list[int]] = []
    original_apply = RollingOutlineStore.apply_rolling_batch

    def recording_apply(self, **kwargs):
        publish_calls.append(list(kwargs["expected_chapter_numbers"]))
        return original_apply(self, **kwargs)

    monkeypatch.setattr(RollingOutlineStore, "apply_rolling_batch", recording_apply)

    with pytest.raises(ValueError, match="^volume_detail_generation_failed:0016-0030"):
        store.generate_volume_detail(generator, volume_id="v3")

    assert RollingOutlineStore(store.root).read_rolling_outline() is None
    result = store.generate_volume_detail(generator, volume_id="v3")

    assert generator.calls.count(tuple(range(1, 16))) == 1
    assert generator.calls.count(tuple(range(16, 31))) == 2
    assert publish_calls == [list(range(1, 61))]
    assert result["detail_status"] == "complete"


def test_generate_volume_detail_handles_sparse_gaps_without_overwriting_existing(
    tmp_path,
) -> None:
    store = _prepare_volume_detail_project(tmp_path)
    outline = store.project_outline()
    outline.pop("source", None)
    template = _generated_opening_plan().outline.chapters[0].model_dump(mode="json")
    outline["chapters"] = [
        {**template, "chapter_number": number, "title": f"Existing {number}"}
        for number in range(1, 61)
        if number not in {10, 30}
    ]
    store.update_project_outline(outline)
    generator = _RecordingVolumeDetailGenerator()

    result = store.generate_volume_detail(generator, volume_id="v3")

    assert generator.calls == [(10,), (30,)]
    assert result["completed_chapters"] == result["total_chapters"] == 60
    rolling = RollingOutlineStore(store.root).read_rolling_outline()
    assert [chapter["chapter_number"] for chapter in rolling["chapters"]] == [10, 30]


def test_sparse_volume_detail_passes_real_neighbors_and_committed_facts(tmp_path) -> None:
    store = _prepare_volume_detail_project(tmp_path)
    outline = store.project_outline()
    outline.pop("source", None)
    template = _generated_opening_plan().outline.chapters[0].model_dump(mode="json")
    outline["chapters"] = [
        {**template, "chapter_number": number, "title": f"Existing {number}"}
        for number in range(1, 61)
        if number != 30
    ]
    store.update_project_outline(outline)
    state = store.state()
    state["world_facts"] = ["The archive seal is forged."]
    state["continuity_facts"] = [
        {"text": "The witness left before chapter 30.", "chapter_number": 29}
    ]
    store._write_json(store.webnovel_dir / "state.json", state)
    generator = _RecordingVolumeDetailGenerator()

    store.generate_volume_detail(generator, volume_id="v3")

    context = generator.contexts[0]
    assert [item["chapter_number"] for item in context["adjacent_chapters"]] == [29, 31]
    assert context["committed_context"]["world_facts"] == ["The archive seal is forged."]
    assert context["committed_context"]["continuity_facts"][0]["chapter_number"] == 29


def test_volume_detail_handoff_rejects_empty_previous_ending() -> None:
    with pytest.raises(ValueError, match="^volume_detail_continuity_invalid:0001-0015$"):
        FileProjectStore._validate_volume_detail_handoff(
            batch_id="0001-0015",
            chapter_numbers=list(range(1, 16)),
            generated_chapters=[
                {**_volume_detail_generated_chapter(number), "ending_hook": "" if number == 15 else "Next"}
                for number in range(1, 16)
            ],
            previous_batch=None,
            adjacent_chapters=[],
            volume_range=(1, 60),
            previous_missing_batch=None,
            next_missing_batch=(16, 30),
        )


def test_volume_detail_handoff_requires_sparse_gap_neighbors() -> None:
    with pytest.raises(ValueError, match="^volume_detail_continuity_invalid:0030-0030$"):
        FileProjectStore._validate_volume_detail_handoff(
            batch_id="0030-0030",
            chapter_numbers=[30],
            generated_chapters=[_volume_detail_generated_chapter(30)],
            previous_batch=None,
            adjacent_chapters=[{"chapter_number": 29, "title": "Before"}],
            volume_range=(1, 60),
            previous_missing_batch=(10, 10),
            next_missing_batch=None,
        )


def test_volume_detail_continuity_failure_does_not_complete_or_publish(tmp_path) -> None:
    store = _prepare_volume_detail_project(tmp_path)

    class MissingEndingGenerator(_RecordingVolumeDetailGenerator):
        def generate_chapter_batch(self, *args, **kwargs):
            result = super().generate_chapter_batch(*args, **kwargs)
            result.chapters[-1].ending_hook = ""
            return result

    with pytest.raises(ValueError, match="volume_detail_continuity_invalid:0001-0015"):
        store.generate_volume_detail(MissingEndingGenerator(), volume_id="v3")

    checkpoints = VolumeDetailCheckpointStore(store.story_system_dir / "volume-detail")
    status = checkpoints.load("v3")
    assert status["batches"][0]["status"] == "failed"
    assert RollingOutlineStore(store.root).read_rolling_outline() is None


def test_generate_volume_detail_rejects_unknown_volume_without_model_call(tmp_path) -> None:
    store = _prepare_volume_detail_project(tmp_path)
    generator = _RecordingVolumeDetailGenerator()

    with pytest.raises(ValueError, match="^volume_detail_volume_missing:next-volume$"):
        store.generate_volume_detail(generator, volume_id="next-volume")

    assert generator.calls == []


def _prepare_next_volume_design_project(tmp_path):
    store = _make_minimal_file_project(tmp_path / "next-volume-design")
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["overall"].update(
        current_strategy="expand",
        core_ending_chapter=200,
        extension_ceiling_chapter=300,
        planned_length=200,
        planned_arc_count=1,
    )
    outline["arcs"] = [
        {
            **outline["arcs"][0],
            "id": "volume-1",
            "start_chapter": 1,
            "end_chapter": 50,
            "is_final_arc": False,
            "story_nodes": _story_nodes(1, 50),
            "extension_gate": {
                "continue_route": "Open the independent workshop.",
                "close_route": "Publish the first ledger.",
            },
            "end_state": "The first guild license is revoked.",
        }
    ]
    outline["chapters"] = []
    store.update_project_outline(outline)
    state = store.state()
    state["current_chapter"] = 50
    state["world_facts"] = ["The first guild license is revoked."]
    state["foreshadowing"] = [
        {
            "id": "seal-signature",
            "text": "The old guild seal contains a second signature.",
            "status": "open",
            "introduced_chapter": 40,
        }
    ]
    state["characters"] = [
        {
            **_planning_card("Lin Xiu", "protagonist"),
            "current_life_profile": {"immediate_problem": "The guild sealed the workshop."},
            "real_state": {"current_goal": "Open an independent workshop."},
        }
    ]
    store._write_json(store.webnovel_dir / "state.json", state)
    return store


def _designed_next_volume(*, start_chapter=51, end_chapter=100, is_final_arc=False):
    return ArcOutline.model_validate(
        {
            "id": "volume-2",
            "title": "Independent workshop",
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "goal": "Recover the missing repair ledger.",
            "obstacle": "The guild controls every legal repair channel.",
            "payoff": "Win an independent repair license.",
            "emotional_curve": "The protagonist loses the old workshop as the price.",
            "key_results": ["Gain the license.", "Cost: lose the old workshop."],
            "hook_plan": "The ledger points to the capital.",
            "irreversible_change": "The protagonist leaves the guild permanently.",
            "end_state": "The independent workshop opens.",
            "extension_gate": {
                "continue_route": "Follow the ledger to the capital.",
                "close_route": "Publish the ledger locally.",
            },
            "midpoint_turn": "The witness forged the ledger.",
            "climax": "Expose the hidden record in public.",
            "next_arc_entry": "A capital inspector arrives.",
            "is_final_arc": is_final_arc,
            "story_nodes": _story_nodes(start_chapter, end_chapter),
        }
    )


class _NextVolumeGenerator:
    def __init__(self, result=None, *, mutate=None):
        self.result = result or _designed_next_volume()
        self.mutate = mutate
        self.calls = []

    def generate_next_volume(self, brief, *, previous_volume, guidance=""):
        self.calls.append(
            {
                "brief": brief,
                "previous_volume": previous_volume,
                "guidance": guidance,
            }
        )
        if self.mutate is not None:
            self.mutate()
        return self.result


def test_volume_workflow_status_reports_missing_plan_partial_and_ready(tmp_path) -> None:
    store = _prepare_next_volume_design_project(tmp_path)
    assert store.volume_workflow_status(51)["status"] == "volume_missing"
    assert store.volume_workflow_status(51)["next_action"] == "design_next_volume"

    store.design_next_volume(_NextVolumeGenerator())
    planned = store.volume_workflow_status(51)
    assert planned["status"] == "volume_plan_ready"
    assert planned["next_action"] == "generate_volume_detail"

    outline = store.project_outline()
    outline.pop("source", None)
    template = _generated_opening_plan().outline.chapters[0].model_dump(mode="json")
    outline["chapters"] = [{**template, "chapter_number": 51}]
    store.update_project_outline(outline)
    partial = store.volume_workflow_status(51)
    assert partial["status"] == "detail_partial"
    assert partial["next_action"] == "generate_volume_detail"

    outline["chapters"] = [
        {**template, "chapter_number": number}
        for number in range(51, 101)
    ]
    store.update_project_outline(outline)
    complete = store.volume_workflow_status(51)
    assert complete["status"] == "detail_complete"
    assert complete["detail_status"] == "detail_complete"
    assert complete["next_action"] == "generate_prose"


@pytest.mark.parametrize(
    ("status", "volume_id", "expected"),
    [
        ("volume_missing", None, "next_volume_required:51"),
        ("volume_plan_ready", "volume-2", "volume_detail_required:volume-2"),
        ("detail_partial", "volume-2", "volume_detail_incomplete:volume-2"),
    ],
)
def test_generate_next_chapter_uses_precise_volume_workflow_gate(
    tmp_path,
    monkeypatch,
    status,
    volume_id,
    expected,
) -> None:
    store = _make_minimal_file_project(
        tmp_path / f"prose-gate-{status}",
        state={"story_id": "s-file", "current_chapter": 50, "world_facts": []},
    )
    called = False

    class FakeEngine:
        def generate_next_chapter(self, story):
            nonlocal called
            called = True
            raise AssertionError("body generator must not run before the volume gate passes")

    monkeypatch.setattr(
        store,
        "volume_workflow_status",
        lambda target_chapter: {
            "schema_version": "volume-workflow/v1",
            "target_chapter": target_chapter,
            "status": status,
            "detail_status": "missing",
            "next_action": "design_next_volume",
            "volume_id": volume_id,
            "volume_range": None if volume_id is None else [51, 100],
        },
    )

    with pytest.raises(ValueError, match=f"^{re.escape(expected)}$"):
        store.generate_next_chapter(engine=FakeEngine())

    assert called is False


def test_design_next_volume_appends_plan_without_writing_detail(tmp_path) -> None:
    store = _prepare_next_volume_design_project(tmp_path)
    generator = _NextVolumeGenerator()

    result = store.design_next_volume(generator, guidance="Keep the conflict local.")

    assert result["status"] == "volume_plan_ready"
    assert result["volume_id"] == "volume-2"
    assert generator.calls[0]["previous_volume"]["id"] == "volume-1"
    assert generator.calls[0]["guidance"] == "Keep the conflict local."
    outline = store.project_outline()
    assert [arc["id"] for arc in outline["arcs"]] == ["volume-1", "volume-2"]
    assert outline["chapters"] == []
    assert RollingOutlineStore(store.root).read_rolling_outline() is None


def test_design_next_volume_is_idempotent_when_successor_exists(tmp_path) -> None:
    store = _prepare_next_volume_design_project(tmp_path)
    store.design_next_volume(_NextVolumeGenerator())
    generator = _NextVolumeGenerator(result=_designed_next_volume(start_chapter=101, end_chapter=150))

    result = store.design_next_volume(generator)

    assert result["status"] == "volume_plan_ready"
    assert result["volume_id"] == "volume-2"
    assert generator.calls == []


def test_design_next_volume_detects_optimistic_conflict_without_writing_result(tmp_path) -> None:
    store = _prepare_next_volume_design_project(tmp_path)

    def mutate_outline():
        changed = store.project_outline()
        changed.pop("source", None)
        changed["overall"]["theme_statement"] = "A concurrent edit."
        store._write_json_atomic(store.webnovel_dir / "outline.json", changed)

    generator = _NextVolumeGenerator(mutate=mutate_outline)

    with pytest.raises(ValueError, match="^outline_changed_during_volume_design$"):
        store.design_next_volume(generator)

    outline = store.project_outline()
    assert [arc["id"] for arc in outline["arcs"]] == ["volume-1"]
    assert outline["overall"]["theme_statement"] == "A concurrent edit."


def test_design_next_volume_passes_current_state_context(tmp_path) -> None:
    store = _prepare_next_volume_design_project(tmp_path)
    generator = _NextVolumeGenerator()

    store.design_next_volume(generator)

    brief = generator.calls[0]["brief"]
    assert brief.world_facts == ["The first guild license is revoked."]
    assert brief.unresolved_foreshadowing[0]["text"] == "The old guild seal contains a second signature."
    assert brief.character_current_states[0]["name"] == "Lin Xiu"
    assert brief.character_current_states[0]["real_state"]["current_goal"] == "Open an independent workshop."


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ({"start_chapter": 52}, "next_volume_start_mismatch"),
        ({"end_chapter": 80}, "volume_too_short:volume-2"),
        ({"story_nodes": _story_nodes(51, 85)}, "story_node_gap:volume-2"),
    ],
)
def test_design_next_volume_revalidates_model_output_without_writing(
    tmp_path,
    mutation,
    error,
) -> None:
    store = _prepare_next_volume_design_project(tmp_path)
    candidate = _designed_next_volume().model_dump(mode="json")
    candidate.update(mutation)
    before = (store.webnovel_dir / "outline.json").read_bytes()

    with pytest.raises(ValueError, match=f"^{error}$"):
        store.design_next_volume(_NextVolumeGenerator(result=candidate))

    assert (store.webnovel_dir / "outline.json").read_bytes() == before
    assert RollingOutlineStore(store.root).read_rolling_outline() is None


def test_design_next_volume_allows_short_final_for_close_strategy(tmp_path) -> None:
    store = _prepare_next_volume_design_project(tmp_path)
    outline = store.project_outline()
    outline.pop("source", None)
    outline["overall"]["current_strategy"] = "close"
    store._write_json_atomic(store.webnovel_dir / "outline.json", outline)

    result = store.design_next_volume(
        _NextVolumeGenerator(
            result=_designed_next_volume(end_chapter=70, is_final_arc=True)
        )
    )

    assert result["volume_range"] == [51, 70]
    saved = store.project_outline()
    assert saved["arcs"][-1]["is_final_arc"] is True
    assert saved["overall"]["core_ending_chapter"] == 70
    assert RollingOutlineStore(store.root).read_rolling_outline() is None


@pytest.mark.parametrize("strategy", ["expand", "observe"])
def test_design_next_volume_rejects_short_final_at_core_ending_without_close(
    tmp_path,
    strategy,
) -> None:
    store = _prepare_next_volume_design_project(tmp_path)
    outline = store.project_outline()
    outline.pop("source", None)
    outline["overall"].update(
        current_strategy=strategy,
        core_ending_chapter=200,
        extension_ceiling_chapter=300,
    )
    outline["arcs"][0].update(
        end_chapter=200,
        story_nodes=_story_nodes(1, 200),
    )
    store._write_json_atomic(store.webnovel_dir / "outline.json", outline)
    state = store.state()
    state["current_chapter"] = 200
    store._write_json_atomic(store.webnovel_dir / "state.json", state)
    candidate = _designed_next_volume(
        start_chapter=201,
        end_chapter=220,
        is_final_arc=True,
    )

    with pytest.raises(ValueError, match="^unexpected_final_volume$"):
        store.design_next_volume(_NextVolumeGenerator(result=candidate))

    assert len(store.project_outline()["arcs"]) == 1


def test_foundation_save_allows_unchanged_committed_legacy_short_volume(
    tmp_path,
) -> None:
    _, store, current_outline = _prepare_extendable_outline(tmp_path)
    current_outline["arcs"][0].update(
        end_chapter=10,
        is_final_arc=False,
        story_nodes=[],
    )
    store.update_project_outline(current_outline)
    legacy_outline = store.project_outline()
    legacy_outline.pop("source", None)

    saved = store._save_generated_outline_foundation(
        _regeneration_plan_from_current(legacy_outline),
        mode="regenerate",
    )

    assert saved["outline"]["arcs"][0]["end_chapter"] == 10
    assert saved["outline"]["arcs"][0]["story_nodes"] == []


def test_extend_generated_outline_plan_fills_missing_rolling_window_chapters(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 10
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    store.update_project_outline(current_outline)
    addition = GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "overall": current_outline["overall"],
                "arcs": [
                    {
                        **current_outline["arcs"][0],
                        "end_chapter": 150,
                        "long_term_antagonist_traces": ["旧名册被换过", "执法堂有人提前封档"],
                    }
                ],
                "chapters": [
                    {
                        "chapter_number": number,
                        "goal": "继续追查旧案",
                        "obstacle": "旧档房封闭",
                        "action": "林照争取查档资格",
                        "turn": "发现新的经手人",
                        "payoff": "锁定下一条线索",
                        "ending_hook": "经手人已经离宗",
                        "cast": ["林照", "周满"],
                    }
                    for number in range(11, 21)
                ]
            },
            "characters": [_planning_card("新档房弟子", "supporting")],
        }
    )

    saved = store.save_generated_outline_plan(addition, mode="extend")

    assert [item["chapter_number"] for item in saved["outline"]["chapters"]] == list(range(1, 21))
    assert saved["outline"]["arcs"][0]["trope_id"] == "low_status_reversal"
    assert saved["outline"]["chapters"][0]["trope_beat"] == "低位压力"
    assert saved["outline"]["arcs"][0]["end_chapter"] == 150
    assert saved["outline"]["arcs"][0]["long_term_antagonist_traces"] == [
        "旧名册被换过",
        "执法堂有人提前封档",
    ]
    assert any(item["name"] == "新档房弟子" for item in saved["characters"])


@pytest.mark.parametrize(
    "new_card_name,cast,error",
    [
        ("新角色", ["未知角色"], "missing_character_card:未知角色"),
        ("林照", ["林照"], "duplicate_existing_character_card:林照"),
    ],
)
def test_extend_direct_save_revalidates_cast_and_new_cards_without_writes(
    tmp_path,
    new_card_name: str,
    cast: list[str],
    error: str,
) -> None:
    store = _make_minimal_file_project(tmp_path / "novel")
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 10
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    store.update_project_outline(current_outline)
    addition = GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "overall": current_outline["overall"],
                "arcs": [current_outline["arcs"][0]],
                "chapters": [
                    {
                        "chapter_number": number,
                        "goal": "继续追查旧案",
                        "obstacle": "旧档房封闭",
                        "action": "林照争取查档资格",
                        "turn": "发现新的经手人",
                        "payoff": "锁定下一条线索",
                        "ending_hook": "经手人已经离宗",
                        "cast": cast,
                    }
                    for number in range(11, 21)
                ],
            },
            "characters": [_planning_card(new_card_name, "supporting")],
        }
    )
    before = {
        path.relative_to(store.root): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match=f"^{error}$"):
        store.save_generated_outline_plan(addition, mode="extend")

    assert {
        path.relative_to(store.root): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.parametrize(
    "overall_trope_id,arc_trope_id,error",
    [
        ("golden_finger_first_test", "low_status_reversal", "unexpected_primary_trope_id"),
        ("low_status_reversal", "golden_finger_first_test", "locked_arc_trope_drift:opening"),
    ],
)
def test_extend_rejects_locked_trope_drift_without_writes(
    tmp_path,
    overall_trope_id: str,
    arc_trope_id: str,
    error: str,
) -> None:
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root)
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 10
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    store.update_project_outline(current_outline)
    addition = GeneratedOutlinePlan.model_validate(
        {
            "outline": {
                "overall": {**current_outline["overall"], "primary_trope_id": overall_trope_id},
                "arcs": [{**current_outline["arcs"][0], "trope_id": arc_trope_id}],
                "chapters": [
                    {
                        "chapter_number": number,
                        "goal": "继续追查旧案",
                        "obstacle": "旧档房封门",
                        "action": "林照争取查档资格",
                        "turn": "发现新的经手人",
                        "payoff": "锁定下一条线索",
                        "ending_hook": "经手人已经离宗",
                        "trope_beat": None,
                        "cast": ["林照", "New"],
                    }
                    for number in range(11, 21)
                ],
            },
            "characters": [_planning_card("New", "supporting")],
        }
    )
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match=f"^{error}$"):
        store.save_generated_outline_plan(addition, mode="extend")

    assert _file_snapshot(root) == before


def test_extend_allows_unlocked_legacy_outline_without_selecting_trope(
    tmp_path,
) -> None:
    _, store, current_outline = _prepare_extendable_outline(tmp_path)
    current_outline["overall"]["primary_trope_id"] = None
    for arc in current_outline["arcs"]:
        arc["trope_id"] = None
    for chapter in current_outline["chapters"]:
        chapter["trope_beat"] = None
    store.update_project_outline(current_outline)

    saved = store.save_generated_outline_plan(
        _extension_plan(current_outline),
        mode="extend",
    )

    assert saved["outline"]["overall"]["primary_trope_id"] is None
    assert all(arc["trope_id"] is None for arc in saved["outline"]["arcs"])
    assert all(
        chapter["trope_beat"] is None
        for chapter in saved["outline"]["chapters"]
        if chapter["chapter_number"] > 10
    )


def test_outline_extension_readiness_reports_missing_prerequisites(tmp_path) -> None:
    _, store, current_outline = _prepare_extendable_outline(tmp_path)
    current_outline["overall"]["story"] = ""
    current_outline["arcs"] = []
    store.update_project_outline(current_outline)
    project = store.project()
    project["character_profiles"] = []
    project["world_blueprint"] = {}
    store._write_json(store.webnovel_dir / "project.json", project)
    state = store.state()
    state["characters"] = []
    store._write_json(store.webnovel_dir / "state.json", state)

    readiness = store.outline_extension_readiness()

    assert readiness["ready"] is False
    assert {item["code"] for item in readiness["blockers"]} == {
        "overall_core_required",
        "stage_arc_required",
        "protagonist_card_required",
        "world_context_required",
    }
    assert readiness["next_chapter_numbers"] == list(range(11, 26))


def test_outline_extension_readiness_accepts_complete_materials(tmp_path) -> None:
    _, store, _ = _prepare_extendable_outline(tmp_path)
    project = store.project()
    project["world_blueprint"] = {
        "premise": "A grounded cultivation mystery.",
        "world_rules": ["Every repair consumes a matching material."],
    }
    store._write_json(store.webnovel_dir / "project.json", project)

    readiness = store.outline_extension_readiness()

    assert readiness["ready"] is True
    assert readiness["blockers"] == []
    assert readiness["next_chapter_numbers"] == list(range(11, 26))


def test_extend_does_not_call_model_when_prerequisites_are_missing(tmp_path) -> None:
    _, store, _ = _prepare_extendable_outline(tmp_path)

    class Generator:
        def generate(self, brief, *, mode, guidance):
            raise AssertionError("planner must not run before readiness passes")

    with pytest.raises(
        ValueError,
        match="^outline_extension_not_ready:world_context_required$",
    ):
        store.generate_outline_plan(Generator(), mode="extend")


def _regeneration_plan_from_current(
    current_outline: dict,
    *,
    arcs: list[dict] | None = None,
    first_trope_beat=None,
) -> GeneratedOutlinePlan:
    payload = _generated_opening_plan().model_dump(mode="json")
    template = payload["outline"]["chapters"][0]
    payload["outline"]["overall"] = {
        **payload["outline"]["overall"],
        **current_outline["overall"],
    }
    payload["outline"]["arcs"] = current_outline["arcs"] if arcs is None else arcs
    payload["outline"]["chapters"] = [
        {
            **template,
            "chapter_number": number,
            "title": f"Regenerated {number}",
            "trope_beat": first_trope_beat if number == 11 else None,
        }
        for number in range(11, 21)
    ]
    return GeneratedOutlinePlan.model_validate(payload)


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
@pytest.mark.parametrize("candidate_state", ["empty", "replacement"])
def test_deleted_trope_locks_do_not_block_future_outline_saves(
    tmp_path,
    monkeypatch,
    mode: str,
    candidate_state: str,
) -> None:
    _, store, current_outline = _prepare_extendable_outline(tmp_path)
    current_outline["overall"]["core_ending_chapter"] = 60
    current_outline["arcs"][0].update(
        end_chapter=10,
        is_final_arc=False,
        story_nodes=[],
    )
    store.update_project_outline(current_outline)
    current_candidates = store._current_project_trope_candidates(
        store.project(),
        store.state(),
    )
    replacement = next(
        candidate
        for candidate in current_candidates
        if candidate["id"] != "low_status_reversal"
    )
    candidates = [] if candidate_state == "empty" else [replacement]
    new_trope_id = None if candidate_state == "empty" else replacement["id"]
    monkeypatch.setattr(store, "_current_project_trope_candidates", lambda *_: candidates)
    new_arc = {
        **current_outline["arcs"][0],
        "id": "new-volume",
        "title": "New volume",
        "start_chapter": 11,
        "end_chapter": 60,
        "trope_id": new_trope_id,
        "is_final_arc": True,
        "story_nodes": _story_nodes(11, 60),
    }
    plan = (
        _extension_plan(current_outline, arcs=[*current_outline["arcs"], new_arc])
        if mode == "extend"
        else _regeneration_plan_from_current(
            current_outline,
            arcs=[*current_outline["arcs"], new_arc],
        )
    )

    saved = store.save_generated_outline_plan(plan, mode=mode)

    arcs = {arc["id"]: arc for arc in saved["outline"]["arcs"]}
    assert saved["outline"]["overall"]["primary_trope_id"] == "low_status_reversal"
    assert arcs["opening"]["trope_id"] == "low_status_reversal"
    assert arcs["new-volume"]["trope_id"] == new_trope_id
    assert saved["outline"]["chapters"][0]["trope_beat"] == "低位压力"


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_deleted_trope_library_still_rejects_unknown_new_arc_id(
    tmp_path,
    monkeypatch,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    current_outline["overall"]["core_ending_chapter"] = 60
    current_outline["arcs"][0].update(
        end_chapter=10,
        is_final_arc=False,
        story_nodes=[],
    )
    store.update_project_outline(current_outline)
    monkeypatch.setattr(store, "_current_project_trope_candidates", lambda *_: [])
    new_arc = {
        **current_outline["arcs"][0],
        "id": "new-volume",
        "title": "New volume",
        "start_chapter": 11,
        "end_chapter": 60,
        "trope_id": "unknown-new-trope",
        "is_final_arc": True,
        "story_nodes": _story_nodes(11, 60),
    }
    plan = (
        _extension_plan(current_outline, arcs=[*current_outline["arcs"], new_arc])
        if mode == "extend"
        else _regeneration_plan_from_current(
            current_outline,
            arcs=[*current_outline["arcs"], new_arc],
        )
    )
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^(unexpected|invalid)_arc_trope_id:new-volume$"):
        store.save_generated_outline_plan(plan, mode=mode)

    assert _file_snapshot(root) == before


def _prepare_deleted_trope_boundary_regeneration(tmp_path, monkeypatch):
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    current_outline["chapters"][9]["trope_beat"] = "committed orphan beat"
    current_outline["chapters"].append(
        {**current_outline["chapters"][9], "chapter_number": 11, "trope_beat": "future orphan beat"}
    )
    store.update_project_outline(current_outline)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    monkeypatch.setattr(store, "_current_project_trope_candidates", lambda *_: [])
    return root, store, current_outline


def test_regenerate_rejects_future_fallback_orphan_beat(tmp_path, monkeypatch) -> None:
    root, store, current_outline = _prepare_deleted_trope_boundary_regeneration(
        tmp_path,
        monkeypatch,
    )
    plan = _regeneration_plan_from_current(
        current_outline,
        first_trope_beat="future orphan beat",
    )
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^unexpected_chapter_trope_beat:11$"):
        store.save_generated_outline_plan(plan, mode="regenerate")

    assert _file_snapshot(root) == before


def test_regenerate_keeps_committed_orphan_beat_but_clears_future_beat(
    tmp_path,
    monkeypatch,
) -> None:
    _, store, current_outline = _prepare_deleted_trope_boundary_regeneration(
        tmp_path,
        monkeypatch,
    )
    plan = _regeneration_plan_from_current(current_outline, first_trope_beat=None)

    saved = store.save_generated_outline_plan(plan, mode="regenerate")

    chapters = {
        chapter["chapter_number"]: chapter
        for chapter in saved["outline"]["chapters"]
    }
    assert chapters[10]["trope_beat"] == "committed orphan beat"
    assert chapters[11]["trope_beat"] is None


def test_generic_regeneration_variants_do_not_embed_one_books_terms(tmp_path):
    store = FileProjectStore(tmp_path / "neutral-regeneration")

    variant = store._regeneration_variant(1)
    rendered = json.dumps(variant, ensure_ascii=False)

    for term in ("灰狼", "药剂铺", "背包", "法杖", "清道夫", "千倍爆率"):
        assert term not in rendered
    assert store._regeneration_title_override(1, variant["id"]) is None


@pytest.mark.parametrize(
    ("mode", "preserves_future_arc"),
    [("extend", True), ("regenerate", False)],
)
def test_generated_outline_handles_omitted_future_arc_by_mode(
    tmp_path,
    mode: str,
    preserves_future_arc: bool,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path, locked_inner_arc=True)
    generated_arcs = [arc for arc in current_outline["arcs"] if arc["id"] != "locked-inner"]
    plan = (
        _extension_plan(current_outline, arcs=generated_arcs)
        if mode == "extend"
        else _regeneration_plan_from_current(current_outline, arcs=generated_arcs)
    )
    if mode == "regenerate":
        before = _file_snapshot(root)
        with pytest.raises(ValueError, match="^volume_too_short:opening$"):
            store.save_generated_outline_plan(plan, mode=mode)
        assert _file_snapshot(root) == before
        return

    saved = store.save_generated_outline_plan(plan, mode=mode)

    has_future_arc = any(
        arc["id"] == "locked-inner" and arc["trope_id"] == "golden_finger_first_test"
        for arc in saved["outline"]["arcs"]
    )
    assert has_future_arc is preserves_future_arc
    assert _file_snapshot(root)


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_rejects_future_nested_arc_inside_locked_arc(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    nested = {
        **current_outline["arcs"][0],
        "id": "future-nested",
        "title": "Future nested",
        "start_chapter": 11,
        "end_chapter": 15,
        "trope_id": "golden_finger_first_test",
        "goal": "Test the anomaly",
    }
    plan = (
        _extension_plan(current_outline, arcs=[*current_outline["arcs"], nested])
        if mode == "extend"
        else _regeneration_plan_from_current(current_outline, arcs=[*current_outline["arcs"], nested])
    )
    before = _file_snapshot(root)

    with pytest.raises(
        ValueError,
        match="^volume_overlap:opening:future-nested$",
    ):
        store.save_generated_outline_plan(plan, mode=mode)

    assert _file_snapshot(root) == before


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_rejects_renamed_arc_overlapping_committed_locked_range_without_writes(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    renamed = {**current_outline["arcs"][0], "id": "renamed-opening", "start_chapter": 10, "end_chapter": 30}
    plan = (
        _extension_plan(current_outline, arcs=[renamed])
        if mode == "extend"
        else _regeneration_plan_from_current(current_outline, arcs=[*current_outline["arcs"], renamed])
    )
    before = _file_snapshot(root)

    with pytest.raises(
        ValueError,
        match="^(volume_first_chapter_must_be_one:renamed-opening|volume_overlap:opening:renamed-opening)$",
    ):
        store.save_generated_outline_plan(plan, mode=mode)

    assert _file_snapshot(root) == before


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_rejects_renamed_arc_exactly_replacing_locked_range_without_writes(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    renamed = {**current_outline["arcs"][0], "id": "renamed-opening"}
    plan = (
        _extension_plan(current_outline, arcs=[renamed])
        if mode == "extend"
        else _regeneration_plan_from_current(current_outline, arcs=[renamed])
    )
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^locked_arc_overlap:renamed-opening$"):
        store.save_generated_outline_plan(plan, mode=mode)

    assert _file_snapshot(root) == before


def test_regenerate_rejects_same_id_locked_trope_drift_without_writes(tmp_path) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path)
    drifted = [{**current_outline["arcs"][0], "trope_id": "golden_finger_first_test"}]
    plan = _regeneration_plan_from_current(current_outline, arcs=drifted)
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^locked_arc_trope_drift:opening$"):
        store.save_generated_outline_plan(plan, mode="regenerate")

    assert _file_snapshot(root) == before


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_accepts_omitted_locked_arc_as_trope_beat_context(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path, locked_inner_arc=True)
    generated_arcs = [arc for arc in current_outline["arcs"] if arc["id"] != "locked-inner"]
    if mode == "extend":
        plan = _extension_plan(
            current_outline,
            arcs=generated_arcs,
            first_trope_beat="异常出现",
        )
    else:
        plan = _regeneration_plan_from_current(current_outline, arcs=generated_arcs)
        payload = plan.model_dump(mode="json")
        for chapter in payload["outline"]["chapters"]:
            if chapter["chapter_number"] == 11:
                chapter["trope_beat"] = "异常出现"
        plan = GeneratedOutlinePlan.model_validate(payload)

    if mode == "regenerate":
        with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:11$"):
            store.save_generated_outline_plan(plan, mode=mode)
        return

    saved = store.save_generated_outline_plan(plan, mode=mode)
    assert any(
        arc["id"] == "locked-inner" and arc["trope_id"] == "golden_finger_first_test"
        for arc in saved["outline"]["arcs"]
    )
    assert _file_snapshot(root)


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generated_outline_rejects_invalid_beat_after_locked_arc_context_merge(
    tmp_path,
    mode: str,
) -> None:
    root, store, current_outline = _prepare_extendable_outline(tmp_path, locked_inner_arc=True)
    generated_arcs = [arc for arc in current_outline["arcs"] if arc["id"] != "locked-inner"]
    if mode == "extend":
        plan = _extension_plan(
            current_outline,
            arcs=generated_arcs,
            first_trope_beat="低位压力",
        )
    else:
        plan = _regeneration_plan_from_current(current_outline, arcs=generated_arcs)
        payload = plan.model_dump(mode="json")
        for chapter in payload["outline"]["chapters"]:
            if chapter["chapter_number"] == 11:
                chapter["trope_beat"] = "低位压力"
        plan = GeneratedOutlinePlan.model_validate(payload)
    before = _file_snapshot(root)

    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:11$"):
        store.save_generated_outline_plan(plan, mode=mode)

    assert _file_snapshot(root) == before


def test_regenerate_preserves_committed_chapter_outline(tmp_path) -> None:
    store = _make_minimal_file_project(tmp_path / "novel")
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    state = store.state()
    state["current_chapter"] = 10
    state["world_facts"] = [{"fact": "Committed fact"}]
    store._write_json(store.webnovel_dir / "state.json", state)
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=150,
        extension_ceiling_chapter=500,
        current_strategy="expand",
        ending_contract="Close both lines.",
    )
    current_outline["arcs"][0].update(
        end_chapter=150,
        game_line_payoff="Win the game arc.",
        reality_line_payoff="Resolve the reality pressure.",
        extension_gate={"continue_route": "Enter the city.", "close_route": "Close the case."},
    )
    store.update_project_outline(current_outline)
    before_outline = store.project_outline()
    before_chapter = before_outline["chapters"][0]

    payload = _generated_opening_plan().model_dump(mode="json")
    template = payload["outline"]["chapters"][0]
    payload["outline"]["arcs"] = current_outline["arcs"]
    payload["outline"]["chapters"] = [
        {
            **template,
            "chapter_number": number,
            "title": f"Regenerated {number}",
            "trope_beat": None,
        }
        for number in range(11, 21)
    ]
    payload["outline"]["overall"]["story"] = "Regenerated future story"
    generated_plan = GeneratedOutlinePlan.model_validate(payload)

    store.save_generated_outline_plan(generated_plan, mode="regenerate")

    after = store.project_outline()
    assert after["chapters"][0] == before_chapter
    assert [item["chapter_number"] for item in after["chapters"]] == list(range(1, 21))
    assert after["overall"]["story"] == "Regenerated future story"
    assert store.state()["world_facts"] == [{"fact": "Committed fact"}]


def test_regenerate_drops_omitted_future_only_arc(tmp_path) -> None:
    _, store, current_outline = _prepare_extendable_outline(tmp_path)
    future_placeholder = {
        **current_outline["arcs"][0],
        "id": "future-placeholder",
        "title": "Future placeholder",
        "start_chapter": 11,
        "end_chapter": 20,
    }
    current_outline["arcs"].append(future_placeholder)
    store.update_project_outline(current_outline)
    saved_current = store.project_outline()
    saved_current.pop("source", None)
    generated_arcs = [
        arc for arc in saved_current["arcs"] if arc["id"] != "future-placeholder"
    ]
    plan = _regeneration_plan_from_current(saved_current, arcs=generated_arcs)

    saved = store.save_generated_outline_plan(plan, mode="regenerate")

    assert "future-placeholder" not in {arc["id"] for arc in saved["outline"]["arcs"]}


def test_continuation_regenerate_preserves_historical_arcs_and_drops_crossing_placeholder(tmp_path) -> None:
    store = _make_minimal_file_project(
        tmp_path / "continuation-history",
        project={"continuation": {"start_after_chapter": 141}},
        state={"current_chapter": 145, "world_facts": [], "characters": []},
    )
    current = _generated_opening_plan().outline.model_dump(mode="json")
    historical = {
        **current["arcs"][0],
        "id": "history-1",
        "title": "原著第一阶段",
        "start_chapter": 1,
        "end_chapter": 141,
        "extension_gate": {"continue_route": "进入下一阶段", "close_route": "按原著结果收束"},
    }
    historical.pop("pacing_stage_id", None)
    crossing = {
        **current["arcs"][0],
        "id": "old-crossing",
        "title": "错误跨界阶段",
        "start_chapter": 1,
        "end_chapter": 153,
        "extension_gate": {"continue_route": "追查总部", "close_route": "守住神殿"},
    }
    current["overall"].update(core_ending_chapter=300, extension_ceiling_chapter=500)
    current["arcs"] = [historical, crossing]
    current["chapters"] = []
    generated = deepcopy(current)
    generated["arcs"] = [
        {**historical, "title": "模型试图改写历史"},
        {
            **historical,
            "id": "future-142",
            "title": "续写阶段",
            "start_chapter": 142,
            "end_chapter": 300,
        },
    ]

    merged = store._preserve_committed_outline(
        current,
        generated,
        current_chapter=145,
        immutable_arc_through=141,
    )

    arcs = {arc["id"]: arc for arc in merged["arcs"]}
    assert arcs["history-1"] == historical
    assert "old-crossing" not in arcs
    assert arcs["future-142"]["start_chapter"] == 142


def test_continuation_trope_lock_ignores_old_arc_crossing_import_boundary() -> None:
    current = _generated_opening_plan().outline.model_dump(mode="json")
    current["arcs"][0].update(start_chapter=1, end_chapter=153)
    generated = deepcopy(current)
    generated["arcs"] = [
        {
            **current["arcs"][0],
            "id": "historical-reconstruction",
            "start_chapter": 1,
            "end_chapter": 141,
        },
        {
            **current["arcs"][0],
            "id": "future-plan",
            "start_chapter": 142,
            "end_chapter": 300,
        },
    ]

    FileProjectStore._validate_generated_locked_tropes_match(
        current,
        generated,
        current_chapter=145,
        locked_through_chapter=141,
    )


def test_continuation_outline_splits_generated_arc_at_import_boundary() -> None:
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["arcs"] = [
        {**outline["arcs"][0], "id": "history", "start_chapter": 1, "end_chapter": 140},
        {**outline["arcs"][0], "id": "crossing", "start_chapter": 141, "end_chapter": 153},
        {**outline["arcs"][0], "id": "future", "start_chapter": 154, "end_chapter": 220},
    ]

    normalized = FileProjectStore._split_outline_arcs_at_boundary(outline, 141)

    assert [(arc["id"], arc["start_chapter"], arc["end_chapter"]) for arc in normalized["arcs"]] == [
        ("history", 1, 140),
        ("crossing-history", 141, 141),
        ("crossing", 142, 153),
        ("future", 154, 220),
    ]
    assert all(
        not (arc["start_chapter"] <= 141 < arc["end_chapter"])
        for arc in normalized["arcs"]
    )


def test_regenerate_at_extension_ceiling_rejects_without_file_changes(tmp_path) -> None:
    store = _make_minimal_file_project(tmp_path / "novel")
    store.save_generated_outline_plan(_generated_opening_plan(), mode="initial")
    current_outline = store.project_outline()
    current_outline.pop("source", None)
    current_outline["overall"].update(
        core_ending_chapter=500,
        extension_ceiling_chapter=500,
    )
    current_outline["arcs"][0]["end_chapter"] = 500
    store.update_project_outline(current_outline)
    state = store.state()
    state["current_chapter"] = 500
    store._write_json(store.webnovel_dir / "state.json", state)

    payload = _generated_opening_plan().model_dump(mode="json")
    payload["outline"]["overall"].update(
        core_ending_chapter=500,
        extension_ceiling_chapter=500,
    )
    payload["outline"]["arcs"][0]["end_chapter"] = 500
    payload["outline"]["chapters"] = []

    before = {
        path.relative_to(store.root): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="^outline_window_already_full$"):
        store.save_generated_outline_plan(
            GeneratedOutlinePlan.model_validate(payload),
            mode="regenerate",
        )

    assert {
        path.relative_to(store.root): path.read_bytes()
        for path in store.root.rglob("*")
        if path.is_file()
    } == before


def test_writing_packet_uses_planned_cast_and_hides_long_term_secrets(tmp_path):
    root = tmp_path / "novel"
    characters = [
        _planning_card("林照", "protagonist", age=19),
        _planning_card("赵衡", "stage_antagonist"),
        _planning_card("周满", "supporting"),
        {
            **_planning_card("顾长老", "long_term_antagonist"),
            "story_drive": {
                "immediate_goal": "让赵衡清掉旧档",
                "failure_stakes": "旧案牵出自己",
                "hidden_matters": ["亲手换掉旧名册"],
            },
            "secrets": ["真实身份是执法堂首座"],
        },
    ]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "character_profiles": characters,
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={
            "story_id": "s-file",
            "current_chapter": 0,
            "world_facts": [],
            "characters": characters,
        },
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["overall"]["ending_contract"] = "游戏线与现实线完整收束。"
    outline["chapters"][0]["cast"] = ["林照", "赵衡", "顾长老"]
    (root / ".webnovel" / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert [card["name"] for card in packet["character_cards"]] == ["林照", "赵衡", "顾长老"]
    assert [card["name"] for card in packet["state"]["characters"]] == ["林照", "赵衡", "顾长老"]
    assert [card["name"] for card in packet["project"]["character_profiles"]] == ["林照", "赵衡", "顾长老"]
    serialized = json.dumps(packet, ensure_ascii=False)
    assert "亲手换掉旧名册" not in serialized
    assert "真实身份是执法堂首座" not in serialized
    assert packet["outline_context"]["active_arc"]["long_term_antagonist_traces"] == ["旧名册被换过"]
    assert packet["outline_context"]["overall"]["ending_contract"]
    assert "extension_gate" not in packet["outline_context"]["active_arc"]
    assert "chapters" not in packet["outline_context"]


def test_xianxia_writing_packet_uses_genre_neutral_titles_and_style_rules(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "xianxia-packet",
        project={
            "project_id": "p-xianxia-packet",
            "title": "万界维修工",
            "world_blueprint": {"genre_plugin_ids": ["xianxia"]},
        },
        state={
            "story_id": "s-xianxia-packet",
            "genre": "修仙",
            "genre_plugin_ids": ["xianxia"],
            "current_chapter": 143,
            "world_facts": [],
        },
    )

    packet = store.writing_packet(144)
    rendered = json.dumps(
        {
            "hard_locks": packet["hard_locks"],
            "title_contract": packet["title_contract"],
            "style_rules": packet["style_rules"],
        },
        ensure_ascii=False,
    )

    assert "具体事件、地点、物件或人物关系" in rendered
    assert "新人物必须先有角色卡" in rendered
    for term in ("网游", "法杖", "前置任务", "NPC服务点", "铜币", "交易行", "角色面板"):
        assert term not in rendered


def test_writing_packet_removes_replaced_baseline_protagonist(tmp_path):
    real_protagonist = {
        "name": "Lin Zhao",
        "role": "protagonist",
        "lifecycle_state": "active",
        "introduced_by": "",
    }
    stale_baseline = {
        "name": "Legacy Hero",
        "role": "protagonist",
        "lifecycle_state": "active",
        "introduced_by": "baseline:protagonist",
    }
    store = _make_minimal_file_project(
        tmp_path / "replaced-baseline-protagonist",
        project={
            "project_id": "p-replaced-baseline",
            "title": "Incense Hall",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={
            "story_id": "s-replaced-baseline",
            "current_chapter": 0,
            "world_facts": [],
            "characters": [real_protagonist, stale_baseline],
        },
    )

    packet = store.writing_packet(1)

    assert [card["name"] for card in packet["character_cards"]] == ["Lin Zhao"]
    assert [card["name"] for card in packet["state"]["characters"]] == ["Lin Zhao"]


def test_writing_packet_keeps_only_baseline_protagonist_when_not_replaced(tmp_path):
    baseline = {
        "name": "Only Hero",
        "role": "protagonist",
        "lifecycle_state": "active",
        "introduced_by": "baseline:protagonist",
    }
    store = _make_minimal_file_project(
        tmp_path / "only-baseline-protagonist",
        project={"project_id": "p-only-baseline", "title": "Game Story"},
        state={
            "story_id": "s-only-baseline",
            "current_chapter": 0,
            "world_facts": [],
            "characters": [baseline],
        },
    )

    packet = store.writing_packet(1)

    assert [card["name"] for card in packet["character_cards"]] == ["Only Hero"]


def test_visible_state_promotes_protagonist_from_project_character_tier(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "stale-protagonist-role",
        project={
            "project_id": "file:stale-protagonist-role",
            "title": "万界维修工",
            "character_profiles": [
                {"name": "林修", "role": "supporting", "character_tier": "protagonist"}
            ],
        },
        state={
            "story_id": "s-stale-role",
            "outline": "林修继承维修之道。",
            "genre": "玄幻",
            "style": "自然口语",
            "characters": [
                {"name": "林修", "role": "supporting", "character_tier": "supporting"}
            ],
        },
    )

    character = store.state()["characters"][0]

    assert character["role"] == "protagonist"
    assert character["character_tier"] == "protagonist"


def test_direction_payload_promotes_stale_chapter_snapshot_protagonist(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "stale-snapshot-protagonist",
        project={
            "project_id": "file:stale-snapshot-protagonist",
            "title": "万界维修工",
            "character_profiles": [
                {"name": "林修", "role": "supporting", "character_tier": "protagonist"}
            ],
        },
        state={
            "story_id": "s-stale-snapshot-role",
            "outline": "林修继承维修之道。",
            "genre": "玄幻",
            "style": "自然口语",
            "current_chapter": 2,
            "characters": [
                {"name": "林修", "role": "protagonist", "character_tier": "protagonist"}
            ],
        },
    )
    stale_snapshot = {
        "story_id": "s-stale-snapshot-role",
        "outline": "林修继承维修之道。",
        "genre": "玄幻",
        "style": "自然口语",
        "current_chapter": 1,
        "characters": [
            {"name": "林修", "role": "supporting", "character_tier": "supporting"}
        ],
    }

    payload = store._story_state_payload_for_direction(stale_snapshot, store.project(), 2)

    assert payload["characters"][0]["role"] == "protagonist"
    assert payload["characters"][0]["character_tier"] == "protagonist"


def test_writing_packet_only_includes_relationships_within_chapter_cast(tmp_path):
    characters = [
        _planning_card("Lin Zhao", "protagonist", age=19),
        _planning_card("Zhao Heng", "stage_antagonist"),
        _planning_card("Zhou Man", "supporting"),
    ]
    project = {
        "project_id": "p-file",
        "title": "Relations",
        "character_profiles": characters,
        "relationship_graph": [
            {"source": "Lin Zhao", "target": "Zhao Heng", "bond": "rivals", "private_notes": ["hidden patron"]},
            {"source": "Lin Zhao", "target": "Zhou Man", "bond": "friends"},
        ],
    }
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project=project,
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": characters},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0]["cast"] = ["Lin Zhao", "Zhao Heng"]
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert [(item["source"], item["target"]) for item in packet["relationship_context"]] == [
        ("Lin Zhao", "Zhao Heng")
    ]
    assert "private_notes" not in packet["relationship_context"][0]
    assert "relationship_graph" not in packet["project"]


def _character_portrait_state():
    return {
        "story_id": "s-file",
        "current_chapter": 0,
        "genre": "都市悬疑",
        "world_facts": [],
        "characters": [
            {
                "name": "林月",
                "role": "药剂师",
                "game_id": "月见",
                "npc_profile": {"service_role": "药剂师", "incentives": ["维持药材供应"]},
                "personality_portrait": {
                    "temperament": {"core_traits": ["嘴硬心软"]},
                    "voice": {"sentence_habit": "先问来意，再说规矩。"},
                },
            }
        ],
    }


def test_state_exposes_completed_character_portrait_without_writing_old_project(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root, state=_character_portrait_state())
    state_path = root / ".webnovel" / "state.json"
    before = state_path.read_text(encoding="utf-8")

    character = store.state()["characters"][0]

    assert character["personality_portrait"]["temperament"]["core_traits"] == ["嘴硬心软"]
    assert character["personality_portrait"]["behavior"]["pressure_mode"]
    assert state_path.read_text(encoding="utf-8") == before


def test_update_character_merges_nested_portrait_and_finds_game_id(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel", state=_character_portrait_state())

    updated = store.update_character(
        "月见",
        {"personality_portrait": {"psychology": {"fear": "欠下人情"}}},
    )

    assert updated["name"] == "林月"
    assert updated["personality_portrait"]["temperament"]["core_traits"] == ["嘴硬心软"]
    assert updated["personality_portrait"]["psychology"]["fear"] == "欠下人情"
    persisted = store._read_json(store.webnovel_dir / "state.json")
    assert persisted["characters"][0]["personality_portrait"]["psychology"]["fear"] == "欠下人情"


def test_complete_character_portrait_persists_without_overwriting_user_fields(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel", state=_character_portrait_state())

    completed = store.complete_character_portrait("林月")

    assert completed["personality_portrait"]["temperament"]["core_traits"] == ["嘴硬心软"]
    assert completed["personality_portrait"]["growth"]["invariants"]
    persisted = store._read_json(store.webnovel_dir / "state.json")
    assert persisted["characters"][0]["personality_portrait"]["growth"]["invariants"]


def test_update_character_rejects_unknown_name_and_renaming(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel", state=_character_portrait_state())

    with pytest.raises(KeyError, match="character_not_found"):
        store.update_character("不存在", {"core_motivation": "x"})
    with pytest.raises(ValueError, match="character_name_immutable"):
        store.update_character("林月", {"name": "其他人"})


def test_regeneration_quality_allows_soft_scene_coverage_warnings():
    writing_review = {
        "issues": [
            "场景卡必写内容缺失：s3-c2-reaction-1 缺少 路人玩家抱怨爆率低。",
            "Scene contract not consumed: s1-c2-inherit-ledger missing visibility_boundary_surface.",
        ],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }
    quality_report = {"ok": False, "issues": ["writing_review"], "writing_review": writing_review}

    assert _regeneration_quality_blocking(quality_report, writing_review) is False


def test_regeneration_quality_blocks_short_chapter():
    writing_review = {
        "issues": ["章节字数偏少：当前约3061字，最低要求3800字。"],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }
    quality_report = {"ok": False, "issues": ["writing_review"], "writing_review": writing_review}

    assert _regeneration_quality_blocking(quality_report, writing_review) is True


def test_regeneration_quality_still_blocks_progression_overreach():
    writing_review = {
        "issues": ["第二章推进过快：从第一章账本直接完成元素回廊前置或升级。"],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }
    quality_report = {"ok": False, "issues": ["writing_review"], "writing_review": writing_review}

    assert _regeneration_quality_blocking(quality_report, writing_review) is True


def test_file_project_store_writes_rewrites_and_commits(tmp_path, monkeypatch):
    root = tmp_path / "novel"
    workflow_log = tmp_path / "chapter_exports" / "workflow_log.jsonl"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_WORKFLOW_LOG_PATH", str(workflow_log))
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps({"story_id": "s-file", "current_chapter": 0, "world_facts": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    store = FileProjectStore(root)
    written = store.write_chapter(
        chapter_number=1,
        title="Chapter One",
        body="Night Ember checked the village counter and kept walking.",
        next_outline="Check the wolf slope.",
        summary="Night Ember enters the village.",
        instructions=["keep it grounded"],
    )

    assert written["schema_version"] == "file-project-write/v1"
    assert "ai_flavor_review" in written["review"]
    assert "cold_reader_review" in written["review"]
    assert "cold_reader_review" in written["review"]["writing_review"]
    assert written["review"]["length_review"]["pass"] is False
    assert written["review"]["length_review"]["body_chars"] < written["review"]["length_review"]["min_chars"]
    assert written["review"]["writing_review"]["pass"] is False
    assert any("章节字数偏少" in issue for issue in written["review"]["writing_review"]["issues"])
    assert (root / ".story-system" / "chapters" / "0001.json").exists()
    assert (root / "chapters" / "0001-Chapter One.md").read_text(encoding="utf-8").startswith("Night Ember")
    assert store.summary()["current_chapter"] == 1
    assert (root / ".story-system" / "commits" / "latest_commit.json").exists()
    project_after_write = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert project_after_write["current_chapter"] == 1
    assert "continuity_state" not in project_after_write["world_blueprint"]
    state_after_write = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state_after_write["chapter_summaries"][-1]["summary"] == "Night Ember enters the village."

    rewritten = store.rewrite_chapter(
        chapter_number=1,
        title="Chapter One Revised",
        body="Night Ember bought nothing. He only counted the cost and left.",
        next_outline="Return after two more glands.",
        instructions=["remove explanatory narrator voice"],
    )

    assert rewritten["schema_version"] == "file-project-rewrite/v1"
    assert "ai_flavor_review" in rewritten["review"]
    assert "cold_reader_review" in rewritten["review"]
    assert "cold_reader_review" in rewritten["review"]["writing_review"]
    assert not (root / "chapters" / "0001-Chapter One.md").exists()
    assert (root / "chapters" / "0001-Chapter One Revised.md").read_text(encoding="utf-8").startswith("Night Ember")
    latest_commit = json.loads((root / ".story-system" / "commits" / "latest_commit.json").read_text(encoding="utf-8"))
    assert latest_commit["operation"] == "rewrite"
    assert any(item["path"] == "chapters/0001-Chapter One Revised.md" for item in latest_commit["manifest"])
    project_after_rewrite = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert "continuity_state" not in project_after_rewrite["world_blueprint"]
    state_after_rewrite = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    continuity_after_rewrite = "\n".join(item["text"] for item in state_after_rewrite["continuity_facts"])
    assert "remove explanatory narrator voice" in continuity_after_rewrite
    assert "keep it grounded" not in continuity_after_rewrite
    workflow_records = [json.loads(line) for line in workflow_log.read_text(encoding="utf-8").splitlines()]
    assert [record["operation"] for record in workflow_records] == ["write", "rewrite"]
    assert workflow_records[0]["chapter"] == 1
    assert workflow_records[1]["chapter_title"] == "Chapter One Revised"


def test_file_project_store_prompt_preview_exposes_generation_prompts(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "character_profiles": [{"name": "苏叶", "role": "protagonist"}],
            "world_blueprint": {
                "world_rules": ["NPC只能处理岗位权限内的事务。"],
                "quest_rules": ["任务必须先登记，再执行和提交。"],
                "economy_rules": ["材料价格必须来自任务、配方或真实稀缺性。"],
            },
        },
        state={
            "story_id": "s-file",
            "outline": "A grounded webgame story.",
            "genre": "网游",
            "style": "白描",
            "current_chapter": 1,
            "world_facts": ["夜烬用新手法杖验证灰狼坡。"],
            "characters": [{"name": "苏叶", "role": "protagonist", "goal": "低调验证机会"}],
        },
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "灰狼坡试水",
        "body": _long_test_body("Night Ember tests the wolf slope."),
        "event_plan": {"chapter_title": "灰狼坡试水", "next_focus": "回村接清道夫委托"},
        "writing_taskbook": {
            "chapter_number": 1,
            "chapter_title": "灰狼坡试水",
            "chapter_goal": "验证灰狼掉落",
            "target_chars": "3800到5500字",
            "style_contract": ["白描"],
            "craft_templates": ["对话场面：别人问、催或提醒；夜烬用完整句子给表面理由。"],
            "global_required": ["写出新手法杖"],
            "global_forbidden": ["不要公开暴露千倍爆率"],
            "scenes": [
                {
                    "key": "entry_login",
                    "title": "登录建号",
                    "goal": "夜烬进入灰烬村",
                    "required_surface": "游戏ID夜烬、新手法杖",
                    "forbidden_surface": "转职",
                    "entry_state": "现实余额紧张",
                    "exit_state": "进入村口",
                    "handoff": "去灰狼坡",
                    "target_chars": 900,
                }
            ],
        },
        "quality_report": {"writing_review": {"pass": False, "issues": ["对话不够自然"], "revision_plan": ["补完整对话"]}},
    }
    store._write_json(root / ".story-system" / "chapters" / "0001.json", chapter)
    store._write_json(root / ".story-system" / "reviews" / "0001.json", chapter["quality_report"])

    preview = store.prompt_preview(1)

    assert preview["schema_version"] == "file-project-prompt-preview/v1"
    assert preview["reconstructed"] is True
    assert preview["source"] == "rebuilt_from_current_project_files"
    modules = {item["key"]: item for item in preview["modules"]}
    assert {"core_context", "character_context", "genre_context", "writing_taskbook", "packet_context"}.issubset(modules)
    assert "source_body" not in modules
    keys = {item["key"] for item in preview["prompts"]}
    assert {
        "director_plan",
        "writer_body",
        "revision",
        "writing_taskbook",
        "expansion",
        "compression",
        "review_agents",
    }.issubset(keys)
    assert "style_adapt" not in keys
    by_key = {item["key"]: item for item in preview["prompts"]}
    assert "## 输出要求" in by_key["writer_body"]["content"]
    assert "## 本章方向" in by_key["writer_body"]["content"]
    assert "## 本章事实" in by_key["writer_body"]["content"]
    assert "## 出场人物" in by_key["writer_body"]["content"]
    assert "## 正文写法" in by_key["writer_body"]["content"]
    assert "character_cards" not in modules["core_context"]["content"]
    assert "苏叶" in by_key["writer_body"]["content"]
    assert "character_context" in by_key["writer_body"]["module_keys"]
    assert "NPC只能处理岗位权限内的事务" in by_key["writer_body"]["content"]
    assert "任务必须先登记" not in by_key["writer_body"]["content"]
    assert "材料价格必须来自任务" not in by_key["writer_body"]["content"]
    assert "## 网游写法" in by_key["writer_body"]["content"]
    assert "语言卡[base]" in by_key["writer_body"]["content"]
    assert "语言卡[login_server]" in by_key["writer_body"]["content"]
    assert "语言卡[combat]" in by_key["writer_body"]["content"]
    assert "语言卡[quest]" not in by_key["writer_body"]["content"]
    assert "语言卡[group_dungeon]" not in by_key["writer_body"]["content"]
    assert "genre_context" in by_key["writer_body"]["module_keys"]
    assert "web_game" not in modules["genre_context"]["content"]
    assert by_key["writer_body"]["genre_stage_profile"] == "game_webnovel"
    assert "game_webnovel.writer" in by_key["writer_body"]["genre_stage_modules"]

    context = store.prompt_context(1)
    assert context["schema_version"] == "file-project-prompt-context/v1"
    assert "prompts" not in context
    assert {item["key"] for item in context["modules"]}.issuperset(
        {"core_context", "character_context", "genre_context", "writing_taskbook"}
    )
    missing = {item["key"]: item for item in context["modules"] if item.get("available") is False}
    assert "dialogue_context" in missing
    assert "验证灰狼掉落" in by_key["writing_taskbook"]["content"]
    assert "对话场面" not in by_key["writing_taskbook"]["content"]
    assert "补完整对话" in by_key["revision"]["content"]
    assert "file-writing-packet/v1" in modules["packet_context"]["content"]
    assert modules["packet_context"]["source"] == "file_project_store.writing_packet_compact_preview"
    assert "完整写作包仍由 writing_packet 接口返回" in modules["packet_context"]["content"]
    assert "game_world_simulation" not in by_key["writer_body"]["content"]
    assert by_key["writer_body"]["chars"] < 18000
    assert modules["packet_context"]["chars"] < 12000
    assert "第一章未获大纲授权时，不新增交易、提交委托、修理或买药水。" in by_key["expansion"]["content"]
    assert "游戏账本" in by_key["compression"]["content"]
    assert "面板反馈" in by_key["compression"]["content"]
    assert "目标篇幅：保留完整网文章节感，调整到5000到5400字，绝对不要超过5500字。" in by_key["compression"]["content"]
    assert "4300到5000字" not in by_key["compression"]["content"]


def test_first_chapter_prompt_preview_uses_regeneration_start_state(tmp_path):
    root = tmp_path / "first-chapter-preview-state"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-preview-state",
            "title": "Preview State",
            "active_story_id": "s-preview-state",
            "character_profiles": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "story_drive": {
                        "long_term_goal": "在游戏里站稳脚跟",
                        "immediate_goal": "处理第一章之后的新任务",
                    },
                    "current_life_profile": {"economic_state": "第一章结束后余额332.60元"},
                }
            ],
        },
        state={
            "story_id": "s-preview-state",
            "outline": "苏叶进入新游戏。",
            "genre": "网游",
            "style": "",
            "current_chapter": 1,
            "world_facts": ["第一章结束后余额332.60元。"],
            "characters": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "memory": ["第一章已经完成。"],
                    "real_state": {"current": {"balance": "332.60元"}},
                }
            ],
        },
    )
    store._write_json(
        root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "进入游戏",
            "body": _long_test_body(),
            "event_plan": {"chapter_title": "进入游戏"},
        },
    )

    preview = store.prompt_preview(1)

    modules = {item["key"]: item["content"] for item in preview["modules"]}
    generation_context = "\n".join(
        [modules["core_context"], modules["character_context"]]
    )
    assert "332.60" not in generation_context
    assert "第一章已经完成" not in generation_context
    assert "处理第一章之后的新任务" not in generation_context
    assert "在游戏里站稳脚跟" in generation_context


def test_non_game_prompt_preview_uses_generic_expansion_and_compression(tmp_path):
    root = tmp_path / "xuanhuan-novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-xuanhuan",
            "title": "玄门旧案",
            "active_story_id": "s-xuanhuan",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={
            "story_id": "s-xuanhuan",
            "outline": "林照登录游戏后查看背包、掉落和任务面板。",
            "genre": "",
            "genre_plugin_ids": ["xuanhuan"],
            "style": "白描",
            "current_chapter": 1,
            "world_facts": ["断香炉牵动祖祠旧规。"],
            "characters": [{"name": "林照", "role": "protagonist", "goal": "查清旧案"}],
        },
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "守炉",
        "body": _long_test_body("Lin guards the censer and follows the clue."),
        "event_plan": {"chapter_title": "守炉", "next_focus": "追查账房来信"},
    }
    store._write_json(root / ".story-system" / "chapters" / "0001.json", chapter)

    preview = store.prompt_preview(1)

    prompts = {item["key"]: item["content"] for item in preview["prompts"]}
    forbidden_terms = ("登录", "掉落", "背包", "血蓝", "耐久", "寄售", "到账", "任务提交", "系统面板")
    assert all(term not in prompts["expansion"] for term in forbidden_terms)
    assert all(term not in prompts["compression"] for term in forbidden_terms)
    assert "不得新增原文或章节计划之外的设定、能力、人物关系、事件结算。" in prompts["expansion"]
    assert "核心冲突" in prompts["compression"]
    assert "人物反应" in prompts["compression"]
    assert "关键线索" in prompts["compression"]
    assert "目标篇幅：保留完整网文章节感，调整到5000到5400字，绝对不要超过5500字。" in prompts["compression"]
    assert "4300到5000字" not in prompts["compression"]


def test_game_prompt_preview_uses_explicit_plugin_id_when_genre_is_empty(tmp_path):
    root = tmp_path / "game-id-only"
    store = _make_minimal_file_project(
        root,
        project={"project_id": "p-game-id", "title": "ID Game", "active_story_id": "s-game-id"},
        state={
            "story_id": "s-game-id",
            "outline": "林照守住断香炉。",
            "genre": "",
            "genre_plugin_ids": ["game_webnovel"],
            "style": "白描",
            "current_chapter": 1,
            "characters": [{"name": "林照", "role": "protagonist"}],
        },
    )
    store._write_json(
        root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "守炉",
            "body": _long_test_body(),
            "event_plan": {"chapter_title": "守炉", "next_focus": "追查来信"},
        },
    )

    preview = store.prompt_preview(1)

    prompts = {item["key"]: item["content"] for item in preview["prompts"]}
    assert "游戏账本" in prompts["compression"]
    assert "面板反馈" in prompts["compression"]
    assert "目标篇幅：保留完整网文章节感，调整到5000到5400字，绝对不要超过5500字。" in prompts["compression"]


def test_untyped_game_text_runtime_and_preview_default_to_generic(tmp_path):
    game_text = "网游里登录游戏后，主角查看游戏ID、交易行、爆率、掉落、背包、玩家和公会。"
    root = tmp_path / "untyped-game-text"
    project = {
        "project_id": "p-untyped",
        "title": "Untyped Story",
        "active_story_id": "s-untyped",
        "seed_outline": game_text,
        "world_summary": game_text,
    }
    state = {
        "story_id": "s-untyped",
        "outline": game_text,
        "genre": "",
        "genre_plugin_ids": [],
        "style": "白描",
        "current_chapter": 1,
        "world_facts": [game_text],
        "characters": [{"name": "林照", "role": "protagonist"}],
    }
    store = _make_minimal_file_project(root, project=project, state=state)
    store._write_json(
        root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "守炉",
            "body": _long_test_body(game_text),
            "event_plan": {"chapter_title": "守炉", "next_focus": "追查来信"},
        },
    )

    preview = store.prompt_preview(1)

    prompts = {item["key"]: item["content"] for item in preview["prompts"]}
    assert store._is_game_story_payload(project, state) is False
    assert "不得新增原文或章节计划之外的设定、能力、人物关系、事件结算。" in prompts["expansion"]
    assert "核心冲突、人物反应、关键线索、代价、转折和下一步钩子" in prompts["compression"]
    assert "游戏账本" not in prompts["compression"]
    assert "面板反馈" not in prompts["compression"]


@pytest.mark.parametrize(
    ("project_genre", "blueprint_ids", "state_genre", "state_ids", "expected_game"),
    [
        ("game_webnovel", [], "", [], True),
        ("", ["game_webnovel"], "", ["xuanhuan"], False),
        ("", ["xuanhuan"], "", ["game_webnovel"], True),
        ("", [], "web game", [], True),
        ("", [], "webgame", [], True),
    ],
)
def test_prompt_preview_genre_contract_matches_runtime_effective_story(
    tmp_path,
    project_genre,
    blueprint_ids,
    state_genre,
    state_ids,
    expected_game,
):
    from packages.story_core.genre_stages.registry import genre_stage_profile_for

    root = tmp_path / f"genre-contract-{len(blueprint_ids)}-{len(state_ids)}-{state_genre or project_genre}"
    project = {
        "project_id": "p-genre-contract",
        "title": "Genre Contract",
        "active_story_id": "s-genre-contract",
        "genre": project_genre,
        "world_blueprint": {"genre_plugin_ids": blueprint_ids},
    }
    state = {
        "story_id": "s-genre-contract",
        "outline": "林照守住断香炉。",
        "genre": state_genre,
        "genre_plugin_ids": state_ids,
        "style": "白描",
        "current_chapter": 1,
        "world_facts": [],
        "characters": [{"name": "林照", "role": "protagonist"}],
    }
    store = _make_minimal_file_project(root, project=project, state=state)
    store._write_json(
        root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "守炉",
            "body": _long_test_body(),
            "event_plan": {"chapter_title": "守炉", "next_focus": "追查来信"},
        },
    )

    effective_story = StoryState.model_validate(
        store._story_state_payload_for_direction(store.state(), store.project(), 1)
    )
    preview = store.prompt_preview(1)

    prompts = {item["key"]: item["content"] for item in preview["prompts"]}
    assert (genre_stage_profile_for(effective_story).profile_id == "game_webnovel") is expected_game
    assert store._is_game_story_payload(store.project(), store.state()) is expected_game
    if expected_game:
        assert "游戏账本" in prompts["compression"]
    else:
        assert "核心冲突" in prompts["compression"]
        assert "游戏账本" not in prompts["compression"]


def test_prompt_preview_uses_project_expansion_and_compression_template_overrides(tmp_path):
    root = tmp_path / "prompt-preview-project-overrides"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-template-preview",
            "title": "Template Preview",
            "active_story_id": "s-template-preview",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        },
        state={
            "story_id": "s-template-preview",
            "outline": "林照守住断香炉。",
            "genre": "",
            "genre_plugin_ids": ["xuanhuan"],
            "style": "白描",
            "current_chapter": 1,
            "world_facts": [],
            "characters": [{"name": "林照", "role": "protagonist"}],
        },
    )
    store._write_json(
        root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "守炉",
            "body": _long_test_body(),
            "event_plan": {"chapter_title": "守炉", "next_focus": "追查来信"},
        },
    )
    store.set_prompt_template_override(
        "expansion",
        "PROJECT EXPANSION {{target_chars}}\n{{expansion_focus}}\n{{source_body}}",
    )
    store.set_prompt_template_override(
        "compression",
        "PROJECT COMPRESSION {{opening_line}}\n{{target_chars}}\n{{compression_method}}\n{{chapter_scope}}\n{{source_body}}",
    )

    preview = store.prompt_preview(1)

    prompts = {item["key"]: item["content"] for item in preview["prompts"]}
    assert "PROJECT EXPANSION" in prompts["expansion"]
    assert "PROJECT COMPRESSION" in prompts["compression"]


@pytest.mark.parametrize(
    ("genre", "plugin_id", "game_context"),
    [
        ("网游", "game_webnovel", True),
        ("玄幻", "xuanhuan", False),
    ],
)
def test_project_length_template_runtime_matches_preview_economy_normalization(
    tmp_path,
    genre,
    plugin_id,
    game_context,
):
    root = tmp_path / f"length-template-contract-{plugin_id}"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": f"p-length-template-{plugin_id}",
            "title": "Length Template Contract",
            "active_story_id": f"s-length-template-{plugin_id}",
            "world_blueprint": {"genre_plugin_ids": [plugin_id]},
        },
        state={
            "story_id": f"s-length-template-{plugin_id}",
            "outline": "主角处理第一章压力。",
            "genre": genre,
            "genre_plugin_ids": [plugin_id],
            "style": "白描",
            "current_chapter": 1,
            "world_facts": [],
            "characters": [{"name": "主角", "role": "protagonist"}],
        },
    )
    body = _long_test_body()
    store._write_json(
        root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "第一章",
            "body": body,
            "event_plan": {"chapter_title": "第一章", "next_focus": "继续追查"},
        },
    )
    store.set_prompt_template_override(
        "expansion",
        "CUSTOM EXPANSION 担保交易 {{target_chars}}\n{{expansion_focus}}\n{{source_body}}",
    )
    store.set_prompt_template_override(
        "compression",
        "CUSTOM COMPRESSION 担保订单 {{opening_line}}\n{{target_chars}}\n{{compression_method}}\n{{chapter_scope}}\n{{source_body}}",
    )
    source_body = f"[原正文由 source_body 注入；面板不展示正文全文；当前正文 {len(body)} 字。]"
    event_plan = {"chapter_title": "第一章", "next_focus": "继续追查"}
    state_before_chapter = store._state_before_chapter(1)
    story = StoryState.model_validate(
        store._story_state_payload_for_direction(
            state_before_chapter,
            store.project(),
            1,
        )
    )

    with prompt_template_scope(store.prompt_template_object, store.prompt_template_source):
        runtime_expansion = _render_expansion_length_prompt(
            story,
            source_body=source_body,
            chapter_number=1,
            event_plan=event_plan,
            world_facts=[],
        )
        runtime_compression = _render_compression_length_prompt(
            story,
            source_body=source_body,
            chapter_number=1,
            event_plan=event_plan,
            world_facts=[],
            outline_anchor=None,
        )

    preview = store.prompt_preview(1)
    prompts = {item["key"]: item["content"] for item in preview["prompts"]}

    assert prompts["expansion"] == runtime_expansion
    assert prompts["compression"] == runtime_compression
    assert normalize_legacy_economy_prompt_value(
        runtime_expansion,
        game_context=game_context,
        chapter_number=1,
    ) == runtime_expansion
    assert normalize_legacy_economy_prompt_value(
        runtime_compression,
        game_context=game_context,
        chapter_number=1,
    ) == runtime_compression
    if game_context:
        assert "担保交易" not in runtime_expansion
        assert "担保订单" not in runtime_compression
        assert "交易行" in runtime_expansion
        assert "官方兑换流水" in runtime_compression
    else:
        assert "担保交易" in runtime_expansion
        assert "担保订单" in runtime_compression


def test_prompt_preview_uses_complete_runtime_story_payload_for_author_constraints(tmp_path):
    root = tmp_path / "prompt-preview-effective-story"
    project = {
        "project_id": "p-effective-story",
        "title": "Effective Story",
        "active_story_id": "s-effective-story",
        "author_constraints": ["PROJECT_RULE"],
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
    }
    state = {
        "story_id": "s-effective-story",
        "outline": "林照守住断香炉。",
        "genre": "",
        "genre_plugin_ids": ["xuanhuan"],
        "style": "白描",
        "current_chapter": 1,
        "author_constraints": ["STATE_RULE"],
        "world_facts": [],
        "characters": [{"name": "林照", "role": "protagonist"}],
    }
    store = _make_minimal_file_project(root, project=project, state=state)
    store._write_json(
        root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "守炉",
            "body": _long_test_body(),
            "event_plan": {"chapter_title": "守炉", "next_focus": "追查来信"},
        },
    )

    effective_payload = store._story_state_payload_for_direction(store.state(), store.project(), 1)
    preview = store.prompt_preview(1)

    modules = {item["key"]: item["content"] for item in preview["modules"]}
    core_context = json.loads(modules["core_context"])
    assert effective_payload["author_constraints"] == ["PROJECT_RULE"]
    assert core_context["author_constraints"] == ["PROJECT_RULE"]
    assert "STATE_RULE" not in modules["core_context"]


def test_prompt_preview_normalizes_legacy_economy_context_in_every_active_module(tmp_path):
    root = tmp_path / "legacy-webgame"
    legacy_trade = "\u62c5\u4fdd\u4ea4\u6613"
    legacy_delivery = "\u533f\u540d\u4ea4\u5272"
    legacy_appraisal = "\u63d0\u4ea4\u9274\u5b9a"
    forbidden_currency = "\u4eba\u6c11\u5e01"
    real_project_legacy_terms = (
        "持牌虚拟资产担保平台、担保交易平台、担保平台、担保订单、担保订单号、"
        "担保交割、稀有资产担保、匿名提交、买家确认收购"
    )
    old_constraint = (
        f"第一章必须通过裂纹狼心{legacy_trade}解决现实急账；旧记录包含{real_project_legacy_terms}。"
    )
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-legacy-economy",
            "title": "旧经济流程测试",
            "active_story_id": "s-legacy-economy",
            "world_blueprint": {"world_rules": [f"裂纹狼心先{legacy_appraisal}，再{legacy_delivery}。"]},
        },
        state={
            "story_id": "s-legacy-economy",
            "outline": old_constraint,
            "genre": "网游",
            "style": "升级流",
            "current_chapter": 1,
            "author_constraints": [old_constraint],
            "world_facts": [f"到账1764.00{forbidden_currency}，付清急账后余额312.60元。"],
            "characters": [
                {"name": "苏叶", "role": "protagonist", "goals": [f"完成{legacy_trade}并处理急账"]}
            ],
        },
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "第一笔到账",
        "body": _long_test_body(f"裂纹狼心{legacy_appraisal}后进入{legacy_delivery}。"),
        "event_plan": {"turn": old_constraint},
        "writing_taskbook": {
            "chapter_number": 1,
            "chapter_goal": old_constraint,
            "global_required": [f"完成{legacy_trade}"],
            "scenes": [],
        },
        "quality_report": {
            "writing_review": {
                "pass": False,
                    "issues": [f"补足裂纹狼心{legacy_appraisal}和{legacy_delivery}"],
                "revision_plan": [f"完成{legacy_trade}"],
            }
        },
    }
    store._write_json(root / ".story-system" / "chapters" / "0001.json", chapter)
    store._write_json(root / ".story-system" / "reviews" / "0001.json", chapter["quality_report"])

    preview = store.prompt_preview(1)
    entries = {
        item["key"]: item["content"]
        for item in [*preview["modules"], *preview["prompts"]]
        if item["key"] in {"director_plan", "writer_body", "revision", "core_context", "character_context", "packet_context"}
    }
    forbidden = (legacy_trade, legacy_delivery, legacy_appraisal, forbidden_currency, "担保", "买家确认")

    assert set(entries) == {"director_plan", "writer_body", "revision", "core_context", "character_context", "packet_context"}
    for key, content in entries.items():
        assert all(term not in content for term in forbidden)
        if key in {"director_plan", "writer_body", "revision"}:
            assert "1764.00" in content or "交易行" in content
            assert all(line in content for line in opening_market_exchange_flow_lines())
    assert "1764.00" not in entries["packet_context"]

    stored_state = json.dumps(store.state(), ensure_ascii=False)
    stored_chapter = json.dumps(store.chapter(1), ensure_ascii=False)
    assert legacy_trade in stored_state
    assert forbidden_currency in stored_state
    assert legacy_appraisal in stored_chapter


def test_real_project_prompt_preview_is_read_only_and_contains_no_legacy_economy_terms():
    worktree_root = Path(__file__).resolve().parents[2]
    candidates = (
        worktree_root / "data" / "exported-projects" / "p-gou-webgame-restored",
        worktree_root.parent.parent / "data" / "exported-projects" / "p-gou-webgame-restored",
    )
    root = next((candidate for candidate in candidates if candidate.exists()), None)
    if root is None:
        pytest.skip("current p-gou-webgame-restored project is unavailable")

    watched = [
        root / ".webnovel" / "project.json",
        root / ".webnovel" / "state.json",
        root / ".webnovel" / "outline.json",
        *sorted((root / "chapters").glob("0001-*.md")),
    ]
    before = {path: path.read_bytes() for path in watched if path.exists()}
    legacy_fixture_text = "\n".join(
        payload.decode("utf-8", errors="ignore") for payload in before.values()
    )
    if not any(
        marker in legacy_fixture_text
        for marker in ("担保净到账", "订单状态变成鉴定中", "匿名担保交易已完成")
    ):
        pytest.skip("real project fixture no longer contains the legacy economy flow")

    preview = FileProjectStore(root).prompt_preview(1)

    entries = {
        item["key"]: item["content"]
        for item in [*preview["modules"], *preview["prompts"]]
        if item["key"]
        in {
            "director_plan",
            "writer_body",
            "revision",
            "core_context",
            "character_context",
            "genre_context",
            "review_context",
            "packet_context",
        }
    }
    entries["writing_packet"] = json.dumps(
        FileProjectStore(root).writing_packet(1),
        ensure_ascii=False,
    )
    forbidden_currency = "\u4eba\u6c11\u5e01"
    legacy_pattern = re.compile(
        "|".join(
            re.escape(term)
            for term in (
                "担保",
                "匿名交割",
                "封存交割",
                "提交鉴定",
                "鉴定中",
                "平台验货",
                "买家确认",
                forbidden_currency,
            )
        )
    )
    future_chapter_pattern = re.compile(
        r"第(?:[二三四五六七八九十百千万零〇两]+|(?:[2-9]\d*|1\d+))章"
    )

    assert set(entries) == {
        "director_plan",
        "writer_body",
        "revision",
        "core_context",
        "character_context",
        "genre_context",
        "review_context",
        "packet_context",
        "writing_packet",
    }
    flow_keys = {
        "director_plan",
        "writer_body",
        "revision",
        "core_context",
        "character_context",
        "packet_context",
        "writing_packet",
    }
    for key, content in entries.items():
        for match in legacy_pattern.finditer(content):
            line_start = content.rfind("\n", 0, match.start()) + 1
            assert future_chapter_pattern.search(content[line_start : match.start()]) is not None
        if key in flow_keys:
            positions = [content.index(line) for line in opening_market_exchange_flow_lines()]
            assert positions == sorted(positions)
    assert "第5章写担保名单" in entries["core_context"]
    assert {path: path.read_bytes() for path in before} == before


def test_file_project_writing_packet_includes_enabled_skill_context(tmp_path, monkeypatch):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "outline": "A grounded webgame story.", "genre": "网游", "current_chapter": 0},
    )
    pack = tmp_path / "skill-pack"
    (pack / "skills" / "writer").mkdir(parents=True)
    (pack / "SKILL.md").write_text("---\nname: local-pack\n---\n\n# Local Pack", encoding="utf-8")
    (pack / "skills" / "writer" / "SKILL.md").write_text(
        "---\nname: writer\ndescription: 正文写作\n---\n\n写出自然对话。",
        encoding="utf-8",
    )
    registry = tmp_path / "registry"
    import_skill_pack_from_path(pack, root=registry)
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))

    store.update_project({"enabled_skill_ids": ["local-pack"]})
    packet = store.writing_packet(1)

    assert packet["skill_context"]["writer"][0]["skill_id"] == "local-pack"
    assert packet["skill_context"]["writer"][0]["modules"][0]["module_id"] == "writer"


def test_file_project_store_generates_next_chapter_without_api(tmp_path):
    root = tmp_path / "novel"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-file",
                "outline": "A grounded game story.",
                "genre": "webgame",
                "style": "plain",
                "current_chapter": 0,
                "world_facts": [],
                "characters": [
                    {
                        "name": "Night Ember",
                        "role": "protagonist",
                        "game_id": "Night Ember",
                        "goals": ["stay quiet"],
                        "memory": ["Entered the village."],
                        "current_emotion": "neutral",
                        "location": "village gate",
                        "game_panel": {"level": 1, "class_path": "apprentice", "currency": "0 gold"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _seed_generation_outline(root, 1)

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(
                update={
                    "current_chapter": 1,
                    "timeline": [
                        TimelineEvent(
                            chapter_number=1,
                            summary="Night Ember checks the counter.",
                            impact="Chapter 1 closes with a visible cost.",
                        )
                    ],
                    "chapter_summaries": [
                        ChapterSummary(
                            chapter_number=1,
                            chapter_title="Generated One",
                            summary="Night Ember checks the counter.",
                        )
                    ],
                }
            )
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Generated One",
                body=_long_test_body("Night Ember checked the quest counter and left quietly."),
                cadence="manual",
                next_outline="Check costs.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Generated One",
                    "cadence": "manual",
                    "summary": "Night Ember checks the counter.",
                    "facts": ["No sale happened."],
                    "next_focus": "Check costs.",
                    "primary_conflict": "Low resources.",
                    "secondary_conflict": "Limited information.",
                    "event_beat": "Counter check.",
                },
            )

    candidate = FileProjectStore(root).generate_next_chapter(engine=FakeEngine(), persist=False)

    assert candidate["schema_version"] == "file-project-candidate/v1"
    assert candidate["candidate"]["status"] == "pending"
    assert not (root / ".story-system" / "chapters" / "0001.json").exists()
    assert json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))["current_chapter"] == 0

    generated = FileProjectStore(root).generate_next_chapter(engine=FakeEngine())

    assert generated["schema_version"] == "file-project-generate-next/v1"
    assert generated["chapter_number"] == 1
    assert (root / ".story-system" / "chapters" / "0001.json").exists()
    assert (root / "chapters" / "0001-Generated One.md").read_text(encoding="utf-8").startswith("Night Ember")
    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state["current_chapter"] == 1
    assert any(item["chapter_number"] == 1 for item in state["chapter_summaries"])
    assert any(item["text"] == "No sale happened." for item in state["continuity_facts"])
    assert state["time_state"]["server_day"] == 1
    assert state["time_state"]["chapter_time_spans"][0]["chapter_number"] == 1
    project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert project["current_chapter"] == 1
    assert project["current_focus"] == "Check costs."
    assert "continuity_state" not in project["world_blueprint"]
    assert "time_state" not in project["world_blueprint"]
    assert state["world_snapshot"]["time_state"]["current_scene_time"] == "第1章章末"
    assert project["character_profiles"][0]["name"] == "Night Ember"
    assert project["character_profiles"][0]["game_panel"]["updated_chapter"] == 1
    packet = FileProjectStore(root).writing_packet(2)
    assert packet["state"]["world_snapshot"]["time_state"]["current_scene_time"] == "第1章章末"
    latest_commit = json.loads((root / ".story-system" / "commits" / "latest_commit.json").read_text(encoding="utf-8"))
    assert latest_commit["operation"] == "generate"


def test_file_project_store_does_not_persist_unaccepted_review_lessons(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(root)

    store.write_chapter(
        chapter_number=1,
        title="Lesson",
        body="Night Ember walked to the slope.",
        next_outline="Continue.",
        summary="Short weak scene.",
    )

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert state["writing_lessons"] == []
    assert project["world_blueprint"]["writing_learning"]["lessons"] == []


def test_file_project_writing_packet_requires_fast_visible_progression(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "genre": "webgame",
            "current_chapter": 4,
            "current_focus": "Turn the hidden route into a visible level gain.",
            "world_facts": [],
        },
    )

    packet = store.writing_packet(5)

    assert any("前10章节奏要快" in rule for rule in packet["style_rules"])
    assert any("连续两章不能只拿线索不给成长" in rule for rule in packet["style_rules"])
    assert packet["state"]["current_focus"] == "Turn the hidden route into a visible level gain."


def test_file_project_writing_packet_omits_legacy_direction_options_and_exposes_rolling_fill(tmp_path):
    """Round 8 Task 5: the three-card direction picker was replaced by the
    rolling outline. The packet no longer carries three pre-generated
    options; instead it surfaces the rolling fill status so the frontend
    can either show the filled outline or prompt the user to retry the
    fill.
    """
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "网游开服，夜烬低调验证千倍爆率。",
            "genre": "网游",
            "style": "番茄升级流",
            "current_chapter": 1,
            "world_facts": ["现实催租压力未解决。"],
            "progression_ledger": {
                "economy": {"game_currency": "0铜", "inventory": {"灰狼毒腺": 8}},
                "quests": {"清道夫委托": "未完成，还差2份毒腺"},
            },
        },
    )

    packet = store.writing_packet(2)

    # Legacy three-card picker is gone.
    assert packet["chapter_direction_options"].get("options") == []
    # Rolling fill status is exposed; no outline present → "missing".
    assert packet["rolling_fill"]["status"] == "missing"
    assert packet["rolling_fill"]["chapter_number"] == 2
    assert packet["next_chapter_outline"] is None
    assert packet["next_chapter_outline_source"] is None


def test_file_project_writing_packet_does_not_offer_branches_over_explicit_chapter_outline(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "genre": "网游",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    (store.webnovel_dir / "outline.json").write_text(
        json.dumps(
            {
                "overall": {"story": "夜烬低调验证混沌之种。"},
                "chapters": [
                    {
                        "chapter_number": 2,
                        "title": "还差八份毒腺",
                        "goal": "补齐八份毒腺并完成清道夫委托。",
                        "payoff": "升到Lv.3。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    packet = store.writing_packet(2)

    assert packet["outline_context"]["chapter"]["title"] == "还差八份毒腺"
    assert packet["chapter_direction_options"] == {}


def test_file_project_generate_next_ignores_legacy_chapter_direction_id(tmp_path):
    """Round 8 Task 5: the three-card direction picker was removed. The
    ``chapter_direction_id`` parameter is preserved on
    ``generate_next_chapter`` for backward compatibility (the API request
    model still has the field), but it is silently ignored: the rolling
    outline now drives the chapter structure.

    The test asserts that a passed-in ``chapter_direction_id`` does NOT
    raise (no ``unknown_chapter_direction`` error) and the generation
    proceeds normally via the rolling-outline path.
    """
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "网游开服，夜烬低调验证千倍爆率。",
            "genre": "网游",
            "style": "番茄升级流",
            "current_chapter": 1,
            "world_facts": ["现实催租压力未解决。"],
            "progression_ledger": {
                "economy": {"game_currency": "0铜", "inventory": {"灰狼毒腺": 8}},
                "quests": {"清道夫委托": "未完成，还差2份毒腺"},
            },
        },
    )
    _seed_generation_outline(root, 2)

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 2})
            return SimpleNamespace(
                chapter_number=2,
                chapter_title="混沌再闪",
                body=_long_test_body("Night Ember hid the strange fragment and counted the cost."),
                cadence="manual",
                next_outline="Check the recorded trace.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "混沌再闪",
                    "cadence": "manual",
                    "summary": "Night Ember sees a hidden trace.",
                    "facts": ["Selected chaos direction."],
                    "next_focus": "Check the recorded trace.",
                    "primary_conflict": "Hidden trace.",
                    "secondary_conflict": "No one else can know.",
                    "event_beat": "Trace appears.",
                },
                quality_report={"ok": True},
            )

    # A legacy chapter_direction_id used to resolve via the
    # chapter-direction options card. Now it is a no-op: the rolling
    # outline (or stub) drives the chapter. The call must succeed.
    generated = store.generate_next_chapter(engine=FakeEngine(), chapter_direction_id="chaos-seed-trace")
    assert generated["chapter_number"] == 2


def test_file_project_writing_packet_exposes_outline_constraints(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "Follow the arc.",
            "world_blueprint": {
                "current_arc": "Opening arc.",
                "opening_arc": {
                    "golden_three_chapters": {"1": {"payoff": "first sale"}},
                    "chapter_beats": [
                        {
                            "chapter": 2,
                            "title": "First Sale",
                            "required_payoff": "finish first sale",
                            "ending_hook": "buyer asks source",
                        }
                    ],
                },
                "volume_plan": {"volume_title": "Newbie Village"},
                "longform_framework": {"progression_ladder": ["Lv.1-5"]},
                "chapter_formula": ["goal-cost-payoff-hook"],
                "progression_rules": ["visible gain every chapter"],
                "forbidden_breaks": ["do not skip the outline"],
            },
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )

    packet = store.writing_packet(2)

    assert packet["target_chars"] == {"min": 4200, "max": 5500}
    assert packet["acceptance_chars"] == {"min": 3800, "max": 5700}
    assert packet["hard_locks"][0] == (
        "正文目标为4200至5500字；低于3800字或超过5700字不能通过章节检查，超过5500字应压缩。"
    )
    assert packet["chapter_number"] == 2
    assert any("4200至5500字" in lock for lock in packet["hard_locks"])
    assert any("当前主线焦点：Follow the arc." in lock for lock in packet["hard_locks"])
    assert packet["scene_cards"][0]["title"] == "First Sale"
    assert packet["scene_cards"][0]["purpose"] == "finish first sale"
    assert packet["scene_cards"][0]["ending_hook"] == "buyer asks source"
    assert isinstance(packet["character_cards"], list)
    outline_context = packet["outline_context"]
    assert set(outline_context) == {"overall", "active_arc", "chapter"}
    assert outline_context["active_arc"]["goal"] == "Opening arc."
    assert outline_context["chapter"]["chapter_number"] == 2
    assert outline_context["chapter"]["payoff"] == "finish first sale"
    assert outline_context["chapter"]["ending_hook"] == "buyer asks source"
    constraints = packet["outline_constraints"]
    assert "current_arc" not in constraints
    assert "opening_arc" not in constraints
    assert constraints["volume_plan"]["volume_title"] == "Newbie Village"
    assert constraints["longform_framework"]["progression_ladder"] == ["Lv.1-5"]
    assert constraints["chapter_formula"] == ["goal-cost-payoff-hook"]
    assert set(constraints) == {
        "volume_plan",
        "longform_framework",
        "chapter_formula",
        "forbidden_breaks",
    }
    assert "progression_rules" not in constraints
    assert "reality_bridge_rules" not in constraints
    assert constraints["forbidden_breaks"] == ["do not skip the outline"]
    assert "visible gain every chapter" in packet["hard_locks"]
    assert isinstance(packet["state"]["characters"], list)


def test_file_project_writing_packet_uses_active_arc_as_later_volume_plan(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "Long Novel",
            "active_story_id": "s-file",
            "world_blueprint": {
                "current_arc": "Opening arc.",
                "volume_plan": {
                    "volume_title": "Opening Volume",
                    "target_chapters": 50,
                    "long_threads": ["follow the central mystery"],
                },
            },
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    store.update_project_outline(
        {
            "overall": {
                "story": "A long story.",
                "core_ending_chapter": 100,
                "extension_ceiling_chapter": 100,
            },
            "arcs": [
                {
                    "id": "vol-1",
                    "title": "Opening Volume",
                    "start_chapter": 1,
                    "end_chapter": 50,
                    "goal": "Finish the opening.",
                },
                {
                    "id": "vol-2",
                    "title": "Reality Volume",
                    "start_chapter": 51,
                    "end_chapter": 100,
                    "goal": "Connect both worlds.",
                    "payoff": "Prove the connection.",
                },
            ],
        }
    )

    packet = store.writing_packet(60)

    assert packet["outline_context"]["active_arc"]["title"] == "Reality Volume"
    assert packet["outline_constraints"]["volume_plan"] == {
        "volume_title": "Reality Volume",
        "target_chapters": 50,
        "core_goal": "Connect both worlds.",
        "phase_beats": [
            {"range": "51-100", "goal": "Prove the connection."}
        ],
        "long_threads": ["follow the central mystery"],
    }


def test_compact_prompt_preview_keeps_only_chapter_execution_contract(tmp_path):
    store = FileProjectStore(tmp_path / "novel")

    preview = store._compact_prompt_preview_packet(
        {
            "target_chars": {"min": 4200, "max": 5500},
            "acceptance_chars": {"min": 3800, "max": 5700},
            "hard_locks": ["Keep the chapter within its acceptance range."],
            "scene_cards": [{"title": "First repair", "purpose": "Fix the gate."}],
            "outline_context": {
                "overall": "A long story summary that already exists in core context.",
                "chapter": {"goal": "Fix the gate", "payoff": "Earn trust", "ending_hook": "A new crack appears"},
            },
            "title_contract": {"style": "concrete_short_title"},
            "style_rules": ["Use concrete action."],
            "outline_constraints": {
                "volume_plan": {"title": "第一卷"},
                "longform_framework": {"chapters": 300},
                "chapter_formula": ["目标-代价-收益-钩子"],
                "progression_rules": ["每章可见成长"],
                "forbidden_breaks": ["不得跳过大纲"],
                "reality_bridge_rules": ["现实到账需结算"],
            },
            "state": {
                "world_facts": ["Repeated world fact"],
                "characters": [
                    {
                        "name": "Lin Xiu",
                        "role": "protagonist",
                        "location": "Repair shop",
                        "goal": "Fix the gate",
                        "state_context": {"cultivation": "Foundation"},
                    }
                ],
            },
            "recent_chapters": [{"chapter_number": 144, "summary": "Repeated recent chapter"}],
            "latest_event_plan": {"turn": "The repair fails once", "chapter_end_hook": "A new crack appears"},
            "latest_review": {"issues": ["Repeated review issue"]},
            "power_system": {"levels": ["Foundation"]},
            "skill_context": {
                "dialogue": [
                    {
                        "skill_id": "dialogue-pack",
                        "modules": [{"module_id": "dialogue", "title": "对话规则"}],
                    }
                ],
                "style": [
                    {
                        "skill_id": "dialogue-pack",
                        "modules": [{"module_id": "dialogue", "title": "对话规则"}],
                    }
                ],
            },
        }
    )

    assert preview["target_chars"] == {"min": 4200, "max": 5500}
    assert preview["acceptance_chars"] == {"min": 3800, "max": 5700}
    assert preview["chapter_outline"] == {
        "goal": "Fix the gate",
        "payoff": "Earn trust",
        "ending_hook": "A new crack appears",
    }
    assert preview["characters"] == [
        {"name": "Lin Xiu", "role": "protagonist", "location": "Repair shop", "goal": "Fix the gate"}
    ]
    assert preview["loaded_skill_modules"] == [
        {
            "skill_id": "dialogue-pack",
            "module_id": "dialogue",
            "title": "对话规则",
            "purposes": ["dialogue", "style"],
        }
    ]
    for duplicate_key in (
        "outline_context",
        "outline_constraints",
        "state",
        "recent_chapters",
        "event_plan",
        "latest_event_plan",
        "latest_review",
        "power_system",
    ):
        assert duplicate_key not in preview


def test_writing_packet_keeps_only_global_progression_governance_in_hard_locks(tmp_path):
    governance_rule = "前十章每章至少完成一次可见成长。"
    descriptive_rule = "成长节奏随剧情自然推进。"
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=3,
        chapter_update={
            "title": "村口闲谈",
            "goal": "拜访灰烬村村长",
            "action": "询问后坡天气",
            "payoff": "确认明日路线",
        },
    )
    project = store.project()
    project["world_blueprint"]["progression_rules"] = [
        governance_rule,
        descriptive_rule,
    ]
    store._write_json(store.webnovel_dir / "project.json", project)

    packet = store.writing_packet(3)

    assert governance_rule in packet["hard_locks"]
    assert descriptive_rule not in packet["hard_locks"]
    assert "progression_rules" not in packet["project"]["world_blueprint"]


def test_writing_packet_recognizes_chinese_and_english_progression_governance(tmp_path):
    chinese_rule = "经验只来自可验证行动"
    english_rule = "Visible gain every chapter"
    descriptive_rule = "Lv.10完成转职"
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=3,
        chapter_update={
            "title": "Village conversation",
            "goal": "Ask about tomorrow's route",
            "action": "Record the weather",
            "payoff": "Confirm the departure time",
        },
    )
    project = store.project()
    project["world_blueprint"]["progression_rules"] = [
        chinese_rule,
        english_rule,
        descriptive_rule,
    ]
    store._write_json(store.webnovel_dir / "project.json", project)

    packet = store.writing_packet(3)

    assert chinese_rule in packet["hard_locks"]
    assert english_rule in packet["hard_locks"]
    assert descriptive_rule not in packet["hard_locks"]


def test_writing_packet_does_not_duplicate_scoped_progression_governance_rule(tmp_path):
    governance_rule = "升级必须留下可验证记录。"
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=3,
        chapter_update={
            "title": "第一次升级",
            "goal": "积累经验并升级",
            "action": "核对成长记录",
            "payoff": "等级提升",
        },
    )
    project = store.project()
    project["world_blueprint"]["progression_rules"] = [governance_rule]
    store._write_json(store.webnovel_dir / "project.json", project)

    packet = store.writing_packet(3)

    assert governance_rule in packet["project"]["world_blueprint"]["progression_rules"]
    assert governance_rule not in packet["hard_locks"]


def test_writing_packet_includes_only_relevant_monster_profiles_at_top_level(tmp_path):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={
            "title": "灰狼坡",
            "goal": "追踪灰狼",
            "action": "观察灰狼的扑咬路线",
            "payoff": "找到灰狼巢穴",
        },
    )
    project = store.project()
    project["world_blueprint"]["monster_profiles"] = [
        {"name": "灰狼", "stats": {"hp": 90}},
        {"name": "史莱姆", "stats": {"hp": 30}},
    ]
    store._write_json(store.webnovel_dir / "project.json", project)

    packet = store.writing_packet(1)

    assert packet["monster_profiles"] == [{"name": "灰狼", "stats": {"hp": 90}}]
    assert "monster_profiles" not in packet["project"]["world_blueprint"]


def test_writing_packet_limits_and_deep_copies_relevant_monster_profiles(tmp_path, monkeypatch):
    names = [f"怪物{i}" for i in range(1, 8)]
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={
            "title": "怪物巡查",
            "goal": "依次观察" + "、".join(names),
            "action": "记录全部目标的行动",
            "payoff": "完成图鉴核对",
        },
    )
    project = store.project()
    profiles = [
        {"name": name, "stats": {"hp": index}}
        for index, name in enumerate(names, start=1)
    ]
    profiles.append({"name": "史莱姆", "stats": {"hp": 99}})
    project["world_blueprint"]["monster_profiles"] = profiles
    monkeypatch.setattr(store, "project", lambda: project)

    packet = store.writing_packet(1)

    assert [item["name"] for item in packet["monster_profiles"]] == names[:6]
    packet["monster_profiles"][0]["stats"]["hp"] = 999
    assert profiles[0]["stats"]["hp"] == 1


def test_rewriting_old_chapter_removes_future_focus_from_entire_writing_packet(tmp_path):
    future_focus = "下一章去白河仓库交易材料并支付现实房租"
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={
            "title": "灰狼坡",
            "goal": "击败灰狼",
            "action": "使用法杖清理怪群",
            "payoff": "获得游戏经验",
        },
        current_chapter=3,
        current_focus=future_focus,
    )

    packet = store.writing_packet(1)

    assert future_focus not in json.dumps(packet, ensure_ascii=False)
    assert "current_focus" not in packet["project"]
    assert packet["state"].get("current_focus") in (None, "")
    assert packet["chapter_direction_options"] == {}


def test_rewriting_first_chapter_reconstructs_start_state_in_writing_packet(tmp_path):
    future_marker = "FUTURE_CHAPTER_RESULT_SHOULD_NOT_REACH_CHAPTER_ONE"
    store = _make_minimal_file_project(
        tmp_path / "historical-first-chapter-packet",
        project={
            "project_id": "p-history",
            "title": "Historical Rewrite",
            "active_story_id": "s-history",
            "character_profiles": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "game_id": "夜烬",
                    "performance_profile": {"speech_style": "会把原因和决定说完整。"},
                }
            ],
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
        state={
            "story_id": "s-history",
            "genre": "网游",
            "current_chapter": 4,
            "world_facts": [future_marker],
            "progression_ledger": {"protagonist": {"level": "Lv.9"}},
            "characters": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "game_id": "夜烬",
                    "current_life_profile": {"immediate_problem": future_marker},
                    "story_drive": {"immediate_goal": future_marker},
                    "game_state": {"current": {"level": "Lv.9", "future": future_marker}},
                    "memory": [future_marker],
                }
            ],
        },
    )

    packet = store.writing_packet(1)
    rendered = json.dumps(packet, ensure_ascii=False)

    assert packet["state"]["current_chapter"] == 0
    assert future_marker not in rendered
    assert packet["character_cards"][0]["name"] == "苏叶"
    assert "会把原因和决定说完整" in rendered


def test_first_chapter_direction_payload_does_not_restore_future_project_profile(tmp_path):
    future_marker = "PROFILE_UPDATED_AFTER_CHAPTER_FOUR"
    store = _make_minimal_file_project(
        tmp_path / "historical-direction-profile",
        project={
            "project_id": "p-history-direction",
            "title": "Historical Direction",
            "active_story_id": "s-history-direction",
            "character_profiles": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "latest_chapter": 4,
                    "identity_profile": {"age": 24, "current_identity": future_marker},
                    "current_life_profile": {"immediate_problem": future_marker},
                    "story_drive": {
                        "long_term_goal": "查清异常来源",
                        "immediate_goal": future_marker,
                    },
                    "performance_profile": {"speech_style": "说话完整。"},
                }
            ],
        },
        state={
            "story_id": "s-history-direction",
            "genre": "网游",
            "current_chapter": 4,
            "characters": [{"name": "苏叶", "role": "protagonist"}],
        },
    )
    base_state = store._conservative_regeneration_state(store.state())

    payload = store._story_state_payload_for_direction(base_state, store.project(), 1)
    rendered = json.dumps(payload, ensure_ascii=False)

    assert future_marker not in rendered
    assert "查清异常来源" in rendered
    assert "说话完整" in rendered


def test_rewriting_later_chapter_uses_previous_snapshot_not_current_state(tmp_path):
    prior_marker = "CHAPTER_ONE_CONFIRMED_STATE"
    future_marker = "CHAPTER_FIVE_CURRENT_STATE"
    store = _make_minimal_file_project(
        tmp_path / "historical-later-chapter-packet",
        project={
            "project_id": "p-history-2",
            "title": "Historical Rewrite",
            "active_story_id": "s-history-2",
            "character_profiles": [{"name": "林修", "role": "protagonist"}],
        },
        state={
            "story_id": "s-history-2",
            "genre": "玄幻",
            "current_chapter": 5,
            "world_facts": [future_marker],
            "characters": [
                {"name": "林修", "role": "protagonist", "memory": [future_marker]}
            ],
        },
    )
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "第一章",
            "chapter_summary": {"summary": prior_marker},
            "updated_story": {
                "story_id": "s-history-2",
                "genre": "玄幻",
                "current_chapter": 1,
                "world_facts": [prior_marker],
                "characters": [
                    {"name": "林修", "role": "protagonist", "memory": [prior_marker]}
                ],
            },
        },
    )

    packet = store.writing_packet(2)
    rendered = json.dumps(packet, ensure_ascii=False)

    assert packet["state"]["current_chapter"] == 1
    assert prior_marker in rendered
    assert future_marker not in rendered


def test_rewriting_chapter_uses_only_chapters_before_target_for_writer_context(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={"story_id": "s-file", "current_chapter": 3, "world_facts": []},
    )
    chapter_markers = {}
    review_markers = {}
    for number in range(1, 4):
        next_focus = f"CHAPTER_{number}_NEXT_FOCUS_UNIQUE"
        event_focus = f"CHAPTER_{number}_EVENT_FOCUS_UNIQUE"
        review_marker = f"CHAPTER_{number}_REVIEW_UNIQUE"
        chapter_markers[number] = (next_focus, event_focus)
        review_markers[number] = review_marker
        store._write_json(
            store.story_system_dir / "chapters" / f"{number:04d}.json",
            {
                "chapter_number": number,
                "chapter_title": f"Chapter {number}",
                "body": f"Completed chapter {number}.",
                "chapter_summary": {"summary": f"Summary {number}"},
                "next_focus": next_focus,
                "next_outline": next_focus,
                "event_plan": {"next_focus": event_focus},
            },
        )
        store._write_json(
            store.story_system_dir / "reviews" / f"{number:04d}.json",
            {"ok": True, "issues": [review_marker]},
        )

    first_packet = store.writing_packet(1)
    first_json = json.dumps(first_packet, ensure_ascii=False)

    assert first_packet["latest_chapter_number"] == 0
    assert first_packet["recent_chapters"] == []
    assert first_packet["latest_event_plan"] == {}
    assert first_packet["latest_review"] == {}
    for number in range(1, 4):
        assert chapter_markers[number][0] not in first_json
        assert chapter_markers[number][1] not in first_json
        assert review_markers[number] not in first_json

    second_packet = store.writing_packet(2)
    second_json = json.dumps(second_packet, ensure_ascii=False)

    assert second_packet["latest_chapter_number"] == 1
    assert [item["chapter_number"] for item in second_packet["recent_chapters"]] == [1]
    assert second_packet["latest_event_plan"]["next_focus"] == chapter_markers[1][1]
    assert second_packet["latest_review"]["issues"] == [review_markers[1]]
    assert chapter_markers[1][0] in second_json
    assert chapter_markers[1][1] in second_json
    assert review_markers[1] in second_json
    for number in (2, 3):
        assert chapter_markers[number][0] not in second_json
        assert chapter_markers[number][1] not in second_json
        assert review_markers[number] not in second_json


def test_trade_chapter_writing_packet_only_includes_relevant_world_modules(tmp_path):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=1,
        chapter_update={
            "title": "第一笔交易",
            "goal": "匿名寄售材料并等待现实到账",
            "action": "在交易行出售材料后提现支付房租账单",
            "payoff": "完成第一笔现实结算",
        },
    )

    packet = store.writing_packet(1)
    blueprint = packet["project"]["world_blueprint"]

    assert blueprint["economy_rules"]
    assert blueprint["reality_bridge_rules"]
    assert "quest_rules" not in blueprint
    assert "quest_network" not in blueprint
    assert "progression_rules" not in blueprint
    assert "server_runtime" not in blueprint
    assert "monster_profiles" not in blueprint
    assert len(flatten_selected_rules(blueprint)) <= 8


def test_quest_chapter_writing_packet_includes_only_matching_chain(tmp_path):
    store = _store_with_shenyu_world(
        tmp_path,
        chapter_number=2,
        chapter_update={
            "title": "后坡巡查",
            "goal": "提交清道夫委托，开启后坡巡查",
            "action": "向灰烬村守卫队登记巡查路线",
            "payoff": "取得后坡调查权限",
        },
    )

    packet = store.writing_packet(2)
    blueprint = packet["project"]["world_blueprint"]
    chains = blueprint["quest_network"]["active_chains"]

    assert [chain["name"] for chain in chains] == ["灰烬村异常链"]
    assert blueprint["quest_rules"]
    assert "server_runtime" not in blueprint
    assert len(flatten_selected_rules(blueprint)) <= 8


def test_writing_packet_includes_reality_bridge_rules_for_relevant_chapter_only(tmp_path):
    root = tmp_path / "novel"
    reality_rules = [f"现实规则{i}" for i in range(1, 9)]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "完成本章计划。",
            "world_blueprint": {
                "reality_bridge_rules": reality_rules,
                "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
            },
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0]["goal"] = "确认第一笔收入到账并支付房租"
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert "reality_bridge_rules" not in packet["outline_constraints"]
    scoped_world = packet["project"]["world_blueprint"]
    assert scoped_world["reality_bridge_rules"] == reality_rules
    assert len(flatten_selected_rules(scoped_world)) <= 8
    assert not any(rule in packet["hard_locks"] for rule in reality_rules)


def test_writing_packet_omits_reality_bridge_rules_for_game_only_chapter(tmp_path):
    root = tmp_path / "novel"
    reality_rules = ["游戏收益只能通过合规渠道进入现实", "现实资金变化必须留下可核对记录"]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "清理矿洞深处的怪物。",
            "world_blueprint": {
                "reality_bridge_rules": reality_rules,
                "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
            },
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0].update(
        {
            "goal": "击败矿洞狼王",
            "action": "组队进入洞穴并清理怪群",
            "payoff": "获得新装备和经验",
            "ending_hook": "更深处传来咆哮",
        }
    )
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert "reality_bridge_rules" not in packet["outline_constraints"]
    assert "reality_bridge_rules" not in packet["project"]["world_blueprint"]
    assert not any(rule in packet["hard_locks"] for rule in reality_rules)


@pytest.mark.parametrize("game_only_focus", ["金币收入到账", "任务奖励到账"])
def test_writing_packet_does_not_treat_game_income_as_reality_bridge(game_only_focus, tmp_path):
    root = tmp_path / "novel"
    reality_rules = ["现实资金变化必须留下可核对记录"]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": game_only_focus,
            "world_blueprint": {"reality_bridge_rules": reality_rules},
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0].update(
        {
            "goal": game_only_focus,
            "action": "领取奖励并整理背包",
            "payoff": "获得游戏金币",
        }
    )
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert "reality_bridge_rules" not in packet["outline_constraints"]
    assert "reality_bridge_rules" not in packet["project"]["world_blueprint"]


def test_writing_packet_ignores_next_focus_when_rewriting_game_only_chapter(tmp_path):
    root = tmp_path / "novel"
    reality_rules = ["现实资金变化必须留下可核对记录"]
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "筹钱支付房租账单",
            "world_blueprint": {"reality_bridge_rules": reality_rules},
        },
        state={"story_id": "s-file", "current_chapter": 3, "world_facts": []},
    )
    outline = _generated_opening_plan().outline.model_dump(mode="json")
    outline["chapters"][0].update(
        {
            "goal": "击败矿洞狼王",
            "action": "进入洞穴清理怪群",
            "payoff": "获得新装备和经验",
            "ending_hook": "更深处传来咆哮",
        }
    )
    (store.webnovel_dir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    packet = store.writing_packet(1)

    assert "reality_bridge_rules" not in packet["outline_constraints"]
    assert "reality_bridge_rules" not in packet["project"]["world_blueprint"]


def test_state_restores_protagonist_character_card_from_ledger(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
        state={
            "story_id": "s-file",
            "current_chapter": 4,
            "world_facts": [],
            "characters": [
                {
                    "name": "药剂师洛婶",
                    "role": "服务NPC",
                    "goals": ["收任务材料"],
                    "memory": ["药剂铺NPC。"],
                }
            ],
            "progression_ledger": {
                "protagonist": {
                    "real_name": "苏叶",
                    "game_id": "夜烬",
                    "class_path": "见习冒险者（未转职）",
                    "level": "Lv.3",
                    "exp": "196/300",
                    "hp": "91/140",
                    "mp": "22/80",
                    "skills": ["基础火球术", "火线牵引"],
                },
                "economy": {"game_currency": "空", "inventory": {"灰狼毒腺": 11}},
                "equipment": {"weapon": "新手法杖", "durability": "10/12"},
            },
        },
    )

    characters = store.state()["characters"]
    protagonist = next(character for character in characters if character["name"] == "苏叶")

    assert protagonist["role"] == "protagonist"
    assert protagonist["game_id"] == "夜烬"
    assert protagonist["game_panel"]["level"] == "Lv.3"
    assert protagonist["game_panel"]["inventory"]["灰狼毒腺"] == 11


def test_empty_project_does_not_fabricate_legacy_protagonist(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-empty",
            "title": "迟到的响应",
            "world_blueprint": {"genre_plugin_ids": ["urban"]},
            "character_profiles": [],
        },
        state={
            "story_id": "file:p-empty",
            "current_chapter": 0,
            "characters": [],
            "world_facts": [],
            "progression_ledger": {},
        },
    )

    assert store.state()["characters"] == []


def test_non_game_project_does_not_apply_game_protagonist_template(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-urban",
            "title": "迟到的响应",
            "world_blueprint": {"genre_plugin_ids": ["urban"]},
            "character_profiles": [],
        },
        state={
            "story_id": "file:p-urban",
            "current_chapter": 1,
            "characters": [],
            "world_facts": [],
            "progression_ledger": {"protagonist": {"real_name": "陈默", "level": "第二阶段"}},
        },
    )

    assert store.state()["characters"] == []


def test_opening_brief_recovers_for_legacy_blank_project(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-empty",
            "title": "迟到的响应",
            "pipeline_stage": "draft",
            "world_blueprint": {"genre_plugin_ids": ["urban"]},
        },
        state={
            "story_id": "file:p-empty",
            "current_chapter": 0,
            "genre_plugin_ids": ["urban"],
            "characters": [],
            "world_facts": [],
        },
    )

    assert store.opening_setup() == {
        "brief": {
            "schema_version": "opening-brief/v1",
            "mode": "blank",
            "novel_type_id": "urban",
            "idea": "请根据书名《迟到的响应》和所选小说类型构思故事。",
            "working_title": "迟到的响应",
        },
        "directions": [],
        "selected_id": "",
        "pipeline_stage": "draft",
        "next_path": "/projects/file%3Ap-empty/setup",
    }


def test_state_does_not_append_legacy_defaults_to_saved_protagonist(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "genre_plugin_ids": ["game_webnovel"],
            "world_facts": [],
            "characters": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "game_id": "夜烬",
                    "goals": ["在《神域》中完成清道夫委托。"],
                    "memory": ["现实余额332.60元。"],
                    "game_panel": {
                        "game_id": "夜烬",
                        "level": "Lv.2",
                        "class_path": "见习者（未转职）",
                        "currency": "39铜币",
                    },
                }
            ],
            "progression_ledger": {
                "protagonist": {
                    "real_name": "苏叶",
                    "game_id": "夜烬",
                    "level": "Lv.2",
                    "class_path": "见习者（未转职）",
                },
                "economy": {"game_currency": "39铜币"},
            },
        },
    )

    protagonist = next(card for card in store.state()["characters"] if card["name"] == "苏叶")

    assert protagonist["goals"] == ["在《神域》中完成清道夫委托。"]
    assert protagonist["memory"] == ["现实余额332.60元。"]
    assert protagonist["game_panel"]["class_path"] == "见习者（未转职）"
    assert protagonist["game_panel"]["currency"] == "39铜币"


def test_state_overlays_ledger_status_on_saved_protagonist_profile(tmp_path):
    store = _make_minimal_file_project(
        tmp_path / "novel",
        state={
            "story_id": "s-file",
            "current_chapter": 2,
            "genre_plugin_ids": ["game_webnovel"],
            "world_facts": [],
            "characters": [
                {
                    "name": "苏叶",
                    "role": "主角",
                    "goals": ["隐藏混沌之种"],
                    "game_panel": {"level": "Lv.1", "currency": "0铜币"},
                    "real_state": {"current": {"balance": "27.60元"}},
                }
            ],
            "progression_ledger": {
                "protagonist": {
                    "real_name": "苏叶",
                    "game_id": "夜烬",
                    "level": "Lv.2",
                    "class_path": "见习者（未转职）",
                    "exp": "75/200",
                },
                "economy": {"game_currency": "39铜币", "inventory": {"灰狼毒腺": 2}},
                "real": {"end_balance": "332.60元"},
            },
        },
    )

    protagonist = next(card for card in store.state()["characters"] if card["name"] == "苏叶")

    assert protagonist["goals"] == ["隐藏混沌之种"]
    assert protagonist["game_panel"]["level"] == "Lv.2"
    assert protagonist["game_panel"]["exp"] == "75/200"
    assert protagonist["game_panel"]["currency"] == "39铜币"
    assert protagonist["game_panel"]["inventory"] == {"灰狼毒腺": 2}
    assert protagonist["real_state"]["current"]["balance"] == "332.60元"


def test_completed_quest_is_not_reintroduced_as_active(tmp_path):
    store = FileProjectStore(tmp_path)
    state = {
        "story_id": "s-file",
        "current_chapter": 1,
        "genre_plugin_ids": ["game_webnovel"],
        "progression_ledger": {
            "quests": {
                "active": "灰狼材料收集：2/10",
                "available": "清道夫委托：提交灰狼毒腺×10；当前2/10",
            }
        },
    }
    chapter = {
        "chapter_number": 1,
        "body": "任务：灰狼材料收集。系统提示：完成任务：灰狼材料收集，获得经验100点。",
    }

    synced = store._sync_ledger_from_chapter_body(state, chapter)

    quests = synced["progression_ledger"]["quests"]
    assert "active" not in quests
    assert quests["灰狼材料收集"] == "已完成"


def test_negated_quest_completion_does_not_mark_quest_completed(tmp_path):
    store = FileProjectStore(tmp_path)
    state = {
        "story_id": "s-file",
        "current_chapter": 1,
        "genre_plugin_ids": ["game_webnovel"],
        "progression_ledger": {"quests": {}},
    }
    chapter = {
        "chapter_number": 1,
        "body": "任务：灰狼材料收集。他还没有完成任务：灰狼材料收集。",
    }

    synced = store._sync_ledger_from_chapter_body(state, chapter)

    quests = synced["progression_ledger"]["quests"]
    assert quests["active"] == "灰狼材料收集"
    assert "灰狼材料收集" not in quests


def test_state_does_not_add_market_buyer_as_character_before_outline_appearance(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "File Novel",
            "active_story_id": "s-file",
            "current_focus": "第5章按大纲写担保名单：确认白河仓库收购规则和交易风险，收购方开始追问材料来源。",
                "world_blueprint": {
                    "genre_plugin_ids": ["game_webnovel"],
                    "opening_arc": {
                    "chapter_beats": [
                        {
                            "chapter": 5,
                            "title": "担保名单",
                            "required_payoff": "确认白河仓库收购规则和交易风险",
                            "ending_hook": "收购方开始追问材料来源",
                        }
                    ]
                }
            },
        },
        state={
            "story_id": "s-file",
            "genre_plugin_ids": ["game_webnovel"],
            "current_chapter": 4,
            "world_facts": [],
        },
    )

    characters = store.state()["characters"]
    assert "白河仓库收购方" not in {character["name"] for character in characters}


def test_xianxia_state_does_not_infer_web_game_service_characters(tmp_path) -> None:
    root = tmp_path / "xianxia-novel"
    store = _make_minimal_file_project(
        root,
        project={
            "current_focus": "第2章确认商会收购规则。",
            "world_blueprint": {"genre_plugin_ids": ["xianxia"]},
        },
        state={
            "story_id": "s-xianxia",
            "genre": "修仙仙侠",
            "genre_plugin_ids": ["xianxia"],
            "current_chapter": 1,
            "characters": [{"name": "林修", "role": "protagonist"}],
        },
    )
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "商会问价",
            "body": "林修在商会询问法器收购，对方提到旧论坛传闻。",
        },
    )

    names = {card["name"] for card in store.state()["characters"]}

    assert names == {"林修"}

    raw_state = dict(store._read_json(store.webnovel_dir / "state.json", {}) or {})
    raw_state["time_state"] = {"server_phase": "开服第1天"}
    synced = store._sync_state_after_chapter(
        raw_state,
        {
            "chapter_number": 1,
            "chapter_title": "商会问价",
            "body": "林修在商会询问法器收购，对方提到旧论坛传闻。",
        },
    )

    assert "time_state" not in synced
    assert "白河仓库收购方" not in json.dumps(synced, ensure_ascii=False)


def test_chapter_entity_does_not_turn_market_buyer_into_character(tmp_path):
    store = FileProjectStore(tmp_path / "novel")

    mention_only = store._chapter_entity_cards(
        {
            "chapter_number": 1,
            "chapter_title": "灰狼坡到账",
            "body": "帖子里的收购人ID叫白河仓库，认证是材料商。",
        }
    )
    assert "白河仓库收购方" not in {card["name"] for card in mention_only}


def test_state_sanitizes_placeholder_facts_from_writing_context(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "current_chapter": 2,
            "world_facts": ["manual draft", "第2章事实：夜烬仍为Lv.1见习冒险者（未转职）", "fresh fact"],
            "chapter_summaries": [
                {
                    "chapter_number": 2,
                    "chapter_title": "Chapter Two",
                    "facts": ["manual draft", "fresh chapter fact"],
                    "primary_conflict": "manual draft",
                    "secondary_conflict": {"note": "manual draft", "source": "secondary_conflict"},
                    "event_beat": {"turn": "real beat"},
                }
            ],
            "memory_index": [
                {"chapter_number": 2, "chapter_title": "Chapter Two", "facts": ["夜烬仍为Lv.1见习冒险者", "clean memory"]}
            ],
        },
    )

    state = store.state()

    assert state["world_facts"] == ["fresh fact"]
    assert state["chapter_summaries"][0]["facts"] == ["fresh chapter fact"]
    assert state["chapter_summaries"][0]["primary_conflict"] == {}
    assert state["chapter_summaries"][0]["secondary_conflict"] == {}
    assert state["chapter_summaries"][0]["event_beat"] == {"turn": "real beat"}
    assert state["memory_index"][0]["facts"] == ["clean memory"]


def test_non_game_chapter_hides_legacy_game_pulse_and_self_conflict(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-xuanhuan",
            "genre": "xuanhuan",
            "current_chapter": 1,
            "characters": [{"name": "Lin", "role": "protagonist"}],
        },
    )
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "Old clue",
            "body": "Lin finds an old key.",
            "simulation_plan": {
                "world_context": {
                    "schema_version": "world-context/v1",
                    "latest_pulse": {
                        "schema_version": "world-pulse/v1",
                        "market_order_book": {"price_copper": 2},
                    },
                }
            },
            "chapter_summary": {
                "chapter_number": 1,
                "summary": "Lin finds an old key.",
                "primary_conflict": {
                    "lead": "Lin",
                    "opposition": "Lin",
                    "collision": "Lin collides with Lin.",
                },
                "event_beat": {
                    "turn": "pressure spike",
                    "pivot": "Lin collides with Lin. Another person applies pressure.",
                },
            },
        },
    )

    chapter = store.chapter(1)

    assert "world_context" not in chapter["simulation_plan"]
    assert chapter["chapter_summary"]["primary_conflict"] == {}
    assert chapter["chapter_summary"]["event_beat"]["pivot"] == "Another person applies pressure."


def test_rewrite_latest_chapter_rebuilds_state_from_previous_snapshot_and_keeps_summary(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )
    for number in range(1, 5):
        store.write_chapter(
            chapter_number=number,
            title=f"Chapter {number}",
            body=f"Night Ember chapter {number}.",
            summary=f"Accepted summary {number}.",
        )
    chapter3_path = root / ".story-system" / "chapters" / "0003.json"
    chapter3 = json.loads(chapter3_path.read_text(encoding="utf-8"))
    chapter3["updated_story"] = {
        "story_id": "s-file",
        "outline": "A grounded game story.",
        "genre": "webgame",
        "style": "plain",
        "current_chapter": 3,
        "progression_ledger": {"protagonist": {"level": "Lv.1"}},
    }
    chapter3_path.write_text(json.dumps(chapter3, ensure_ascii=False), encoding="utf-8")
    state_path = root / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["current_chapter"] = 4
    state["progression_ledger"] = {"protagonist": {"level": "Lv.2"}}
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    store.rewrite_chapter(
        chapter_number=4,
        title="Chapter 4",
        body="Night Ember keeps the hidden route and returns to repair.",
        instructions=["hidden route remains"],
    )

    state_after = json.loads(state_path.read_text(encoding="utf-8"))
    chapter4 = json.loads((root / ".story-system" / "chapters" / "0004.json").read_text(encoding="utf-8"))
    assert state_after["progression_ledger"]["protagonist"]["level"] == "Lv.1"
    assert chapter4["chapter_summary"]["summary"] == "Accepted summary 4."
    assert chapter4["chapter_summary"]["summary"] != "Manual rewrite chapter 4."


def test_persist_bundle_ignores_stale_bundle_updated_story(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": ["source:canonical"]},
    )

    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Fresh Chapter",
        body=_long_test_body("Night Ember keeps the current ledger clean."),
        cadence="manual",
        next_outline="Continue from fresh facts.",
        updated_story={
            "story_id": "s-file",
            "current_chapter": 99,
            "world_facts": ["stale fact should not return"],
        },
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "chapter_title": "Fresh Chapter",
            "cadence": "manual",
            "summary": "Fresh summary wins.",
            "facts": ["fresh fact from summary"],
            "next_focus": "Continue from fresh facts.",
            "primary_conflict": "Clean state.",
            "secondary_conflict": "Old snapshot.",
            "event_beat": "Persist.",
        },
    )

    store.persist_bundle(bundle)

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    facts = "\n".join(item["text"] for item in state["continuity_facts"])
    assert "fresh fact from summary" in facts
    assert "Fresh summary wins." not in facts
    assert "stale fact should not return" not in facts
    assert state["current_chapter"] == 1


def test_persist_bundle_uses_runtime_updated_story(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "progression_ledger": {"economy": {"game_currency": "0铜"}},
            "world_facts": ["source:canonical"],
        },
    )

    bundle = SimpleNamespace(
        chapter_number=2,
        chapter_title="Ledger Chapter",
        body=_long_test_body("Night Ember turns the completed quest into a clean ledger."),
        cadence="manual",
        next_outline="Continue from the updated ledger.",
        updated_story={
            "story_id": "s-file",
            "outline": "Canonical outline.",
            "genre": "game_webnovel",
            "style": "plain",
            "current_chapter": 2,
            "progression_ledger": {"economy": {"game_currency": "5铜"}},
            "world_facts": ["source:canonical"],
            "timeline": [
                {"chapter_number": 2, "summary": "Ledger settles.", "impact": "Currency updates."}
            ],
            "chapter_summaries": [
                {"chapter_number": 2, "chapter_title": "Ledger Chapter", "summary": "ledger settles"}
            ],
        },
        chapter_summary={
            "chapter_title": "Ledger Chapter",
            "cadence": "manual",
            "summary": "The quest reward and costs settle into the ledger.",
            "facts": ["ledger fact"],
            "next_focus": "Continue from the updated ledger.",
            "primary_conflict": "Clean state.",
            "secondary_conflict": "Old snapshot.",
            "event_beat": "Persist.",
        },
    )

    store.persist_bundle(bundle)

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state["progression_ledger"]["economy"]["game_currency"] == "5铜"
    assert state["current_chapter"] == 2


def test_persist_old_chapter_rewrite_does_not_roll_back_global_state(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "current_chapter": 5,
            "progression_ledger": {"protagonist": {"level": "Lv.5", "canonical": True}},
            "world_facts": ["chapter five is canonical"],
        },
    )
    bundle = SimpleNamespace(
        chapter_number=2,
        chapter_title="Rewritten Two",
        body=_long_test_body("The rewritten second chapter remains local to its slot."),
        cadence="manual",
        next_outline="Continue without rolling back.",
        updated_story={
            "story_id": "s-file",
            "current_chapter": 2,
            "progression_ledger": {"protagonist": {"level": "Lv.2", "stale": True}},
            "world_facts": ["stale chapter two state"],
            "chapter_summaries": [],
        },
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "chapter_title": "Rewritten Two",
            "cadence": "manual",
            "summary": "Chapter two is rewritten in place.",
            "facts": ["chapter two rewrite saved"],
            "next_focus": "Continue without rolling back.",
            "primary_conflict": "Historical rewrite.",
            "secondary_conflict": "Global continuity.",
            "event_beat": "Rewrite.",
        },
    )

    store.persist_bundle(bundle, operation="regenerate")

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    chapter = json.loads((root / ".story-system" / "chapters" / "0002.json").read_text(encoding="utf-8"))
    assert chapter["chapter_number"] == 2
    assert state["current_chapter"] == 5
    assert state["progression_ledger"]["protagonist"] == {"level": "Lv.5", "canonical": True}
    assert "chapter five is canonical" in state["world_facts"]
    assert "stale chapter two state" not in state["world_facts"]


def test_regenerate_historical_chapter_rebases_structured_attribute_ledger_through_future_snapshots(tmp_path):
    root = tmp_path / "historical-attribute-rebase"
    rule = {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {"Strength": 5, "Intelligence": 5, "Agility": 5},
        "allow_carry": True,
        "respec_rule": "Respec in town.",
    }
    project = {
        "project_id": "p-historical-attribute-rebase",
        "title": "Historical Attribute Rebase",
        "active_story_id": "s-historical-attribute-rebase",
        "genre": "game_webnovel",
        "world_blueprint": {
            "genre_plugin_ids": ["game_webnovel"],
            "power_system_spec": {"attribute_allocation": rule},
        },
    }

    def attribute_slice(
        *,
        attributes,
        remaining,
        awards,
        allocations,
        level,
    ):
        return {
            "level": level,
            "attributes": attributes,
            "unallocated_attribute_points": remaining,
            "attribute_point_awards": awards,
            "attribute_allocations": allocations,
        }

    award_two = {"level": 2, "points": 5, "chapter": 2}
    award_three = {"level": 3, "points": 5, "chapter": 3}
    award_five = {"level": 4, "points": 5, "chapter": 5}
    old_two = {"chapter": 2, "allocations": {"Strength": 5}, "remaining": 0, "reason": "old build"}
    alloc_three = {"chapter": 3, "allocations": {"Intelligence": 2}, "remaining": 3, "reason": "spell check"}
    alloc_four = {"chapter": 4, "allocations": {"Agility": 3}, "remaining": 0, "reason": "movement check"}
    alloc_five = {"chapter": 5, "allocations": {"Strength": 1}, "remaining": 4, "reason": "gear check"}
    global_protagonist = attribute_slice(
        attributes={"Strength": 11, "Intelligence": 7, "Agility": 8},
        remaining=4,
        awards=[award_two, award_three, award_five],
        allocations=[old_two, alloc_three, alloc_four, alloc_five],
        level="Lv.4",
    )
    global_protagonist["hp"] = "87/100"
    state = {
        "story_id": "s-historical-attribute-rebase",
        "outline": "Ari changes an early build without erasing later continuity.",
        "genre": "game_webnovel",
        "style": "plain",
        "current_chapter": 5,
        "progression_ledger": {
            "protagonist": global_protagonist,
            "economy": {"game_currency": "91 copper", "inventory": {"ore": 7}},
            "quests": {"active": "chapter-five-quest"},
        },
        "time_state": {"current_scene_time": "chapter five end", "elapsed_minutes_since_launch": 250},
        "chapter_summaries": [{"chapter_number": 5, "summary": "The fifth chapter remains canonical."}],
        "world_facts": ["chapter five economy and quest remain canonical"],
        "characters": [
            {
                "name": "Ari",
                "role": "protagonist",
                "game_state": {"current": deepcopy(global_protagonist), "recent_changes": []},
                "game_panel": deepcopy(global_protagonist),
            }
        ],
    }
    store = _make_minimal_file_project(root, project=project, state=state)
    _seed_generation_outline(root, 2)

    def snapshot(number, protagonist, *, currency, quest, scene_time):
        return {
            "story_id": "s-historical-attribute-rebase",
            "outline": state["outline"],
            "genre": "game_webnovel",
            "style": "plain",
            "current_chapter": number,
            "progression_ledger": {
                "protagonist": protagonist,
                "economy": {"game_currency": currency},
                "quests": {"active": quest},
            },
            "time_state": {"current_scene_time": scene_time},
            "chapter_summaries": [{"chapter_number": number, "summary": f"chapter {number} summary"}],
            "world_facts": [f"chapter {number} world fact"],
            "characters": [{"name": "Ari", "role": "protagonist"}],
        }

    chapter_protagonists = {
        1: attribute_slice(attributes=rule["base_attributes"], remaining=0, awards=[], allocations=[], level="Lv.1"),
        2: attribute_slice(
            attributes={"Strength": 10, "Intelligence": 5, "Agility": 5},
            remaining=0,
            awards=[award_two],
            allocations=[old_two],
            level="Lv.2",
        ),
        3: attribute_slice(
            attributes={"Strength": 10, "Intelligence": 7, "Agility": 5},
            remaining=3,
            awards=[award_two, award_three],
            allocations=[old_two, alloc_three],
            level="Lv.3",
        ),
        4: attribute_slice(
            attributes={"Strength": 10, "Intelligence": 7, "Agility": 8},
            remaining=0,
            awards=[award_two, award_three],
            allocations=[old_two, alloc_three, alloc_four],
            level="Lv.3",
        ),
        5: deepcopy(global_protagonist),
    }
    future_non_attribute = {}
    for number in range(1, 6):
        updated_story = snapshot(
            number,
            chapter_protagonists[number],
            currency=f"{number * 10} copper",
            quest=f"quest-{number}",
            scene_time=f"chapter {number} end",
        )
        chapter = {
            "chapter_number": number,
            "chapter_title": f"Chapter {number}",
            "body": _long_test_body(f"Chapter {number} keeps its structured state."),
            "updated_story": updated_story,
            "chapter_summary": {"chapter_number": number, "summary": f"chapter {number} summary"},
        }
        store._write_json(store.story_system_dir / "chapters" / f"{number:04d}.json", chapter)
        if number >= 3:
            future_non_attribute[number] = {
                "economy": deepcopy(updated_story["progression_ledger"]["economy"]),
                "quests": deepcopy(updated_story["progression_ledger"]["quests"]),
                "time_state": deepcopy(updated_story["time_state"]),
                "chapter_summaries": deepcopy(updated_story["chapter_summaries"]),
                "world_facts": deepcopy(updated_story["world_facts"]),
            }

    class FakeEngine:
        def generate_next_chapter(self, story):
            assert story.current_chapter == 1
            updated = story.model_dump(mode="json")
            updated["current_chapter"] = 2
            updated["progression_ledger"]["protagonist"] = attribute_slice(
                attributes={"Strength": 5, "Intelligence": 10, "Agility": 5},
                remaining=0,
                awards=[award_two],
                allocations=[
                    {
                        "chapter": 2,
                        "allocations": {"Intelligence": 5},
                        "remaining": 0,
                        "reason": "rewritten build",
                    }
                ],
                level="Lv.2",
            )
            return SimpleNamespace(
                chapter_number=2,
                chapter_title="Rewritten Intelligence Build",
                body=_long_test_body("Ari confirms the rewritten structured build."),
                cadence="measured",
                next_outline="Continue into chapter three.",
                updated_story=StoryState.model_validate(updated),
                quality_report={"ok": True, "issues": []},
                chapter_summary={
                    "chapter_title": "Rewritten Intelligence Build",
                    "cadence": "measured",
                    "summary": "Ari commits to Intelligence.",
                    "facts": ["The structured ledger records Intelligence plus five."],
                    "next_focus": "Continue into chapter three.",
                    "primary_conflict": "Build choice.",
                    "secondary_conflict": "Later continuity.",
                    "event_beat": "Reallocate.",
                },
            )

    store.regenerate_chapter(2, engine=FakeEngine())

    chapters = {
        number: json.loads(
            (root / ".story-system" / "chapters" / f"{number:04d}.json").read_text(encoding="utf-8")
        )
        for number in range(2, 6)
    }
    assert chapters[2]["updated_story"]["current_chapter"] == 2
    final_allocations = [
        {"chapter": 2, "allocations": {"Intelligence": 5}, "remaining": 0, "reason": "rewritten build"},
        alloc_three,
        alloc_four,
        alloc_five,
    ]
    expected_attributes = {
        2: {"Strength": 5, "Intelligence": 10, "Agility": 5},
        3: {"Strength": 5, "Intelligence": 12, "Agility": 5},
        4: {"Strength": 5, "Intelligence": 12, "Agility": 8},
        5: {"Strength": 6, "Intelligence": 12, "Agility": 8},
    }
    for number, chapter in chapters.items():
        protagonist = chapter["updated_story"]["progression_ledger"]["protagonist"]
        assert protagonist["attributes"] == expected_attributes[number]
        assert protagonist["attribute_allocations"] == final_allocations[: number - 1]
        assert len(protagonist["attribute_allocations"]) == len(
            {(item["chapter"], tuple(item["allocations"].items())) for item in protagonist["attribute_allocations"]}
        )
        if number >= 3:
            updated_story = chapter["updated_story"]
            assert updated_story["progression_ledger"]["economy"] == future_non_attribute[number]["economy"]
            assert updated_story["progression_ledger"]["quests"] == future_non_attribute[number]["quests"]
            for field in ("time_state", "chapter_summaries", "world_facts"):
                assert updated_story[field] == future_non_attribute[number][field]

    global_state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert global_state["current_chapter"] == 5
    assert global_state["progression_ledger"]["economy"] == state["progression_ledger"]["economy"]
    assert global_state["progression_ledger"]["quests"] == state["progression_ledger"]["quests"]
    assert global_state["time_state"] == state["time_state"]
    assert global_state["chapter_summaries"] == state["chapter_summaries"]
    assert global_state["world_facts"] == state["world_facts"]
    protagonist = global_state["progression_ledger"]["protagonist"]
    assert protagonist["hp"] == "87/100"
    assert protagonist["attributes"] == expected_attributes[5]
    assert protagonist["unallocated_attribute_points"] == 4
    assert protagonist["attribute_point_awards"] == [award_two, award_three, award_five]
    assert protagonist["attribute_allocations"] == final_allocations
    character = global_state["characters"][0]
    for mirror in (character["game_state"]["current"], character["game_panel"]):
        for field in (
            "attributes",
            "unallocated_attribute_points",
            "attribute_point_awards",
            "attribute_allocations",
        ):
            assert mirror[field] == protagonist[field]


def test_historical_attribute_rebase_rejects_future_overspend_without_writes(tmp_path):
    root = tmp_path / "historical-attribute-rebase-invalid"
    rule = {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {"Strength": 5, "Intelligence": 5},
        "allow_carry": True,
        "respec_rule": "Respec in town.",
    }
    project = {
        "project_id": "p-rebase-invalid",
        "title": "Invalid Future Allocation",
        "active_story_id": "s-rebase-invalid",
        "genre": "game_webnovel",
        "world_blueprint": {"power_system_spec": {"attribute_allocation": rule}},
    }
    state = {
        "story_id": "s-rebase-invalid",
        "outline": "Structured history only.",
        "genre": "game_webnovel",
        "style": "plain",
        "current_chapter": 3,
        "progression_ledger": {
            "protagonist": {
                "level": "Lv.2",
                "attributes": {"Strength": 10, "Intelligence": 5},
                "unallocated_attribute_points": 0,
                "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 2}],
                "attribute_allocations": [
                    {"chapter": 2, "allocations": {"Strength": 5}, "remaining": 0, "reason": "old"}
                ],
            },
            "economy": {"game_currency": "30 copper"},
        },
        "world_facts": ["global state must remain byte-for-byte unchanged"],
    }
    store = _make_minimal_file_project(root, project=project, state=state)
    target_story = {
        **state,
        "current_chapter": 2,
        "progression_ledger": {
            "protagonist": {
                "level": "Lv.2",
                "attributes": {"Strength": 5, "Intelligence": 10},
                "unallocated_attribute_points": 0,
                "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 2}],
                "attribute_allocations": [
                    {
                        "chapter": 2,
                        "allocations": {"Intelligence": 5},
                        "remaining": 0,
                        "reason": "rewrite",
                    }
                ],
            }
        },
    }
    future_story = deepcopy(state)
    future_story["progression_ledger"]["protagonist"]["attribute_allocations"].append(
        {"chapter": 3, "allocations": {"Strength": 1}, "remaining": 0, "reason": "overspend"}
    )
    for number, updated_story in ((2, target_story), (3, future_story)):
        store._write_json(
            store.story_system_dir / "chapters" / f"{number:04d}.json",
            {
                "chapter_number": number,
                "chapter_title": f"Chapter {number}",
                "body": _long_test_body(f"Chapter {number} existing body."),
                "updated_story": updated_story,
            },
        )
    before = _file_snapshot(root)
    bundle = SimpleNamespace(
        chapter_number=2,
        chapter_title="Rejected Rewrite",
        body=_long_test_body("The prose contains no attribute parsing contract."),
        cadence="measured",
        next_outline="Do not persist this rewrite.",
        updated_story=StoryState.model_validate(target_story),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "chapter_title": "Rejected Rewrite",
            "cadence": "measured",
            "summary": "This rewrite must fail before persistence.",
            "facts": ["The future allocation overspends."],
            "next_focus": "Keep the old files.",
            "primary_conflict": "Invalid ledger.",
            "secondary_conflict": "Atomic persistence.",
            "event_beat": "Reject.",
        },
    )

    with pytest.raises(ValueError, match="^attribute_rebase_invalid_allocation:3$"):
        store.persist_bundle(bundle, operation="regenerate")

    assert _file_snapshot(root) == before


def _historical_rebase_transaction_case(root):
    rule = {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {"Strength": 5, "Intelligence": 5},
        "allow_carry": True,
        "respec_rule": "Respec in town.",
    }
    project = {
        "project_id": "p-rebase-transaction",
        "title": "Rebase Transaction",
        "active_story_id": "s-rebase-transaction",
        "genre": "game_webnovel",
        "world_blueprint": {"power_system_spec": {"attribute_allocation": rule}},
    }
    award_two = {"level": 2, "points": 5, "chapter": 2}
    award_three = {"level": 3, "points": 5, "chapter": 3}
    old_two = {"chapter": 2, "allocations": {"Strength": 5}, "remaining": 0, "reason": "old"}
    new_two = {"chapter": 2, "allocations": {"Intelligence": 5}, "remaining": 0, "reason": "rewrite"}
    alloc_three = {"chapter": 3, "allocations": {"Strength": 2}, "remaining": 3, "reason": "later"}
    state = {
        "story_id": "s-rebase-transaction",
        "outline": "A transactional historical rewrite.",
        "genre": "game_webnovel",
        "style": "plain",
        "current_chapter": 3,
        "progression_ledger": {
            "protagonist": {
                "level": "Lv.3",
                "attributes": {"Strength": 12, "Intelligence": 5},
                "unallocated_attribute_points": 3,
                "attribute_point_awards": [award_two, award_three],
                "attribute_allocations": [old_two, alloc_three],
            },
            "economy": {"game_currency": "30 copper"},
        },
        "world_facts": ["chapter three remains current"],
        "characters": [{"name": "Ari", "role": "protagonist"}],
    }
    store = _make_minimal_file_project(root, project=project, state=state)
    _seed_generation_outline(root, 2)

    def story(chapter, protagonist):
        return {
            "story_id": state["story_id"],
            "outline": state["outline"],
            "genre": state["genre"],
            "style": state["style"],
            "current_chapter": chapter,
            "progression_ledger": {
                "protagonist": protagonist,
                "economy": {"game_currency": f"{chapter * 10} copper"},
            },
            "world_facts": [f"chapter {chapter} fact"],
            "characters": [{"name": "Ari", "role": "protagonist"}],
        }

    old_target_story = story(
        2,
        {
            "level": "Lv.2",
            "attributes": {"Strength": 10, "Intelligence": 5},
            "unallocated_attribute_points": 0,
            "attribute_point_awards": [award_two],
            "attribute_allocations": [old_two],
        },
    )
    target_story = story(
        2,
        {
            "level": "Lv.2",
            "attributes": {"Strength": 5, "Intelligence": 10},
            "unallocated_attribute_points": 0,
            "attribute_point_awards": [award_two],
            "attribute_allocations": [new_two],
        },
    )
    future_story = story(
        3,
        {
            "level": "Lv.3",
            "attributes": {"Strength": 12, "Intelligence": 5},
            "unallocated_attribute_points": 3,
            "attribute_point_awards": [award_two, award_three],
            "attribute_allocations": [old_two, alloc_three],
        },
    )
    for number, updated_story in ((2, old_target_story), (3, future_story)):
        store._write_json(
            store.story_system_dir / "chapters" / f"{number:04d}.json",
            {
                "chapter_number": number,
                "chapter_title": f"Old Chapter {number}",
                "body": _long_test_body(f"Old chapter {number}."),
                "updated_story": updated_story,
            },
        )
    store._write_json(store.story_system_dir / "reviews" / "0002.json", {"old_review": True})
    store._write_text(store.chapters_dir / "0002-Old Chapter 2.md", "old markdown")

    def bundle(number, title, updated_story):
        return SimpleNamespace(
            chapter_number=number,
            chapter_title=title,
            body=_long_test_body(f"{title} body."),
            cadence="measured",
            next_outline="Continue.",
            updated_story=StoryState.model_validate(updated_story),
            quality_report={"ok": True, "issues": []},
            chapter_summary={
                "chapter_title": title,
                "cadence": "measured",
                "summary": f"{title} summary.",
                "facts": [f"{title} fact."],
                "next_focus": "Continue.",
                "primary_conflict": "State.",
                "secondary_conflict": "Order.",
                "event_beat": "Persist.",
            },
        )

    target_bundle = bundle(2, "Rewritten Two", target_story)
    concurrent_story = story(
        3,
        {
            "level": "Lv.3",
            "attributes": {"Strength": 7, "Intelligence": 10},
            "unallocated_attribute_points": 3,
            "attribute_point_awards": [award_two, award_three],
            "attribute_allocations": [new_two, alloc_three],
        },
    )
    concurrent_story["progression_ledger"]["concurrent_update"] = {"owner": "B"}
    return store, target_bundle, bundle(3, "Concurrent Three", concurrent_story)


def test_historical_rebase_syncs_attribute_mirrors_for_chinese_protagonist_role(tmp_path):
    root = tmp_path / "historical-rebase-chinese-protagonist"
    store, target_bundle, _ = _historical_rebase_transaction_case(root)
    state_path = store.webnovel_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    old_slice = {
        field: deepcopy(state["progression_ledger"]["protagonist"][field])
        for field in (
            "attributes",
            "unallocated_attribute_points",
            "attribute_point_awards",
            "attribute_allocations",
        )
    }
    state["characters"] = [
        {
            "name": "Ari",
            "role": "主角",
            "game_state": {"current": deepcopy(old_slice), "recent_changes": []},
            "game_panel": deepcopy(old_slice),
        }
    ]
    store._write_json(state_path, state)

    store.persist_bundle(target_bundle, operation="regenerate")

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    protagonist = persisted["progression_ledger"]["protagonist"]
    character = persisted["characters"][0]
    for mirror in (character["game_state"]["current"], character["game_panel"]):
        for field in old_slice:
            assert mirror[field] == protagonist[field]


@pytest.mark.parametrize("failure_point", ["markdown", "commit"])
def test_historical_rebase_rolls_back_all_project_files_after_late_failure(
    tmp_path,
    monkeypatch,
    failure_point,
):
    root = tmp_path / f"historical-rebase-{failure_point}-failure"
    store, target_bundle, _ = _historical_rebase_transaction_case(root)
    workflow_path = root / ".story-system" / "workflow" / "workflow_log.jsonl"
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text("old workflow\n", encoding="utf-8")
    monkeypatch.setenv("NOVEL_AUTOGROWTH_WORKFLOW_LOG_PATH", str(workflow_path))
    commits_dir = store.story_system_dir / "commits"
    commits_dir.mkdir(parents=True, exist_ok=True)
    (commits_dir / "old.json").write_text('{"old": true}', encoding="utf-8")
    before = _file_snapshot(root)

    if failure_point == "markdown":
        original_write_text = store._write_text

        def fail_markdown(path, text):
            if path.parent == store.chapters_dir:
                raise OSError("injected_markdown_failure")
            return original_write_text(path, text)

        monkeypatch.setattr(store, "_write_text", fail_markdown)
        expected = "injected_markdown_failure"
    else:
        original_commit = store.commit

        def fail_after_commit(**kwargs):
            original_commit(**kwargs)
            raise RuntimeError("injected_commit_failure")

        monkeypatch.setattr(store, "commit", fail_after_commit)
        expected = "injected_commit_failure"

    with pytest.raises((OSError, RuntimeError), match=expected):
        store.persist_bundle(target_bundle, operation="regenerate")

    assert _file_snapshot(root) == before


def test_historical_rebase_reports_compensation_failure(tmp_path, monkeypatch):
    root = tmp_path / "historical-rebase-rollback-failure"
    store, target_bundle, _ = _historical_rebase_transaction_case(root)

    def fail_markdown(_path, _text):
        raise OSError("injected_markdown_failure")

    def fail_rollback(_snapshot, _directories):
        raise OSError("injected_rollback_failure")

    monkeypatch.setattr(store, "_write_text", fail_markdown)
    monkeypatch.setattr(store, "_restore_managed_files", fail_rollback)

    with pytest.raises(RuntimeError, match="^historical_persistence_rollback_failed$"):
        store.persist_bundle(target_bundle, operation="regenerate")


def test_persist_bundle_serializes_historical_prepare_with_concurrent_chapter_write(tmp_path, monkeypatch):
    root = tmp_path / "historical-rebase-concurrent"
    store_a, target_bundle, concurrent_bundle = _historical_rebase_transaction_case(root)
    store_b = FileProjectStore(root)
    prepared = threading.Event()
    release_a = threading.Event()
    b_done = threading.Event()
    errors = []
    original_prepare = store_a._prepare_historical_attribute_rebase

    def pause_after_prepare(chapter, updated_story):
        result = original_prepare(chapter, updated_story)
        prepared.set()
        assert release_a.wait(5)
        return result

    monkeypatch.setattr(store_a, "_prepare_historical_attribute_rebase", pause_after_prepare)

    def run_a():
        try:
            store_a.persist_bundle(target_bundle, operation="regenerate")
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def run_b():
        try:
            store_b.persist_bundle(concurrent_bundle, operation="regenerate")
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            b_done.set()

    thread_a = threading.Thread(target=run_a, name="historical-rebase-a")
    thread_b = threading.Thread(target=run_b, name="chapter-three-b")
    thread_a.start()
    assert prepared.wait(5)
    thread_b.start()
    assert not b_done.wait(0.2)
    release_a.set()
    thread_a.join(5)
    thread_b.join(5)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    assert errors == []
    chapter_three = json.loads(
        (store_a.story_system_dir / "chapters" / "0003.json").read_text(encoding="utf-8")
    )
    assert chapter_three["updated_story"]["progression_ledger"]["concurrent_update"] == {"owner": "B"}


def test_regenerate_serializes_state_read_and_generation_per_project(tmp_path):
    root = tmp_path / "regenerate-whole-operation-lock"
    store_a, target_bundle, concurrent_template = _historical_rebase_transaction_case(root)
    store_b = FileProjectStore(root)
    a_generating = threading.Event()
    release_a = threading.Event()
    a_done = threading.Event()
    b_generated = threading.Event()
    allow_b_return = threading.Event()
    observed_b_attributes = {}
    errors = []

    class HistoricalEngine:
        def generate_next_chapter(self, _story):
            a_generating.set()
            assert release_a.wait(5)
            return target_bundle

    class NextChapterEngine:
        def generate_next_chapter(self, story):
            observed_b_attributes.update(story.progression_ledger["protagonist"]["attributes"])
            updated = story.model_dump(mode="json")
            updated["current_chapter"] = 3
            updated["progression_ledger"]["concurrent_update"] = {"owner": "B"}
            b_generated.set()
            assert allow_b_return.wait(5)
            return SimpleNamespace(
                **{
                    **vars(concurrent_template),
                    "updated_story": StoryState.model_validate(updated),
                }
            )

    def run_a():
        try:
            store_a.regenerate_chapter(2, engine=HistoricalEngine())
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            a_done.set()

    def run_b():
        try:
            store_b.regenerate_chapter(3, engine=NextChapterEngine())
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread_a = threading.Thread(target=run_a, name="historical-regenerate-a")
    thread_b = threading.Thread(target=run_b, name="next-regenerate-b")
    thread_a.start()
    assert a_generating.wait(5)
    thread_b.start()
    b_was_blocked = not b_generated.wait(0.2)
    release_a.set()
    assert a_done.wait(5)
    allow_b_return.set()
    thread_a.join(5)
    thread_b.join(5)

    assert b_was_blocked
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    assert errors == []
    assert observed_b_attributes == {"Strength": 5, "Intelligence": 10}
    final_state = json.loads((store_a.webnovel_dir / "state.json").read_text(encoding="utf-8"))
    assert final_state["progression_ledger"]["protagonist"]["attributes"]["Intelligence"] == 10


def test_regenerate_generation_lock_is_independent_between_projects(tmp_path):
    store_a, target_a, _ = _historical_rebase_transaction_case(tmp_path / "project-a")
    store_b, target_b, _ = _historical_rebase_transaction_case(tmp_path / "project-b")
    a_generating = threading.Event()
    release_a = threading.Event()
    b_generated = threading.Event()
    errors = []

    class BlockingEngine:
        def generate_next_chapter(self, _story):
            a_generating.set()
            assert release_a.wait(5)
            return target_a

    class IndependentEngine:
        def generate_next_chapter(self, _story):
            b_generated.set()
            return target_b

    def regenerate(store, engine):
        try:
            store.regenerate_chapter(2, engine=engine)
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    thread_a = threading.Thread(target=regenerate, args=(store_a, BlockingEngine()))
    thread_b = threading.Thread(target=regenerate, args=(store_b, IndependentEngine()))
    thread_a.start()
    assert a_generating.wait(5)
    thread_b.start()
    b_ran_independently = b_generated.wait(1)
    release_a.set()
    thread_a.join(5)
    thread_b.join(5)

    assert b_ran_independently
    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    assert errors == []


def test_usable_bundle_state_keeps_valid_runtime_character_updates(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    current_state = {
        "story_id": "s-file",
        "outline": "Canonical outline.",
        "genre": "game_webnovel",
        "style": "plain",
        "current_chapter": 1,
        "characters": [{"name": "Ari", "role": "protagonist", "current_emotion": "stale"}],
        "timeline": [{"chapter_number": 1, "summary": "First.", "impact": "Continue."}],
        "chapter_summaries": [
            {"chapter_number": 1, "chapter_title": "One", "summary": "First.", "next_focus": "Continue."}
        ],
    }
    updated_story = {
        "story_id": "s-file",
        "outline": "Canonical outline.",
        "genre": "game_webnovel",
        "style": "plain",
        "current_chapter": 2,
        "progression_ledger": {"protagonist": {"level": "Lv.2"}},
        "characters": [{"name": "Ari", "role": "protagonist", "current_emotion": "focused"}],
        "time_state": {"current_scene_time": "chapter two end"},
    }

    usable = store._usable_bundle_state(updated_story, current_state, target_chapter=2)

    assert usable["characters"][0]["current_emotion"] == "focused"
    assert usable["time_state"] == {"current_scene_time": "chapter two end"}
    assert usable["timeline"] == current_state["timeline"]
    assert usable["chapter_summaries"] == current_state["chapter_summaries"]


def test_usable_bundle_state_rejects_partial_updated_story(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    current_state = {
        "story_id": "s-file",
        "outline": "Canonical outline.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 1,
        "characters": [{"name": "Ari", "role": "protagonist"}],
        "world_facts": ["canonical world fact"],
    }

    usable = store._usable_bundle_state(
        {"story_id": "s-file", "current_chapter": 2, "characters": []},
        current_state,
        target_chapter=2,
    )

    assert usable == current_state


def test_persist_bundle_keeps_runtime_character_and_syncs_attribute_history(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-file",
            "title": "Attribute Story",
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "genre": "game_webnovel",
            "characters": [{"name": "Ari", "role": "protagonist", "current_emotion": "stale"}],
        },
    )
    awards = [
        {"level": 2, "points": 5, "chapter": 1},
        {"level": 3, "points": 5, "chapter": 2},
    ]
    allocations = [
        {"chapter": 1, "allocations": {"Intelligence": 5}, "remaining": 0},
        {"chapter": 2, "allocations": {"Constitution": 2}, "remaining": 3},
    ]
    bundle = SimpleNamespace(
        chapter_number=2,
        chapter_title="A New Build",
        body=_long_test_body("The panel shows level: 3. Ari changes the build after the quest reward."),
        cadence="manual",
        next_outline="Test the new build.",
        updated_story={
            "story_id": "s-file",
            "outline": "Ari tests a new attribute build.",
            "current_chapter": 2,
            "genre": "game_webnovel",
            "style": "plain",
            "progression_ledger": {
                "protagonist": {
                    "level": "Lv.3",
                    "attributes": {"Intelligence": 10, "Constitution": 7},
                    "unallocated_attribute_points": 3,
                    "attribute_point_awards": awards,
                    "attribute_allocations": allocations,
                }
            },
            "characters": [{"name": "Ari", "role": "protagonist", "current_emotion": "focused"}],
            "chapter_summaries": [],
        },
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "chapter_title": "A New Build",
            "cadence": "manual",
            "summary": "Ari changes the build.",
            "facts": ["Ari keeps three points."],
            "next_focus": "Test the new build.",
            "primary_conflict": "Build choice.",
            "secondary_conflict": "Limited points.",
            "event_beat": "Allocate.",
        },
    )

    store.persist_bundle(bundle)

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    character = state["characters"][0]
    assert character["current_emotion"] == "focused"
    for state_slice in (character["game_state"]["current"], character["game_panel"]):
        assert state_slice["attributes"] == {"Intelligence": 10, "Constitution": 7}
        assert state_slice["unallocated_attribute_points"] == 3
        assert state_slice["attribute_point_awards"] == awards
        assert state_slice["attribute_allocations"] == allocations


def test_rewrite_chapter_uses_canonical_state_not_embedded_snapshot(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": ["source:canonical"]},
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "Old Chapter",
        "body": "Old body.",
        "next_outline": "Old next.",
        "updated_story": {
            "story_id": "s-file",
            "current_chapter": 1,
            "world_facts": ["stale embedded snapshot"],
        },
        "chapter_summary": {
            "chapter_title": "Old Chapter",
            "cadence": "manual",
            "summary": "Old summary.",
            "facts": ["old fact"],
            "next_focus": "Old next.",
            "primary_conflict": "Old.",
            "secondary_conflict": "Old.",
            "event_beat": "Old.",
        },
    }
    (root / ".story-system" / "chapters" / "0001.json").write_text(json.dumps(chapter, ensure_ascii=False), encoding="utf-8")
    (root / ".story-system" / "reviews" / "0001.json").write_text(
        json.dumps({"writing_review": {"pass": True, "issues": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "chapters" / "0001-Old Chapter.md").write_text("Old body.", encoding="utf-8")

    store.rewrite_chapter(
        chapter_number=1,
        title="Rewritten Chapter",
        body="Night Ember rewrites only the live facts.",
        instructions=["fresh rewrite fact"],
    )

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    facts = "\n".join(item["text"] for item in state["continuity_facts"])
    assert "fresh rewrite fact" in facts
    assert "stale embedded snapshot" not in facts


def test_regenerate_blocks_frozen_chapter(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "current_chapter": 1,
            "world_facts": [],
            "progression_ledger": {"continuity_lock": {"chapters_frozen": [1]}},
        },
    )

    _seed_generation_outline(root, 1)

    try:
        store.regenerate_chapter(1, engine=SimpleNamespace(generate_next_chapter=lambda story: None))
    except ValueError as exc:
        assert str(exc) == "chapter_frozen:1:regenerate"
    else:
        raise AssertionError("expected frozen chapter regeneration to fail")


def test_freeze_opening_baseline_rebuilds_state_and_blocks_rewrites(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "Opening test.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 3,
            "world_facts": [],
            "timeline": ["chapter 1: stale shell"],
            "chapter_summaries": [
                {"chapter_title": "One", "summary": "stale unnumbered shell"},
                {"chapter_number": 2, "chapter_title": "Old Two", "summary": "stale two"},
            ],
        },
    )
    store.write_chapter(chapter_number=1, title="One", body="Night Ember sees the grey prompt.", summary="First accepted.")
    store.write_chapter(
        chapter_number=2,
        title="Two",
        body="Night Ember submits 清道夫委托已提交 and 等级升到Lv.2. 钱袋：空。背包：粗糙狼皮×7，小法力药水×1。",
        summary="Second accepted.",
        instructions=["等级升到Lv.2", "钱袋：空", "灰狼毒腺×0", "粗糙狼皮×7", "小法力药水×1"],
    )
    store.write_chapter(chapter_number=3, title="Three", body="Night Ember reaches 后坡登记 and 灰石裂缝.", summary="Third accepted.")

    frozen = store.freeze_opening_baseline(through_chapter=3)

    assert frozen["chapters_frozen"] == [1, 2, 3]
    assert frozen["preflight"]["ok"] is True
    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert [item["chapter_number"] for item in state["chapter_summaries"]] == [1, 2, 3]
    assert "stale unnumbered shell" not in json.dumps(state, ensure_ascii=False)
    assert state["progression_ledger"]["protagonist"]["level"] == "Lv.2"
    assert state["progression_ledger"]["economy"]["game_currency"] == "空"
    assert state["progression_ledger"]["economy"]["inventory"]["灰狼毒腺"] == 0
    assert state["progression_ledger"]["continuity_lock"]["opening_baseline"]["next_chapter"] == 4
    project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert "continuity_state" not in project.get("world_blueprint", {})
    assert "stale two" not in json.dumps(state, ensure_ascii=False)

    try:
        store.write_chapter(chapter_number=1, title="Bad Rewrite", body="Should not write.", overwrite=True)
    except ValueError as exc:
        assert str(exc) == "chapter_frozen:1:write"
    else:
        raise AssertionError("expected frozen write to fail")


def test_opening_preflight_reports_stale_tokens_after_baseline(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "Opening test.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )
    store.write_chapter(chapter_number=1, title="One", body="Night Ember starts.", summary="First.")
    store.freeze_opening_baseline(through_chapter=1)
    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    state["world_facts"].append("旧设定：元素法师学徒。")
    (root / ".webnovel" / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    report = FileProjectStore(root).opening_preflight(next_chapter=2)

    assert report["ok"] is False
    assert "元素法师学徒" in report["issues"][0]


def test_file_project_store_dedupes_npc_aliases_and_filters_surface_entities(tmp_path):
    store = FileProjectStore(tmp_path / "novel")
    chapter = {
        "chapter_number": 1,
        "chapter_title": "药剂铺窗口",
        "body": "夜烬走进药剂铺。灰头巾老妇人抬头。公共频道还在滚动。清道夫委托写在木牌上。",
        "chapter_summary": {"summary": "夜烬问药剂师。"},
    }

    cards = store._merge_character_cards([], store._chapter_entity_cards(chapter))

    assert [card["name"] for card in cards] == ["药剂师洛婶"]
    assert cards[0]["role"] == "服务NPC"
    assert "药剂师NPC" not in {card["name"] for card in cards}
    assert "药剂铺老妇人" not in {card["name"] for card in cards}
    assert "公共频道" not in {card["name"] for card in cards}
    assert "清道夫委托" not in {card["name"] for card in cards}


def test_file_project_store_filters_stale_non_character_profiles(tmp_path):
    store = FileProjectStore(tmp_path / "novel")
    project = {
        "project_id": "p-file",
        "character_profiles": [
            {"name": "公共频道", "role": "玩家群体", "memory": ["旧噪音。"]},
            {"name": "药剂铺老妇人", "role": "服务NPC", "memory": ["旧药剂铺卡。"]},
        ],
    }
    state = {
        "characters": [
            {"name": "药剂师NPC", "role": "服务NPC", "memory": ["第1章：委托十份一批。"]},
            {"name": "清道夫委托", "role": "任务线", "memory": ["不是人物。"]},
        ]
    }
    chapter = {
        "chapter_number": 1,
        "chapter_title": "药剂铺窗口",
        "body": "夜烬问药剂师。",
        "chapter_summary": {
            "chapter_title": "药剂铺窗口",
            "cadence": "urgent",
            "summary": "夜烬问药剂师。",
            "facts": ["药剂铺十份一批。"],
            "next_focus": "回灰狼坡。",
            "primary_conflict": "材料不足。",
            "secondary_conflict": "0铜。",
            "event_beat": "窗口规则。",
        },
    }

    synced = store._sync_project_after_chapter(project, state, chapter)

    names = [profile["name"] for profile in synced["character_profiles"]]
    assert names == ["药剂师洛婶"]
    assert synced["character_profiles"][0]["memory"][-1] == "第1章：委托十份一批。"


def test_sync_project_after_chapter_applies_relationship_state_changes(tmp_path):
    store = _make_minimal_file_project(tmp_path / "novel")
    project = {
        "project_id": "p-file",
        "relationship_graph": [
            {"source": "Lin Zhao", "target": "Zhao Heng", "origin": "first meeting", "trust": 40, "tension": 20}
        ],
    }
    state = {
        "characters": [
            {
                "name": "Lin Zhao",
                "role": "protagonist",
                "relationships": {
                    "Zhao Heng": {"target": "Zhao Heng", "bond": "open rivals", "trust": 10, "tension": 85}
                },
            }
        ]
    }
    chapter = {
        "chapter_number": 3,
        "chapter_title": "Public conflict",
        "body": "Lin Zhao leaves evidence in public.",
        "chapter_summary": {"summary": "Lin Zhao leaves evidence in public.", "facts": [], "next_focus": "continue"},
    }

    synced = store._sync_project_after_chapter(project, state, chapter)

    edge = synced["relationship_graph"][0]
    assert edge["origin"] == "first meeting"
    assert edge["bond"] == "open rivals"
    assert edge["trust"] == 10
    assert edge["tension"] == 85
    assert edge["last_changed_chapter"] == 3
    assert edge["changes"][-1]["chapter_number"] == 3


def test_file_project_store_regenerates_target_chapter_with_rotating_variant(tmp_path, monkeypatch):
    root = tmp_path / "novel"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {"schema_version": "story-system-master-setting/v1", "project": {"project_id": "p-file", "title": "File Novel"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(
                {
                    "project_id": "p-file",
                    "title": "File Novel",
                    "author_constraints": ["第一章必须通过裂纹狼心担保交易解决现实急账。"],
                    "character_profiles": [{"name": "苏叶", "role": "主角", "game_id": "夜烬"}],
                },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-file",
                "outline": "网游开服，主角先确认边界。",
                "genre": "网游",
                "style": "番茄升级流",
                "author_constraints": ["第一章不得交易。"],
                "writing_lessons": ["删除第一章实际交易，只保留价牌。"],
                "current_chapter": 1,
                "world_facts": ["世界摘要：保留。", "第1章事实：灰鼠毒腺x18。", "第4章章末：巡夜人残牌和废井污染源。"],
                "progression_ledger": {
                    "inventory": ["灰鼠毒腺18份"],
                    "simulation_variant": {"id": "old"},
                },
                "characters": [
                    {
                        "name": "苏叶",
                        "role": "主角",
                        "game_id": "夜烬",
                        "game_panel": {"game_id": "夜烬", "inventory": {"灰鼠毒腺": "18份"}},
                        "memory": ["第1章灰鼠毒腺。", "第4章章末有巡夜人残牌。", "现实压力。"],
                    },
                    {"name": "公共频道", "role": "玩家群体", "memory": ["旧噪音。"]},
                ],
                "chapter_summaries": [{"chapter_number": 1, "chapter_title": "旧第一章", "summary": "旧版。"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = FileProjectStore(root)
    store.write_chapter(chapter_number=1, title="旧第一章", body="旧正文。", summary="旧版。")

    monkeypatch.setattr(
        store,
        "require_volume_detail_for_prose",
        lambda target_chapter: {
            "status": "detail_complete",
            "target_chapter": target_chapter,
        },
    )
    seen_variants: list[str] = []

    class FakeEngine:
        def generate_next_chapter(self, story):
            assert story.author_constraints == []
            assert story.writing_lessons == []
            simulation_variant = story.progression_ledger["simulation_variant"]
            variant = simulation_variant["id"]
            seen_variants.append(variant)
            assert "skip_style_adapt" not in simulation_variant
            assert simulation_variant["skip_expansion"] is False
            dumped_story = json.dumps(story.model_dump(mode="json"), ensure_ascii=False)
            assert "灰鼠" not in dumped_story
            assert "巡夜人残牌" not in dumped_story
            assert "第4章" not in dumped_story
            assert "废井" not in dumped_story
            assert story.chapter_summaries == []
            assert [character.name for character in story.characters] == ["苏叶"]
            assert story.characters[0].game_panel.game_id == "夜烬"
            assert story.characters[0].game_panel.inventory == {}
            updated_story = story.model_copy(
                update={
                    "current_chapter": 1,
                    "timeline": [TimelineEvent(chapter_number=1, summary="新版第一章完成。", impact="推进开局。")],
                    "chapter_summaries": [
                        ChapterSummary(chapter_number=1, chapter_title=f"新版-{variant}", summary="新版第一章完成。")
                    ],
                }
            )
            return SimpleNamespace(
                chapter_number=1,
                chapter_title=f"新版-{variant}",
                body=_long_test_body(f"正文使用变体 {variant}。"),
                cadence="manual",
                next_outline="继续确认边界。",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": f"新版-{variant}",
                    "cadence": "manual",
                    "summary": f"使用 {variant} 重推。",
                    "facts": [f"variant:{variant}"],
                    "next_focus": "继续确认边界。",
                    "primary_conflict": "边界",
                    "secondary_conflict": "代价",
                    "event_beat": "重推",
                },
            )

    regenerated = store.regenerate_chapter(1, engine=FakeEngine())

    assert regenerated["schema_version"] == "file-project-regenerate/v1"
    assert regenerated["chapter_number"] == 1
    assert regenerated["chapter_title"] == "新版-focus-character-choice"
    assert seen_variants == ["focus-character-choice"]
    assert regenerated["simulation_variant"]["id"] == "focus-character-choice"
    assert "skip_style_adapt" not in regenerated["simulation_variant"]
    assert regenerated["simulation_variant"]["skip_expansion"] is False
    assert (root / "chapters" / "0001-新版-focus-character-choice.md").exists()


def test_regenerate_uses_complete_runtime_story_payload_for_project_genre(monkeypatch, tmp_path):
    root = tmp_path / "regenerate-effective-story"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-regenerate-effective",
            "title": "Regenerate Effective",
            "active_story_id": "s-regenerate-effective",
            "genre": "game_webnovel",
            "author_constraints": ["PROJECT_RULE"],
            "world_blueprint": {"genre_plugin_ids": ["game_webnovel"]},
        },
        state={
            "story_id": "s-regenerate-effective",
            "outline": "夜烬准备进入新手村。",
            "genre": "",
            "genre_plugin_ids": [],
            "style": "白描",
            "current_chapter": 1,
            "author_constraints": ["STATE_RULE"],
            "world_facts": [],
            "characters": [{"name": "苏叶", "role": "protagonist", "game_id": "夜烬"}],
        },
    )
    _seed_generation_outline(root, 1)
    captured = {}

    class FakeEngine:
        def generate_next_chapter(self, story):
            captured["story"] = story
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="重新开服",
                chapter_summary={},
                quality_report={"ok": True},
            )

    monkeypatch.setattr(
        store,
        "persist_bundle",
        lambda bundle, **_kwargs: {
            "chapter_number": bundle.chapter_number,
            "chapter_title": bundle.chapter_title,
        },
    )

    store.regenerate_chapter(1, engine=FakeEngine())

    story = captured["story"]
    assert story.genre == "game_webnovel"
    assert story.genre_plugin_ids == ["game_webnovel"]
    assert story.author_constraints == ["PROJECT_RULE"]


def test_regenerate_first_chapter_can_save_candidate_without_existing_chapters(tmp_path):
    root = tmp_path / "regenerate-first-candidate"
    store = _make_minimal_file_project(
        root,
        project={
            "title": "First Candidate",
        },
        state={
            "story_id": "s-regenerate-first",
            "outline": "从第一章重新开始。",
            "genre": "都市",
            "style": "自然",
            "current_chapter": 0,
            "world_facts": [],
            "characters": [{"name": "苏叶", "role": "protagonist"}],
        },
    )

    _seed_generation_outline(root, 1)

    class FakeEngine:
        def generate_next_chapter(self, story):
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="新的第一章",
                body=_long_test_body("苏叶重新开始。"),
                cadence="manual",
                next_outline="继续。",
                updated_story=story.model_copy(update={"current_chapter": 1}),
                chapter_summary={"chapter_title": "新的第一章", "summary": "苏叶重新开始。"},
                quality_report={"ok": True},
            )

    result = store.regenerate_chapter(1, engine=FakeEngine(), persist=False)

    assert result["schema_version"] == "file-project-candidate/v1"
    assert result["candidate"]["status"] == "pending"


def test_regenerate_first_chapter_uses_master_opening_state_instead_of_old_chapter_result(
    monkeypatch,
    tmp_path,
):
    root = tmp_path / "regenerate-first-from-opening-state"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-opening-state",
            "title": "Opening State",
            "active_story_id": "s-opening-state",
            "genre": "game_webnovel",
        },
        state={
            "story_id": "s-opening-state",
            "outline": "夜烬从开服重新开始。",
            "genre": "game_webnovel",
            "current_chapter": 1,
            "progression_ledger": {
                "protagonist": {"level": "Lv.2"},
                "economy": {"game_currency": "80铜币"},
                "quests": {"active": "旧第一章任务已完成"},
            },
            "timeline": [{"chapter_number": 1, "summary": "旧第一章完成"}],
            "chapter_summaries": [{"chapter_number": 1, "summary": "旧第一章"}],
        },
    )
    _seed_generation_outline(root, 1)
    master = store.master_setting()
    master["state"] = {
        "story_id": "s-opening-state",
        "outline": "夜烬从开服重新开始。",
        "genre": "game_webnovel",
        "current_chapter": 0,
        "progression_ledger": {
            "protagonist": {"level": "Lv.1"},
            "economy": {"game_currency": "空", "inventory": {}},
            "real": {"start_balance": "43.20元"},
        },
        "time_state": {"current_scene_time": "第一章开始前"},
        "timeline": [],
        "chapter_summaries": [],
    }
    store._write_json(store.story_system_dir / "MASTER_SETTING.json", master)
    store.write_chapter(
        chapter_number=1,
        title="旧第一章",
        body=_long_test_body("旧第一章已经升级并完成任务。"),
        summary="旧第一章完成。",
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            ledger = story.progression_ledger
            assert story.current_chapter == 0
            assert ledger["protagonist"]["level"] == "Lv.1"
            assert ledger["economy"]["game_currency"] == "空"
            assert ledger["real"]["start_balance"] == "43.20元"
            assert "quests" not in ledger
            assert story.timeline == []
            assert story.chapter_summaries == []
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="新的第一章",
                quality_report={"ok": True},
                chapter_summary={},
            )

    monkeypatch.setattr(
        store,
        "persist_bundle",
        lambda bundle, **_kwargs: {
            "chapter_number": bundle.chapter_number,
            "chapter_title": bundle.chapter_title,
        },
    )

    store.regenerate_chapter(1, engine=FakeEngine())


def test_manual_rewrite_latest_chapter_rebuilds_from_opening_state(tmp_path):
    root = tmp_path / "manual-rewrite-from-opening-state"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-manual-opening",
            "outline": "从第一章开始。",
            "genre": "fantasy",
            "current_chapter": 1,
            "world_facts": ["旧第一章结果"],
            "progression_ledger": {"old_chapter_result": True},
        },
    )
    master = store.master_setting()
    master["state"] = {
        "story_id": "s-manual-opening",
        "outline": "从第一章开始。",
        "genre": "fantasy",
        "current_chapter": 0,
        "world_facts": ["开书前事实"],
        "progression_ledger": {"opening_resource": 3},
        "timeline": [],
        "chapter_summaries": [],
    }
    store._write_json(store.story_system_dir / "MASTER_SETTING.json", master)
    store.write_chapter(
        chapter_number=1,
        title="旧第一章",
        body=_long_test_body("旧第一章消耗了全部资源。"),
        summary="旧结果。",
    )

    store.rewrite_chapter(
        chapter_number=1,
        title="新第一章",
        body=_long_test_body("主角重新检查手里的三份材料，然后出门。"),
    )

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state["progression_ledger"]["opening_resource"] == 3
    assert "old_chapter_result" not in state["progression_ledger"]
    assert "旧第一章结果" not in state["world_facts"]


def test_regenerate_second_chapter_uses_previous_snapshot_for_attribute_reallocation(tmp_path):
    root = tmp_path / "regenerate-attribute-baseline"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-regenerate-attributes",
            "title": "Attribute Rewrite",
            "active_story_id": "s-regenerate-attributes",
            "genre": "game_webnovel",
            "world_blueprint": {
                "genre_plugin_ids": ["game_webnovel"],
                "power_system_spec": {
                    "attribute_allocation": {
                        "mode": "free",
                        "points_per_level": 5,
                        "starting_level": 1,
                        "base_attributes": {"Intelligence": 5, "Constitution": 5},
                        "allow_carry": True,
                        "respec_rule": "Respec in town.",
                    }
                },
            },
        },
        state={
            "story_id": "s-regenerate-attributes",
            "outline": "Ari tests a new build.",
            "genre": "game_webnovel",
            "style": "plain",
            "current_chapter": 2,
            "author_constraints": ["Use the current author rule."],
            "progression_ledger": {
                "protagonist": {
                    "level": "Lv.2",
                    "attributes": {"Intelligence": 10, "Constitution": 5},
                    "unallocated_attribute_points": 0,
                    "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 1}],
                    "attribute_allocations": [
                        {"chapter": 2, "allocations": {"Intelligence": 5}, "remaining": 0}
                    ],
                }
            },
            "characters": [
                {"name": "Ari", "role": "protagonist", "current_emotion": "chapter-two-stale"}
            ],
        },
    )
    chapter_one_state = {
        "story_id": "s-regenerate-attributes",
        "outline": "Ari tests a new build.",
        "genre": "game_webnovel",
        "style": "plain",
        "current_chapter": 1,
        "author_constraints": ["Old author rule."],
        "progression_ledger": {
            "protagonist": {
                "level": "Lv.2",
                "attributes": {"Intelligence": 5, "Constitution": 5},
                "unallocated_attribute_points": 5,
                "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 1}],
                "attribute_allocations": [],
            }
        },
        "characters": [{"name": "Ari", "role": "protagonist", "current_emotion": "chapter-one-ready"}],
        "chapter_summaries": [{"chapter_number": 1, "summary": "Ari earns five points."}],
    }
    _seed_generation_outline(root, 2)
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "First Reward",
            "body": _long_test_body("The panel shows level: 2 and five available points."),
            "updated_story": chapter_one_state,
            "chapter_summary": {"chapter_number": 1, "summary": "Ari earns five points."},
        },
    )
    store._write_json(
        store.story_system_dir / "chapters" / "0002.json",
        {
            "chapter_number": 2,
            "chapter_title": "Old Allocation",
            "body": _long_test_body("Ari spends five points on Intelligence."),
        },
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            protagonist = story.progression_ledger["protagonist"]
            assert story.current_chapter == 1
            assert story.author_constraints == ["Use the current author rule."]
            assert story.characters[0].current_emotion == "chapter-one-ready"
            assert protagonist["unallocated_attribute_points"] == 5
            assert protagonist["attribute_allocations"] == []
            updated = story.model_dump(mode="json")
            updated["current_chapter"] = 2
            updated["progression_ledger"]["protagonist"] = {
                "level": "Lv.2",
                "attributes": {"Intelligence": 5, "Constitution": 10},
                "unallocated_attribute_points": 0,
                "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 1}],
                "attribute_allocations": [
                    {"chapter": 2, "allocations": {"Constitution": 5}, "remaining": 0}
                ],
            }
            return SimpleNamespace(
                chapter_number=2,
                chapter_title="New Allocation",
                body=_long_test_body("The panel shows level: 2. Ari spends five points on Constitution."),
                cadence="manual",
                next_outline="Test the Constitution build.",
                updated_story=StoryState.model_validate(updated),
                quality_report={"ok": True, "issues": []},
                chapter_summary={
                    "chapter_title": "New Allocation",
                    "cadence": "manual",
                    "summary": "Ari changes the allocation.",
                    "facts": ["Constitution receives five points."],
                    "next_focus": "Test the Constitution build.",
                    "primary_conflict": "Build choice.",
                    "secondary_conflict": "Limited points.",
                    "event_beat": "Reallocate.",
                },
            )

    store.regenerate_chapter(2, engine=FakeEngine())

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    protagonist = state["progression_ledger"]["protagonist"]
    assert protagonist["attribute_point_awards"] == [{"level": 2, "points": 5, "chapter": 1}]
    assert protagonist["attribute_allocations"] == [
        {"chapter": 2, "allocations": {"Constitution": 5}, "remaining": 0}
    ]
    assert protagonist["unallocated_attribute_points"] == 0


def test_regenerate_without_previous_snapshot_does_not_reuse_completed_chapter_state(monkeypatch, tmp_path):
    root = tmp_path / "regenerate-safe-fallback"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-regenerate-fallback",
            "outline": "Ari tests a build.",
            "genre": "game_webnovel",
            "style": "plain",
            "current_chapter": 2,
            "progression_ledger": {
                "protagonist": {
                    "level": "Lv.2",
                    "unallocated_attribute_points": 0,
                    "attribute_allocations": [
                        {"chapter": 2, "allocations": {"Intelligence": 5}, "remaining": 0}
                    ],
                }
            },
            "characters": [{"name": "Ari", "role": "protagonist"}],
        },
    )
    _seed_generation_outline(root, 2)
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "Legacy First",
            "body": _long_test_body("The panel shows level: 2."),
        },
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            allocations = story.progression_ledger.get("protagonist", {}).get("attribute_allocations", [])
            assert not any(item.get("chapter") == 2 for item in allocations)
            return SimpleNamespace(chapter_number=2, chapter_title="Fallback Rewrite", quality_report={}, chapter_summary={})

    monkeypatch.setattr(
        store,
        "persist_bundle",
        lambda bundle, **_kwargs: {"chapter_number": bundle.chapter_number, "chapter_title": bundle.chapter_title},
    )

    store.regenerate_chapter(2, engine=FakeEngine())


def test_regenerate_without_snapshot_whitelists_stable_state_only(monkeypatch, tmp_path):
    root = tmp_path / "regenerate-conservative-fallback"
    chapter_two_markers = {
        "world": "CHAPTER2_WORLD_FACT",
        "foreshadowing": "CHAPTER2_FORESHADOWING",
        "arc": "CHAPTER2_ARC_RECAP",
        "monster": "CHAPTER2_MONSTER",
        "emotion": "CHAPTER2_EMOTION",
        "goal": "CHAPTER2_GOAL",
    }
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-regenerate-conservative",
            "outline": "A stable book outline.",
            "genre": "fantasy",
            "genre_plugin_ids": ["xuanhuan"],
            "style": "plain",
            "current_chapter": 2,
            "author_constraints": ["Keep the book-level rule."],
            "world_facts": [chapter_two_markers["world"]],
            "foreshadowing": [
                {"text": chapter_two_markers["foreshadowing"], "first_chapter": 2, "status": "open"}
            ],
            "arc_recaps": [
                {"start_chapter": 2, "end_chapter": 2, "recap": chapter_two_markers["arc"]}
            ],
            "monster_profiles": [{"name": chapter_two_markers["monster"]}],
            "progression_ledger": {"chapter_two_complete": True},
            "characters": [
                {
                    "name": "Ari",
                    "role": "protagonist",
                    "current_emotion": chapter_two_markers["emotion"],
                    "goals": [chapter_two_markers["goal"]],
                }
            ],
        },
    )
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "Legacy First",
            "body": _long_test_body("The first chapter establishes a clean baseline."),
        },
    )

    _seed_generation_outline(root, 2)

    class FakeEngine:
        def generate_next_chapter(self, story):
            dumped = json.dumps(story.model_dump(mode="json"), ensure_ascii=False)
            assert story.story_id == "s-regenerate-conservative"
            assert story.outline == "A stable book outline."
            assert story.genre == "fantasy"
            assert story.genre_plugin_ids == ["xuanhuan"]
            assert story.style == "plain"
            assert story.author_constraints == ["Keep the book-level rule."]
            assert "Ari" not in [character.name for character in story.characters]
            for marker in chapter_two_markers.values():
                assert marker not in dumped
            return SimpleNamespace(
                chapter_number=2,
                chapter_title="Conservative Rewrite",
                quality_report={},
                chapter_summary={},
            )

    monkeypatch.setattr(
        store,
        "persist_bundle",
        lambda bundle, **_kwargs: {
            "chapter_number": bundle.chapter_number,
            "chapter_title": bundle.chapter_title,
        },
    )

    store.regenerate_chapter(2, engine=FakeEngine())


def test_regenerate_without_snapshot_uses_static_standard_character_profiles(monkeypatch, tmp_path):
    root = tmp_path / "regenerate-standard-character-profiles"
    store = _make_minimal_file_project(
        root,
        project={
            "project_id": "p-static-profiles",
            "title": "Static Profiles",
            "active_story_id": "s-static-profiles",
            "character_profiles": [
                {
                    "name": "Ari",
                    "role": "protagonist",
                    "character_tier": "lead",
                    "first_appearance": 1,
                    "game_id": "Ember",
                    "identity_profile": {"age": 31, "occupation": "watchmaker"},
                    "background_profile": {"upbringing": "Old mall"},
                    "story_drive": {
                        "immediate_goal": "Keep the shop open",
                        "long_term_goal": "Repair the family relationship",
                    },
                    "performance_profile": {
                        "speech_style": "Reserved, but answers in complete sentences."
                    },
                    "current_emotion": "CHAPTER2_EMOTION",
                    "goals": ["CHAPTER2_GOAL"],
                    "location": "CHAPTER2_LOCATION",
                    "game_state": {"current": {"level": "Lv.9"}},
                    "memory": ["CHAPTER2_MEMORY"],
                }
            ],
            "characters": [{"name": "Legacy Ari", "role": "protagonist"}],
        },
        state={
            "story_id": "s-static-profiles",
            "outline": "Ari starts from the book baseline.",
            "genre": "fantasy",
            "style": "plain",
            "current_chapter": 2,
        },
    )
    store._write_json(
        store.story_system_dir / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "Legacy First",
            "body": _long_test_body("The first chapter establishes the setting."),
        },
    )

    _seed_generation_outline(root, 2)

    class FakeEngine:
        def generate_next_chapter(self, story):
            by_name = {character.name: character for character in story.characters}
            assert "Legacy Ari" not in by_name
            ari = by_name["Ari"]
            assert ari.role == "protagonist"
            assert ari.character_tier == "lead"
            assert ari.first_appearance == 1
            assert ari.game_id == "Ember"
            assert ari.identity_profile.age == 31
            assert ari.identity_profile.occupation == "watchmaker"
            assert ari.background_profile.upbringing == "Old mall"
            assert ari.story_drive.immediate_goal == "Keep the shop open"
            assert ari.story_drive.long_term_goal == "Repair the family relationship"
            assert ari.performance_profile.speech_style == "Reserved, but answers in complete sentences."
            assert ari.current_emotion == "neutral"
            assert ari.goals == ["Keep the shop open", "Repair the family relationship"]
            assert ari.location == ""
            assert ari.game_state == {}
            assert ari.memory == []
            return SimpleNamespace(
                chapter_number=2,
                chapter_title="Static Profile Rewrite",
                quality_report={},
                chapter_summary={},
            )

    monkeypatch.setattr(
        store,
        "persist_bundle",
        lambda bundle, **_kwargs: {
            "chapter_number": bundle.chapter_number,
            "chapter_title": bundle.chapter_title,
        },
    )

    store.regenerate_chapter(2, engine=FakeEngine())


def test_file_project_store_passes_temporary_guidance_to_regeneration(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    store.write_chapter(chapter_number=1, title="Old One", body="Old body kept costs visible.", summary="Old summary.")
    _seed_generation_outline(root, 1)
    guidance = "Use the dissection report: keep exp 30/100 and do not jump to class change."
    seen_guidance: list[dict] = []

    class FakeEngine:
        def generate_next_chapter(self, story):
            temporary = story.progression_ledger["simulation_variant"]["rewrite_guidance"]
            seen_guidance.append(temporary)
            assert temporary["source"] == "book_dissection"
            assert temporary["text"] == guidance
            updated_story = story.model_copy(
                update={
                    "current_chapter": 1,
                    "timeline": [TimelineEvent(chapter_number=1, summary="Guided rewrite completed.", impact="The opening advanced.")],
                    "chapter_summaries": [
                        ChapterSummary(chapter_number=1, chapter_title="Guided One", summary="Guidance shaped the rewrite.")
                    ],
                }
            )
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Guided One",
                body=_long_test_body("Night Ember keeps exp 30/100 visible and stays away from class change."),
                cadence="manual",
                next_outline="Continue the guided path.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Guided One",
                    "cadence": "manual",
                    "summary": "Guidance shaped the rewrite.",
                    "facts": ["guided rewrite"],
                    "next_focus": "Continue the guided path.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "guided",
                },
            )

    regenerated = store.regenerate_chapter(1, engine=FakeEngine(), guidance=guidance)

    assert seen_guidance == [{"source": "book_dissection", "text": guidance}]
    assert regenerated["simulation_variant"]["rewrite_guidance"]["text"] == guidance
    state_after = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert "rewrite_guidance" not in state_after.get("progression_ledger", {}).get("simulation_variant", {})


def test_file_project_store_regenerate_does_not_fail_on_continuity_quality_fields(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    _seed_generation_outline(root, 1)
    store.write_chapter(
        chapter_number=1,
        title="Old One",
        body=_long_test_body("Old draft keeps costs visible."),
        summary="Old summary.",
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Regenerated One",
                body=_long_test_body("Regenerated body keeps structure and continuity."),
                cadence="manual",
                next_outline="Continue from continuity.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Regenerated One",
                    "cadence": "manual",
                    "summary": "Continuity fields are missing in report.",
                    "facts": ["continuity fallback"],
                    "next_focus": "Continue from continuity.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "continuity",
                },
                quality_report={
                    "ok": False,
                    "issues": ["body", "chapter_title", "next_outline", "timeline", "chapter_summaries"],
                    "writing_review": {"pass": False, "issues": ["body", "chapter_title", "next_outline", "timeline", "chapter_summaries"]},
                },
            )

    regenerated = store.regenerate_chapter(1, engine=FakeEngine())

    assert regenerated["schema_version"] == "file-project-regenerate/v1"
    assert isinstance(regenerated["chapter_title"], str) and bool(regenerated["chapter_title"])
    assert regenerated["chapter_number"] == 1


def test_file_project_store_regenerate_replaces_import_placeholder_summary(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded suspense story.",
            "genre": "suspense",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": ["chapter 1 fact: continue", "chapter 1 summary: continue"],
            "continuity_facts": [
                {
                    "text": "continue",
                    "source_chapter": 1,
                    "status": "active",
                    "updated_chapter": 1,
                }
            ],
            "chapter_summaries": [
                {
                    "chapter_number": 1,
                    "chapter_title": "Imported One",
                    "summary": "continue",
                    "facts": ["continue"],
                    "next_focus": "continue",
                }
            ],
            "timeline": [{"chapter_number": 1, "summary": "continue", "impact": "continue"}],
        },
    )
    _seed_generation_outline(root, 1)
    store.write_chapter(
        chapter_number=1,
        title="Imported One",
        body=_long_test_body("The imported draft still carries placeholder memory."),
        summary="continue",
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            body = _long_test_body(
                "Chen Mo verifies that the printer predicted the crash and finds a second warning."
            )
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Death Printer",
                body=body,
                cadence="measured",
                next_outline="continue",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_number": 1,
                    "chapter_title": "Death Printer",
                    "summary": "continue",
                    "facts": ["continue"],
                    "next_focus": "continue",
                    "event_beat": {
                        "turn": "A second warning names the resident from the leak dispute."
                    },
                },
            )

    store.regenerate_chapter(1, engine=FakeEngine())

    chapter = store.chapter(1)
    summary = chapter["chapter_summary"]
    assert summary["summary"] != "continue"
    assert summary["facts"] != ["continue"]
    assert summary["next_focus"] == "A second warning names the resident from the leak dispute."

    state = store.state()
    assert state["chapter_summaries"][-1]["summary"] != "continue"
    assert state["timeline"][-1]["summary"] != "continue"
    assert not any(str(item).endswith(": continue") for item in state["world_facts"])
    assert not any(item.get("text") == "continue" for item in state["continuity_facts"])


def test_file_project_store_blocks_short_generated_bundle(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )
    _seed_generation_outline(root, 1)

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Too Short",
                body="Night Ember only looks around.",
                cadence="manual",
                next_outline="Continue.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Too Short",
                    "cadence": "manual",
                    "summary": "Too short.",
                    "facts": ["too short"],
                    "next_focus": "Continue.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "short",
                },
            )

    with pytest.raises(ValueError, match="generate_length_failed"):
        store.generate_next_chapter(engine=FakeEngine())

    assert not (root / ".story-system" / "chapters" / "0001.json").exists()


def test_file_project_store_saves_short_first_draft_for_human_review(tmp_path):
    root = tmp_path / "novel-human-review"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file-human-review",
            "outline": "A grounded story.",
            "genre": "general",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )
    _seed_generation_outline(root, 1)

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="First Draft",
                body="This is a usable but short first draft.",
                cadence="manual",
                next_outline="Continue.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "First Draft",
                    "cadence": "manual",
                    "summary": "A short first draft.",
                    "facts": ["first draft saved"],
                    "next_focus": "Continue.",
                    "primary_conflict": "choice",
                    "secondary_conflict": "time",
                    "event_beat": "draft",
                },
            )

    result = store.generate_next_chapter(
        engine=FakeEngine(),
        accept_quality_warnings=True,
    )

    assert result["chapter_number"] == 1
    saved = store.chapter(1)
    assert saved["body"] == "This is a usable but short first draft."
    assert saved["quality_report"]["manual_quality_override"] is True


def test_file_project_store_expands_short_chapter_as_candidate(tmp_path):
    root = tmp_path / "manual-expand"
    store = _make_minimal_file_project(
        root,
        project={"project_id": "p-manual-expand", "title": "Manual Expand"},
        state={
            "story_id": "s-manual-expand",
            "outline": "A grounded story.",
            "genre": "general",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": ["The repair shop is still open."],
        },
    )
    _seed_generation_outline(root, 1)
    source_body = "The customer waits beside the counter. " * 30
    store.write_chapter(
        chapter_number=1,
        title="Short Chapter",
        body=source_body,
        summary="The customer waits.",
    )
    expanded_body = "The customer and Chen Mo work through the repair in full. " * 85

    class FakeOrchestrator:
        def __init__(self):
            self.calls = []

        def _timed_chat(self, story, prompt, **kwargs):
            self.calls.append({"story": story, "prompt": prompt, "kwargs": kwargs})
            return expanded_body, ""

    orchestrator = FakeOrchestrator()
    result = store.expand_chapter(1, orchestrator=orchestrator)

    assert len(orchestrator.calls) == 1
    assert source_body.strip() in orchestrator.calls[0]["prompt"]
    assert result["schema_version"] == "file-project-candidate/v1"
    assert result["candidate"]["operation"] == "regenerate"
    assert result["candidate"]["body"] == expanded_body
    assert store.chapter(1)["body"] == source_body


def test_file_project_store_expands_full_length_chapter_as_candidate(tmp_path):
    root = tmp_path / "manual-expand-full"
    store = _make_minimal_file_project(
        root,
        project={"project_id": "p-manual-expand-full", "title": "Manual Expand Full"},
        state={
            "story_id": "s-manual-expand-full",
            "outline": "A grounded story.",
            "genre": "general",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    _seed_generation_outline(root, 1)
    store.write_chapter(
        chapter_number=1,
        title="Full Chapter",
        body="甲" * 3800,
        summary="Already full length.",
    )

    expanded_body = "乙" * 4400

    class FakeOrchestrator:
        def _timed_chat(self, *_args, **_kwargs):
            return expanded_body, ""

    result = store.expand_chapter(1, orchestrator=FakeOrchestrator())

    assert result["candidate"]["body"] == expanded_body
    assert store.chapter(1)["body"] == "甲" * 3800


@pytest.mark.parametrize(
    ("model_body", "expected_error"),
    [
        ("", "chapter_expansion_failed:empty_body"),
        ("原文。" * 100, "chapter_expansion_failed:invalid_length"),
        ("超长。" * 2000, "chapter_expansion_failed:invalid_length"),
    ],
    ids=["empty", "not-longer", "too-long"],
)
def test_file_project_store_rejects_invalid_manual_expansion_output(
    tmp_path,
    model_body,
    expected_error,
):
    root = tmp_path / f"manual-expand-invalid-{len(model_body)}"
    store = _make_minimal_file_project(
        root,
        project={"project_id": "p-manual-expand-invalid", "title": "Manual Expand Invalid"},
        state={
            "story_id": "s-manual-expand-invalid",
            "outline": "A grounded story.",
            "genre": "general",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    _seed_generation_outline(root, 1)
    store.write_chapter(
        chapter_number=1,
        title="Short Chapter",
        body="原文。" * 100,
        summary="Short.",
    )

    class FakeOrchestrator:
        def _timed_chat(self, *_args, **_kwargs):
            return model_body, ""

    with pytest.raises(ValueError, match=expected_error):
        store.expand_chapter(1, orchestrator=FakeOrchestrator())


def test_file_project_store_blocks_failed_generated_quality_report(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )
    _seed_generation_outline(root, 1)

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Bad Trade",
                body=_long_test_body("Night Ember keeps the body long enough but closes the trade too early."),
                cadence="manual",
                next_outline="Continue.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Bad Trade",
                    "cadence": "manual",
                    "summary": "Quality should block this generated chapter.",
                    "facts": ["bad trade closure"],
                    "next_focus": "Continue.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "blocked",
                },
                quality_report={
                    "ok": False,
                    "issues": ["writing_review"],
                    "writing_review": {
                        "pass": False,
                        "issues": ["第一章提前展开交易闭环：出现寄售、上架、成交、到账、手续费或提现。"],
                    },
                },
            )

    with pytest.raises(ValueError, match="generate_quality_failed"):
        store.generate_next_chapter(engine=FakeEngine())

    assert not (root / ".story-system" / "chapters" / "0001.json").exists()


def test_file_project_store_persists_generated_chapter_with_unpassed_advisory_review(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )
    _seed_generation_outline(root, 1)

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Usable Draft",
                body=_long_test_body("The chapter is complete but the dialogue can still be polished."),
                cadence="manual",
                next_outline="Continue.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Usable Draft",
                    "cadence": "manual",
                    "summary": "The usable draft advances the story.",
                    "facts": ["the chapter advanced"],
                    "next_focus": "Continue.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "advanced",
                },
                quality_report={
                    "ok": False,
                    "issues": ["writing_review"],
                    "writing_review": {
                        "pass": False,
                        "issues": ["现代中文对话不够自然，建议局部修改。"],
                    },
                    "simplified_review": {
                        "status": "needs_revision",
                        "pass": True,
                        "has_hard_errors": False,
                        "needs_revision": True,
                    },
                },
            )

    generated = store.generate_next_chapter(engine=FakeEngine())

    assert generated["chapter_number"] == 1
    assert (root / ".story-system" / "chapters" / "0001.json").exists()
    assert not list((root / ".story-system" / "failed-drafts").glob("*-generate-ch1.json"))


def test_file_project_store_preserves_rejected_regeneration_as_failed_draft(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    _seed_generation_outline(root, 1)
    store.write_chapter(chapter_number=1, title="Old One", body="Old accepted body.", summary="Old summary.")

    class FakeEngine:
        def generate_next_chapter(self, story):
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Rejected One",
                body=_long_test_body("The panel and required scene facts are still missing."),
                cadence="manual",
                next_outline="Continue.",
                updated_story=story.model_copy(update={"current_chapter": 1}),
                chapter_summary={
                    "chapter_title": "Rejected One",
                    "cadence": "manual",
                    "summary": "This draft did not pass review.",
                    "facts": [],
                    "next_focus": "Continue.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "attempted",
                },
                quality_report={
                    "ok": False,
                    "issues": ["writing_review"],
                    "writing_review": {"pass": False, "issues": ["第一章缺少带身份栏的角色面板。"]},
                    "simplified_review": {"has_hard_errors": True, "needs_revision": True},
                },
            )

    with pytest.raises(ChapterQualityError):
        store.regenerate_chapter(1, engine=FakeEngine())

    assert list((root / ".story-system" / "failed-drafts").glob("*-regenerate-ch1.json"))
    saved = store.chapter(1)
    assert saved["chapter_title"] == "Old One"


def test_persist_bundle_quality_failure_raises_chapter_quality_error_with_report(tmp_path):
    from packages.story_core.file_project_store import ChapterQualityError

    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": []},
    )
    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Fresh Chapter",
        body=_long_test_body(),
        cadence="manual",
        next_outline="Continue.",
        updated_story={"story_id": "s-file", "current_chapter": 1},
        chapter_summary={
            "chapter_title": "Fresh Chapter",
            "cadence": "manual",
            "summary": "Fresh summary.",
            "facts": ["fresh fact"],
            "next_focus": "Continue.",
            "primary_conflict": "Clean state.",
            "secondary_conflict": "Old snapshot.",
            "event_beat": "Persist.",
        },
    )

    with pytest.raises(ChapterQualityError, match="generate_quality_failed") as exc_info:
        store.persist_bundle(bundle)

    assert exc_info.value.operation == "generate"
    assert exc_info.value.quality_report.get("ok") is False



def test_file_project_store_generate_bundle_with_empty_failure_body_reports_generate_failed_reason(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )

    bundle = _failed_bundle(
        StoryState(
            story_id="s-file",
            outline="A grounded game story.",
            genre="webgame",
            style="plain",
            current_chapter=0,
            world_facts=[],
        ),
        1,
        "plan_timeout",
    )

    with pytest.raises(ValueError, match="generate_failed:plan_timeout"):
        store.persist_bundle(bundle, operation="generate")


def test_file_project_store_generate_bundle_with_empty_body_reports_generate_failed(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )

    bundle = {
        "chapter_number": 1,
        "chapter_title": "第一章",
        "body": "",
        "quality_report": {
            "ok": False,
            "issues": ["body", "cadence", "next_outline", "timeline", "chapter_summaries"],
            "writing_review": {
                "pass": False,
                "issues": ["body", "cadence", "next_outline", "timeline", "chapter_summaries"],
            },
        },
    }

    with pytest.raises(ValueError, match="generate_failed:body"):
        store.persist_bundle(bundle, operation="generate")


def test_file_project_store_regenerate_bundle_with_empty_body_reports_regenerate_failed(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )

    bundle = {
        "chapter_number": 1,
        "chapter_title": "第一章",
        "body": "",
        "quality_report": {
            "ok": False,
            "issues": ["body", "timeline", "chapter_summaries"],
            "writing_review": {"pass": False, "issues": ["body", "timeline", "chapter_summaries"]},
        },
    }

    with pytest.raises(ValueError, match="regenerate_failed:body"):
        store.persist_bundle(bundle, operation="regenerate")


def test_file_project_store_normalizes_generated_chapter_title_prefix(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 0,
            "world_facts": [],
        },
    )
    _seed_generation_outline(root, 1)

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="第1章 夜烬",
                body=_long_test_body("Night Ember keeps the body long enough and clean."),
                cadence="manual",
                next_outline="Continue.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "第1章 夜烬",
                    "cadence": "manual",
                    "summary": "Title should be normalized.",
                    "facts": ["title normalized"],
                    "next_focus": "Continue.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "title",
                },
                quality_report={
                    "ok": True,
                    "issues": [],
                    "writing_review": {"pass": True, "issues": []},
                },
            )

    generated = store.generate_next_chapter(engine=FakeEngine())

    assert generated["chapter_title"] == "夜烬"
    assert (root / "chapters" / "0001-夜烬.md").exists()


def test_file_project_store_reads_exported_layout(tmp_path):
    root = tmp_path / "novel"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)

    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {"project_id": "p-test", "title": "测试书", "active_story_id": "s-test"},
                "active_story_id": "s-test",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-test", "title": "测试书", "active_story_id": "s-test"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-test",
                "genre": "网游",
                "style": "升级流",
                "current_chapter": 1,
                "author_constraints": ["不要写后台判断"],
                "world_facts": ["洛婶在药剂铺"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "第一章 灰烬村",
        "body": "夜烬走进药剂铺，洛婶抬头看了他一眼。",
        "chapter_summary": {"summary": "夜烬见到洛婶。"},
        "event_plan": {"next_focus": "补齐毒腺"},
        "quality_report": {"writing_review": {"pass": True, "issues": []}},
    }
    (root / ".story-system" / "chapters" / "0001.json").write_text(
        json.dumps(chapter, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".story-system" / "reviews" / "0001.json").write_text(
        json.dumps({"writing_review": {"pass": True, "issues": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "chapters" / "0001-第一章.md").write_text(chapter["body"], encoding="utf-8")

    store = FileProjectStore(root)

    assert store.exists()
    assert store.summary()["chapter_count"] == 1
    assert store.review(1)["writing_review"]["pass"] is True
    assert store.query("洛婶")["result_count"] > 0
    packet = store.writing_packet(2)
    assert packet["target_chapter"] == 2
    assert packet["latest_chapter_number"] == 1
    assert packet["prose_renderer"]["skill"] == "chinese-novelist"
    assert packet["prose_renderer"]["role"] == "prose_renderer_only"
    assert packet["title_contract"]["style"] == "tomato_concrete_short_title"
    assert any("句子要完整" in rule for rule in packet["style_rules"])
    assert all("番茄爆款网文" not in rule for rule in packet["style_rules"])
    assert packet["recent_chapters"][0]["next_focus"] == "补齐毒腺"
