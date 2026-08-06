from __future__ import annotations

import inspect
import json
import logging
import os
import re
import stat
import tempfile
import threading
import uuid
import ctypes
from ctypes import wintypes
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import quote
from pydantic import ValidationError

_MISSING = object()


if os.name == "nt":
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _KERNEL32.CreateFileW.restype = wintypes.HANDLE
    _KERNEL32.GetFileAttributesW.argtypes = (wintypes.LPCWSTR,)
    _KERNEL32.GetFileAttributesW.restype = wintypes.DWORD
    _KERNEL32.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _KERNEL32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.GetFileSizeEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
    _KERNEL32.GetFileSizeEx.restype = wintypes.BOOL
    _KERNEL32.ReadFile.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
    _KERNEL32.ReadFile.restype = wintypes.BOOL
else:
    _KERNEL32 = None

from packages.story_core.attribute_allocation import (
    normalize_attribute_allocation_rule,
    rebuild_attribute_progression,
)
from packages.story_core.chapter_continuity import build_continuity_interface
from packages.story_core.chapter_direction import build_chapter_direction_options
from packages.story_core.web_game_economy import (
    normalize_legacy_economy_prompt_value,
)
from packages.story_core.character_portraits import complete_character_portrait as complete_portrait
from packages.story_core.cover_renderer import CoverRenderError, normalize_cover_title
from packages.story_core.character_profiles import (
    filter_character_cards,
    is_non_character_card,
    merge_character_alias_cards,
    merge_character_profile,
    normalize_character_profile,
    normalize_speech_style_for_writing,
    remove_cross_character_aliases,
)
from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.book_style import normalize_book_style
from packages.story_core.cold_reader_review import review_cold_reader_experience
from packages.story_core.editor_agent import review_editor_agent
from packages.story_core.equipment_cards import (
    equipment_cards_for_context,
    merge_equipment_cards,
    normalize_equipment_cards,
)
from packages.story_core.elastic_outline import outline_window_status, validate_outline_for_project
from packages.story_core.dual_state import (
    merge_state_change,
    normalize_character_state,
    project_character_for_scene,
    scene_kind_for_cards,
)
from packages.story_core.foreshadowing import (
    canonicalize_foreshadowing_ledger,
    normalize_foreshadowing_text,
    reconcile_foreshadowing,
    select_unresolved_foreshadowing,
)
from packages.story_core.models import CharacterState, ForeshadowingState, StoryState
from packages.story_core.novel_type_catalog import (
    is_game_story_type,
    normalize_novel_type_ids,
    novel_type_prompt_context,
    novel_type_id_from_metadata_fact,
    resolve_novel_type_id,
    runtime_novel_type,
)
from packages.story_core.opening_directions import (
    GeneratedOpeningDirectionSet,
    OpeningBrief,
    OpeningDirectionSet,
    validate_opening_direction_set_primary_tropes,
)
from packages.story_core.outline_planning import (
    GeneratedOutlinePlan,
    INITIAL_OUTLINE_CHAPTER_COUNT,
    validate_generated_continuation_plan,
    validate_generated_opening_plan,
    validate_generated_trope_selection,
)
from packages.story_core.outline_planning_generation import OutlinePlanningBrief
from packages.story_core.outline_generation_checkpoints import OutlineCheckpointStore
from packages.story_core.candidate_draft import CandidateDraft
from packages.story_core.generation_progress import report_generation_progress
from packages.story_core.pipeline.chapter_pipeline import build_chapter_pipeline_event
from packages.story_core.persistence.candidate_store import CandidateStore
from packages.story_core.persistence.chapter_store import ChapterStore
from packages.story_core.persistence.snapshot_store import SnapshotStore
from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.prompt_templates import (
    PromptTemplate,
    get_global_prompt_template,
    list_default_prompt_templates,
    prompt_template_applicability,
    prompt_template_scope,
    validate_prompt_template,
)
from packages.story_core.prompt_call_log import PromptCallLog, prompt_call_recording
from packages.story_core.project_outline import (
    normalize_outline_for_story_type,
    normalize_project_outline,
    outline_from_legacy_project,
    select_outline_context,
)
from packages.story_core.reader_feel_review import review_reader_feel
from packages.story_core.story_core_card import (
    StoryCoreCard,
    outline_seed_from_story_core,
    merge_story_core_into_overall,
    story_core_from_direction,
    story_core_from_overall,
    story_core_projection,
)
from packages.story_core.relationship_graph import (
    apply_relationship_updates,
    graph_from_character_cards,
    merge_relationship_graph,
    normalize_relationship_graph,
    select_relationship_subgraph,
)
from packages.story_core.quality import validate_bundle
from packages.story_core.reader_agent import review_reader_agent
from packages.story_core.reviewer_agent import review_reviewer_agent
from packages.story_core.simplified_review import build_simplified_review
from packages.story_core.workflow_telemetry import append_workflow_telemetry
from packages.story_core.writing_learning import learning_snapshot, lessons_from_quality_report, merge_writing_lessons
from packages.story_core.writing_packet import power_system_context_for_state, prose_renderer_contract
from packages.story_core.skill_packs import (
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
    skill_pack_prompt_context,
)
from packages.story_core.writing_taskbook import format_taskbook_brief_section
from packages.story_core.world_blueprint_context import (
    merge_world_blueprint,
    select_world_context,
    sync_world_markdown,
)


_PROJECT_UPDATE_LOCKS: dict[str, threading.RLock] = {}
_PROJECT_UPDATE_LOCKS_GUARD = threading.Lock()
_PROGRESSION_GOVERNANCE_CHINESE_MARKERS = (
    "必须",
    "不得",
    "不能",
    "每章",
    "至少",
    "前十章",
    "只",
    "只能",
    "仅",
    "一律",
    "禁止",
    "严禁",
    "务必",
)
_PROGRESSION_GOVERNANCE_ENGLISH_MARKERS = (
    "must",
    "shall",
    "never",
    "cannot",
    "only",
    "every chapter",
    "at least",
    "required",
)


def _project_update_lock(root: Path) -> threading.RLock:
    key = os.path.normcase(str(root.resolve()))
    with _PROJECT_UPDATE_LOCKS_GUARD:
        return _PROJECT_UPDATE_LOCKS.setdefault(key, threading.RLock())


def _is_progression_governance_rule(rule: str) -> bool:
    if any(marker in rule for marker in _PROGRESSION_GOVERNANCE_CHINESE_MARKERS):
        return True
    folded = rule.casefold()
    return any(
        re.search(rf"\b{re.escape(marker)}\b", folded)
        for marker in _PROGRESSION_GOVERNANCE_ENGLISH_MARKERS
    )


def _progression_governance_hard_locks(
    progression_rules: Any,
    scoped_progression_rules: Any,
) -> list[str]:
    if not isinstance(progression_rules, list):
        return []

    scoped = {
        str(rule).strip()
        for rule in (
            scoped_progression_rules
            if isinstance(scoped_progression_rules, list)
            else []
        )
        if isinstance(rule, str) and rule.strip()
    }
    selected: list[str] = []
    for value in progression_rules:
        if not isinstance(value, str):
            continue
        rule = value.strip()
        if (
            not rule
            or rule in scoped
            or rule in selected
            or not _is_progression_governance_rule(rule)
        ):
            continue
        selected.append(rule)
    return selected


def _select_relevant_monster_profiles(
    monster_profiles: Any,
    relevance_text: str,
    *,
    max_profiles: int = 6,
) -> list[dict[str, Any]]:
    if not isinstance(monster_profiles, list):
        return []

    relevance = str(relevance_text or "").casefold()
    selected: list[dict[str, Any]] = []
    for profile in monster_profiles:
        if not isinstance(profile, dict):
            continue
        identifiers = (
            str(profile.get(field) or "").strip().casefold()
            for field in ("name", "title")
        )
        if any(identifier and identifier in relevance for identifier in identifiers):
            selected.append(deepcopy(profile))
        if len(selected) >= max_profiles:
            break
    return selected


def _with_project_update_lock(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with _project_update_lock(self.root):
            return method(self, *args, **kwargs)

    return locked


def _state_namespace_has_content(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    current = value.get("current")
    if isinstance(current, dict) and any(item not in (None, "", [], {}) for item in current.values()):
        return True
    recent_changes = value.get("recent_changes")
    return isinstance(recent_changes, list) and bool(recent_changes)


def _normalize_character_persistence_card(
    card: dict[str, Any],
    *,
    is_game_story: bool,
) -> dict[str, Any]:
    normalized = normalize_character_state(card, is_game_story=is_game_story)
    performance = normalized.get("performance_profile")
    if isinstance(performance, dict):
        performance = dict(performance)
        performance["speech_style"] = normalize_speech_style_for_writing(
            performance.get("speech_style")
        )
        if performance.get("speech_style") == "白话、完整、少装腔；解释选择时把原因说清。":
            performance["speech_style"] = "白话、完整、少装腔；只说当下会说的话，理由藏在语气、动作和必要回答里。"
        normalized["performance_profile"] = performance
    if is_game_story:
        current = normalized.get("game_state", {}).get("current") if isinstance(normalized.get("game_state"), dict) else None
        if isinstance(current, dict):
            panel = dict(normalized.get("game_panel") or {})
            for field in (
                "game_id",
                "level",
                "class_path",
                "exp",
                "hp",
                "mp",
                "attributes",
                "skills",
                "equipment",
                "inventory",
                "currency",
                "quests",
                "risk",
            ):
                value = current.get(field)
                if value not in (None, "", [], {}):
                    panel[field] = value
            normalized["game_panel"] = panel
    for state_name in ("current_state", "real_state", "game_state"):
        if not _state_namespace_has_content(normalized.get(state_name)):
            normalized.pop(state_name, None)
    return normalized


_GAME_STATE_FIELDS = (
    "game_id",
    "level",
    "class_path",
    "exp",
    "hp",
    "mp",
    "attributes",
    "skills",
    "equipment",
    "inventory",
    "currency",
    "quests",
    "risk",
    "backpack",
)


def _sync_game_panel_from_state(card: dict[str, Any]) -> dict[str, Any]:
    """Mirror structured game state into the legacy panel."""

    panel = dict(card.get("game_panel") or {})
    state = dict(card.get("game_state") or {})
    current = dict(state.get("current") or {}) if isinstance(state.get("current"), dict) else {}
    for field in _GAME_STATE_FIELDS:
        value = current.get(field)
        if value not in (None, "", [], {}):
            panel[field] = deepcopy(value)
    card["game_panel"] = panel
    return card


def _sync_game_state_mirror(card: dict[str, Any]) -> dict[str, Any]:
    """Materialize game state from a legacy panel without touching reality."""

    panel = dict(card.get("game_panel") or {})
    state = dict(card.get("game_state") or {})
    current = dict(state.get("current") or {}) if isinstance(state.get("current"), dict) else {}
    for field in _GAME_STATE_FIELDS:
        value = panel.get(field)
        if value not in (None, "", [], {}):
            current.setdefault(field, deepcopy(value))
    state["current"] = current
    state.setdefault("recent_changes", [])
    card["game_state"] = state
    return card


SOFT_REGENERATION_ISSUE_MARKERS = (
    "正文带出后台硬词",
    "战斗写成攻略说明",
    "比喻配额超标",
    "AI味",
    "段首主语单调",
    "段落形态",
    "推演事件未被正文场景化",
    "场景卡必写内容缺失",
    "Scene contract not consumed",
    "命名NPC出场缺少完整设定",
)

_REGENERATION_CONTINUITY_QUALITY_ISSUES: tuple[str, ...] = (
    "body",
    "chapter_title",
    "cadence",
    "next_outline",
    "timeline",
    "chapter_summaries",
    "chapter_title_summary",
    "cadence_summary",
    "summary",
)

FILE_CHAPTER_MIN_CHARS = 3800
FILE_CHAPTER_TARGET_MIN_CHARS = 4200
FILE_CHAPTER_MAX_CHARS = 5500
FILE_CHAPTER_HARD_MAX_CHARS = FILE_CHAPTER_MAX_CHARS + 200
NON_BLOCKING_QUALITY_ISSUES = {"body_too_long"}


def _blocking_quality_issues(quality_report: dict[str, Any]) -> list[str]:
    return [
        issue
        for raw_issue in (quality_report.get("issues") or [])
        if (issue := str(raw_issue).strip())
        and issue != "writing_review"
        and issue not in NON_BLOCKING_QUALITY_ISSUES
    ]


def _without_monster_stat_surfaces(text: str) -> str:
    text = re.sub(
        r"(?:系统(?:弹出)?(?:怪物)?信息|怪物信息)\s*[：:][^。！？\n]*[。！？]?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    monster_panel = re.compile(
        r"【[^】]+】(?:\s*【(?:等级|生命|攻击方式|技能|特性)[^】]*】){2,}",
        flags=re.IGNORECASE,
    )
    text = monster_panel.sub(lambda match: "" if "攻击方式" in match.group(0) else match.group(0), text)
    compact_monster_panel = re.compile(
        r"【(?=[^】]*(?:等级|Lv\.?))(?=[^】]*生命)(?=[^】]*攻击方式)[^】]+】",
        flags=re.IGNORECASE,
    )
    return compact_monster_panel.sub("", text)


def _chapter_length_review(body: str) -> dict[str, Any]:
    body_chars = len("".join(str(body or "").split()))
    issues: list[str] = []
    if body_chars < FILE_CHAPTER_MIN_CHARS:
        issues.append(f"章节字数偏少：当前约{body_chars}字，最低要求{FILE_CHAPTER_MIN_CHARS}字。")
    elif body_chars > FILE_CHAPTER_HARD_MAX_CHARS:
        issues.append(f"章节字数超标：当前约{body_chars}字，建议不超过{FILE_CHAPTER_MAX_CHARS}字。")
    return {
        "pass": not issues,
        "body_chars": body_chars,
        "min_chars": FILE_CHAPTER_MIN_CHARS,
        "max_chars": FILE_CHAPTER_MAX_CHARS,
        "issues": issues,
    }


def _assert_auto_chapter_length(body: str, *, operation: str) -> None:
    """Reject generated chapters that cannot satisfy the file-project length gate."""

    length_review = _chapter_length_review(body)
    if length_review.get("pass", True):
        return
    body_chars = int(length_review.get("body_chars") or 0)
    min_chars = int(length_review.get("min_chars") or FILE_CHAPTER_MIN_CHARS)
    if body_chars < min_chars:
        issue = "; ".join(str(item) for item in length_review.get("issues", []) if str(item).strip())
        raise ValueError(f"{operation}_length_failed:{issue or f'body_chars {body_chars} < {min_chars}'}")


def _is_regeneration_continuity_failure(
    quality_report: dict[str, Any],
    writing_review: dict[str, Any] | None,
) -> bool:
    quality_issues = [str(item).strip() for item in (quality_report.get("issues") or []) if str(item).strip()]
    if not quality_issues:
        return False
    if any(issue not in _REGENERATION_CONTINUITY_QUALITY_ISSUES for issue in quality_issues):
        return False
    return True

def _regeneration_quality_blocking(quality_report: dict[str, Any], writing_review: dict[str, Any] | None) -> bool:
    if not writing_review:
        return True
    combined_report = {**quality_report, "writing_review": writing_review}
    simplified = build_simplified_review(combined_report)
    if simplified.get("has_hard_errors"):
        return True
    return bool(_blocking_quality_issues(quality_report))


def _promote_downstream_rewrite_status(quality_report: dict[str, Any]) -> None:
    writing_review = (
        quality_report.get("writing_review")
        if isinstance(quality_report.get("writing_review"), dict)
        else {}
    )
    required = bool(writing_review.get("downstream_rewrite_required"))
    quality_report["downstream_rewrite_required"] = required
    if required and writing_review.get("downstream_chapter_number"):
        quality_report["downstream_chapter_number"] = writing_review["downstream_chapter_number"]
    else:
        quality_report.pop("downstream_chapter_number", None)


class ChapterQualityError(ValueError):
    """Quality gate rejection carrying the full quality report for user-facing formatting."""

    def __init__(
        self,
        message: str,
        *,
        quality_report: dict[str, Any] | None = None,
        operation: str = "",
    ) -> None:
        super().__init__(message)
        self.quality_report = quality_report if isinstance(quality_report, dict) else {}
        self.operation = operation


def _assert_auto_chapter_quality(
    quality_report: dict[str, Any],
    *,
    operation: str,
) -> None:
    if operation not in {"generate", "regenerate"}:
        return
    if operation == "regenerate" and bool(quality_report.get("regeneration_degraded")):
        return
    if not isinstance(quality_report, dict) or quality_report.get("ok") is not False:
        return
    writing_review = quality_report.get("writing_review") if isinstance(quality_report.get("writing_review"), dict) else None
    review_result = quality_report.get("review_result")
    if isinstance(review_result, dict) and review_result.get("schema_version") == "review-result/v2":
        review_status = str(review_result.get("status") or "")
        if review_status in {"warning", "passed"}:
            quality_report["quality_warning"] = {
                "status": review_status,
                "needs_revision": bool(review_result.get("needs_revision")),
                "summary": "正文已保存，仍有局部修改建议。" if review_status == "warning" else "正文已通过硬门禁和软审稿。",
            }
            return
        if review_status == "blocked":
            issues = list(quality_report.get("issues") or [])
            if isinstance(writing_review, dict):
                issues.extend(writing_review.get("issues") or [])
            issue_text = "; ".join(str(item) for item in issues[:6] if str(item).strip())
            raise ChapterQualityError(
                f"{operation}_quality_failed:{issue_text or 'review_result_blocked'}",
                quality_report=quality_report,
                operation=operation,
            )
    # Fall back to legacy simplified-review semantics for historical data.
    simplified_review = (
        quality_report.get("simplified_review")
        if isinstance(quality_report.get("simplified_review"), dict)
        else build_simplified_review({**quality_report, "writing_review": writing_review or {}})
    )
    structural_issues = _blocking_quality_issues(quality_report)
    if simplified_review and not bool(simplified_review.get("has_hard_errors")) and not structural_issues:
        quality_report["quality_warning"] = {
            "status": str(simplified_review.get("status") or "needs_revision"),
            "needs_revision": bool(simplified_review.get("needs_revision")),
            "summary": str(simplified_review.get("summary") or "正文已保存，仍有局部修改建议。"),
        }
        return
    if operation == "regenerate" and _is_regeneration_continuity_failure(quality_report, writing_review):
        quality_report["regeneration_degraded"] = True
        return
    issues = list(quality_report.get("issues") or [])
    if isinstance(writing_review, dict):
        issues.extend(writing_review.get("issues") or [])
    issue_text = "; ".join(str(item) for item in issues[:6] if str(item).strip())
    if _regeneration_quality_blocking(quality_report, writing_review):
        raise ChapterQualityError(
            f"{operation}_quality_failed:{issue_text or 'quality_report_not_ok'}",
            quality_report=quality_report,
            operation=operation,
        )


def _bundle_generation_failure_reason(quality_report: Any) -> str:
    if not isinstance(quality_report, dict):
        return ""
    for key in ("degradation_reason", "failure_reason"):
        reason = str(quality_report.get(key) or "").strip()
        if reason:
            return reason
    return ""


def _normalize_chapter_title(title: str, chapter_number: int) -> str:
    cleaned = str(title or "").strip()
    cleaned = re.sub(rf"^\s*第\s*{chapter_number}\s*章[：:\s、.-]*", "", cleaned).strip()
    cleaned = re.sub(r"^\s*第\s*[零一二三四五六七八九十百千万]+\s*章[：:\s、.-]*", "", cleaned).strip()
    return cleaned or str(title or "").strip() or f"Chapter {chapter_number}"


def _chapter_outline_title(outline_context: Any, chapter_number: int) -> str | None:
    if not isinstance(outline_context, dict):
        return None
    chapter = outline_context.get("chapter")
    if not isinstance(chapter, dict):
        return None
    try:
        planned_number = int(chapter.get("chapter_number") or 0)
    except (TypeError, ValueError):
        return None
    title = str(chapter.get("title") or "").strip()
    return title if planned_number == chapter_number and title else None


def _manual_chapter_quality_report(
    chapter: dict[str, Any],
    *,
    genre_context: Any = None,
) -> dict[str, Any]:
    quality_report = validate_bundle(chapter)
    body = str(chapter.get("body") or "")
    length_review = _chapter_length_review(body)
    ai_flavor_review = review_ai_flavor(body)
    reader_feel_review = review_reader_feel(body)
    prose_style_review = review_prose_style(body, genre_context=genre_context)
    cold_reader_review = review_cold_reader_experience(
        body,
        previous_summary=str((chapter.get("event_plan") or {}).get("summary") or ""),
        genre_context=genre_context,
    )
    reader_agent_review = review_reader_agent(
        body,
        previous_summary=str((chapter.get("event_plan") or {}).get("summary") or ""),
        cold_reader_review=cold_reader_review,
    )
    editor_agent_review = review_editor_agent(
        body,
        genre_context=genre_context,
        prose_style_review=prose_style_review,
        ai_flavor_review=ai_flavor_review,
    )
    reviewer_agent_review = review_reviewer_agent(
        chapter_number=int(chapter.get("chapter_number") or 0),
        body=body,
        event_plan=chapter.get("event_plan") if isinstance(chapter.get("event_plan"), dict) else {},
        world_facts=[],
    )

    issues = [str(item) for item in quality_report.get("issues", []) if str(item).strip()]
    for issue in length_review.get("issues", []):
        text = str(issue).strip()
        if text and text not in issues:
            issues.append(text)
    quality_metrics = quality_report.setdefault("metrics", {})
    if isinstance(quality_metrics, dict):
        quality_metrics["body_chars"] = length_review["body_chars"]
        quality_metrics["target_min_chars"] = length_review["min_chars"]
        quality_metrics["target_max_chars"] = length_review["max_chars"]
        quality_metrics["target_range"] = f'{length_review["min_chars"]}-{length_review["max_chars"]}字'
    scores: dict[str, Any] = {}
    for prefix, report in (
        ("ai_flavor", ai_flavor_review),
        ("reader_feel", reader_feel_review),
        ("prose_style", prose_style_review),
        ("cold_reader", cold_reader_review),
    ):
        for key, score in (report.get("scores") or {}).items():
            scores[f"{prefix}_{key}"] = score
        for issue in report.get("issues", []):
            reason = issue.get("reason") if isinstance(issue, dict) else str(issue)
            if reason and reason not in issues:
                issues.append(reason)
    for agent_review in (reader_agent_review, editor_agent_review, reviewer_agent_review):
        for issue in agent_review.get("issues", []):
            text = str(issue).strip()
            if text and text not in issues:
                issues.append(text)

    pass_review = (
        bool(quality_report.get("ok"))
        and bool(length_review.get("pass", True))
        and bool(ai_flavor_review.get("pass", True))
        and bool(reader_feel_review.get("pass", True))
        and bool(prose_style_review.get("pass", True))
        and bool(cold_reader_review.get("pass", True))
        and bool(reader_agent_review.get("pass", True))
        and bool(editor_agent_review.get("pass", True))
        and bool(reviewer_agent_review.get("pass", True))
    )
    writing_review = {
        "pass": pass_review,
        "issues": issues,
        "scores": scores,
        "length_review": length_review,
        "ai_flavor_review": ai_flavor_review,
        "reader_feel_review": reader_feel_review,
        "prose_style_review": prose_style_review,
        "cold_reader_review": cold_reader_review,
        "reader_agent_review": reader_agent_review,
        "editor_agent_review": editor_agent_review,
        "reviewer_agent_review": reviewer_agent_review,
        "revision_plan": _merge_revision_plans(
            ai_flavor_review.get("revision_plan", []),
            reader_feel_review.get("revision_plan", []),
            prose_style_review.get("revision_plan", []),
            cold_reader_review.get("revision_plan", []),
            reader_agent_review.get("revision_plan", []),
            editor_agent_review.get("revision_plan", []),
            reviewer_agent_review.get("revision_plan", []),
        ),
    }
    report = {
        "schema_version": "file-writing-review/v2",
        "writing_review": writing_review,
        "quality_report": quality_report,
        "length_review": length_review,
        "ai_flavor_review": ai_flavor_review,
        "reader_feel_review": reader_feel_review,
        "prose_style_review": prose_style_review,
        "cold_reader_review": cold_reader_review,
        "reader_agent_review": reader_agent_review,
        "editor_agent_review": editor_agent_review,
        "reviewer_agent_review": reviewer_agent_review,
    }
    if not pass_review:
        quality_report["ok"] = False
        quality_report["issues"] = issues
        report["ok"] = False
        report["issues"] = issues
    else:
        report["ok"] = bool(quality_report.get("ok"))
        report["issues"] = issues
    report["simplified_review"] = build_simplified_review(report)
    return report


def _merge_revision_plans(*plans: Any) -> list[str]:
    merged: list[str] = []
    for plan in plans:
        for item in plan or []:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def _project_legacy_review(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure a v1 review payload also exposes the canonical v2 fields.

    Persisted historical chapter data was saved before the v2 schema
    existed. Callers that always expect ``review_result`` and
    ``simplified_review`` keys get them computed on demand without
    mutating the underlying persisted file.
    """
    if not isinstance(payload, dict):
        return payload
    projected = dict(payload)
    explicit = projected.get("review_result")
    if isinstance(explicit, dict) and explicit.get("schema_version") == "review-result/v2":
        projected.setdefault("simplified_review", explicit)
        return projected
    fallback = build_simplified_review(projected)
    if isinstance(fallback, dict):
        projected["simplified_review"] = fallback
        projected.setdefault("review_result", fallback)
        projected["ok"] = projected.get("ok", fallback.get("pass", True))
    return projected


class _PinnedPublishingFilesystem:
    """Pin publishing directories for one transaction.

    POSIX operations use the pinned directory descriptors directly (openat /
    renameat semantics).  Windows keeps every ancestor open without
    ``FILE_SHARE_DELETE``; the resulting directory handles make an ancestor
    rename/delete fail until the transaction has cleaned up.
    """

    _REPARSE_POINT = 0x400

    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        self._root_fd: int | None = None
        self._dir_fds: dict[tuple[str, ...], int] = {}
        self._posix_root_path: str | None = None
        self._windows_handles: list[int] = []
        self._windows_final_root: str | None = None

    def __enter__(self) -> "_PinnedPublishingFilesystem":
        try:
            if os.name == "nt":
                self._pin_windows_directory(self.root)
            else:
                if not os.path.exists("/proc/self/fd"):
                    raise ValueError("publishing_asset_write_failed")
                flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                self._root_fd = os.open(self.root, flags)
                if not stat.S_ISDIR(os.fstat(self._root_fd).st_mode):
                    raise ValueError("publishing_asset_write_failed")
                self._posix_root_path = os.path.realpath(os.readlink(f"/proc/self/fd/{self._root_fd}"))
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_exc_info: object) -> None:
        logger = logging.getLogger(__name__)
        for descriptor in reversed(list(self._dir_fds.values())):
            try:
                os.close(descriptor)
            except OSError:
                logger.warning("publishing directory descriptor cleanup deferred")
        self._dir_fds.clear()
        if self._root_fd is not None:
            try:
                os.close(self._root_fd)
            except OSError:
                logger.warning("publishing root descriptor cleanup deferred")
            self._root_fd = None
        if os.name == "nt":
            for handle in reversed(self._windows_handles):
                if _KERNEL32 is not None and not _KERNEL32.CloseHandle(wintypes.HANDLE(handle)):
                    logger.warning("publishing directory handle cleanup deferred")
            self._windows_handles.clear()

    def _relative(self, path: Path) -> tuple[str, ...]:
        try:
            return Path(path).absolute().relative_to(self.root).parts
        except ValueError as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @staticmethod
    def _is_asset_target(parts: tuple[str, ...]) -> bool:
        return len(parts) >= 3 and parts[0] == ".webnovel" and parts[1] == "assets"

    def _parent_fd(self, path: Path, *, create: bool) -> tuple[int, str]:
        parts = self._relative(path)
        if not parts:
            raise ValueError("publishing_asset_write_failed")
        parent_parts = parts[:-1]
        current_fd = self._root_fd
        if current_fd is None:  # pragma: no cover - callers are always in the transaction context
            raise ValueError("publishing_asset_write_failed")
        for index, part in enumerate(parent_parts):
            key = parent_parts[: index + 1]
            pinned = self._dir_fds.get(key)
            if pinned is not None:
                current_fd = pinned
                continue
            try:
                details = os.lstat(part, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise ValueError("publishing_asset_write_failed")
                os.mkdir(part, dir_fd=current_fd)
                details = os.lstat(part, dir_fd=current_fd)
            if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
                raise ValueError("publishing_asset_write_failed")
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(part, flags, dir_fd=current_fd)
            try:
                if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    raise ValueError("publishing_asset_write_failed")
                self._assert_posix_descriptor_contained(descriptor)
            except Exception:
                os.close(descriptor)
                raise
            self._dir_fds[key] = descriptor
            current_fd = descriptor
        self._assert_posix_descriptor_contained(current_fd)
        return current_fd, parts[-1]

    def _assert_posix_descriptor_contained(self, descriptor: int) -> None:
        """Detect a rename of a pinned directory out of the trusted root on Linux."""
        if self._posix_root_path is None:
            return  # Platforms without procfs still use descriptor-relative syscalls.
        current = os.path.realpath(os.readlink(f"/proc/self/fd/{descriptor}"))
        try:
            Path(current).relative_to(self._posix_root_path)
        except ValueError as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @staticmethod
    def _windows_final_path(handle: int) -> str:
        if _KERNEL32 is None:  # pragma: no cover - Windows only
            raise OSError("kernel32 unavailable")
        needed = _KERNEL32.GetFinalPathNameByHandleW(wintypes.HANDLE(handle), None, 0, 0)
        if not needed:
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW")
        buffer = ctypes.create_unicode_buffer(needed + 1)
        if not _KERNEL32.GetFinalPathNameByHandleW(wintypes.HANDLE(handle), buffer, len(buffer), 0):
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW")
        return os.path.normcase(os.path.normpath(buffer.value.removeprefix("\\\\?\\")))

    def _pin_windows_directory(self, path: Path) -> None:
        if _KERNEL32 is None:  # pragma: no cover - Windows only
            raise OSError("kernel32 unavailable")
        flags = 0x02000000 | 0x00200000  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        handle = _KERNEL32.CreateFileW(
            str(path), 0x80000000, 0x00000001 | 0x00000002, None, 3, flags, None
        )
        handle_value = wintypes.HANDLE(handle).value
        invalid_handle = wintypes.HANDLE(-1).value
        if handle_value is None or handle_value == invalid_handle:
            raise OSError(ctypes.get_last_error(), "CreateFileW")
        try:
            attrs = _KERNEL32.GetFileAttributesW(str(path))
            if attrs == 0xFFFFFFFF or attrs & self._REPARSE_POINT:
                raise ValueError("publishing_asset_write_failed")
            final = self._windows_final_path(handle_value)
            if self._windows_final_root is None:
                self._windows_final_root = final
            elif os.path.commonpath([self._windows_final_root, final]) != self._windows_final_root:
                raise ValueError("publishing_asset_write_failed")
        except Exception:
            _KERNEL32.CloseHandle(wintypes.HANDLE(handle_value))
            raise
        self._windows_handles.append(handle_value)

    def _windows_assert_target(self, path: Path, *, create: bool) -> None:
        parts = self._relative(path)
        current = self.root
        for part in parts[:-1]:
            current = current / part
            if not os.path.lexists(current):
                if not create:
                    raise ValueError("publishing_asset_write_failed")
                current.mkdir()
            self._pin_windows_directory(current)
        if os.path.lexists(path) and FileProjectStore._is_reparse_point(path):
            raise ValueError("publishing_asset_write_failed")

    def assert_target(self, path: Path) -> None:
        parts = self._relative(path)
        create = self._is_asset_target(parts)
        if os.name == "nt":
            self._windows_assert_target(path, create=create)
            return
        parent_fd, name = self._parent_fd(path, create=create)
        try:
            details = os.lstat(name, dir_fd=parent_fd)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(details.st_mode):
            raise ValueError("publishing_asset_write_failed")

    def exists(self, path: Path) -> bool:
        self.assert_target(path)
        if os.name == "nt":
            return os.path.lexists(path)
        parent_fd, name = self._parent_fd(path, create=False)
        try:
            os.lstat(name, dir_fd=parent_fd)
            return True
        except FileNotFoundError:
            return False

    def read_bytes(self, path: Path) -> bytes:
        self.assert_target(path)
        if os.name == "nt":
            return path.read_bytes()
        parent_fd, name = self._parent_fd(path, create=False)
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                return handle.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def read_bounded_bytes(self, path: Path, max_bytes: int) -> bytes:
        """Open once through pinned ancestors and read a regular file with a hard cap."""
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("publishing_asset_read_failed")
        self.assert_target(path)
        if os.name == "nt":
            if _KERNEL32 is None:  # pragma: no cover - Windows only
                raise ValueError("publishing_asset_read_failed")
            flags = 0x00200000  # OPEN_REPARSE_POINT
            handle = _KERNEL32.CreateFileW(str(path), 0x80000000, 0x00000001 | 0x00000002, None, 3, flags, None)
            handle_value = wintypes.HANDLE(handle).value
            invalid_handle = wintypes.HANDLE(-1).value
            if handle_value is None or handle_value == invalid_handle:
                if ctypes.get_last_error() in {2, 3}:
                    raise FileNotFoundError(path)
                raise ValueError("publishing_asset_read_failed")
            try:
                attrs = _KERNEL32.GetFileAttributesW(str(path))
                if attrs == 0xFFFFFFFF or attrs & self._REPARSE_POINT:
                    raise ValueError("publishing_asset_read_failed")
                final = self._windows_final_path(handle_value)
                if self._windows_final_root is None or os.path.commonpath([self._windows_final_root, final]) != self._windows_final_root:
                    raise ValueError("publishing_asset_read_failed")
                size_value = ctypes.c_longlong()
                if not _KERNEL32.GetFileSizeEx(wintypes.HANDLE(handle_value), ctypes.byref(size_value)):
                    raise ValueError("publishing_asset_read_failed")
                size = size_value.value
                if size <= 0 or size > max_bytes:
                    raise ValueError("publishing_asset_read_failed")
                chunks: list[bytes] = []
                remaining = max_bytes + 1
                while remaining:
                    buffer = ctypes.create_string_buffer(min(64 * 1024, remaining))
                    read = wintypes.DWORD()
                    if not _KERNEL32.ReadFile(wintypes.HANDLE(handle_value), buffer, len(buffer), ctypes.byref(read), None):
                        raise ValueError("publishing_asset_read_failed")
                    if not read.value:
                        break
                    chunks.append(buffer.raw[: read.value])
                    remaining -= read.value
                content = b"".join(chunks)
            finally:
                _KERNEL32.CloseHandle(wintypes.HANDLE(handle_value))
            if not content or len(content) > max_bytes:
                raise ValueError("publishing_asset_read_failed")
            return content
        parent_fd, name = self._parent_fd(path, create=False)
        descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_size <= 0 or details.st_size > max_bytes:
                raise ValueError("publishing_asset_read_failed")
            chunks: list[bytes] = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if not content or len(content) > max_bytes:
                raise ValueError("publishing_asset_read_failed")
            return content
        finally:
            os.close(descriptor)

    def prepare(self, path: Path, content: bytes, *, suffix: str) -> Path:
        self.assert_target(path)
        if os.name == "nt":
            return self._prepare_windows(path, content, suffix=suffix)
        parent_fd, target_name = self._parent_fd(path, create=True)
        try:
            existing_details = os.stat(target_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing_mode = None
        else:
            if stat.S_ISLNK(existing_details.st_mode):
                raise ValueError("publishing_asset_write_failed")
            existing_mode = stat.S_IMODE(existing_details.st_mode)
        name = f".{path.name}.{uuid.uuid4().hex}{suffix}"
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        temp_path = path.parent / name
        try:
            if existing_mode is not None:
                os.fchmod(descriptor, existing_mode)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.unlink(name, dir_fd=parent_fd)
            except OSError:
                logging.getLogger(__name__).warning("publishing temp cleanup deferred: %s", temp_path)
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        return temp_path

    def _prepare_windows(self, path: Path, content: bytes, *, suffix: str) -> Path:
        fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=suffix)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    logging.getLogger(__name__).warning("publishing temp descriptor cleanup deferred: %s", temp_path)
                fd = None
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("publishing temp cleanup deferred: %s", temp_path)
            raise
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    logging.getLogger(__name__).warning("publishing temp descriptor cleanup deferred: %s", temp_path)
        return temp_path

    def replace(self, source: Path, target: Path) -> None:
        self.assert_target(source)
        self.assert_target(target)
        if os.name == "nt":
            os.replace(source, target)
            return
        source_fd, source_name = self._parent_fd(source, create=False)
        target_fd, target_name = self._parent_fd(target, create=False)
        os.replace(source_name, target_name, src_dir_fd=source_fd, dst_dir_fd=target_fd)

    def unlink(self, path: Path) -> None:
        self.assert_target(path)
        if os.name == "nt":
            path.unlink(missing_ok=True)
            return
        parent_fd, name = self._parent_fd(path, create=False)
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass

    def fsync_parent(self, path: Path) -> None:
        if os.name == "nt":
            return
        try:
            descriptor, _ = self._parent_fd(path, create=False)
            os.fsync(descriptor)
        except OSError:
            pass


class FileProjectStore:
    """Read plugin-friendly story project files from a directory."""

    PUBLISHING_ASSET_MAX_BYTES = 20 * 1024 * 1024

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.story_system_dir = self.root / ".story-system"
        self.webnovel_dir = self.root / ".webnovel"
        self.chapters_dir = self.root / "chapters"
        self._active_publishing_filesystem: _PinnedPublishingFilesystem | None = None
        self.candidate_store = CandidateStore(self.root)
        self.chapter_store = ChapterStore(self.root)
        self.snapshot_store = SnapshotStore()

    def _read_json(self, path: Path, default: Any = None) -> Any:
        return self.snapshot_store.read_json(path, default)

    def _write_json(self, path: Path, payload: Any) -> None:
        self.snapshot_store.write_json(path, payload)

    def _write_json_atomic(self, path: Path, payload: Any) -> None:
        self.snapshot_store.write_json_atomic(path, payload)

    @property
    def prompt_template_overrides_path(self) -> Path:
        return self.story_system_dir / "prompt_templates.json"

    def _prompt_template_overrides(self) -> dict[str, dict[str, Any]]:
        payload = self._read_json(self.prompt_template_overrides_path, {}) or {}
        templates = payload.get("templates", {}) if isinstance(payload, dict) else {}
        return templates if isinstance(templates, dict) else {}

    def effective_prompt_template(self, key: str) -> dict[str, Any]:
        template, source = self._effective_prompt_template_object(key)
        return {
            **template.as_dict(),
            "source": source,
        }

    def _effective_prompt_template_object(self, key: str) -> tuple[PromptTemplate, str]:
        global_template = get_global_prompt_template(key)
        override = self._prompt_template_overrides().get(key)
        if isinstance(override, dict) and isinstance(override.get("content"), str):
            template = PromptTemplate(
                key=global_template.key,
                title=global_template.title,
                stage=global_template.stage,
                content=override["content"],
                required_variables=global_template.required_variables,
            )
            validate_prompt_template(template)
            source = "project_override"
        else:
            template = global_template
            source = (
                "global_default"
                if template.content == next(item.content for item in list_default_prompt_templates() if item.key == key)
                else "global_override"
            )
        return template, source

    def prompt_template_object(self, key: str) -> PromptTemplate:
        return self._effective_prompt_template_object(key)[0]

    def prompt_template_source(self, key: str) -> str:
        return self._effective_prompt_template_object(key)[1]

    def prompt_templates(self) -> list[dict[str, Any]]:
        project = self.project()
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        is_game_story = self._is_game_story_payload(project, state)
        templates: list[dict[str, Any]] = []
        for item in list_default_prompt_templates():
            applicability = prompt_template_applicability(item.key)
            active_for_project = (
                applicability == "all"
                or (applicability == "game_only" and is_game_story)
                or (applicability == "non_game_only" and not is_game_story)
            )
            templates.append(
                {
                    **self.effective_prompt_template(item.key),
                    "applicability": applicability,
                    "active_for_project": active_for_project,
                }
            )
        return templates

    def prompt_call_log(self) -> PromptCallLog:
        from packages.story_core.genre_stages.registry import genre_stage_profile_for

        project_id = str(self.project().get("project_id") or self.root.name)
        if not project_id.startswith("file:"):
            project_id = f"file:{project_id}"
        project = self.project()
        state = self.state()
        chapter_number = max(1, int(state.get("current_chapter") or 0) + 1)
        story = StoryState.model_validate(
            self._story_state_payload_for_direction(state, project, chapter_number)
        )
        return PromptCallLog(
            self.story_system_dir,
            project_id=project_id,
            profile=genre_stage_profile_for(story),
        )

    @_with_project_update_lock
    def set_prompt_template_override(self, key: str, content: str) -> dict[str, Any]:
        base = get_global_prompt_template(key)
        candidate = PromptTemplate(
            key=base.key,
            title=base.title,
            stage=base.stage,
            content=str(content),
            required_variables=base.required_variables,
        )
        validate_prompt_template(candidate)
        overrides = self._prompt_template_overrides()
        overrides[key] = {
            "content": candidate.content,
            "version": candidate.version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json_atomic(
            self.prompt_template_overrides_path,
            {"schema_version": "project-prompt-templates/v1", "templates": overrides},
        )
        return self.effective_prompt_template(key)

    @_with_project_update_lock
    def delete_prompt_template_override(self, key: str) -> dict[str, Any]:
        get_global_prompt_template(key)
        overrides = self._prompt_template_overrides()
        overrides.pop(key, None)
        self._write_json_atomic(
            self.prompt_template_overrides_path,
            {"schema_version": "project-prompt-templates/v1", "templates": overrides},
        )
        return self.effective_prompt_template(key)

    def _replace_json_transaction(self, payloads: dict[Path, Any]) -> None:
        self.snapshot_store.replace_json_transaction(payloads)

    @property
    def cover_base_path(self) -> Path:
        return self.webnovel_dir / "assets" / "cover-base.png"

    @property
    def rendered_cover_path(self) -> Path:
        return self.webnovel_dir / "assets" / "cover.png"

    @staticmethod
    def _publishing_assets_default() -> dict[str, Any]:
        return {
            "schema_version": "publishing-assets/v1",
            "synopsis": None,
            "cover": None,
        }

    @staticmethod
    def _json_safe_dict(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            raise ValueError("publishing_asset_write_failed")
        try:
            serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
            restored = json.loads(serialized)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ValueError("publishing_asset_write_failed") from exc
        if not isinstance(restored, dict):  # pragma: no cover - guarded above
            raise ValueError("publishing_asset_write_failed")
        FileProjectStore._validate_publishing_value(restored)
        return restored

    @staticmethod
    def _validate_publishing_value(value: Any) -> None:
        containers = 0

        def visit(item: Any, depth: int = 0) -> None:
            nonlocal containers
            if depth > 32:
                raise ValueError("publishing_asset_write_failed")
            if isinstance(item, str):
                if len(item) > 16_000:
                    raise ValueError("publishing_asset_write_failed")
                return
            if item is None or isinstance(item, (bool, int, float)):
                return
            if isinstance(item, dict):
                containers += 1
                if containers > 1_024 or any(not isinstance(key, str) for key in item):
                    raise ValueError("publishing_asset_write_failed")
                for nested in item.values():
                    visit(nested, depth + 1)
                return
            if isinstance(item, list):
                containers += 1
                if containers > 1_024:
                    raise ValueError("publishing_asset_write_failed")
                for nested in item:
                    visit(nested, depth + 1)
                return
            raise ValueError("publishing_asset_write_failed")

        visit(value)
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 65_536:
            raise ValueError("publishing_asset_write_failed")

    @staticmethod
    def _json_safe_value(value: Any) -> tuple[bool, Any]:
        try:
            serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
            restored = json.loads(serialized)
            FileProjectStore._validate_publishing_value(restored)
            return True, restored
        except (TypeError, ValueError, OverflowError, RecursionError):
            return False, None

    @staticmethod
    def _publishing_path_like_key(key: str) -> bool:
        folded = key.casefold()
        return folded in {"path", "file", "filename", "url", "uri", "filepath", "file_path"} or folded.endswith(
            ("_path", "_file", "_filename", "_url", "_uri", "_filepath")
        )

    @classmethod
    def _sanitize_future_publishing_value(cls, value: Any) -> Any:
        """Deep-clone JSON-safe future data while removing storage references."""
        dropped = object()

        def unsafe_string(item: str) -> bool:
            candidate = item.strip()
            return bool(
                candidate.startswith(("/", "\\", "file:"))
                or re.match(r"^[a-zA-Z]:[\\/]", candidate)
                or re.search(r"(^|[\\/])\.\.([\\/]|$)", candidate)
            )

        def clean(item: Any) -> Any:
            if isinstance(item, str) and unsafe_string(item):
                return dropped
            if isinstance(item, dict):
                sanitized: dict[str, Any] = {}
                for key, nested in item.items():
                    if not isinstance(key, str) or cls._publishing_path_like_key(key):
                        continue
                    cleaned = clean(nested)
                    if cleaned is not dropped:
                        sanitized[key] = cleaned
                return sanitized
            if isinstance(item, list):
                return [cleaned for nested in item if (cleaned := clean(nested)) is not dropped]
            return item

        cleaned = clean(value)
        return None if cleaned is dropped else cleaned

    @classmethod
    def _normalize_publishing_assets(cls, value: Any) -> dict[str, Any]:
        normalized = cls._publishing_assets_default()
        if not isinstance(value, dict):
            return normalized
        for key, item in value.items():
            if key in {"schema_version", "synopsis", "cover", "updated_at"} or not isinstance(key, str):
                continue
            if cls._publishing_path_like_key(key):
                continue
            is_safe, safe_item = cls._json_safe_value(item)
            if is_safe:
                normalized[key] = cls._sanitize_future_publishing_value(safe_item)
        updated_at = value.get("updated_at")
        if isinstance(updated_at, str) and updated_at.strip():
            normalized["updated_at"] = updated_at.strip()
        synopsis = value.get("synopsis")
        if isinstance(synopsis, dict):
            try:
                normalized["synopsis"] = cls._sanitize_future_publishing_value(cls._json_safe_dict(synopsis))
            except ValueError:
                pass
        raw_cover = value.get("cover")
        if not isinstance(raw_cover, dict):
            return normalized
        cover: dict[str, Any] = {}
        for key, item in raw_cover.items():
            if not isinstance(key, str):
                continue
            if cls._publishing_path_like_key(key) and key not in {"base_path", "rendered_path"}:
                continue
            is_safe, safe_item = cls._json_safe_value(item)
            if is_safe:
                cover[key] = cls._sanitize_future_publishing_value(safe_item)
        prompt = raw_cover.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            cover["prompt"] = prompt.strip()[:2000]
        else:
            cover.pop("prompt", None)
        model = raw_cover.get("model")
        if isinstance(model, str) and model.strip():
            cover["model"] = model.strip()
        else:
            cover.pop("model", None)
        if raw_cover.get("base_path") == "assets/cover-base.png":
            cover["base_path"] = "assets/cover-base.png"
        else:
            cover.pop("base_path", None)
        if raw_cover.get("rendered_path") == "assets/cover.png":
            cover["rendered_path"] = "assets/cover.png"
        else:
            cover.pop("rendered_path", None)
        schema_version = raw_cover.get("schema_version")
        if isinstance(schema_version, str) and schema_version.strip():
            cover["schema_version"] = schema_version.strip()
        else:
            cover.pop("schema_version", None)
        rendered_title = raw_cover.get("rendered_title")
        if isinstance(rendered_title, str):
            cover["rendered_title"] = rendered_title
        else:
            cover.pop("rendered_title", None)
        normalized["cover"] = cover or None
        return normalized

    def _safe_metadata_document(self, path: Path) -> dict[str, Any]:
        try:
            payload = self._read_json(path, {})
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        try:
            details = os.lstat(path)
        except FileNotFoundError:
            return False
        return path.is_symlink() or bool(getattr(details, "st_file_attributes", 0) & 0x400)

    def _assert_publishing_target_safe(self, target: Path) -> None:
        if self._active_publishing_filesystem is not None:
            self._active_publishing_filesystem.assert_target(target)
            return
        target = Path(target)
        try:
            relative = target.absolute().relative_to(self.root)
        except ValueError as exc:
            raise ValueError("publishing_asset_write_failed") from exc
        current = self.root
        if self._is_reparse_point(current):
            raise ValueError("publishing_asset_write_failed")
        for part in relative.parts[:-1]:
            current = current / part
            if self._is_reparse_point(current):
                raise ValueError("publishing_asset_write_failed")
        if os.path.lexists(target) and self._is_reparse_point(target):
            raise ValueError("publishing_asset_write_failed")
        if not target.parent.resolve().is_relative_to(self.root):
            raise ValueError("publishing_asset_write_failed")

    @staticmethod
    def _complete_project_payload(project: Any) -> bool:
        return (
            isinstance(project, dict)
            and isinstance(project.get("project_id"), str)
            and bool(project["project_id"].strip())
            and isinstance(project.get("title"), str)
            and bool(project["title"].strip())
        )

    @classmethod
    def _complete_master_payload(cls, master: Any) -> bool:
        return (
            isinstance(master, dict)
            and master.get("schema_version") == "story-system-master-setting/v1"
            and cls._complete_project_payload(master.get("project"))
        )

    def _mutation_metadata_document(self, path: Path) -> dict[str, Any] | None:
        self._assert_publishing_target_safe(path)
        filesystem = self._active_publishing_filesystem
        exists = filesystem.exists(path) if filesystem is not None else os.path.lexists(path)
        if not exists:
            return None
        try:
            raw = filesystem.read_bytes(path) if filesystem is not None else path.read_bytes()
            payload = json.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("publishing_asset_write_failed") from exc
        if not isinstance(payload, dict):
            raise ValueError("publishing_asset_write_failed")
        return dict(payload)

    def _publishing_assets_from_metadata(self) -> dict[str, Any]:
        project = self._safe_metadata_document(self.webnovel_dir / "project.json")
        if "publishing_assets" in project:
            return self._normalize_publishing_assets(project.get("publishing_assets"))
        master = self._safe_metadata_document(self.story_system_dir / "MASTER_SETTING.json")
        master_project = master.get("project")
        if isinstance(master_project, dict):
            return self._normalize_publishing_assets(master_project.get("publishing_assets"))
        return self._publishing_assets_default()

    def _prepare_publishing_temp(self, path: Path, content: bytes, *, suffix: str = ".tmp") -> Path:
        if self._active_publishing_filesystem is not None:
            return self._active_publishing_filesystem.prepare(path, content, suffix=suffix)
        self._assert_publishing_target_safe(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_publishing_target_safe(path)
        fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=suffix)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt" and path.exists():
                os.chmod(temp_path, os.stat(path).st_mode & 0o777)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("publishing temp cleanup deferred: %s", temp_path)
            raise
        return temp_path

    def _replace_asset(self, source: Path, target: Path) -> None:
        if self._active_publishing_filesystem is not None:
            self._active_publishing_filesystem.replace(source, target)
        else:
            os.replace(source, target)

    def _replace_metadata(self, source: Path, target: Path) -> None:
        if self._active_publishing_filesystem is not None:
            self._active_publishing_filesystem.replace(source, target)
        else:
            os.replace(source, target)

    def _restore_publishing_backup(self, backup: Path, target: Path) -> None:
        self._assert_publishing_target_safe(target)
        if self._active_publishing_filesystem is not None:
            self._active_publishing_filesystem.replace(backup, target)
        else:
            os.replace(backup, target)

    def _best_effort_unlink(self, path: Path) -> None:
        try:
            if self._active_publishing_filesystem is not None:
                self._active_publishing_filesystem.unlink(path)
            else:
                path.unlink(missing_ok=True)
        except (OSError, ValueError):
            logging.getLogger(__name__).warning("publishing transaction cleanup deferred: %s", path)

    def _best_effort_fsync_parent(self, path: Path) -> None:
        if os.name == "nt":
            return
        if self._active_publishing_filesystem is not None:
            try:
                self._active_publishing_filesystem.fsync_parent(path)
            except (OSError, ValueError):
                logging.getLogger(__name__).warning("publishing parent fsync deferred: %s", path.parent)
            return
        try:
            descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            try:
                os.close(descriptor)
            except OSError:
                logging.getLogger(__name__).warning("publishing parent descriptor cleanup deferred: %s", path.parent)

    def _publishing_metadata_payloads(
        self,
        publishing_assets: dict[str, Any],
    ) -> dict[Path, dict[str, Any]]:
        project_path = self.webnovel_dir / "project.json"
        master_path = self.story_system_dir / "MASTER_SETTING.json"
        project = self._mutation_metadata_document(project_path)
        master = self._mutation_metadata_document(master_path)
        if project is None and master is None:
            raise ValueError("publishing_asset_write_failed")
        if project is None:
            master_project = master.get("project") if isinstance(master, dict) else None
            if not self._complete_master_payload(master) or not self._complete_project_payload(master_project):
                raise ValueError("publishing_asset_write_failed")
            project = dict(master_project)
        if master is None:
            if not self._complete_project_payload(project):
                raise ValueError("publishing_asset_write_failed")
            master = {"schema_version": "story-system-master-setting/v1", "project": deepcopy(project)}
        master_project = master.get("project")
        if not isinstance(master_project, dict):
            raise ValueError("publishing_asset_write_failed")
        if not self._complete_project_payload(project) or not self._complete_project_payload(master_project):
            raise ValueError("publishing_asset_write_failed")
        master_project = dict(master_project)
        project["publishing_assets"] = deepcopy(publishing_assets)
        master_project["publishing_assets"] = deepcopy(publishing_assets)
        master["project"] = master_project
        return {project_path: project, master_path: master}

    def _publishing_transaction(
        self,
        publishing_assets: dict[str, Any],
        *,
        asset_contents: tuple[bytes, bytes] | None = None,
        asset_updates: dict[Path, bytes] | None = None,
    ) -> None:
        """Best-effort cross-file transaction; retained .rollback files signal incomplete recovery after a fault."""
        self._validate_publishing_value(publishing_assets)
        if asset_contents is not None and asset_updates is not None:
            raise ValueError("publishing_asset_write_failed")
        metadata_targets = [
            self.webnovel_dir / "project.json",
            self.story_system_dir / "MASTER_SETTING.json",
        ]
        if asset_contents is not None:
            asset_updates = {
                self.cover_base_path: asset_contents[0],
                self.rendered_cover_path: asset_contents[1],
            }
        asset_updates = asset_updates or {}
        allowed_asset_targets = {self.cover_base_path, self.rendered_cover_path}
        if any(target not in allowed_asset_targets or not isinstance(content, bytes) for target, content in asset_updates.items()):
            raise ValueError("publishing_asset_write_failed")
        asset_targets = list(asset_updates)
        all_targets = asset_targets + metadata_targets
        prepared: list[Path] = []
        rollback_files: dict[Path, Path | None] = {}
        committed: list[Path] = []
        with _PinnedPublishingFilesystem(self.root) as filesystem:
            prior_filesystem = self._active_publishing_filesystem
            self._active_publishing_filesystem = filesystem
            try:
                metadata_payloads = self._publishing_metadata_payloads(publishing_assets)
                metadata_targets = list(metadata_payloads)
                for target in all_targets:
                    self._assert_publishing_target_safe(target)
                    if filesystem.exists(target):
                        rollback_files[target] = self._prepare_publishing_temp(
                            target, filesystem.read_bytes(target), suffix=".rollback"
                        )
                    else:
                        rollback_files[target] = None
                if asset_updates:
                    asset_temps: list[Path] = []
                    for target in asset_targets:
                        content = asset_updates[target]
                        prepared_temp = self._prepare_publishing_temp(target, content)
                        prepared.append(prepared_temp)
                        asset_temps.append(prepared_temp)
                else:
                    asset_temps = []

                metadata_temps: dict[Path, Path] = {}
                for target, payload in metadata_payloads.items():
                    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
                    metadata_temps[target] = self._prepare_publishing_temp(target, serialized)
                    prepared.append(metadata_temps[target])

                for source, target in zip(asset_temps, asset_targets, strict=True):
                    self._replace_asset(source, target)
                    committed.append(target)
                    self._best_effort_fsync_parent(target)
                for target in metadata_targets:
                    self._replace_metadata(metadata_temps[target], target)
                    committed.append(target)
                    self._best_effort_fsync_parent(target)
                for backup in rollback_files.values():
                    if backup is not None:
                        self._best_effort_unlink(backup)
            except Exception as exc:
                rollback_errors: list[Exception] = []
                for target in reversed(committed):
                    try:
                        backup = rollback_files[target]
                        if backup is None:
                            filesystem.unlink(target)
                        else:
                            self._restore_publishing_backup(backup, target)
                        self._best_effort_fsync_parent(target)
                    except Exception as rollback_exc:  # pragma: no cover - exercised by fault seams
                        rollback_errors.append(rollback_exc)
                for path in prepared:
                    self._best_effort_unlink(path)
                if rollback_errors:
                    raise ValueError("publishing_asset_write_failed") from ExceptionGroup(
                        "publishing transaction and recovery failures", [exc, *rollback_errors]
                    )
                for backup in rollback_files.values():
                    if backup is not None:
                        self._best_effort_unlink(backup)
                raise ValueError("publishing_asset_write_failed") from exc
            finally:
                for path in prepared:
                    self._best_effort_unlink(path)
                self._active_publishing_filesystem = prior_filesystem

    @_with_project_update_lock
    def publishing_assets(self) -> dict[str, Any]:
        return self._publishing_assets_from_metadata()

    @_with_project_update_lock
    def save_synopsis(
        self,
        synopsis: dict[str, Any],
        *,
        expected_synopsis: dict[str, Any] | None | object = _MISSING,
    ) -> dict[str, Any]:
        try:
            saved = self._publishing_assets_from_metadata()
            if expected_synopsis is not _MISSING and saved.get("synopsis") != expected_synopsis:
                raise ValueError("publishing_asset_stale_synopsis")
            saved["synopsis"] = self._json_safe_dict(synopsis)
            saved["updated_at"] = self._publishing_updated_at()
            self._publishing_transaction(saved)
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_synopsis"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @staticmethod
    def _publishing_prompt(prompt: str) -> str:
        if not isinstance(prompt, str):
            raise ValueError("publishing_asset_write_failed")
        normalized = prompt.strip()
        if not normalized or len(normalized) > 2000:
            raise ValueError("publishing_asset_write_failed")
        return normalized

    @staticmethod
    def _publishing_updated_at() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @_with_project_update_lock
    def save_cover_prompt(self, prompt: str, *, expected_prompt: str | None = None) -> dict[str, Any]:
        try:
            saved = self._publishing_assets_from_metadata()
            cover = dict(saved["cover"] or {})
            if expected_prompt is not None and str(cover.get("prompt") or "") != expected_prompt.strip():
                raise ValueError("publishing_asset_stale_cover")
            cover["prompt"] = self._publishing_prompt(prompt)
            cover["updated_at"] = self._publishing_updated_at()
            saved["cover"] = cover
            saved["updated_at"] = cover["updated_at"]
            self._publishing_transaction(saved)
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_cover"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @_with_project_update_lock
    def save_cover(
        self,
        *,
        prompt: str,
        base_image: bytes,
        rendered_image: bytes,
        model: str,
        expected_prompt: str | None = None,
        expected_title: str | None = None,
        rendered_title: str | None = None,
    ) -> dict[str, Any]:
        try:
            if not isinstance(base_image, bytes) or not isinstance(rendered_image, bytes):
                raise ValueError("publishing_asset_write_failed")
            if len(base_image) > self.PUBLISHING_ASSET_MAX_BYTES or len(rendered_image) > self.PUBLISHING_ASSET_MAX_BYTES:
                raise ValueError("publishing_asset_write_failed")
            if not base_image or not rendered_image or not isinstance(model, str) or not model.strip() or len(model.strip()) > 256:
                raise ValueError("publishing_asset_write_failed")
            project = self.project()
            try:
                title = normalize_cover_title(str(project.get("title") or ""))
            except CoverRenderError as exc:
                raise ValueError("publishing_asset_write_failed") from exc
            if not title:
                raise ValueError("publishing_asset_write_failed")
            saved = self._publishing_assets_from_metadata()
            current_prompt = str((saved.get("cover") or {}).get("prompt") or "")
            if expected_prompt is not None and current_prompt != expected_prompt.strip():
                raise ValueError("publishing_asset_stale_cover")
            if expected_title is not None and title != expected_title:
                raise ValueError("publishing_asset_stale_cover")
            if rendered_title is not None and rendered_title != title:
                raise ValueError("publishing_asset_stale_cover")
            updated_at = self._publishing_updated_at()
            saved["cover"] = {
                "prompt": self._publishing_prompt(prompt),
                "model": model.strip(),
                "base_path": "assets/cover-base.png",
                "rendered_path": "assets/cover.png",
                "schema_version": "cover/v1",
                "base_image_version": sha256(base_image).hexdigest(),
                "rendered_from_base_version": sha256(base_image).hexdigest(),
                "rendered_title": rendered_title or title,
                "image_version": sha256(rendered_image).hexdigest(),
                "mime_type": "image/png",
                "updated_at": updated_at,
            }
            saved["updated_at"] = updated_at
            self._publishing_transaction(saved, asset_contents=(base_image, rendered_image))
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_cover"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @_with_project_update_lock
    def save_cover_base(self, *, prompt: str, base_image: bytes, model: str, expected_prompt: str | None = None, expected_title: str | None = None) -> dict[str, Any]:
        """Persist a validated source image without replacing the current rendered cover."""
        try:
            if not isinstance(base_image, bytes) or not base_image or len(base_image) > self.PUBLISHING_ASSET_MAX_BYTES:
                raise ValueError("publishing_asset_write_failed")
            if not isinstance(model, str) or not model.strip() or len(model.strip()) > 256:
                raise ValueError("publishing_asset_write_failed")
            saved = self._publishing_assets_from_metadata()
            current_prompt = str((saved.get("cover") or {}).get("prompt") or "")
            current_title = normalize_cover_title(str(self.project().get("title") or ""))
            if (expected_prompt is not None and current_prompt != expected_prompt.strip()) or (expected_title is not None and current_title != expected_title):
                raise ValueError("publishing_asset_stale_cover")
            cover = dict(saved["cover"] or {})
            updated_at = self._publishing_updated_at()
            cover.update(
                {
                    "prompt": self._publishing_prompt(prompt),
                    "model": model.strip(),
                    "base_path": "assets/cover-base.png",
                    "schema_version": "cover/v1",
                    "base_image_version": sha256(base_image).hexdigest(),
                    "updated_at": updated_at,
                }
            )
            saved["cover"] = cover
            saved["updated_at"] = updated_at
            self._publishing_transaction(saved, asset_updates={self.cover_base_path: base_image})
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_cover"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    def _read_publishing_asset(self, path: Path) -> bytes | None:
        try:
            with _PinnedPublishingFilesystem(self.root) as filesystem:
                if not filesystem.exists(path):
                    return None
                content = filesystem.read_bounded_bytes(path, self.PUBLISHING_ASSET_MAX_BYTES)
            if not content or len(content) > self.PUBLISHING_ASSET_MAX_BYTES:
                raise ValueError("publishing_asset_read_failed")
            return content
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError("publishing_asset_read_failed") from exc

    @_with_project_update_lock
    def read_cover_base(self) -> tuple[bytes, str] | None:
        content = self._read_publishing_asset(self.cover_base_path)
        if content is None:
            return None
        cover = self._publishing_assets_from_metadata().get("cover") or {}
        derived = sha256(content).hexdigest()
        version = str(cover.get("base_image_version") or derived) if isinstance(cover, dict) else derived
        if version != derived:
            raise ValueError("publishing_asset_read_failed")
        return content, version

    @_with_project_update_lock
    def read_rendered_cover(self) -> bytes | None:
        return self._read_publishing_asset(self.rendered_cover_path)

    @_with_project_update_lock
    def save_rendered_cover(self, rendered_image: bytes, *, expected_base_version: str, expected_title: str | None = None, rendered_title: str | None = None) -> dict[str, Any]:
        try:
            if not isinstance(rendered_image, bytes) or not rendered_image or len(rendered_image) > self.PUBLISHING_ASSET_MAX_BYTES:
                raise ValueError("publishing_asset_write_failed")
            saved = self._publishing_assets_from_metadata()
            cover = dict(saved["cover"] or {})
            if cover.get("base_path") != "assets/cover-base.png":
                raise ValueError("publishing_asset_write_failed")
            current_base_version = str(cover.get("base_image_version") or "")
            if not current_base_version:
                base = self._read_publishing_asset(self.cover_base_path)
                if base is None:
                    raise ValueError("publishing_asset_write_failed")
                current_base_version = sha256(base).hexdigest()
                cover["base_image_version"] = current_base_version
            if not expected_base_version or current_base_version != expected_base_version:
                raise ValueError("publishing_asset_stale_base")
            try:
                title = normalize_cover_title(str(self.project().get("title") or ""))
            except CoverRenderError as exc:
                raise ValueError("publishing_asset_write_failed") from exc
            if not title:
                raise ValueError("publishing_asset_write_failed")
            if expected_title is not None and title != expected_title:
                raise ValueError("publishing_asset_stale_cover")
            if rendered_title is not None and rendered_title != title:
                raise ValueError("publishing_asset_stale_cover")
            updated_at = self._publishing_updated_at()
            cover.update(
                {
                    "rendered_path": "assets/cover.png",
                    "schema_version": "cover/v1",
                    "rendered_title": rendered_title or title,
                    "image_version": sha256(rendered_image).hexdigest(),
                    "rendered_from_base_version": expected_base_version,
                    "mime_type": "image/png",
                    "updated_at": updated_at,
                }
            )
            saved["cover"] = cover
            saved["updated_at"] = updated_at
            self._publishing_transaction(saved, asset_updates={self.rendered_cover_path: rendered_image})
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_base", "publishing_asset_stale_cover"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @staticmethod
    def _snapshot_managed_files(
        paths: list[Path],
        directories: list[Path],
    ) -> tuple[dict[Path, bytes | None], tuple[Path, ...]]:
        return SnapshotStore.snapshot_managed_files(paths, directories)

    @staticmethod
    def _restore_managed_files(
        snapshot: dict[Path, bytes | None],
        directories: tuple[Path, ...],
    ) -> None:
        SnapshotStore.restore_managed_files(snapshot, directories)

    def _write_text(self, path: Path, text: str) -> None:
        self.snapshot_store.write_text(path, text)

    def _chapter_markdown_name(self, chapter_number: int, title: str) -> str:
        return self.chapter_store.markdown_name(chapter_number, title)

    def _remove_chapter_markdowns(self, chapter_number: int) -> None:
        self.chapter_store.remove_markdowns(chapter_number)

    def _chapter_paths(self, chapter_number: int, title: str) -> dict[str, Path]:
        return self.chapter_store.paths(chapter_number, title)

    def _append_workflow_log(
        self,
        *,
        chapter_number: int,
        chapter_title: str,
        review: dict[str, Any],
        operation: str,
    ) -> None:
        if not isinstance(review, dict) or review.get("workflow_log_path"):
            return
        project = self.project()
        state = self.state()
        path = append_workflow_telemetry(
            chapter=chapter_number,
            chapter_title=chapter_title,
            operation=operation,
            quality_report=review,
            project_id=str(project.get("project_id") or ""),
            story_id=str(state.get("story_id") or project.get("active_story_id") or ""),
        )
        if path is not None:
            review["workflow_log_path"] = str(path)

    def _bundle_to_dict(self, bundle: Any) -> dict[str, Any]:
        if hasattr(bundle, "model_dump"):
            return bundle.model_dump(mode="json")
        if isinstance(bundle, dict):
            return dict(bundle)
        return {
            key: value
            for key, value in vars(bundle).items()
            if not key.startswith("_")
        }

    def _save_candidate_from_bundle(
        self,
        bundle: Any,
        *,
        project_id: str,
        quality_report: dict[str, Any] | None = None,
        operation: str = "generate",
    ) -> CandidateDraft:
        submission_payload = self._bundle_to_dict(bundle)
        updated_story = submission_payload.get("updated_story")
        if hasattr(updated_story, "model_dump"):
            submission_payload["updated_story"] = updated_story.model_dump(mode="json")
        candidate = CandidateDraft.create(
            project_id=project_id,
            chapter_number=int(getattr(bundle, "chapter_number", 0) or 0),
            chapter_title=str(getattr(bundle, "chapter_title", "") or ""),
            body=str(getattr(bundle, "body", "") or ""),
            context_snapshot_id=str(getattr(bundle, "context_snapshot_id", "") or ""),
            quality_report=quality_report
            if isinstance(quality_report, dict)
            else getattr(bundle, "quality_report", None)
            if isinstance(getattr(bundle, "quality_report", None), dict)
            else {},
            submission_payload=submission_payload,
            operation=operation,
        )
        self.candidate_store.save_latest(candidate)
        report_generation_progress(
            build_chapter_pipeline_event(
                "candidate_output",
                "保存候选稿",
                status="done",
                source="candidate_store",
                used_modules=["candidate_store"],
                reads=["最终正文", "综合审稿结果", "待确认状态变更"],
                outputs={
                    "candidate_id": candidate.candidate_id,
                    "chapter_number": candidate.chapter_number,
                    "operation": candidate.operation,
                    "status": candidate.status,
                    "context_snapshot_id": candidate.context_snapshot_id,
                },
            )
        )
        return candidate

    def _ensure_regenerate_continuity_fields(
        self,
        chapter: dict[str, Any],
        *,
        chapter_number: int,
        chapter_title: str,
    ) -> dict[str, Any]:
        repaired = dict(chapter)
        repaired["chapter_title"] = chapter_title
        if not repaired.get("cadence"):
            repaired["cadence"] = "measured"
        if not repaired.get("next_outline"):
            repaired["next_outline"] = "continue"

        summary_payload = self._chapter_summary_payload(repaired)
        chapter_summary = repaired.get("chapter_summary")
        if not isinstance(chapter_summary, dict):
            repaired["chapter_summary"] = summary_payload
        else:
            normalized = dict(chapter_summary)
            normalized.setdefault("chapter_title", summary_payload["chapter_title"])
            normalized.setdefault("cadence", summary_payload.get("cadence") or repaired.get("cadence", "measured"))
            normalized.setdefault("summary", summary_payload["summary"])
            normalized.setdefault("next_focus", summary_payload["next_focus"])
            normalized.setdefault("facts", summary_payload["facts"])
            normalized.setdefault("unresolved_threads", summary_payload["unresolved_threads"])
            normalized.setdefault("resolved_threads", summary_payload["resolved_threads"])
            normalized.setdefault("primary_conflict", summary_payload["primary_conflict"])
            normalized.setdefault("secondary_conflict", summary_payload["secondary_conflict"])
            normalized.setdefault("event_beat", summary_payload["event_beat"])
            repaired["chapter_summary"] = normalized
            summary_payload = self._chapter_summary_payload(repaired)

        if not repaired.get("next_outline"):
            repaired["next_outline"] = (
                str(summary_payload.get("next_focus") or "continue") or "continue"
            )

        updated_story = repaired.get("updated_story")
        if hasattr(updated_story, "model_dump"):
            updated_story = updated_story.model_dump(mode="json")
        if not isinstance(updated_story, dict):
            updated_story = {}

        if isinstance(updated_story.get("timeline"), list):
            pass
        else:
            updated_story["timeline"] = [
                {
                    "chapter_number": chapter_number,
                    "summary": summary_payload["summary"],
                    "impact": summary_payload.get("next_focus") or repaired["next_outline"],
                }
            ]

        if isinstance(updated_story.get("chapter_summaries"), list):
            pass
        else:
            updated_story["chapter_summaries"] = [summary_payload]

        repaired["updated_story"] = updated_story
        return repaired

    def _compact_text(self, value: Any, limit: int = 180) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _merge_unique(self, current: list[Any], additions: list[Any], *, limit: int = 80) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()
        for item in [*current, *additions]:
            if item in (None, ""):
                continue
            key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result[-limit:]

    def _coerce_summary_mapping(self, value: Any, *, label: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value in (None, ""):
            return {}
        return {"note": self._compact_text(value, 220), "source": label}

    def _clean_state_fact_list(self, values: Any) -> list[Any]:
        if not isinstance(values, list):
            return []
        blocked_fragments = (
            "manual draft",
            "第2章事实：夜烬仍为Lv.1",
            "夜烬仍为Lv.1见习冒险者",
            "第2章事实：新手法杖9/10",
            "第2章事实：背包为粗糙狼皮×7",
        )
        return [
            item
            for item in values
            if not (isinstance(item, str) and any(fragment in item for fragment in blocked_fragments))
        ]

    def _clean_summary_mapping(self, value: Any, *, label: str) -> dict[str, Any]:
        mapping = self._coerce_summary_mapping(value, label=label)
        if not mapping:
            return {}
        meaningful_values = [item for key, item in mapping.items() if key != "source"]
        if not meaningful_values or all(self._is_placeholder_text(item) for item in meaningful_values):
            return {}
        return mapping

    def _is_placeholder_text(self, value: Any) -> bool:
        text = self._compact_text(value, 260).lower()
        if not text:
            return True
        return text in {
            "continue",
            "manual draft",
            "manual rewrite",
            "manual chapter",
            "chapter-progress",
        } or text.startswith("codex hand-written")

    def _first_mapping_text(self, value: Any, keys: tuple[str, ...], fallback: str = "") -> str:
        if isinstance(value, dict):
            for key in keys:
                text = self._compact_text(value.get(key), 260)
                if text and not self._is_placeholder_text(text):
                    return text
            note = self._compact_text(value.get("note"), 260)
            if note and not self._is_placeholder_text(note):
                return note
            return fallback
        text = self._compact_text(value, 260)
        if text and not self._is_placeholder_text(text):
            return text
        return fallback

    def _hydrate_chapter_display_fields(self, chapter: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
        """Backfill workbench insight cards for legacy/manual file chapters.

        Generated bundles already carry these fields. Older restored chapters and
        hand-written rewrites may only have a chapter summary, which made the UI
        show empty "not organized yet" cards even though enough chapter state
        existed to present a useful reading report.
        """

        hydrated = dict(chapter)
        source_state = state if isinstance(state, dict) else self.state()
        hydrated = self._sanitize_legacy_chapter_artifacts(hydrated, source_state)
        summary = self._chapter_summary_payload(hydrated)
        summary_text = self._compact_text(summary.get("summary"), 260)
        next_focus = self._compact_text(summary.get("next_focus"), 220) or hydrated.get("next_outline") or "continue"

        if not isinstance(hydrated.get("chapter_intent"), dict) or not hydrated.get("chapter_intent"):
            primary = self._coerce_summary_mapping(summary.get("primary_conflict"), label="primary_conflict")
            secondary = self._coerce_summary_mapping(summary.get("secondary_conflict"), label="secondary_conflict")
            collision = self._first_mapping_text(primary, ("collision", "summary", "detail"), summary_text)
            hydrated["chapter_intent"] = {
                "chapter_title": summary.get("chapter_title"),
                "cadence": summary.get("cadence") or hydrated.get("cadence") or "measured",
                "next_focus": next_focus,
                "primary_conflict": primary | {"collision": collision},
                "secondary_conflict": secondary,
            }

        if not isinstance(hydrated.get("event_beat"), dict) or not hydrated.get("event_beat"):
            event_beat = self._coerce_summary_mapping(summary.get("event_beat"), label="event_beat")
            pivot = self._first_mapping_text(event_beat, ("pivot", "summary", "detail"), summary_text)
            hydrated["event_beat"] = {
                "turn": self._first_mapping_text(event_beat, ("turn",), "chapter-progress"),
                "pivot": pivot,
            }

        if not isinstance(hydrated.get("memory_constraints"), dict) or not hydrated.get("memory_constraints"):
            facts = [
                self._compact_text(item, 220)
                for item in (summary.get("facts") if isinstance(summary.get("facts"), list) else [])
                if str(item).strip() and not self._is_placeholder_text(item)
            ]
            hydrated["memory_constraints"] = {
                "must_keep_facts": facts[:8] or ([summary_text] if summary_text else []),
                "unresolved_threads": [
                    self._compact_text(item, 220)
                    for item in (
                        summary.get("unresolved_threads")
                        if isinstance(summary.get("unresolved_threads"), list)
                        else []
                    )
                    if str(item).strip()
                ][:8],
                "current_focus": next_focus,
            }

        if not isinstance(hydrated.get("character_moves"), list) or not hydrated.get("character_moves"):
            names = self._character_names_in_chapter(source_state, hydrated)
            if not names:
                for character in source_state.get("characters", []) if isinstance(source_state.get("characters"), list) else []:
                    if isinstance(character, dict) and str(character.get("name") or "").strip():
                        names = [str(character["name"]).strip()]
                        break
            hydrated["character_moves"] = [
                {
                    "name": name,
                    "goal": next_focus,
                    "action": summary_text,
                    "priority": index + 1,
                }
                for index, name in enumerate(names[:4])
            ]

        if not hydrated.get("next_outline") and next_focus:
            hydrated["next_outline"] = next_focus

        return hydrated

    def _sanitize_legacy_chapter_artifacts(
        self,
        chapter: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Hide stale cross-genre artifacts without rewriting accepted prose."""

        cleaned = deepcopy(chapter)
        project = self.project()
        game_story = self._is_game_story_payload(project, state)

        if not game_story:
            simulation_plan = cleaned.get("simulation_plan")
            if isinstance(simulation_plan, dict):
                world_context = simulation_plan.get("world_context")
                world_text = json.dumps(world_context, ensure_ascii=False).lower()
                game_markers = (
                    "world-pulse/v1",
                    "market_order_book",
                    "price_copper",
                    "white_robe_guild",
                    "service_npc",
                )
                if any(marker in world_text for marker in game_markers):
                    simulation_plan = dict(simulation_plan)
                    simulation_plan.pop("world_context", None)
                    cleaned["simulation_plan"] = simulation_plan

        summary = cleaned.get("chapter_summary")
        if isinstance(summary, dict):
            summary = dict(summary)
            primary = summary.get("primary_conflict")
            if isinstance(primary, dict):
                lead = str(primary.get("lead") or "").strip()
                opposition = str(primary.get("opposition") or "").strip()
                if lead and lead == opposition:
                    collision = str(primary.get("collision") or "").strip()
                    summary["primary_conflict"] = {}
                    event_beat = summary.get("event_beat")
                    if isinstance(event_beat, dict) and collision:
                        event_beat = dict(event_beat)
                        pivot = str(event_beat.get("pivot") or "")
                        if collision in pivot:
                            event_beat["pivot"] = pivot.replace(collision, "").strip(" ，。")
                        summary["event_beat"] = event_beat
                    cleaned["chapter_summary"] = summary

        return cleaned

    def _sanitize_story_state(self, state: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(state)
        ledger = sanitized.get("progression_ledger")
        if isinstance(ledger, dict):
            ledger = dict(ledger)
            economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
            if isinstance(economy.get("inventory"), dict):
                ledger.pop("inventory", None)
            if economy.get("game_currency") not in (None, "", [], {}):
                ledger.pop("currency", None)
            if isinstance(ledger.get("skills"), list):
                ledger["skills"] = [item for item in ledger["skills"] if "熟练度" not in str(item)]
                if not ledger["skills"]:
                    ledger.pop("skills", None)
            pressure = ledger.get("pressure") if isinstance(ledger.get("pressure"), dict) else {}
            next_pressure = pressure.get("next") if isinstance(pressure, dict) else None
            if isinstance(next_pressure, list):
                pressure = dict(pressure)
                pressure["next"] = [
                    "后坡探路前置已满足，但等级和补给仍压着风险"
                    if "熟练度" in str(item)
                    else item
                    for item in next_pressure
                ]
                ledger["pressure"] = pressure
            sanitized["progression_ledger"] = ledger
        sanitized["world_facts"] = self._clean_state_fact_list(sanitized.get("world_facts"))
        summaries: list[Any] = []
        changed = False
        for item in sanitized.get("chapter_summaries", []) if isinstance(sanitized.get("chapter_summaries"), list) else []:
            if not isinstance(item, dict):
                summaries.append(item)
                continue
            summary = dict(item)
            cleaned_facts = self._clean_state_fact_list(summary.get("facts"))
            if cleaned_facts != summary.get("facts"):
                summary["facts"] = cleaned_facts
                changed = True
            for field in ("primary_conflict", "secondary_conflict", "event_beat"):
                coerced = self._clean_summary_mapping(summary.get(field), label=field)
                if coerced != summary.get(field):
                    summary[field] = coerced
                    changed = True
            summaries.append(summary)
        deduped_summaries = self._dedupe_numbered_records(summaries)
        if changed or deduped_summaries != sanitized.get("chapter_summaries"):
            sanitized["chapter_summaries"] = deduped_summaries
        if isinstance(sanitized.get("timeline"), list):
            sanitized["timeline"] = self._dedupe_numbered_records(list(sanitized.get("timeline") or []))
        if isinstance(sanitized.get("memory_index"), list):
            memory_records = []
            for item in sanitized.get("memory_index") or []:
                if isinstance(item, dict):
                    record = dict(item)
                    record["facts"] = self._clean_state_fact_list(record.get("facts"))
                    memory_records.append(record)
                else:
                    memory_records.append(item)
            sanitized["memory_index"] = self._dedupe_numbered_records(memory_records)
        return sanitized

    def _strip_temporary_generation_fields(self, state: dict[str, Any]) -> dict[str, Any]:
        stripped = dict(state)
        ledger = stripped.get("progression_ledger")
        if not isinstance(ledger, dict):
            return stripped
        ledger = dict(ledger)
        variant = ledger.get("simulation_variant")
        if isinstance(variant, dict) and "rewrite_guidance" in variant:
            variant = dict(variant)
            variant.pop("rewrite_guidance", None)
            ledger["simulation_variant"] = variant
            stripped["progression_ledger"] = ledger
        return stripped

    def _validated_runtime_state(
        self,
        updated_story: Any,
        current_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(updated_story, dict) or not updated_story:
            return None
        if updated_story.get("story_id") != current_state.get("story_id"):
            return None
        if not all(
            isinstance(updated_story.get(field), str)
            for field in ("story_id", "outline", "genre", "style")
        ):
            return None
        chapter_number = updated_story.get("current_chapter")
        if not isinstance(chapter_number, int) or isinstance(chapter_number, bool) or chapter_number < 0:
            return None
        try:
            validated = StoryState.model_validate(updated_story)
        except (TypeError, ValueError):
            return None

        usable = validated.model_dump(mode="json")
        extra_contracts = {
            "time_state": lambda value: isinstance(value, dict),
            "novel_type": lambda value: isinstance(value, str),
            "novel_type_id": lambda value: isinstance(value, str),
            "novel_type_ids": lambda value: isinstance(value, list)
            and all(isinstance(item, str) for item in value),
        }
        for field, is_valid in extra_contracts.items():
            source = updated_story if field in updated_story else current_state
            value = source.get(field)
            if is_valid(value):
                usable[field] = deepcopy(value)
        return self._strip_temporary_generation_fields(usable)

    def _usable_bundle_state(
        self,
        updated_story: Any,
        current_state: dict[str, Any],
        *,
        target_chapter: int,
    ) -> dict[str, Any]:
        usable = self._validated_runtime_state(updated_story, current_state)
        if usable is None:
            return current_state
        try:
            bundle_chapter = int(usable.get("current_chapter") or 0)
            current_chapter = int(current_state.get("current_chapter") or 0)
        except (TypeError, ValueError):
            return current_state
        if bundle_chapter != target_chapter or bundle_chapter not in {
            current_chapter,
            current_chapter + 1,
        }:
            return current_state
        for field in ("timeline", "chapter_summaries", "memory_index"):
            current_records = current_state.get(field)
            usable_records = usable.get(field)
            if not isinstance(current_records, list):
                continue
            usable[field] = self._dedupe_numbered_records(
                [*current_records, *(usable_records if isinstance(usable_records, list) else [])]
            )
        return usable

    @staticmethod
    def _protagonist_ledger(state: dict[str, Any], *, chapter_number: int) -> dict[str, Any]:
        ledger = state.get("progression_ledger")
        protagonist = ledger.get("protagonist") if isinstance(ledger, dict) else None
        if not isinstance(protagonist, dict):
            raise ValueError(f"attribute_rebase_missing_protagonist:{chapter_number}")
        return protagonist

    @staticmethod
    def _replace_attribute_slice(state: dict[str, Any], attribute_slice: dict[str, Any]) -> None:
        fields = (
            "attributes",
            "unallocated_attribute_points",
            "attribute_point_awards",
            "attribute_allocations",
        )
        ledger = dict(state.get("progression_ledger") or {})
        protagonist = dict(ledger.get("protagonist") or {})
        for field in fields:
            protagonist[field] = deepcopy(attribute_slice[field])
        ledger["protagonist"] = protagonist
        state["progression_ledger"] = ledger

        for raw_character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(raw_character, dict):
                continue
            role = str(raw_character.get("role") or "").strip().casefold()
            tier = str(raw_character.get("character_tier") or "").strip().casefold()
            if role not in {"protagonist", "主角"} and tier != "protagonist":
                continue
            game_state = dict(raw_character.get("game_state") or {})
            current = dict(game_state.get("current") or {})
            panel = dict(raw_character.get("game_panel") or {})
            for field in fields:
                current[field] = deepcopy(attribute_slice[field])
                panel[field] = deepcopy(attribute_slice[field])
            game_state["current"] = current
            game_state.setdefault("recent_changes", [])
            raw_character["game_state"] = game_state
            raw_character["game_panel"] = panel

    @staticmethod
    def _parse_foreshadowing_ledger(raw_ledger: Any) -> list[ForeshadowingState]:
        if not isinstance(raw_ledger, (list, tuple)):
            return []
        parsed: list[ForeshadowingState] = []
        for item in raw_ledger:
            try:
                parsed.append(ForeshadowingState.model_validate(item))
            except ValidationError:
                continue
        return parsed

    @staticmethod
    def _foreshadowing_chapter_number(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            chapter_number = int(value)
        except (TypeError, ValueError):
            return None
        return chapter_number if chapter_number > 0 else None

    def _project_foreshadowing_history(
        self,
        existing_ledger: Any,
        chapters: list[dict[str, Any]],
        *,
        evidence_complete: bool,
        manual_ledger: Any = None,
    ) -> tuple[
        list[dict[str, Any]],
        dict[int, list[dict[str, Any]]],
        list[dict[str, Any]],
    ]:
        existing = self._parse_foreshadowing_ledger(existing_ledger)
        manual = self._parse_foreshadowing_ledger(manual_ledger)
        if not manual and manual_ledger is None:
            manual = [entry for entry in existing if entry.payoff_plan.strip()]
        manual_keys = {
            normalize_foreshadowing_text(entry.text) for entry in manual
        }
        if evidence_complete:
            pending_terminal = [
                entry
                for entry in canonicalize_foreshadowing_ledger([*existing, *manual])
                if entry.status == "resolved" and entry.resolved_chapter is not None
            ]
            ledger = canonicalize_foreshadowing_ledger(
                [
                    *[
                        entry
                        for entry in manual
                        if entry.status != "resolved" or entry.resolved_chapter is None
                    ],
                    *[
                        entry
                        for entry in existing
                        if (
                            entry.status == "expired"
                            or (entry.status == "resolved" and entry.resolved_chapter is None)
                        )
                        and normalize_foreshadowing_text(entry.text) not in manual_keys
                    ],
                ]
            )
        else:
            pending_terminal = []
            ledger = canonicalize_foreshadowing_ledger([*existing, *manual])

        by_chapter: dict[int, list[dict[str, Any]]] = {}
        for chapter in sorted(
            chapters,
            key=lambda item: self._foreshadowing_chapter_number(
                item.get("chapter_number")
            ) or 0,
        ):
            chapter_number = self._foreshadowing_chapter_number(
                chapter.get("chapter_number")
            )
            if chapter_number is None:
                continue
            summary = self._chapter_summary_payload(chapter)
            due_terminal = [
                entry
                for entry in pending_terminal
                if int(entry.resolved_chapter or 0) <= chapter_number
            ]
            if due_terminal:
                pending_terminal = [
                    entry for entry in pending_terminal if entry not in due_terminal
                ]
            ledger = reconcile_foreshadowing(
                [*ledger, *due_terminal],
                chapter_number=chapter_number,
                unresolved_threads=summary["unresolved_threads"],
                resolved_threads=summary["resolved_threads"],
            )
            by_chapter[chapter_number] = [entry.model_dump() for entry in ledger]

        if pending_terminal:
            ledger = reconcile_foreshadowing(
                [*ledger, *pending_terminal],
                chapter_number=max(by_chapter, default=0),
                unresolved_threads=[],
            )
        final = [entry.model_dump() for entry in ledger]
        manual_final = [
            entry.model_dump()
            for entry in ledger
            if normalize_foreshadowing_text(entry.text) in manual_keys
        ]
        return final, by_chapter, manual_final

    def _historical_foreshadowing_for_rewrite(
        self,
        replacement_chapter: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw_global = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        if not isinstance(raw_global, dict):
            return None
        target_chapter = self._foreshadowing_chapter_number(
            replacement_chapter.get("chapter_number")
        )
        current_chapter = self._foreshadowing_chapter_number(
            raw_global.get("current_chapter")
        )
        if (
            target_chapter is None
            or current_chapter is None
            or target_chapter >= current_chapter
        ):
            return None

        chapters_by_number = {target_chapter: replacement_chapter}
        available_numbers = {
            number for number in self.chapter_numbers() if number <= current_chapter
        }
        for chapter_number in sorted(available_numbers):
            if chapter_number > current_chapter or chapter_number == target_chapter:
                continue
            try:
                saved_chapter = self._read_json(
                    self.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
                    {},
                )
            except (OSError, ValueError):
                continue
            saved_chapter_number = (
                self._foreshadowing_chapter_number(saved_chapter.get("chapter_number"))
                if isinstance(saved_chapter, dict)
                else None
            )
            if saved_chapter_number == chapter_number:
                chapters_by_number[chapter_number] = saved_chapter

        expected_numbers = set(range(1, current_chapter + 1))
        summaries_complete = all(
            isinstance(chapter.get("chapter_summary"), dict)
            and isinstance(chapter["chapter_summary"].get("unresolved_threads"), list)
            for chapter in chapters_by_number.values()
        )
        evidence_complete = (
            expected_numbers == set(chapters_by_number)
            and summaries_complete
        )
        final_ledger, by_chapter, manual_ledger = self._project_foreshadowing_history(
            raw_global.get("foreshadowing"),
            list(chapters_by_number.values()),
            evidence_complete=evidence_complete,
            manual_ledger=raw_global.get("manual_foreshadowing"),
        )
        return {
            "final": final_ledger,
            "manual": manual_ledger,
            "by_chapter": by_chapter,
            "chapters": chapters_by_number,
            "evidence_complete": evidence_complete,
        }

    def _prepare_historical_attribute_rebase(
        self,
        chapter: dict[str, Any],
        updated_story: Any,
    ) -> tuple[dict[str, Any], dict[Path, Any]] | None:
        target_chapter = int(chapter.get("chapter_number") or 0)
        raw_global = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        if not isinstance(raw_global, dict):
            return None
        current_chapter = int(raw_global.get("current_chapter") or 0)
        if target_chapter >= current_chapter:
            return None

        project = self.project()
        blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        power_system = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), dict) else {}
        rule = normalize_attribute_allocation_rule(power_system.get("attribute_allocation"))
        if not rule:
            return None

        target_state = self._validated_runtime_state(updated_story, raw_global)
        if target_state is None or int(target_state.get("current_chapter") or 0) != target_chapter:
            raise ValueError(f"attribute_rebase_invalid_target_snapshot:{target_chapter}")
        prepared_chapter = self._hydrate_chapter_display_fields(deepcopy(chapter), target_state)
        target_state = self._sync_state_after_chapter(deepcopy(target_state), prepared_chapter)
        target_state = self._sync_ledger_from_chapter_body(target_state, prepared_chapter)
        target_state["current_chapter"] = target_chapter
        target_protagonist = self._protagonist_ledger(target_state, chapter_number=target_chapter)

        future_chapters: list[tuple[int, Path, dict[str, Any]]] = []
        future_protagonists: list[tuple[int, dict[str, Any]]] = []
        for chapter_number in range(target_chapter + 1, current_chapter + 1):
            path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
            raw_chapter = self._read_json(path)
            if not isinstance(raw_chapter, dict):
                raise ValueError(f"attribute_rebase_missing_future_chapter:{chapter_number}")
            snapshot = raw_chapter.get("updated_story")
            snapshot_chapter = snapshot.get("current_chapter") if isinstance(snapshot, dict) else None
            if (
                not isinstance(snapshot, dict)
                or isinstance(snapshot_chapter, bool)
                or not isinstance(snapshot_chapter, int)
                or snapshot_chapter != chapter_number
            ):
                raise ValueError(f"attribute_rebase_invalid_future_snapshot:{chapter_number}")
            protagonist = self._protagonist_ledger(snapshot, chapter_number=chapter_number)
            future_chapters.append((chapter_number, path, deepcopy(raw_chapter)))
            future_protagonists.append((chapter_number, protagonist))

        rebuilt = rebuild_attribute_progression(
            rule,
            target_chapter,
            target_protagonist,
            future_protagonists,
        )
        self._replace_attribute_slice(target_state, rebuilt[target_chapter])
        prepared_chapter["updated_story"] = target_state
        prepared_chapter["chapter_summary"] = self._chapter_summary_payload(prepared_chapter)

        payloads: dict[Path, Any] = {}
        for chapter_number, path, future_chapter in future_chapters:
            snapshot = deepcopy(future_chapter["updated_story"])
            self._replace_attribute_slice(snapshot, rebuilt[chapter_number])
            StoryState.model_validate(snapshot)
            future_chapter["updated_story"] = snapshot
            payloads[path] = future_chapter

        rebuilt_global = deepcopy(raw_global)
        self._replace_attribute_slice(rebuilt_global, rebuilt[current_chapter])
        StoryState.model_validate(target_state)
        StoryState.model_validate(rebuilt_global)
        payloads[self.webnovel_dir / "state.json"] = rebuilt_global
        return prepared_chapter, payloads

    def _chapter_summary_payload(self, chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        summary = dict(chapter.get("chapter_summary") or {})
        title = str(chapter.get("chapter_title") or summary.get("chapter_title") or f"Chapter {chapter_number}")
        summary_text = self._compact_text(summary.get("summary") or chapter.get("next_outline") or chapter.get("body"), 320)
        raw_facts = summary.get("facts") if isinstance(summary.get("facts"), list) else []
        facts = [self._compact_text(item, 220) for item in raw_facts if str(item).strip()]
        if summary_text and not facts:
            facts = [summary_text]
        return {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "cadence": summary.get("cadence") or chapter.get("cadence") or "measured",
            "summary": summary_text or f"Chapter {chapter_number}.",
            "facts": facts[:8],
            "unresolved_threads": [
                self._compact_text(item, 220)
                for item in (summary.get("unresolved_threads") if isinstance(summary.get("unresolved_threads"), list) else [])
                if str(item).strip()
            ][:8],
            "resolved_threads": [
                self._compact_text(item, 220)
                for item in (summary.get("resolved_threads") if isinstance(summary.get("resolved_threads"), list) else [])
                if str(item).strip()
            ][:8],
            "next_focus": self._compact_text(
                summary.get("next_focus")
                or chapter.get("next_outline")
                or (chapter.get("event_plan") or {}).get("next_focus")
                or "continue",
                220,
            ),
            "primary_conflict": self._coerce_summary_mapping(
                summary.get("primary_conflict") or chapter.get("conflict_summary", {}).get("primary_conflict"),
                label="primary_conflict",
            ),
            "secondary_conflict": self._coerce_summary_mapping(
                summary.get("secondary_conflict") or chapter.get("conflict_summary", {}).get("secondary_conflict"),
                label="secondary_conflict",
            ),
            "event_beat": self._coerce_summary_mapping(
                summary.get("event_beat") or chapter.get("event_beat"),
                label="event_beat",
            ),
        }

    def _replace_by_chapter_number(self, items: list[Any], entry: dict[str, Any], *, limit: int = 120) -> list[Any]:
        chapter_number = entry.get("chapter_number")
        filtered = [
            item
            for item in items
            if not (
                (isinstance(item, dict) and item.get("chapter_number") == chapter_number)
                or (
                    isinstance(item, str)
                    and chapter_number is not None
                    and re.match(rf"^\s*chapter\s+{int(chapter_number)}\s*:", item, re.IGNORECASE)
                )
            )
        ]
        filtered.append(entry)
        filtered.sort(key=lambda item: int(item.get("chapter_number") or 0) if isinstance(item, dict) else 0)
        return filtered[-limit:]

    def _dedupe_numbered_records(self, items: list[Any], *, limit: int = 240) -> list[Any]:
        """Keep one structured record per chapter and drop stale manual shells."""

        records: list[Any] = []
        seen_titles_by_number: dict[int, str] = {}
        for item in items:
            if isinstance(item, dict):
                try:
                    number = int(item.get("chapter_number") or 0)
                except (TypeError, ValueError):
                    number = 0
                title = str(item.get("chapter_title") or "").strip()
                if number > 0:
                    seen_titles_by_number[number] = title
                    records = [
                        existing
                        for existing in records
                        if not (
                            isinstance(existing, dict)
                            and int(existing.get("chapter_number") or 0) == number
                        )
                    ]
                    records.append(item)
                    continue
                if title and title not in seen_titles_by_number.values():
                    records.append(item)
                continue
            if isinstance(item, str) and re.match(r"^\s*chapter\s+\d+\s*:", item, re.IGNORECASE):
                continue
            records.append(item)
        numbered_titles = {title for title in seen_titles_by_number.values() if title}
        records = [
            item
            for item in records
            if not (
                isinstance(item, dict)
                and not int(item.get("chapter_number") or 0)
                and str(item.get("chapter_title") or "").strip() in numbered_titles
            )
        ]
        records.sort(key=lambda item: int(item.get("chapter_number") or 0) if isinstance(item, dict) else 0)
        return records[-limit:]

    def _derive_opening_progression_ledger(self, chapters: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
        """Rebuild the current game ledger from accepted opening chapters."""

        ledger = dict(current)
        text = "\n".join(
            str(part or "")
            for chapter in chapters
            for part in (
                chapter.get("body"),
                (chapter.get("chapter_summary") or {}).get("summary"),
                "\n".join(str(item) for item in ((chapter.get("chapter_summary") or {}).get("facts") or [])),
                (chapter.get("chapter_summary") or {}).get("next_focus"),
            )
        )
        progression_text = "\n".join(
            _without_monster_stat_surfaces(str(chapter.get("body") or ""))
            for chapter in chapters
        )
        protagonist = dict(ledger.get("protagonist") or {})
        panel = dict(ledger.get("panel") or {})
        economy = dict(ledger.get("economy") or {})
        equipment = dict(ledger.get("equipment") or {})
        quests = dict(ledger.get("quests") or {})

        level_matches = re.findall(
            r"(?:等级提升至|升级到|升级至|升到|当前等级[：:]?|等级[：:]?|level\s*[:=]?)\s*(?:Lv\.?)?\s*(\d+)",
            progression_text,
            flags=re.IGNORECASE,
        )
        compact_panel_levels = re.findall(
            r"【[^】]{1,24}；\s*Lv\.?\s*(\d+)(?=[^】]{0,24}(?:经验|生命|法力|可用属性点))",
            progression_text,
            flags=re.IGNORECASE,
        )
        if compact_panel_levels:
            level_matches = compact_panel_levels
        if not level_matches and "Lv.2" in progression_text and any(
            token in progression_text for token in ("升到", "升级", "等级", "提升")
        ):
            level_matches = ["2"]
        if level_matches:
            level = f"Lv.{int(level_matches[-1])}"
            protagonist["level"] = level
            panel["level"] = level
        if "见习者" in text or "见习冒险者" in text or "未转职" in text:
            protagonist["identity"] = "见习者（未转职）"
            protagonist["class_path"] = "见习者（未转职）"
            panel["identity"] = "见习者（未转职）"

        exp_matches = re.findall(r"经验\s*([0-9]+\s*/\s*[0-9]+)", progression_text)
        if exp_matches:
            protagonist["exp"] = re.sub(r"\s+", "", exp_matches[-1])
        elif "等级升到Lv.2" in text or "Lv.2" in text:
            protagonist.setdefault("exp", "12/200")

        durability_matches = re.findall(
            r"(?:新手法杖[：:]\s*|法杖[^，。；\n]{0,12})(\d{1,2}\s*/\s*\d{1,2})",
            progression_text,
        )
        if durability_matches:
            equipment["weapon"] = "新手法杖"
            equipment["durability"] = re.sub(r"\s+", "", durability_matches[-1])
            protagonist["weapon_durability"] = f"新手法杖：{equipment['durability']}"
        elif "新手法杖" in text:
            equipment.setdefault("weapon", "新手法杖")

        inventory = self._derive_opening_inventory(chapters)
        if inventory:
            economy["inventory"] = inventory
        if "钱袋：空" in text or "钱袋空" in text or "钱袋又空" in text:
            economy["game_currency"] = "空"
        elif "30铜" in text or "三十铜" in text:
            economy["game_currency"] = "30铜"
        real_balance_matches = re.findall(
            r"(?:银行卡可用余额|现实余额|可用余额|账户余额|余额)\s*(?:[：:]\s*)?(?:只剩|还有|变成|变为|为)?\s*(\d+(?:\.\d{1,2})?)\s*元",
            text,
        )
        if real_balance_matches:
            economy["real_balance"] = f"{real_balance_matches[-1]}元"
        if "清道夫委托已提交" in text or "清道夫委托完成" in text:
            quests["清道夫委托"] = "已提交；奖励30铜已领取"
        if "后坡登记" in text:
            quests["后坡登记"] = "清道夫委托完成后已开启，夜烬已进入后坡第一段"
        if "灰石裂缝" in text:
            quests["灰石裂缝"] = "已发现；混沌之种出现第二次响应"

        if protagonist:
            ledger["protagonist"] = protagonist
        if panel:
            ledger["panel"] = panel
        if economy:
            ledger["economy"] = economy
            ledger.pop("currency", None)
            ledger.pop("inventory", None)
        if equipment:
            ledger["equipment"] = equipment
        if quests:
            ledger["quests"] = quests
        return ledger

    def _chapter_text_for_ledger(self, chapter: dict[str, Any]) -> str:
        summary = chapter.get("chapter_summary") if isinstance(chapter.get("chapter_summary"), dict) else {}
        return "\n".join(
            str(part or "")
            for part in (
                chapter.get("body"),
                summary.get("summary"),
                "\n".join(str(item) for item in (summary.get("facts") or [])),
                summary.get("next_focus"),
            )
        )

    def _derive_opening_inventory(self, chapters: list[dict[str, Any]]) -> dict[str, int]:
        inventory: dict[str, int] = {}
        tracked = {"灰狼毒腺", "粗糙狼皮", "小法力药水"}
        for chapter in sorted(chapters, key=lambda item: int(item.get("chapter_number") or 0)):
            text = self._chapter_text_for_ledger(chapter)
            scoped_backpacks = [
                item
                for item in re.findall(r"背包[^。\n】]*", text)
                if any(name in item and "×" in item for name in tracked)
            ]
            if scoped_backpacks:
                scoped: dict[str, int] = {}
                for name, count in re.findall(r"([\u4e00-\u9fa5A-Za-z0-9·]+)\s*[×xX]\s*(\d+)", scoped_backpacks[-1]):
                    if name in tracked:
                        scoped[name] = int(count)
                if scoped:
                    inventory.update(scoped)
            if "清道夫委托已提交" in text or "清道夫委托完成" in text:
                inventory["灰狼毒腺"] = 0
            if int(chapter.get("chapter_number") or 0) > 2:
                for name, count in re.findall(r"([\u4e00-\u9fa5A-Za-z0-9·]+)\s*[×xX]\s*(\d+)", text):
                    if name in {"灰狼毒腺", "粗糙狼皮"}:
                        inventory[name] = int(inventory.get(name, 0)) + int(count)
            if "喝掉了小法力药水" in text and inventory.get("小法力药水", 0) > 0:
                inventory["小法力药水"] = int(inventory["小法力药水"]) - 1
        return inventory

    def _character_names_in_chapter(self, state: dict[str, Any], chapter: dict[str, Any]) -> list[str]:
        text = "\n".join(
            [
                str(chapter.get("chapter_title") or ""),
                str(chapter.get("body") or ""),
                str((chapter.get("chapter_summary") or {}).get("summary") or ""),
            ]
        )
        names: list[str] = []
        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict):
                continue
            name = str(character.get("name") or "").strip()
            game_id = str(character.get("game_id") or (character.get("game_panel") or {}).get("game_id") or "").strip()
            if (name and name in text) or (game_id and game_id in text):
                names.append(name or game_id)
        for move in chapter.get("character_moves", []) if isinstance(chapter.get("character_moves"), list) else []:
            if isinstance(move, dict) and str(move.get("name") or "").strip():
                names.append(str(move["name"]).strip())
        return self._merge_unique([], names, limit=16)

    def _chapter_entity_cards(self, chapter: dict[str, Any]) -> list[dict[str, Any]]:
        """Infer trackable NPC/system cards from visible chapter text.

        Web-game chapters often introduce durable entities as services or
        information surfaces rather than named people. They still need cards so
        later simulation can remember their boundaries.
        """
        chapter_number = int(chapter.get("chapter_number") or 0)
        text = "\n".join(
            [
                str(chapter.get("chapter_title") or ""),
                str(chapter.get("body") or ""),
                str((chapter.get("chapter_summary") or {}).get("summary") or ""),
            ]
        )
        specs = [
            {
                "name": "论坛",
                "triggers": ("论坛", "帖子"),
                "role": "信息源",
                "location": "内置论坛",
                "goal": "提供玩家传闻、掉率基准、价格噪声和开服情报",
                "memory": "论坛已出现为开服信息源：掉率、坐标、材料价格和玩家抱怨都从这里进入叙事。",
                "active": True,
            },
            {
                "name": "公共频道",
                "triggers": ("公共频道", "世界频道"),
                "role": "玩家群体",
                "location": "聊天频道",
                "goal": "暴露散人玩家情绪、抢怪冲突、组队需求和即时传闻",
                "memory": "公共频道持续滚动玩家喊话，是低可信但高频的世界噪声。",
                "active": False,
            },
            {
                "name": "交易行告示牌",
                "triggers": ("交易行", "告示牌", "求购："),
                "role": "市场机制",
                "location": "起始村广场",
                "goal": "显示求购单、均价、成交量和区域材料流通预警",
                "memory": "交易行告示牌已显示灰狼毒腺求购、均价和材料流通预警，是经济线的可见界面。",
                "active": True,
            },
            {
                "name": "药剂师NPC",
                "triggers": ("药剂师", "药剂铺"),
                "role": "服务NPC",
                "location": "起始村药剂铺",
                "goal": "按规则收取任务材料、出售法力药水并提示下一环任务",
                "memory": "药剂师NPC负责委托、药水价格和材料提交，话术机械且边界明确。",
                "active": True,
            },
            {
                "name": "药剂铺老妇人",
                "triggers": ("灰头巾老妇人", "老妇人", "药剂铺"),
                "role": "服务NPC",
                "location": "起始村药剂铺",
                "goal": "执行药剂铺收货规则：十份一批，少了不收",
                "memory": "药剂铺老妇人明确毒腺十份一批，不零收；单份交易需走交易木牌。",
                "active": False,
            },
            {
                "name": "清道夫委托",
                "triggers": ("清道夫委托", "提交十份灰狼毒腺"),
                "role": "任务线",
                "location": "起始村药剂铺",
                "goal": "用灰狼毒腺回收驱动新手任务，并逐步提高材料要求",
                "memory": "清道夫委托一环需要十份灰狼毒腺，奖励三十铜；下一环需要灰狼心脏。",
                "active": True,
            },
            {
                "name": "铁匠铺自助修理台",
                "triggers": ("自助修理台", "铁匠铺", "修复新手法杖"),
                "role": "服务设施",
                "location": "起始村铁匠铺",
                "goal": "提供装备修复并扣除铜币",
                "memory": "铁匠铺自助修理台可修复新手法杖，当前修复成本为三铜。",
                "active": False,
            },
            {
                "name": "系统公告",
                "triggers": ("系统滚动条", "系统公告", "区域材料流通预警"),
                "role": "系统机制",
                "location": "玩家界面",
                "goal": "以可见公告暴露协议提示、任务进度和风险变化",
                "memory": "系统公告/滚动条已用于呈现底层协议、隐藏优势和任务/路线进度反馈。",
                "active": True,
            },
        ]
        cards: list[dict[str, Any]] = []
        for spec in specs:
            if not any(trigger and trigger in text for trigger in spec["triggers"]):
                continue
            active = bool(spec["active"])
            active_triggers = spec.get("active_triggers")
            if isinstance(active_triggers, tuple) and any(trigger and trigger in text for trigger in active_triggers):
                active = True
            cards.append(
                {
                    "name": spec["name"],
                    "role": spec["role"],
                    "game_id": "",
                    "goals": [spec["goal"]],
                    "memory": [f"第{chapter_number}章：{spec['memory']}"] if chapter_number else [spec["memory"]],
                    "relationships": {},
                    "current_emotion": "steady",
                    "location": spec["location"],
                    "secrets": [],
                    "frozen": False,
                    "lifecycle_state": "active" if active else "proposed",
                    "last_proposed_chapter": chapter_number,
                    "last_approved_chapter": chapter_number if active else 0,
                    "introduced_by": f"chapter:{chapter_number}" if chapter_number else "chapter",
                    "npc_profile": {
                        "service_role": spec["role"],
                        "authority_scope": [spec["goal"]],
                        "information_limits": ["只能提供正文已可见的信息，不替作者解释规则。"],
                        "incentives": [],
                        "interaction_rules": ["作为界面、服务或NPC边界参与推演。"],
                    },
                }
            )
        return cards

    def _outline_text_for_chapter(self, project: dict[str, Any], chapter_number: int) -> str:
        blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        opening_arc = blueprint.get("opening_arc") if isinstance(blueprint.get("opening_arc"), dict) else {}
        beats = opening_arc.get("chapter_beats") if isinstance(opening_arc.get("chapter_beats"), list) else []
        parts = [str(project.get("current_focus") or ""), str(blueprint.get("current_arc") or "")]
        for beat in beats:
            if isinstance(beat, dict) and int(beat.get("chapter") or 0) == chapter_number:
                parts.extend(str(beat.get(key) or "") for key in ("title", "required_payoff", "ending_hook"))
        return "\n".join(parts)

    def _proposed_character_cards_from_outline(self, state: dict[str, Any], project: dict[str, Any]) -> list[dict[str, Any]]:
        target = int(state.get("current_chapter") or 0) + 1
        text = self._outline_text_for_chapter(project, target)
        specs: list[dict[str, Any]] = []
        if "村长" in text:
            specs.append(
                {
                    "name": "灰烬村村长",
                    "role": "村内任务NPC",
                    "location": "灰烬村",
                    "goals": ["只按村内记录和任务前置放行，不主动透露隐藏线。"],
                    "memory": [f"第{target}章大纲可能需要村长承接灰石裂缝记录。"],
                    "character_type": "任务节点NPC",
                    "core_motivation": "维护村内任务秩序，避免异常记录扩散。",
                    "behavior_logic": "只承认可见记录，不承认玩家猜测。",
                    "interaction_mode": "说话像办手续，能给的只给一半。",
                    "story_function": "承接隐藏路线和任务权限。",
                    "chapter_role": f"第{target}章待出场",
                }
            )
        cards: list[dict[str, Any]] = []
        for spec in specs:
            cards.append(
                {
                    **spec,
                    "current_emotion": "steady",
                    "frozen": False,
                    "lifecycle_state": "proposed",
                    "last_proposed_chapter": target,
                    "last_approved_chapter": 0,
                    "introduced_by": f"outline:{target}",
                    "npc_profile": {
                        "service_role": spec["role"],
                        "authority_scope": spec["goals"],
                        "information_limits": ["出场前只作为写作包候选卡；正文未写到之前不能当成已出场事实。"],
                        "interaction_rules": ["如果本章使用这个人物，必须先按角色卡写，不得临场换身份。"],
                    },
                }
            )
        return cards

    def _canonical_character_name(self, name: str) -> str:
        aliases = {
            "药剂师NPC": "药剂师洛婶",
            "药剂师": "药剂师洛婶",
            "药剂铺老妇人": "药剂师洛婶",
            "灰头巾老妇人": "药剂师洛婶",
            "老妇人": "药剂师洛婶",
            "洛婶": "药剂师洛婶",
            "补给商·铁栓": "仓库管理员铁栓",
            "补给商铁栓": "仓库管理员铁栓",
            "铁栓": "仓库管理员铁栓",
        }
        return aliases.get(name.strip(), name.strip())

    def _is_character_card(self, card: dict[str, Any]) -> bool:
        name = self._canonical_character_name(str(card.get("name") or ""))
        role = str(card.get("role") or "").strip()
        if not name:
            return False
        if is_non_character_card({**card, "name": name, "role": role}):
            return False
        return True

    def _merge_character_cards(self, existing: list[Any], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_name: dict[str, dict[str, Any]] = {}
        for item in existing:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            name = self._canonical_character_name(str(item.get("name") or ""))
            if name:
                item["name"] = name
            if not self._is_character_card(item):
                continue
            if name:
                by_name[name] = dict(item)
        for card in additions:
            card = dict(card)
            name = self._canonical_character_name(str(card.get("name") or ""))
            if not name:
                continue
            card["name"] = name
            if not self._is_character_card(card):
                continue
            current = dict(by_name.get(name) or {"name": name})
            current["role"] = current.get("role") or card.get("role") or "NPC"
            current["game_id"] = current.get("game_id") or card.get("game_id") or ""
            if card.get("game_panel"):
                panel = dict(current.get("game_panel") or {})
                panel.update({key: value for key, value in dict(card.get("game_panel") or {}).items() if value not in (None, "", [], {})})
                current["game_panel"] = panel
            for field in (
                "character_type",
                "core_motivation",
                "behavior_logic",
                "interaction_mode",
                "story_function",
                "chapter_role",
                "social_profile",
                "psychological_profile",
                "moral_profile",
                "performance_profile",
            ):
                if field == "performance_profile" and isinstance(current.get(field), dict) and isinstance(card.get(field), dict):
                    profile = dict(current[field])
                    legacy_speech = "白话、完整、少装腔；解释选择时把原因说清。"
                    if profile.get("speech_style") == legacy_speech and card[field].get("speech_style"):
                        profile["speech_style"] = card[field]["speech_style"]
                    current[field] = profile
                    continue
                if card.get(field) and not current.get(field):
                    current[field] = card[field]
            current["goals"] = self._merge_unique(list(current.get("goals") or []), list(card.get("goals") or []), limit=8)
            current["memory"] = self._merge_unique(list(current.get("memory") or []), list(card.get("memory") or []), limit=20)
            current["poison_points"] = self._merge_unique(
                list(current.get("poison_points") or []),
                list(card.get("poison_points") or []),
                limit=8,
            )
            current["location"] = card.get("location") or current.get("location") or ""
            current["current_emotion"] = current.get("current_emotion") or card.get("current_emotion") or "steady"
            current["relationships"] = current.get("relationships") or {}
            current["secrets"] = current.get("secrets") or []
            current["frozen"] = bool(current.get("frozen") or False)
            if current.get("lifecycle_state") != "active":
                current["lifecycle_state"] = card.get("lifecycle_state") or current.get("lifecycle_state") or "proposed"
            current["last_proposed_chapter"] = max(
                int(current.get("last_proposed_chapter") or 0),
                int(card.get("last_proposed_chapter") or 0),
            )
            current["last_approved_chapter"] = max(
                int(current.get("last_approved_chapter") or 0),
                int(card.get("last_approved_chapter") or 0),
            )
            current["introduced_by"] = current.get("introduced_by") or card.get("introduced_by") or ""
            if card.get("npc_profile") and not current.get("npc_profile"):
                current["npc_profile"] = card["npc_profile"]
            by_name[name] = current
        return list(by_name.values())

    def _protagonist_character_card(self, state: dict[str, Any], project: dict[str, Any] | None = None) -> dict[str, Any] | None:
        ledger = state.get("progression_ledger") if isinstance(state.get("progression_ledger"), dict) else {}
        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
        if not protagonist:
            return None
        economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
        real = ledger.get("real") if isinstance(ledger.get("real"), dict) else {}
        equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
        quests = ledger.get("quests") if isinstance(ledger.get("quests"), dict) else {}
        name = str(protagonist.get("real_name") or "").strip()
        game_id = str(protagonist.get("game_id") or "").strip()
        if not name and not game_id:
            return None
        current_chapter = int(state.get("current_chapter") or 0)
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}
        skills = protagonist.get("skills") if isinstance(protagonist.get("skills"), list) else []
        weapon = str(equipment.get("weapon") or "新手法杖").strip()
        durability = str(equipment.get("durability") or protagonist.get("weapon_durability") or "").strip()
        current_goal = "推进当前游戏目标。"
        recovered_memory: list[str] = []
        real_balance = real.get("end_balance") or real.get("balance")
        if real_balance:
            recovered_memory.append(f"当前现实余额：{real_balance}。")
        level = protagonist.get("level") or ""
        exp = protagonist.get("exp") or ""
        if level or exp:
            recovered_memory.append(f"当前游戏进度：{level}，经验{exp}。")
        return {
            "name": name or game_id,
            "role": "protagonist",
            "game_id": game_id,
            "character_type": "现实压力型网游主角",
            "core_motivation": "先解决现实账单，再把千倍爆率藏在幕后，换成等级、装备、路线和交易渠道优势。",
            "behavior_logic": "先看成本、退路和暴露风险，再动手；能用规则和地形解决，就不正面炫耀。",
            "interaction_mode": "对外少说异常，只说够用的理由；面对NPC按规则办事，面对玩家保持普通新手的样子。",
            "story_function": "承载现实压力、隐藏优势和新手村快速成长线。",
            "chapter_role": "主视角",
            "goals": [current_goal],
            "memory": recovered_memory,
            "location": str(protagonist.get("location") or state.get("current_location") or ""),
            "current_emotion": "克制",
            "secrets": ["掉落判定×1000", "混沌之种未解析"],
            "poison_points": ["不能写成装高手", "不能让外人全知主角异常", "对话要口语化并说完整"],
            "game_panel": {
                "game_id": game_id,
                "level": protagonist.get("level") or (ledger.get("panel") or {}).get("level"),
                "class_path": protagonist.get("class_path") or protagonist.get("identity") or "见习者（未转职）",
                "exp": protagonist.get("exp") or "",
                "hp": protagonist.get("hp") or "",
                "mp": protagonist.get("mp") or "",
                "skills": skills,
                "equipment": {
                    "武器": weapon,
                    "耐久": durability,
                    "强化": equipment.get("modifier") or "",
                },
                "inventory": inventory,
                "currency": economy.get("game_currency") or "",
                "quests": quests,
                "updated_chapter": current_chapter,
            },
            "performance_profile": {
                "speech_style": "白话、完整、少装腔；只说当下会说的话，理由藏在语气、动作和必要回答里。",
                "action_style": "先观察规则和地形，再做低风险动作。",
                "risk_posture": "隐藏异常收益，避免被玩家和NPC提前盯上。",
                "decision_rules": ["不公开千倍爆率", "优先解决现实压力和游戏内续航", "每章要有可见成长"],
            },
            "frozen": False,
            "lifecycle_state": "active",
            "last_proposed_chapter": current_chapter,
            "last_approved_chapter": current_chapter,
            "introduced_by": "baseline:protagonist",
        }

    def _infer_chapter_duration_minutes(self, chapter: dict[str, Any]) -> int:
        text = "\n".join([str(chapter.get("body") or ""), str((chapter.get("chapter_summary") or {}).get("summary") or "")])
        explicit_minutes = [int(value) for value in re.findall(r"(\d{1,3})\s*分钟", text)]
        if explicit_minutes:
            return max(10, min(240, explicit_minutes[-1]))
        explicit_hours = [int(value) for value in re.findall(r"(\d{1,2})\s*小时", text)]
        if explicit_hours:
            return max(30, min(360, explicit_hours[-1] * 60))
        if any(token in text for token in ("回村", "交任务", "修复", "购买", "寄售", "职业大厅")):
            return 45
        if any(token in text for token in ("灰狼坡深处", "副本", "试炼", "赶路", "采样")):
            return 60
        return 40

    def _clock_label(self, minutes_since_launch: int) -> str:
        day = minutes_since_launch // (24 * 60) + 1
        minute_of_day = minutes_since_launch % (24 * 60)
        if minute_of_day < 5 * 60:
            phase = "深夜"
        elif minute_of_day < 8 * 60:
            phase = "清晨"
        elif minute_of_day < 12 * 60:
            phase = "上午"
        elif minute_of_day < 14 * 60:
            phase = "中午"
        elif minute_of_day < 18 * 60:
            phase = "下午"
        elif minute_of_day < 21 * 60:
            phase = "傍晚"
        else:
            phase = "夜晚"
        return f"开服第{day}天{phase}"

    def _sync_time_state_after_chapter(self, state: dict[str, Any], project: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            return {}
        existing = dict(state.get("time_state") or ((project.get("world_blueprint") or {}).get("time_state") or {}))
        launch_offset = int(existing.get("launch_clock_offset_minutes") or 17 * 60)
        previous_elapsed = int(existing.get("elapsed_minutes_since_launch") or 0)
        spans = [
            dict(item)
            for item in existing.get("chapter_time_spans", [])
            if isinstance(item, dict) and int(item.get("chapter_number") or 0) != chapter_number
        ]
        # Replaying earlier chapters should rebuild elapsed time from the remaining spans.
        previous_elapsed = sum(int(item.get("duration_minutes") or 0) for item in spans)
        duration = self._infer_chapter_duration_minutes(chapter)
        start_label = self._clock_label(launch_offset + previous_elapsed)
        end_minutes = previous_elapsed + duration
        end_label = self._clock_label(launch_offset + end_minutes)
        span = {
            "chapter_number": chapter_number,
            "chapter_title": chapter.get("chapter_title") or f"Chapter {chapter_number}",
            "start": start_label,
            "end": end_label,
            "duration_minutes": duration,
            "scene_time": f"第{chapter_number}章章末",
        }
        spans.append(span)
        spans.sort(key=lambda item: int(item.get("chapter_number") or 0))
        total_elapsed = sum(int(item.get("duration_minutes") or 0) for item in spans)
        day = total_elapsed // (24 * 60) + 1
        time_state = {
            "server_day": day,
            "server_phase": f"开服第{day}天",
            "game_clock": self._clock_label(launch_offset + total_elapsed).replace(f"开服第{day}天", "") or "开服初期",
            "real_clock": existing.get("real_clock") or "晚上",
            "launch_clock_offset_minutes": launch_offset,
            "current_scene_time": f"第{chapter_number}章章末",
            "elapsed_minutes_since_launch": total_elapsed,
            "elapsed_since_launch": f"约{max(1, round(total_elapsed / 60, 1))}小时",
            "chapter_time_spans": spans[-120:],
            "cooldowns": existing.get("cooldowns") or [],
            "scheduled_events": existing.get("scheduled_events") or [],
            "time_rules": self._merge_unique(
                list(existing.get("time_rules") or []),
                [
                    "下一章必须承接 current_scene_time，除非正文明确下线、过夜或长途赶路。",
                    "前期开服节奏按小时推进，不要无说明跳到第二天或跨越大量任务。",
                    "寄售、任务、怪物刷新和NPC服务需要写出等待、路程或冷却代价。",
                ],
                limit=20,
            ),
        }
        state["time_state"] = time_state
        return time_state

    def _sync_state_after_chapter(self, state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            return state
        synced = dict(state)
        summary = self._chapter_summary_payload(chapter)
        foreshadowing = self._parse_foreshadowing_ledger(synced.get("foreshadowing"))
        reconciled_foreshadowing = reconcile_foreshadowing(
            foreshadowing,
            chapter_number=chapter_number,
            unresolved_threads=summary["unresolved_threads"],
            resolved_threads=summary["resolved_threads"],
        )
        synced["foreshadowing"] = [
            item.model_dump() for item in reconciled_foreshadowing
        ]
        if "manual_foreshadowing" in synced:
            manual_keys = {
                normalize_foreshadowing_text(item.text)
                for item in self._parse_foreshadowing_ledger(
                    synced.get("manual_foreshadowing")
                )
            }
            synced["manual_foreshadowing"] = [
                item.model_dump()
                for item in reconciled_foreshadowing
                if normalize_foreshadowing_text(item.text) in manual_keys
            ]
        synced["current_chapter"] = max(int(synced.get("current_chapter") or 0), chapter_number)
        synced["chapter_summaries"] = self._replace_by_chapter_number(
            list(synced.get("chapter_summaries") or []),
            summary,
            limit=240,
        )
        chapter_fact_prefix = f"第{chapter_number}章事实："
        chapter_summary_prefix = f"第{chapter_number}章摘要："
        existing_world_facts = [
            str(item)
            for item in list(synced.get("world_facts") or [])
            if not str(item).startswith(chapter_fact_prefix) and not str(item).startswith(chapter_summary_prefix)
        ]
        facts = [f"第{chapter_number}章事实：{fact}" for fact in summary["facts"]]
        facts.append(f"第{chapter_number}章摘要：{summary['summary']}")
        synced["world_facts"] = self._merge_unique(existing_world_facts, facts, limit=260)
        timeline_entry = {
            "chapter_number": chapter_number,
            "summary": summary["summary"],
            "impact": summary["next_focus"],
        }
        synced["timeline"] = self._replace_by_chapter_number(
            list(synced.get("timeline") or []),
            timeline_entry,
            limit=240,
        )
        memory_entry = {
            "chapter_number": chapter_number,
            "chapter_title": summary["chapter_title"],
            "summary": summary["summary"],
            "tags": [],
            "characters": self._character_names_in_chapter(synced, chapter),
            "locations": [],
            "factions": [],
            "quests": [],
            "items": [],
            "facts": summary["facts"],
            "unresolved_threads": summary["unresolved_threads"],
            "resolved_threads": summary["resolved_threads"],
        }
        current_project = self.project()
        is_game_story = self._is_game_story_payload(current_project, synced)
        protagonist_card = (
            self._protagonist_character_card(synced, current_project)
            if is_game_story
            else None
        )
        protagonist_cards = [protagonist_card] if protagonist_card else []
        entity_cards = self._chapter_entity_cards(chapter) if is_game_story else []
        synced["characters"] = self._merge_character_cards(
            list(synced.get("characters") or []),
            [*protagonist_cards, *entity_cards],
        )
        character_entity_names = [
            self._canonical_character_name(str(card.get("name") or ""))
            for card in entity_cards
            if self._is_character_card(card)
        ]
        memory_entry["characters"] = self._merge_unique(
            list(memory_entry["characters"]),
            [*([str(protagonist_card["name"])] if protagonist_card else []), *character_entity_names],
            limit=24,
        )
        synced["memory_index"] = self._replace_by_chapter_number(
            list(synced.get("memory_index") or []),
            memory_entry,
            limit=240,
        )
        if is_game_story:
            self._sync_time_state_after_chapter(synced, current_project, chapter)
        else:
            synced.pop("time_state", None)
        return synced

    def _sync_project_after_chapter(self, project: dict[str, Any], state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            return project
        summary = self._chapter_summary_payload(chapter)
        synced = dict(project)
        synced["current_chapter"] = chapter_number
        is_game_story = self._is_game_story_payload(synced, state)
        blueprint = dict(synced.get("world_blueprint") or {})
        equipment_merge = merge_equipment_cards(
            blueprint.get("equipment_cards"),
            state.get("equipment_cards"),
        )
        if equipment_merge.cards:
            blueprint["equipment_cards"] = equipment_merge.cards
        continuity = dict(blueprint.get("continuity_state") or {})
        previous_chapter_facts: list[str] = []
        for item in continuity.get("chapter_facts", []) if isinstance(continuity.get("chapter_facts"), list) else []:
            if isinstance(item, dict) and int(item.get("chapter_number") or 0) == chapter_number:
                previous_chapter_facts = [str(fact) for fact in item.get("facts") or [] if str(fact).strip()]
                break
        chapter_record = {
            "chapter_number": chapter_number,
            "chapter_title": summary["chapter_title"],
            "summary": summary["summary"],
            "facts": summary["facts"],
            "unresolved_threads": summary["unresolved_threads"],
            "next_focus": summary["next_focus"],
        }
        continuity["latest_chapter"] = chapter_number
        continuity["latest_title"] = summary["chapter_title"]
        continuity["latest_summary"] = summary["summary"]
        continuity["next_focus"] = summary["next_focus"]
        continuity["chapter_facts"] = self._replace_by_chapter_number(
            list(continuity.get("chapter_facts") or []),
            chapter_record,
            limit=120,
        )
        existing_running_facts = [
            str(item)
            for item in list(continuity.get("running_facts") or [])
            if str(item) not in previous_chapter_facts
        ]
        continuity["running_facts"] = self._merge_unique(
            existing_running_facts,
            summary["facts"],
            limit=160,
        )
        blueprint["continuity_state"] = continuity
        if is_game_story and isinstance(state.get("time_state"), dict):
            blueprint["time_state"] = state["time_state"]
        elif not is_game_story:
            blueprint.pop("time_state", None)
        synced["world_blueprint"] = blueprint
        if summary["next_focus"] and summary["next_focus"] != "continue":
            synced["current_focus"] = summary["next_focus"]

        existing_profiles: list[dict[str, Any]] = []
        for item in synced.get("character_profiles", []) if isinstance(synced.get("character_profiles"), list) else []:
            if not isinstance(item, dict):
                continue
            profile = dict(item)
            name = self._canonical_character_name(str(profile.get("name") or ""))
            if not name:
                continue
            profile["name"] = name
            if not self._is_character_card(profile):
                continue
            existing_profiles.append(profile)
        by_name = {str(item.get("name")): item for item in existing_profiles}
        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict):
                continue
            character = dict(character)
            name = self._canonical_character_name(str(character.get("name") or ""))
            if not name:
                continue
            character["name"] = name
            if not self._is_character_card(character):
                continue
            profile = dict(by_name.get(name) or {"name": name})
            for key in ("role", "game_id", "goals", "secrets", "relationships", "lifecycle_state"):
                if character.get(key) not in (None, "", [], {}):
                    profile[key] = character.get(key)
            if isinstance(character.get("real_state"), dict) and character["real_state"]:
                profile["real_state"] = deepcopy(character["real_state"])
            elif not is_game_story:
                profile.pop("game_state", None)
            if is_game_story and isinstance(character.get("game_state"), dict) and character["game_state"]:
                profile["game_state"] = deepcopy(character["game_state"])
            profile["current_emotion"] = character.get("current_emotion") or profile.get("current_emotion") or "neutral"
            profile["current_location"] = character.get("location") or profile.get("current_location") or ""
            profile["latest_chapter"] = chapter_number
            memories = character.get("memory") if isinstance(character.get("memory"), list) else []
            if memories:
                profile["memory"] = self._merge_unique(
                    list(profile.get("memory") or []),
                    [self._compact_text(item, 180) for item in memories[-6:]],
                    limit=40,
                )
            game_panel = character.get("game_panel")
            if isinstance(game_panel, dict) and game_panel:
                panel = dict(game_panel)
                if is_game_story and isinstance(character.get("game_state"), dict):
                    current = character["game_state"].get("current")
                    if isinstance(current, dict):
                        for field in _GAME_STATE_FIELDS:
                            value = current.get(field)
                            if value not in (None, "", [], {}):
                                panel[field] = deepcopy(value)
                profile["game_panel"] = panel | {"updated_chapter": chapter_number}
            if not is_game_story:
                profile.pop("game_state", None)
            by_name[name] = profile
        synced["character_profiles"] = list(by_name.values())
        relationship_updates: list[dict[str, Any]] = []
        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict):
                continue
            source = self._canonical_character_name(str(character.get("name") or ""))
            relationships = character.get("relationships")
            if isinstance(relationships, dict):
                items = relationships.items()
            elif isinstance(relationships, list):
                items = (("", item) for item in relationships)
            else:
                items = ()
            for fallback_target, relation in items:
                if not isinstance(relation, dict):
                    continue
                target = self._canonical_character_name(
                    str(relation.get("target") or relation.get("name") or fallback_target or "")
                )
                if not source or not target or source == target:
                    continue
                relation_summary = self._compact_text(
                    relation.get("current_state")
                    or relation.get("bond")
                    or summary.get("summary")
                    or "关系状态更新",
                    180,
                )
                relationship_updates.append(
                    {
                        "source": source,
                        "target": target,
                        "relation_type": relation.get("relation_type"),
                        "bond": relation.get("bond"),
                        "current_state": relation.get("current_state"),
                        "trust": relation.get("trust"),
                        "tension": relation.get("tension"),
                        "last_changed_chapter": chapter_number,
                        "changes": [
                            {
                                "chapter_number": chapter_number,
                                "summary": relation_summary,
                                "trust": relation.get("trust"),
                                "tension": relation.get("tension"),
                            }
                        ],
                    }
                )
        synced["relationship_graph"] = apply_relationship_updates(
            synced.get("relationship_graph"), relationship_updates
        )
        return synced

    def _prepare_sync_after_chapter(
        self,
        chapter: dict[str, Any],
        state: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        base_state = dict(state or self.state())
        synced_state = self._sync_state_after_chapter(base_state, chapter)
        synced_state = self._sync_ledger_from_chapter_body(synced_state, chapter)
        chapter["updated_story"] = synced_state
        chapter["chapter_summary"] = self._chapter_summary_payload(chapter)
        new_lessons = lessons_from_quality_report(chapter.get("quality_report") if isinstance(chapter.get("quality_report"), dict) else {})
        synced_state["writing_lessons"] = merge_writing_lessons(synced_state.get("writing_lessons"), new_lessons)
        chapter["updated_story"] = synced_state
        synced_project = self._sync_project_after_chapter(self.project(), synced_state, chapter)
        blueprint = dict(synced_project.get("world_blueprint") or {})
        blueprint["writing_learning"] = learning_snapshot(synced_state.get("writing_lessons"))
        synced_project["world_blueprint"] = blueprint
        return synced_state, synced_project

    def _sync_after_chapter(self, chapter: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
        synced_state, synced_project = self._prepare_sync_after_chapter(chapter, state)
        self._write_json(self.webnovel_dir / "state.json", synced_state)
        self._write_json(self.webnovel_dir / "project.json", synced_project)
        return synced_state

    def _state_before_chapter(self, chapter_number: int) -> dict[str, Any]:
        current_state = dict(self.state())
        current_chapter = int(current_state.get("current_chapter") or 0)
        if chapter_number > current_chapter:
            return current_state
        return self._generation_state_for_target(current_state, chapter_number)

    def _chapter_body_ledger_summary(self, chapter: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        title = str(chapter.get("chapter_title") or f"第{chapter_number}章")
        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
        economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
        real = ledger.get("real") if isinstance(ledger.get("real"), dict) else {}
        equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
        quests = ledger.get("quests") if isinstance(ledger.get("quests"), dict) else {}
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}

        exp = str(protagonist.get("exp") or "").strip()
        hp = str(protagonist.get("hp") or "").strip()
        mp = str(protagonist.get("mp") or "").strip()
        durability = str(equipment.get("durability") or "").strip()
        currency = str(economy.get("game_currency") or "").strip()
        backpack = str(economy.get("backpack") or "").strip()
        real_balance = str(real.get("end_balance") or economy.get("real_balance") or "").strip()
        start_balance = str(real.get("start_balance") or "").strip()
        balance_unchanged = bool(real_balance and start_balance and real_balance == start_balance)

        inv_text = "、".join(f"{name}×{count}" for name, count in inventory.items()) if inventory else "空"
        facts: list[str] = [
            f"苏叶现实余额{real_balance}" if real_balance else "",
            f"夜烬仍为{str(protagonist.get('level') or 'Lv.1')}见习者（未转职）",
            f"经验{exp}" if exp else "",
            f"生命{hp}" if hp else "",
            f"法力{mp}" if mp else "",
            f"新手法杖{durability}" if durability else "",
            f"钱袋{currency}" if currency else "",
            f"背包为{inv_text}" + (f"，占用{backpack}" if backpack else ""),
        ]
        for name, value in quests.items():
            text = str(value).strip()
            if text:
                facts.append(f"{name}：{text}")
        facts = [item for item in facts if item]

        quest_focus = ""
        for name in ("后坡巡查", "清道夫委托"):
            if name in quests:
                quest_focus = f"{name}{quests[name]}"
                break
        summary = f"夜烬本章推进{quest_focus or '当前任务'}，章末账本为经验{exp or '未明'}、生命{hp or '未明'}、法力{mp or '未明'}、钱袋{currency or '未明'}、背包{inv_text}。"
        existing_summary = chapter.get("chapter_summary") if isinstance(chapter.get("chapter_summary"), dict) else {}
        confirmed_focus = str(existing_summary.get("next_focus") or "").strip()
        if not confirmed_focus:
            candidate = str(chapter.get("next_outline") or "").strip()
            confirmed_focus = "" if candidate.lower() in {"", "continue"} else candidate
        next_focus = confirmed_focus or "承接当前任务状态，推进一个具体目标并更新账本。"
        if not confirmed_focus and "后坡巡查" in quests and "2/3" in str(quests["后坡巡查"]):
            next_focus = "先解决血蓝和补给，再完成后坡巡查最后一段。"
        return {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "cadence": "measured",
            "summary": summary,
            "facts": facts[:12],
            "unresolved_threads": [
                item
                for item in (
                    "后坡巡查还未完成" if "后坡巡查" in quests and "2/3" in str(quests["后坡巡查"]) else "",
                    "现实余额仍未改变" if balance_unchanged else "",
                    "混沌之种仍未解析" if "混沌之种" in str(chapter.get("body") or "") else "",
                )
                if item
            ],
            "next_focus": next_focus,
            "primary_conflict": {"collision": next_focus},
            "secondary_conflict": {"detail": "旁人只能把夜烬看成低血、熟路或运气好的散人。"},
            "event_beat": {"turn": "任务推进", "pivot": next_focus},
        }

    def _sync_game_character_from_ledger(
        self,
        character: dict[str, Any],
        ledger: dict[str, Any],
        *,
        chapter_number: int | None = None,
    ) -> dict[str, Any]:
        """Write game ledger leaves to game_state and its legacy panel only."""

        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
        economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
        equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
        quests = ledger.get("quests")
        pressure = ledger.get("pressure") if isinstance(ledger.get("pressure"), dict) else {}
        panel = dict(character.get("game_panel") or {})
        game_state = dict(character.get("game_state") or {})
        current = dict(game_state.get("current") or {}) if isinstance(game_state.get("current"), dict) else {}
        previous_current = deepcopy(current)

        game_id = protagonist.get("game_id") or current.get("game_id") or panel.get("game_id") or character.get("game_id")
        if not game_id and character.get("name") == "苏叶":
            game_id = "夜烬"
        values = {
            "game_id": game_id,
            "level": protagonist.get("level"),
            "class_path": protagonist.get("class_path") or protagonist.get("identity"),
            "exp": protagonist.get("exp"),
            "hp": protagonist.get("hp"),
            "mp": protagonist.get("mp"),
            "attributes": protagonist.get("attributes"),
            "unallocated_attribute_points": protagonist.get("unallocated_attribute_points"),
            "attribute_point_awards": protagonist.get("attribute_point_awards"),
            "attribute_allocations": protagonist.get("attribute_allocations"),
            "equipment": equipment,
            "inventory": economy.get("inventory"),
            "backpack": economy.get("backpack"),
            "currency": economy.get("game_currency") or economy.get("currency") or ledger.get("currency"),
            "quests": quests,
            "risk": pressure,
        }
        skills = ledger.get("skills") or protagonist.get("skills")
        if isinstance(skills, list):
            values["skills"] = [str(item) for item in skills if str(item).strip()]
        elif isinstance(skills, dict):
            values["skills"] = [
                str(item)
                for value in skills.values()
                for item in (value if isinstance(value, list) else [value])
                if str(item).strip()
            ]

        attribute_fields = {
            "attributes",
            "unallocated_attribute_points",
            "attribute_point_awards",
            "attribute_allocations",
        }

        def valid_attribute_value(field: str, value: Any) -> bool:
            if field == "attributes":
                return isinstance(value, dict)
            if field == "unallocated_attribute_points":
                return isinstance(value, int) and not isinstance(value, bool) and value >= 0
            return isinstance(value, list) and all(isinstance(item, dict) for item in value)

        for field, value in values.items():
            if field in attribute_fields:
                if field not in protagonist or not valid_attribute_value(field, value):
                    continue
            elif value in (None, "", [], {}):
                continue
            current[field] = deepcopy(value)
            panel[field] = deepcopy(value)
        if current.get("game_id"):
            character["game_id"] = current["game_id"]
        if chapter_number is not None:
            panel["updated_chapter"] = chapter_number
        game_state["current"] = current
        game_state.setdefault("recent_changes", [])
        changed_fields = [
            field
            for field in values
            if previous_current.get(field) != current.get(field)
        ]
        if chapter_number is not None and changed_fields:
            fact = f"游戏账本更新：{', '.join(changed_fields[:5])}"
            recent_changes = game_state["recent_changes"]
            if not any(
                isinstance(item, dict)
                and item.get("chapter") == int(chapter_number)
                and item.get("fact") == fact
                for item in recent_changes
            ):
                recent_changes.append({"chapter": int(chapter_number), "fact": fact})
        character["game_state"] = game_state
        character["game_panel"] = panel
        return character

    @staticmethod
    def _chapter_state_events(chapter: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for key in ("state_changes", "events", "ledger_events"):
            raw = chapter.get(key)
            if isinstance(raw, dict):
                raw = raw.get("events") or raw.get("changes") or []
            if isinstance(raw, list):
                events.extend(item for item in raw if isinstance(item, dict))
        summary = chapter.get("chapter_summary")
        if isinstance(summary, dict) and isinstance(summary.get("state_changes"), list):
            events.extend(item for item in summary["state_changes"] if isinstance(item, dict))
        return events

    @staticmethod
    def _event_change_payload(
        event: dict[str, Any],
        *,
        line: str,
        strict_namespace: bool = False,
    ) -> dict[str, Any]:
        change = event.get("change") or event.get("state_change") or event.get("state_delta")
        if not isinstance(change, dict):
            change = {}
        namespace_keys = {"real_change", "real_state", "game_change", "game_state"}
        has_namespace = any(key in event or key in change for key in namespace_keys)
        if line == "reality":
            candidates = (
                event.get("real_change"),
                event.get("real_state"),
                change.get("real_change"),
                change.get("real_state"),
            )
        else:
            candidates = (
                event.get("game_change"),
                event.get("game_state"),
                change.get("game_change"),
                change.get("game_state"),
            )
        selected = next((item for item in candidates if isinstance(item, dict)), None) if has_namespace else None
        if selected is None and not has_namespace and not strict_namespace:
            selected = change
        if not isinstance(selected, dict):
            return {}
        if isinstance(selected.get("current"), dict):
            current = selected["current"]
        else:
            current = {
                key: value
                for key, value in selected.items()
                if key not in {"line", "scene_line", "fact", "recent_changes", "real_change", "game_change"}
            }
        return {
            "current": deepcopy(current),
            "fact": str(event.get("fact") or selected.get("fact") or change.get("fact") or "").strip(),
        } if current else {}

    def _apply_chapter_state_events(
        self,
        state: dict[str, Any],
        chapter: dict[str, Any],
        *,
        is_game_story: bool,
    ) -> None:
        chapter_number = int(chapter.get("chapter_number") or 0)
        characters = state.get("characters") if isinstance(state.get("characters"), list) else []
        for event in self._chapter_state_events(chapter):
            raw_line = str(event.get("line") or event.get("scene_line") or "").strip().lower()
            if raw_line in {"游戏", "game_state"}:
                raw_line = "game"
            elif raw_line in {"现实", "real", "real_state"}:
                raw_line = "reality"
            elif raw_line in {"混合", "mixed", "过渡", "切换"}:
                raw_line = "transition"
            if raw_line not in {"game", "reality", "transition"}:
                continue
            lines = ("reality", "game") if raw_line == "transition" else (raw_line,)
            for line in lines:
                if line == "game" and not is_game_story:
                    continue
                change = self._event_change_payload(
                    event,
                    line=line,
                    strict_namespace=raw_line == "transition",
                )
                if not isinstance(change.get("current"), dict) or not change["current"]:
                    continue
                target = str(event.get("character") or event.get("character_name") or event.get("target") or "").strip()
                if target:
                    selected = [
                        item
                        for item in characters
                        if isinstance(item, dict) and item.get("name") == target
                    ]
                    if not selected:
                        continue
                else:
                    selected = [
                        item
                        for item in characters
                        if isinstance(item, dict) and item.get("role") in {"protagonist", "主角"}
                    ]
                    if not selected:
                        selected = [item for item in characters if isinstance(item, dict)][:1]
                for character in selected:
                    state_key = "game_state" if line == "game" else "real_state"
                    existing = character.get(state_key) if isinstance(character.get(state_key), dict) else {}
                    existing_current = existing.get("current") if isinstance(existing.get("current"), dict) else {}
                    if not any(existing_current.get(key) != value for key, value in change["current"].items()):
                        continue
                    merged = merge_state_change(
                        character,
                        line=line,
                        change=change,
                        chapter=chapter_number,
                    )
                    character.clear()
                    character.update(merged)
                    if line == "game":
                        _sync_game_panel_from_state(character)

    def _sync_ledger_from_chapter_body(self, state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        body = str(chapter.get("body") or "")
        protagonist_body = _without_monster_stat_surfaces(body)
        is_game_story = self._is_game_story_payload(self.project(), state)
        if not body or not is_game_story:
            self._apply_chapter_state_events(state, chapter, is_game_story=is_game_story)
            return state
        chinese_markers = (
            "经验",
            "生命",
            "法力",
            "钱袋：",
            "钱袋:",
            "背包",
            "背包：",
            "背包:",
            "新手法杖",
            "后坡巡查",
            "清道夫委托",
            "铜币",
            "等级：",
            "等级:",
            "任务：",
            "任务:",
            "现实余额",
            "可用余额",
            "银行卡可用余额",
        )
        english_field = re.search(
            r"\b(?:experience|exp|hp|health|mp|mana|inventory|backpack|level|durability|equipment)\s*(?:[:=]|\s+\d)",
            body,
            flags=re.IGNORECASE,
        )
        currency_field = re.search(
            r"\b(?:currency|coins?)\s*[:=]",
            body,
            flags=re.IGNORECASE,
        )
        amount_context = re.search(
            r"\b\d+(?:\.\d+)?\s*(?:coins?|copper|gold|silver)\b",
            body,
            flags=re.IGNORECASE,
        )
        if not any(marker in body for marker in chinese_markers) and not (english_field or currency_field or amount_context):
            self._apply_chapter_state_events(state, chapter, is_game_story=is_game_story)
            return state
        ledger = dict(state.get("progression_ledger") or {})
        protagonist = dict(ledger.get("protagonist") or {})
        panel = dict(ledger.get("panel") or {})
        economy = dict(ledger.get("economy") or {})
        real = dict(ledger.get("real") or {})
        equipment = dict(ledger.get("equipment") or {})
        quests = dict(ledger.get("quests") or {})

        def last(pattern: str, source: str | None = None) -> str:
            matches = re.findall(pattern, body if source is None else source, flags=re.IGNORECASE)
            return str(matches[-1]).strip() if matches else ""

        level = last(
            r"【[^】]{1,24}；\s*lv\.?\s*(\d+)(?=[^】]{0,24}(?:经验|生命|法力|可用属性点))",
            protagonist_body,
        )
        if not level:
            level = last(
            r"(?:等级提升至|升级到|升级至|升到|当前等级\s*[：:]?|等级\s*[：:]?|level\s*[:=]?)\s*(?:lv\.?\s*)?(\d+)",
            protagonist_body,
            )
        exp = last(r"(?:经验|experience|exp)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+)", protagonist_body)
        hp = last(r"(?:生命|hp|health)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+)", protagonist_body)
        mp = last(r"(?:法力|mp|mana)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+)", protagonist_body)
        durability = last(
            r"(?:新手法杖[^。！？\n]{0,60}?耐久\s*(?:回到|恢复到|变为|为)?|法杖[^。！？\n]{0,60}?耐久\s*(?:回到|恢复到|变为|为)?|耐久(?:回到|恢复到|变为)|durability\s*[:=]?)\s*(\d+\s*/\s*\d+|\d{1,3}%)",
            protagonist_body,
        )
        money = last(r"(?:钱袋\s*[：:]|currency\s*[:=]|coins?\s*[:=])\s*([^\n。；,，】]+)")
        if not money:
            amount_matches = re.findall(
                r"\b\d+(?:\.\d+)?\s*(?:coins?|copper|gold|silver)\b",
                body,
                flags=re.IGNORECASE,
            )
            money = str(amount_matches[-1]).strip() if amount_matches else ""
        patrol = last(r"后坡巡查[：:]\s*(\d+\s*/\s*\d+)")
        quest_line = last(r"(?<!完成)(?:任务\s*[：:]|quest(?:\s+status)?\s*[:=])\s*([^\n。】]+)")
        real_balance = last(
            r"(?:银行卡可用余额|现实账户余额|现实余额|可用余额)"
            r"\s*(?:(?:停在|变为|变成|还有|只剩|为)\s*)?[：:]?\s*"
            r"(\d+(?:\.\d+)?\s*元)"
        )

        if level:
            protagonist["level"] = f"Lv.{level}"
            panel["level"] = protagonist["level"]
        if exp:
            protagonist["exp"] = exp.replace(" ", "")
            panel["exp"] = protagonist["exp"]
        if hp:
            protagonist["hp"] = hp.replace(" ", "")
        if mp:
            protagonist["mp"] = mp.replace(" ", "")
        if durability:
            protagonist["weapon_durability"] = f"新手法杖：{durability.replace(' ', '')}"
            equipment["weapon"] = "新手法杖"
            equipment["durability"] = durability.replace(" ", "")
        if money:
            economy["game_currency"] = money.rstrip("】】 ]")
        if real_balance:
            normalized_balance = real_balance.replace(" ", "")
            real["end_balance"] = normalized_balance
            economy["real_balance"] = normalized_balance
        if "急账代付已通过" in body or re.search(r"房租[^。\n]{0,80}信用卡最低还款[^。\n]{0,40}已付清", body):
            real["paid"] = "正文明确写出的现实急账已付清"

        inventory_lines = re.findall(
            r"(?:背包|inventory|backpack)\s*(?:[：:]\s*)?([^\n。]+)",
            body,
            flags=re.IGNORECASE,
        )
        quantified_inventory_lines = [
            str(item).strip()
            for item in inventory_lines
            if re.search(r"[×xX*＊]\s*\d+", str(item))
        ]
        inventory_line = quantified_inventory_lines[-1] if quantified_inventory_lines else ""
        if inventory_line:
            inventory: dict[str, int] = {}
            for raw_item, count in re.findall(
                r"([^×xX*＊,，;；]+?)\s*[×xX*＊]\s*(\d+)",
                inventory_line,
            ):
                item = re.sub(r"\s+", " ", raw_item).strip(" \t:：;；,，、")
                item = re.sub(r"^(?:里|中)?(?:还剩|只剩|剩下|有|装着)\s*", "", item)
                item = re.sub(r"^(?:和|及|以及)\s*", "", item)
                if item:
                    inventory[item] = int(count)
            if inventory:
                economy["inventory"] = inventory
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}
        removed_inventory_items = [
            item
            for item in list(inventory)
            if f"{item}从背包消失" in body or f"{item}已从背包消失" in body
        ]
        for item in removed_inventory_items:
            inventory.pop(item, None)
        if removed_inventory_items:
            economy["inventory"] = inventory
        occupied = last(r"占用[：:]\s*(\d+\s*/\s*20)")
        if not occupied and inventory_line:
            occupied_match = re.search(r"(?:占用)?\s*(\d+\s*/\s*20)", inventory_line)
            occupied = occupied_match.group(1) if occupied_match else ""
        if removed_inventory_items and inventory:
            economy["backpack"] = f"{len(inventory)}/20"
        elif occupied:
            economy["backpack"] = occupied.replace(" ", "")
        completed_quests: list[str] = []
        for match in re.finditer(r"完成任务\s*[：:]?\s*([^\n。；;，,】\]]+)", body):
            prefix = body[max(0, match.start() - 12) : match.start()]
            if re.search(
                r"(?:还没有|没有|尚未|并未|未能|无法|不能|如果|若|要是|只要|一旦|等到?|是否|能否)\s*$",
                prefix,
            ):
                continue
            completed_name = match.group(1).strip(" \t：:，,")
            if completed_name:
                completed_quests.append(completed_name)

        active_quest = str(quests.get("active") or "").strip()
        active_name = re.split(r"[：:(（]", active_quest, maxsplit=1)[0].strip()
        for completed_name in completed_quests:
            quests[completed_name] = "已完成"
            if active_name == completed_name:
                quests.pop("active", None)
        if quest_line and quest_line not in completed_quests:
            quests["active"] = quest_line
        cleaner_progress = last(r"清道夫(?:任务)?[^。！？\n]{0,40}?(\d+\s*/\s*\d+)")
        if cleaner_progress:
            quests["active"] = f"清道夫：{cleaner_progress.replace(' ', '')}；未提交"

        if "清道夫委托已完成" in body:
            quests["清道夫委托"] = "已提交；奖励30铜已领取"
            inv = economy.get("inventory")
            if isinstance(inv, dict) and "灰狼毒腺" not in inv:
                inv["灰狼毒腺"] = 0
        elif "清道夫委托" in body and ("未接取" in body or "没接" in body or "没交" in body):
            quests["清道夫委托"] = "未接取；未提交；奖励未到账"
        if "后坡巡查未登记" in body or "我先不接" in body:
            quests["后坡巡查"] = "可登记；第二章章末未登记"
        if patrol:
            quests["后坡巡查"] = patrol.replace(" ", "")
        for stale_quest in ("导师基础登记", "元素回廊前置", "职业试炼", "转职任务"):
            if stale_quest in quests and stale_quest not in body:
                quests.pop(stale_quest, None)

        protagonist.setdefault("identity", "见习者（未转职）")
        protagonist.setdefault("class_path", "见习者（未转职）")
        protagonist.setdefault("level", "Lv.1")
        panel.setdefault("identity", "见习者（未转职）")
        panel.setdefault("level", "Lv.1")

        ledger["protagonist"] = protagonist
        protagonist.pop("cost_delta", None)
        ledger["panel"] = panel
        ledger["economy"] = economy
        ledger["real"] = real
        ledger["equipment"] = equipment
        equipment.pop("durability_delta", None)
        ledger["quests"] = quests
        state["progression_ledger"] = ledger

        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict) or character.get("role") not in {"protagonist", "主角"}:
                continue
            character.setdefault("game_panel", {})
            character["game_panel"]["identity"] = protagonist.get("identity", "见习者（未转职）")
            self._sync_game_character_from_ledger(
                character,
                ledger,
                chapter_number=int(chapter.get("chapter_number") or 0),
            )
            if real_balance:
                real_state = dict(character.get("real_state") or {})
                current_real = dict(real_state.get("current") or {})
                current_real["balance"] = real["end_balance"]
                real_state["current"] = current_real
                real_state.setdefault("recent_changes", [])
                character["real_state"] = real_state
        if level or exp or hp or mp or durability or money or real_balance or inventory_line or quest_line:
            summary = self._chapter_body_ledger_summary(chapter, ledger)
            chapter["chapter_summary"] = summary
            state["chapter_summaries"] = self._replace_by_chapter_number(
                list(state.get("chapter_summaries") or []),
                summary,
                limit=240,
            )
            chapter_number = int(chapter.get("chapter_number") or 0)
            fact_prefix = f"第{chapter_number}章事实："
            summary_prefix = f"第{chapter_number}章摘要："
            existing_world_facts = [
                str(item)
                for item in list(state.get("world_facts") or [])
                if not str(item).startswith(fact_prefix) and not str(item).startswith(summary_prefix)
            ]
            body_facts = [f"{fact_prefix}{fact}" for fact in summary["facts"]]
            body_facts.append(f"{summary_prefix}{summary['summary']}")
            state["world_facts"] = self._merge_unique(existing_world_facts, body_facts, limit=260)
            timeline_entry = {
                "chapter_number": chapter_number,
                "summary": summary["summary"],
                "impact": summary["next_focus"],
            }
            state["timeline"] = self._replace_by_chapter_number(
                list(state.get("timeline") or []),
                timeline_entry,
                limit=240,
            )
            memory_entry = {
                "chapter_number": chapter_number,
                "chapter_title": summary["chapter_title"],
                "summary": summary["summary"],
                "tags": [],
                "characters": self._character_names_in_chapter(state, chapter),
                "locations": [],
                "factions": [],
                "quests": [],
                "items": [],
                "facts": summary["facts"],
                "unresolved_threads": summary["unresolved_threads"],
            }
            state["memory_index"] = self._replace_by_chapter_number(
                list(state.get("memory_index") or []),
                memory_entry,
                limit=240,
            )
        self._apply_chapter_state_events(state, chapter, is_game_story=is_game_story)
        return state

    def _frozen_chapters(self) -> set[int]:
        state = self.state()
        ledger = state.get("progression_ledger") if isinstance(state.get("progression_ledger"), dict) else {}
        lock = ledger.get("continuity_lock") if isinstance(ledger.get("continuity_lock"), dict) else {}
        raw = lock.get("chapters_frozen") if isinstance(lock.get("chapters_frozen"), list) else []
        frozen: set[int] = set()
        for item in raw:
            try:
                frozen.add(int(item))
            except (TypeError, ValueError):
                continue
        return frozen

    def _assert_chapter_not_frozen(self, chapter_number: int, operation: str) -> None:
        if chapter_number in self._frozen_chapters():
            raise ValueError(f"chapter_frozen:{chapter_number}:{operation}")

    def freeze_opening_baseline(self, *, through_chapter: int = 3, commit_message: str | None = None) -> dict[str, Any]:
        """Rebuild durable opening memory from chapter files and lock it.

        The opening chapters are the highest-leverage continuity source for a
        webnovel. This method strips stale state shells, replays the accepted
        chapter records into state memory, and records a small continuity lock
        that later generation can preflight against.
        """

        if through_chapter <= 0:
            raise ValueError("through_chapter_must_be_positive")
        available = set(self.chapter_numbers())
        missing = [number for number in range(1, through_chapter + 1) if number not in available]
        if missing:
            raise FileNotFoundError(f"missing_opening_chapters:{','.join(str(item) for item in missing)}")

        original = self.state()
        rebuilt = dict(original)
        rebuilt["chapter_summaries"] = [
            item
            for item in self._dedupe_numbered_records(list(rebuilt.get("chapter_summaries") or []))
            if not (isinstance(item, dict) and 0 < int(item.get("chapter_number") or 0) <= through_chapter)
        ]
        rebuilt["timeline"] = [
            item
            for item in self._dedupe_numbered_records(list(rebuilt.get("timeline") or []))
            if not (isinstance(item, dict) and 0 < int(item.get("chapter_number") or 0) <= through_chapter)
        ]
        rebuilt["memory_index"] = [
            item
            for item in self._dedupe_numbered_records(list(rebuilt.get("memory_index") or []))
            if not (isinstance(item, dict) and 0 < int(item.get("chapter_number") or 0) <= through_chapter)
        ]

        chapter_titles: dict[str, str] = {}
        opening_chapters: list[dict[str, Any]] = []
        for number in range(1, through_chapter + 1):
            chapter = self.chapter(number)
            opening_chapters.append(chapter)
            chapter_titles[str(number)] = str(chapter.get("chapter_title") or f"Chapter {number}")
            rebuilt = self._sync_state_after_chapter(rebuilt, chapter)

        rebuilt["current_chapter"] = max(int(rebuilt.get("current_chapter") or 0), through_chapter)
        ledger = self._derive_opening_progression_ledger(opening_chapters, dict(rebuilt.get("progression_ledger") or {}))
        lock = dict(ledger.get("continuity_lock") or {})
        frozen = sorted(set(self._frozen_chapters()) | set(range(1, through_chapter + 1)))
        lock["chapters_frozen"] = frozen
        lock["opening_baseline"] = {
            "through_chapter": through_chapter,
            "chapter_titles": chapter_titles,
            "next_chapter": through_chapter + 1,
            "source": "chapter_files",
        }
        ledger["continuity_lock"] = lock
        rebuilt["progression_ledger"] = ledger
        self._write_json(self.webnovel_dir / "state.json", rebuilt)

        project = self.project()
        synced_project = dict(project)
        blueprint = dict(synced_project.get("world_blueprint") or {})
        continuity = dict(blueprint.get("continuity_state") or {})
        continuity["chapter_facts"] = [
            item
            for item in continuity.get("chapter_facts", [])
            if not (isinstance(item, dict) and 0 < int(item.get("chapter_number") or 0) <= through_chapter)
        ]
        blueprint["continuity_state"] = continuity
        synced_project["world_blueprint"] = blueprint
        for chapter in opening_chapters:
            synced_project = self._sync_project_after_chapter(synced_project, rebuilt, chapter)
        synced_project["current_chapter"] = max(int(synced_project.get("current_chapter") or 0), through_chapter)
        self._write_json(self.webnovel_dir / "project.json", synced_project)

        commit = self.commit(
            message=commit_message or f"freeze opening baseline through chapter {through_chapter}",
            operation="freeze-opening",
            chapter_number=through_chapter,
        )
        return {
            "schema_version": "file-project-opening-baseline/v1",
            "through_chapter": through_chapter,
            "chapters_frozen": frozen,
            "chapter_titles": chapter_titles,
            "preflight": self.opening_preflight(next_chapter=through_chapter + 1),
            "commit": commit,
        }

    def opening_preflight(self, *, next_chapter: int | None = None) -> dict[str, Any]:
        """Report whether the current project state can safely continue."""

        state = self.state()
        persisted_state = self._read_json(self.webnovel_dir / "state.json", {}) or state
        ledger = state.get("progression_ledger") if isinstance(state.get("progression_ledger"), dict) else {}
        lock = ledger.get("continuity_lock") if isinstance(ledger.get("continuity_lock"), dict) else {}
        baseline = lock.get("opening_baseline") if isinstance(lock.get("opening_baseline"), dict) else {}
        through_chapter = int(baseline.get("through_chapter") or 0)
        target = int(next_chapter or baseline.get("next_chapter") or (int(state.get("current_chapter") or 0) + 1))
        issues: list[str] = []

        if through_chapter:
            missing_frozen = [
                number
                for number in range(1, through_chapter + 1)
                if number not in self._frozen_chapters()
            ]
            if missing_frozen:
                issues.append(f"opening chapters not frozen: {missing_frozen}")
            missing_files = [
                number
                for number in range(1, through_chapter + 1)
                if number not in self.chapter_numbers()
            ]
            if missing_files:
                issues.append(f"opening chapter files missing: {missing_files}")
            if target <= through_chapter:
                issues.append(f"next chapter {target} would rewrite frozen opening baseline")

        numbered_summaries = [
            int(item.get("chapter_number") or 0)
            for item in state.get("chapter_summaries", [])
            if isinstance(item, dict) and int(item.get("chapter_number") or 0) > 0
        ]
        duplicate_summaries = sorted({number for number in numbered_summaries if numbered_summaries.count(number) > 1})
        if duplicate_summaries:
            issues.append(f"duplicate chapter summaries: {duplicate_summaries}")

        preflight_text = {
            "author_constraints": persisted_state.get("author_constraints", []),
            "world_facts": persisted_state.get("world_facts", []),
            "timeline": persisted_state.get("timeline", []),
            "chapter_summaries": persisted_state.get("chapter_summaries", []),
            "memory_index": persisted_state.get("memory_index", []),
            "progression_ledger": persisted_state.get("progression_ledger", {}),
        }
        text_blob = json.dumps(preflight_text, ensure_ascii=False)
        blocked_tokens = (
            "？？",
            "门槛",
            "熟练度",
            "元素法师学徒",
            "货币：",
            "法师兄",
            "先看成本",
            "先看余额",
            "先问价",
        )
        leaked = [token for token in blocked_tokens if token in text_blob]
        if leaked:
            issues.append(f"blocked stale tokens in state: {leaked}")
        bad_titles = [
            str(item.get("chapter_title") or "")
            for item in state.get("chapter_summaries", [])
            if isinstance(item, dict)
            and re.fullmatch(r"[\?？]{2,}", str(item.get("chapter_title") or "").strip())
        ]
        if bad_titles:
            issues.append("chapter titles are unresolved question marks")

        return {
            "schema_version": "file-project-opening-preflight/v1",
            "ok": not issues,
            "issues": issues,
            "next_chapter": target,
            "opening_baseline": baseline,
        }

    def _assert_opening_preflight(self, chapter_number: int) -> None:
        report = self.opening_preflight(next_chapter=chapter_number)
        baseline = report.get("opening_baseline") if isinstance(report.get("opening_baseline"), dict) else {}
        if baseline and not report.get("ok"):
            raise ValueError(f"opening_preflight_failed:{'; '.join(report.get('issues') or [])}")

    def exists(self) -> bool:
        return (self.story_system_dir / "MASTER_SETTING.json").exists() and (self.webnovel_dir / "state.json").exists()

    def master_setting(self) -> dict[str, Any]:
        return self._read_json(self.story_system_dir / "MASTER_SETTING.json", {}) or {}

    @staticmethod
    def _is_game_story_payload(project: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
        world_blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        state = state if isinstance(state, dict) else {}
        state_ids = normalize_novel_type_ids(state.get("genre_plugin_ids"))
        genre_plugin_ids = state_ids or normalize_novel_type_ids(world_blueprint.get("genre_plugin_ids"))
        return is_game_story_type(
            {
                "genre_plugin_ids": genre_plugin_ids,
                "genre": state.get("genre") or project.get("genre"),
            }
        )

    def project(self) -> dict[str, Any]:
        project = self._read_json(self.webnovel_dir / "project.json", {}) or self.master_setting().get("project", {}) or {}
        project = dict(project)
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        is_game_story = self._is_game_story_payload(project, state)
        project["character_profiles"] = remove_cross_character_aliases(filter_character_cards(merge_character_alias_cards([
            _normalize_character_persistence_card(item, is_game_story=is_game_story)
            for item in project.get("character_profiles", [])
            if isinstance(item, dict)
        ])))
        if "relationship_graph" in project:
            project["relationship_graph"] = normalize_relationship_graph(project.get("relationship_graph"))
        else:
            project["relationship_graph"] = graph_from_character_cards(project.get("character_profiles"))
        return project

    def _review_genre_context(self) -> dict[str, Any]:
        project = self.project()
        state = self.state()
        blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        genre_ids = normalize_novel_type_ids(state.get("genre_plugin_ids"))
        if not genre_ids:
            genre_ids = normalize_novel_type_ids(blueprint.get("genre_plugin_ids"))
        return {
            "genre": str(state.get("genre") or project.get("genre") or ""),
            "genre_plugin_ids": genre_ids,
        }

    def opening_brief(self) -> dict[str, Any]:
        path = self.webnovel_dir / "opening_brief.json"
        payload = self._read_json(path, {})
        project = self.project()
        pipeline_stage = str(project.get("pipeline_stage") or "")
        recoverable_legacy_blank = pipeline_stage == "draft" or (
            pipeline_stage in {"direction_ready", "outlining"}
            and (self.webnovel_dir / "opening_directions.json").is_file()
        )
        if not payload and recoverable_legacy_blank:
            blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
            novel_type_ids = normalize_novel_type_ids(blueprint.get("genre_plugin_ids"))
            if not novel_type_ids:
                state = self._read_json(self.webnovel_dir / "state.json", {})
                novel_type_ids = normalize_novel_type_ids(state.get("genre_plugin_ids"))
            title = str(project.get("title") or "未命名作品").strip() or "未命名作品"
            payload = {
                "schema_version": "opening-brief/v1",
                "mode": "blank",
                "novel_type_id": novel_type_ids[0] if novel_type_ids else "generic_webnovel",
                "idea": f"请根据书名《{title}》和所选小说类型构思故事。",
                "working_title": title,
            }
            self._write_json_atomic(path, payload)
        return OpeningBrief.model_validate(payload).model_dump(mode="json")

    def opening_directions(self) -> dict[str, Any] | None:
        path = self.webnovel_dir / "opening_directions.json"
        if not path.exists():
            return None
        return OpeningDirectionSet.model_validate(self._read_json(path, {})).model_dump(mode="json")

    def opening_setup(self) -> dict[str, Any]:
        project = self.project()
        candidates = self.opening_directions()
        project_id = str(project.get("project_id") or self.root.name)
        public_project_id = project_id if project_id.startswith("file:") else f"file:{project_id}"
        selected_id = str((candidates or {}).get("selected_id") or "")
        pipeline_stage = str(project.get("pipeline_stage") or "idea_pending")
        next_page = "outline" if selected_id or pipeline_stage == "outlining" else "setup"
        return {
            "brief": self.opening_brief(),
            "directions": list((candidates or {}).get("directions") or []),
            "selected_id": selected_id,
            "pipeline_stage": pipeline_stage,
            "next_path": f"/projects/{quote(public_project_id, safe='')}/{next_page}",
        }

    def _selected_opening_direction(self) -> dict[str, Any] | None:
        payload = self.opening_directions()
        selected_id = str((payload or {}).get("selected_id") or "")
        if not selected_id:
            return None
        return next(
            (
                dict(direction)
                for direction in (payload or {}).get("directions") or []
                if isinstance(direction, dict) and str(direction.get("id") or "") == selected_id
            ),
            None,
        )

    def story_core(self) -> dict[str, Any]:
        project = self.project()
        outline = dict(self.project_outline())
        outline.pop("source", None)
        overall = dict(outline.get("overall") or {})
        return story_core_from_overall(
            overall,
            title=str(project.get("title") or ""),
        ).model_dump(mode="json")

    def story_core_context(self, stage: str) -> dict[str, Any]:
        return story_core_projection(
            StoryCoreCard.model_validate(self.story_core()),
            stage,
        )

    @_with_project_update_lock
    def update_story_core(self, payload: dict[str, Any]) -> dict[str, Any]:
        card = StoryCoreCard.model_validate(payload)
        outline = dict(self.project_outline())
        outline.pop("source", None)
        outline["overall"] = merge_story_core_into_overall(
            outline.get("overall"),
            card,
            overwrite=True,
        )
        saved_outline = self.update_project_outline(outline)
        return story_core_from_overall(
            saved_outline.get("overall"),
            title=str(self.project().get("title") or card.title),
        ).model_dump(mode="json")

    def _opening_direction_trope_candidates(
        self,
        brief: OpeningBrief | dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        validated_brief = OpeningBrief.model_validate(brief or self.opening_brief())
        genre = runtime_novel_type(validated_brief.novel_type_id)
        if genre is None:
            raise ValueError("invalid_novel_type")
        prompt_context = novel_type_prompt_context(genre)
        return [
            dict(item)
            for item in prompt_context.get("genre_trope_templates", [])
            if isinstance(item, dict)
        ]

    def _current_opening_direction_novel_type_id(
        self,
        brief: OpeningBrief | dict[str, Any] | None = None,
    ) -> str:
        validated_brief = OpeningBrief.model_validate(brief or self.opening_brief())
        project = self.project()
        world_blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        raw_ids = world_blueprint.get("genre_plugin_ids")
        if isinstance(raw_ids, str):
            has_explicit_type = bool(raw_ids.strip())
        elif isinstance(raw_ids, list):
            has_explicit_type = any(str(item).strip() for item in raw_ids)
        else:
            has_explicit_type = False
        normalized_ids = normalize_novel_type_ids(raw_ids)
        if normalized_ids:
            return normalized_ids[0]
        if has_explicit_type:
            raise ValueError("invalid_novel_type")
        return validated_brief.novel_type_id

    @_with_project_update_lock
    def generate_opening_directions(
        self, generator: Any, *, guidance: str = ""
    ) -> dict[str, Any]:
        existing = self.opening_directions()
        if existing and existing.get("selected_id"):
            raise ValueError("direction_already_selected")
        brief = OpeningBrief.model_validate(self.opening_brief())
        try:
            current_type_id = self._current_opening_direction_novel_type_id(brief)
            effective_brief = brief.model_copy(update={"novel_type_id": current_type_id})
            trope_candidates = self._opening_direction_trope_candidates(effective_brief)
            result = generator.generate(effective_brief, guidance=guidance.strip())
            generated_directions = validate_opening_direction_set_primary_tropes(
                GeneratedOpeningDirectionSet.model_validate(result),
                trope_candidates,
            )
            directions = OpeningDirectionSet.model_validate(
                generated_directions.model_dump(mode="json")
            )
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == "invalid_novel_type":
                raise ValueError("opening_direction_generation_failed") from exc
            if isinstance(exc, ValueError) and str(exc) == "opening_direction_generation_failed":
                raise
            raise ValueError("opening_direction_generation_failed") from exc
        project = {**self.project(), "pipeline_stage": "direction_ready"}
        self._replace_json_transaction(
            {
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "opening_directions.json": directions.model_dump(mode="json"),
            }
        )
        return self.opening_setup()

    @_with_project_update_lock
    def select_opening_direction(self, direction_id: str) -> dict[str, Any]:
        payload = self.opening_directions()
        if payload is None:
            raise KeyError("direction_not_found")
        directions = OpeningDirectionSet.model_validate(payload)
        if directions.selected_id:
            raise ValueError("direction_already_selected")
        selected = next(
            (direction for direction in directions.directions if direction.id == direction_id),
            None,
        )
        if selected is None:
            raise KeyError("direction_not_found")

        current_project = self.project()
        current_title = str(current_project.get("title") or "").strip()
        title = selected.title if not current_title or current_title in {"未命名作品", "Untitled"} else current_title
        project = {
            **current_project,
            "title": title,
            "pipeline_stage": "outlining",
        }
        story_core = story_core_from_direction(selected)
        outline = normalize_project_outline(
            outline_seed_from_story_core(
                story_core,
                primary_trope_id=selected.primary_trope_id,
            )
        )
        selected_directions = directions.model_copy(update={"selected_id": selected.id})
        self._replace_json_transaction(
            {
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "outline.json": outline,
                self.webnovel_dir / "opening_directions.json": selected_directions.model_dump(mode="json"),
            }
        )
        return self.opening_setup()

    @_with_project_update_lock
    def project_outline(self) -> dict[str, Any]:
        # 先尝试 Markdown 大纲双向同步（last-writer-wins）；同步失败静默降级，
        # 绝不能因为 md 解析/导出问题搞挂读接口。
        try:
            from packages.story_core.outline_markdown_sync import sync_outline_if_stale

            sync_outline_if_stale(self.root)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "outline markdown sync failed", exc_info=True
            )
        path = self.webnovel_dir / "outline.json"
        if path.exists():
            project = self.project()
            state = self._read_json(self.webnovel_dir / "state.json", {})
            normalized = normalize_outline_for_story_type(
                self._read_json(path, {}),
                is_game_story=self._is_game_story_payload(project, state),
            )
            legacy_path = self.webnovel_dir / "story_core.json"
            if legacy_path.exists():
                try:
                    legacy = StoryCoreCard.model_validate(self._read_json(legacy_path, {}))
                    normalized["overall"] = merge_story_core_into_overall(
                        normalized.get("overall"), legacy, overwrite=False
                    )
                    saved = self.update_project_outline(normalized)
                    normalized = {key: value for key, value in saved.items() if key != "source"}
                    archive_path = self.webnovel_dir / "story_core.legacy.json"
                    suffix = 2
                    while archive_path.exists():
                        archive_path = self.webnovel_dir / f"story_core.legacy-{suffix}.json"
                        suffix += 1
                    legacy_path.rename(archive_path)
                except Exception:  # noqa: BLE001
                    logging.getLogger(__name__).warning(
                        "legacy story core migration failed", exc_info=True
                    )
            return {**normalized, "source": "saved"}
        return {**outline_from_legacy_project(self.project()), "source": "legacy"}

    @_with_project_update_lock
    def update_project_outline(self, payload: dict[str, Any]) -> dict[str, Any]:
        outline_payload = dict(payload)
        outline_payload.pop("source", None)
        state = self._read_json(self.webnovel_dir / "state.json", {})
        outline_payload = normalize_outline_for_story_type(
            outline_payload,
            is_game_story=self._is_game_story_payload(self.project(), state),
        )
        current_chapter = int(state.get("current_chapter") or 0)
        normalized = validate_outline_for_project(
            outline_payload, current_chapter=current_chapter
        )
        self._write_json_atomic(self.webnovel_dir / "outline.json", normalized)
        # 保存后立即把 json 字段级合并渲染回 大纲/*.md；导出失败不影响保存结果，
        # 导出状态只写日志，避免把运行状态混进可再次提交的大纲数据。
        try:
            from packages.story_core.outline_markdown_sync import export_outline_to_markdown

            export_outline_to_markdown(self.root, normalized)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "outline markdown export failed: %s", exc, exc_info=True
            )
        return {**normalized, "source": "saved"}

    def _planning_opening_direction(
        self,
        project: dict[str, Any],
        outline: dict[str, Any],
    ) -> dict[str, Any]:
        directions = self.opening_directions()
        selected_id = str((directions or {}).get("selected_id") or "")
        selected = next(
            (
                dict(item)
                for item in (directions or {}).get("directions", [])
                if isinstance(item, dict) and str(item.get("id") or "") == selected_id
            ),
            None,
        )
        if selected:
            return {
                "title": str(selected.get("title") or ""),
                "hook": str(selected.get("hook") or ""),
                "opening_promise": str(selected.get("opening_promise") or ""),
                "primary_trope_id": selected.get("primary_trope_id"),
            }
        overall = outline.get("overall") if isinstance(outline.get("overall"), dict) else {}
        seed = str(project.get("seed_outline") or project.get("world_summary") or overall.get("story") or project.get("title") or "")
        primary_trope_id = overall.get("primary_trope_id")
        if isinstance(primary_trope_id, str):
            primary_trope_id = primary_trope_id.strip() or None
        else:
            primary_trope_id = None
        return {
            "title": str(project.get("title") or ""),
            "hook": str(overall.get("story") or seed),
            "opening_promise": str(overall.get("ending_direction") or "开篇建立的核心冲突会得到阶段性兑现。"),
            "primary_trope_id": primary_trope_id,
        }

    def _current_project_trope_candidates(
        self,
        project: dict[str, Any],
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        genre_ids = normalize_novel_type_ids(blueprint.get("genre_plugin_ids"))
        if not genre_ids:
            genre_ids = normalize_novel_type_ids(state.get("genre_plugin_ids"))
        if not genre_ids:
            genre_ids = ["generic_webnovel"]
        genre = runtime_novel_type(genre_ids[0])
        if genre is None:
            raise ValueError("invalid_novel_type")
        prompt_context = novel_type_prompt_context(genre)
        return [
            dict(item)
            for item in prompt_context.get("genre_trope_templates", [])
            if isinstance(item, dict)
        ]

    @staticmethod
    def _outline_primary_trope_id(outline: dict[str, Any]) -> str | None:
        overall = outline.get("overall") if isinstance(outline.get("overall"), dict) else {}
        primary_trope_id = overall.get("primary_trope_id")
        if isinstance(primary_trope_id, str):
            return primary_trope_id.strip() or None
        return None

    @staticmethod
    def _validate_generated_locked_tropes_match(
        current: dict[str, Any],
        generated: dict[str, Any],
        *,
        current_chapter: int,
        locked_through_chapter: int | None = None,
    ) -> None:
        current_arcs = {
            str(arc.get("id")): arc
            for arc in current.get("arcs", [])
            if isinstance(arc, dict) and str(arc.get("id") or "").strip()
        }
        locked_current_arcs = [
            arc
            for arc in current_arcs.values()
            if arc.get("trope_id") is not None
            and (
                locked_through_chapter is None
                or int(arc.get("end_chapter") or 0) <= locked_through_chapter
            )
        ]
        for arc in generated.get("arcs", []):
            if not isinstance(arc, dict):
                continue
            arc_id = str(arc.get("id") or "")
            current_arc = current_arcs.get(arc_id)
            if not current_arc:
                for locked_arc in locked_current_arcs:
                    exact_range = (
                        int(arc["start_chapter"]) == int(locked_arc["start_chapter"])
                        and int(arc["end_chapter"]) == int(locked_arc["end_chapter"])
                    )
                    committed_overlap = max(
                        int(arc["start_chapter"]),
                        int(locked_arc["start_chapter"]),
                    ) <= min(
                        int(arc["end_chapter"]),
                        int(locked_arc["end_chapter"]),
                        current_chapter,
                    )
                    if exact_range or committed_overlap:
                        raise ValueError(f"locked_arc_overlap:{arc_id}")
                continue
            current_trope_id = current_arc.get("trope_id")
            generated_trope_id = arc.get("trope_id")
            current_arc_locked = (
                locked_through_chapter is None
                or int(current_arc.get("end_chapter") or 0) <= locked_through_chapter
            )
            if current_arc_locked and current_trope_id is not None and generated_trope_id != current_trope_id:
                raise ValueError(f"locked_arc_trope_drift:{arc_id}")

    def _planning_brief(self) -> OutlinePlanningBrief:
        project = self.project()
        outline = dict(self.project_outline())
        outline.pop("source", None)
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        plugin_ids = blueprint.get("genre_plugin_ids") if isinstance(blueprint.get("genre_plugin_ids"), list) else []
        novel_type_id = str(plugin_ids[0] if plugin_ids else "generic_webnovel")
        existing_cards: list[dict[str, Any]] = []
        existing_character_names: list[str] = []
        seen_character_names: set[str] = set()
        for item in [
            *(project.get("character_profiles") if isinstance(project.get("character_profiles"), list) else []),
            *(state.get("characters") if isinstance(state.get("characters"), list) else []),
        ]:
            if not isinstance(item, dict) or is_non_character_card(item):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in seen_character_names:
                continue
            seen_character_names.add(name)
            existing_character_names.append(name)
            if len(existing_cards) >= 6:
                continue
            card = normalize_character_profile(item)
            existing_cards.append(
                {
                    key: card.get(key)
                    for key in (
                        "name",
                        "role",
                        "character_tier",
                        "first_appearance",
                        "identity_profile",
                        "background_profile",
                        "current_life_profile",
                        "story_drive",
                        "dialogue_examples",
                    )
                }
            )
        summaries = state.get("chapter_summaries") if isinstance(state.get("chapter_summaries"), list) else []
        continuation = project.get("continuation") if isinstance(project.get("continuation"), dict) else {}
        raw_continuation_start = continuation.get("start_after_chapter")
        continuation_start = (
            int(raw_continuation_start)
            if isinstance(raw_continuation_start, int)
            and not isinstance(raw_continuation_start, bool)
            and raw_continuation_start >= 1
            else None
        )
        historical_summaries: list[dict[str, Any]] = []
        if continuation_start is not None:
            for path in sorted((self.story_system_dir / "chapters").glob("*.json")):
                payload = self._read_json(path, {})
                if not isinstance(payload, dict):
                    continue
                number = payload.get("chapter_number")
                if (
                    not isinstance(number, int)
                    or isinstance(number, bool)
                    or number < 1
                    or number > continuation_start
                ):
                    continue
                chapter_summary = payload.get("chapter_summary")
                summary = (
                    str(chapter_summary.get("summary") or "").strip()
                    if isinstance(chapter_summary, dict)
                    else ""
                )
                historical_summaries.append(
                    {
                        "chapter_number": number,
                        "title": str(payload.get("chapter_title") or "").strip(),
                        "summary": summary[:500],
                    }
                )
        return OutlinePlanningBrief(
            novel_type_id=novel_type_id,
            title=str(project.get("title") or ""),
            overall_context=dict(outline.get("overall") or {}),
            opening_direction=self._planning_opening_direction(project, outline),
            author_constraints=[str(item) for item in project.get("author_constraints", []) if str(item).strip()],
            existing_outline=outline,
            existing_characters=existing_cards,
            existing_character_names=existing_character_names,
            current_chapter=int(state.get("current_chapter") or 0),
            recent_chapter_summaries=[dict(item) for item in summaries[-3:] if isinstance(item, dict)],
            continuation_start_chapter=continuation_start,
            historical_chapter_summaries=historical_summaries,
            power_system_spec=(
                dict(blueprint.get("power_system_spec"))
                if isinstance(blueprint.get("power_system_spec"), dict)
                else {}
            ),
        )

    def _merge_generated_character_cards(self, generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
        project = self.project()
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        existing: dict[str, dict[str, Any]] = {}
        existing_order: list[str] = []
        for item in [
            *(project.get("character_profiles") if isinstance(project.get("character_profiles"), list) else []),
            *(state.get("characters") if isinstance(state.get("characters"), list) else []),
        ]:
            if not isinstance(item, dict) or is_non_character_card(item):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            if name not in existing:
                existing[name] = dict(item)
                existing_order.append(name)
            else:
                existing[name] = merge_character_profile(existing[name], item)

        generated_names: list[str] = []
        for card in generated:
            if is_non_character_card(card):
                continue
            name = str(card.get("name") or "").strip()
            if not name:
                continue
            generated_names.append(name)
            current = existing.get(name, {"name": name})
            merged = merge_character_profile(current, card)
            generated_role = str(card.get("role") or "").strip().casefold()
            generated_tier = str(card.get("character_tier") or "").strip().casefold()
            current_role = str(current.get("role") or "").strip().casefold()
            current_tier = str(current.get("character_tier") or "").strip().casefold()
            if generated_role == "protagonist" and current_role in {"", "supporting"}:
                merged["role"] = card["role"]
            if generated_tier == "protagonist" and current_tier in {"", "supporting"}:
                merged["character_tier"] = card["character_tier"]
            existing[name] = merged
        order = [*generated_names, *(name for name in existing_order if name not in generated_names)]
        cards = [
            normalize_character_profile(existing[name])
            for name in order
            if not is_non_character_card(existing[name])
        ]
        for card in cards:
            if not isinstance(card.get("relationships"), dict):
                card["relationships"] = {}
        return cards

    def _extend_outline(
        self,
        current: dict[str, Any],
        addition: dict[str, Any],
        *,
        current_chapter: int,
    ) -> dict[str, Any]:
        current = normalize_project_outline(current)
        addition = normalize_project_outline(addition)
        added_numbers = [int(item["chapter_number"]) for item in addition["chapters"]]
        expected = outline_window_status(
            current,
            current_chapter=current_chapter,
        )["next_chapter_numbers"]
        if not expected:
            raise ValueError("outline_window_already_full")
        if added_numbers != expected:
            raise ValueError("generated_chapters_do_not_match_target_window")
        arcs = {str(item["id"]): dict(item) for item in current["arcs"]}
        for arc in addition["arcs"]:
            arc_id = str(arc["id"])
            existing_arc = arcs.get(arc_id)
            if existing_arc is None:
                arcs[arc_id] = dict(arc)
                continue
            merged_arc = merge_character_profile(existing_arc, arc)
            merged_arc["end_chapter"] = max(int(existing_arc["end_chapter"]), int(arc["end_chapter"]))
            if existing_arc.get("trope_id") is not None:
                merged_arc["trope_id"] = existing_arc["trope_id"]
            merged_arc["long_term_antagonist_traces"] = list(
                dict.fromkeys(
                    [
                        *existing_arc.get("long_term_antagonist_traces", []),
                        *arc.get("long_term_antagonist_traces", []),
                    ]
                )
            )
            arcs[arc_id] = merged_arc
        return normalize_project_outline(
            {
                "overall": merge_character_profile(current["overall"], addition["overall"]),
                "arcs": list(arcs.values()),
                "chapters": [*current["chapters"], *addition["chapters"]],
            }
        )

    @staticmethod
    def _split_outline_arcs_at_boundary(
        outline: dict[str, Any],
        boundary: int,
    ) -> dict[str, Any]:
        normalized = normalize_project_outline(outline)
        source_arcs = [dict(arc) for arc in normalized["arcs"]]
        historical_ends = [
            int(arc["end_chapter"])
            for arc in source_arcs
            if int(arc["end_chapter"]) <= boundary
        ]
        latest_historical_end = max(historical_ends, default=0)
        boundary_is_historical = any(
            int(arc["start_chapter"]) <= boundary <= int(arc["end_chapter"])
            and int(arc["end_chapter"]) <= boundary
            for arc in source_arcs
        )
        arcs: list[dict[str, Any]] = []
        for arc in source_arcs:
            start = int(arc["start_chapter"])
            end = int(arc["end_chapter"])
            if not (start <= boundary < end):
                arcs.append(arc)
                continue
            if not boundary_is_historical:
                history_start = max(start, latest_historical_end + 1)
                if history_start <= boundary:
                    history_arc = {
                        **arc,
                        "id": f"{arc['id']}-history",
                        "title": f"{arc['title']}（已发生）",
                        "start_chapter": history_start,
                        "end_chapter": boundary,
                    }
                    arcs.append(history_arc)
                    latest_historical_end = boundary
                    boundary_is_historical = True
            arcs.append({**arc, "start_chapter": boundary + 1})
        return normalize_project_outline(
            {
                **normalized,
                "arcs": sorted(
                    arcs,
                    key=lambda item: (
                        int(item["start_chapter"]),
                        int(item["end_chapter"]),
                    ),
                ),
            }
        )

    def _preserve_committed_outline(
        self,
        current: dict[str, Any],
        generated: dict[str, Any],
        *,
        current_chapter: int,
        immutable_arc_through: int | None = None,
    ) -> dict[str, Any]:
        current = normalize_project_outline(current)
        generated = normalize_project_outline(generated)
        overall = dict(generated["overall"])
        current_primary_trope_id = self._outline_primary_trope_id(current)
        if current_primary_trope_id is not None:
            overall["primary_trope_id"] = current_primary_trope_id
        current_arcs = {str(item["id"]): dict(item) for item in current["arcs"]}
        arcs = {str(item["id"]): dict(item) for item in generated["arcs"]}
        for arc_id, current_arc in current_arcs.items():
            arc_start = int(current_arc["start_chapter"])
            arc_end = int(current_arc["end_chapter"])
            if immutable_arc_through is not None and arc_end <= immutable_arc_through:
                arcs[arc_id] = current_arc
                continue
            if arc_id not in arcs:
                crosses_immutable_boundary = (
                    immutable_arc_through is not None
                    and arc_start <= immutable_arc_through < arc_end
                )
                if arc_start <= current_chapter and not crosses_immutable_boundary:
                    arcs[arc_id] = current_arc
                continue
            if current_arc.get("trope_id") is not None:
                arcs[arc_id]["trope_id"] = current_arc["trope_id"]
        committed = {
            item["chapter_number"]: item
            for item in current["chapters"]
            if item["chapter_number"] <= current_chapter
        }
        future = {
            item["chapter_number"]: item
            for item in generated["chapters"]
            if item["chapter_number"] > current_chapter
        }
        merged = normalize_project_outline(
            {
                "overall": overall,
                "arcs": list(arcs.values()),
                "chapters": [*committed.values(), *future.values()],
            }
        )
        if immutable_arc_through is not None:
            return self._split_outline_arcs_at_boundary(
                merged,
                immutable_arc_through,
            )
        return merged

    @_with_project_update_lock
    def save_generated_outline_plan(self, plan: Any, *, mode: str) -> dict[str, Any]:
        validated = GeneratedOutlinePlan.model_validate(plan)
        if mode not in {"initial", "regenerate", "extend"}:
            raise ValueError("invalid_outline_planning_mode")

        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        project = dict(self.project())
        continuation = project.get("continuation") if isinstance(project.get("continuation"), dict) else {}
        raw_continuation_start = continuation.get("start_after_chapter")
        continuation_start = (
            int(raw_continuation_start)
            if isinstance(raw_continuation_start, int)
            and not isinstance(raw_continuation_start, bool)
            and raw_continuation_start >= 1
            else None
        )
        current_chapter = int(state.get("current_chapter") or 0)
        current_outline = dict(self.project_outline())
        current_outline.pop("source", None)
        validation_fallback_outline = current_outline
        if mode == "regenerate":
            validation_fallback_outline = deepcopy(current_outline)
            validation_fallback_outline["arcs"] = [
                arc
                for arc in validation_fallback_outline.get("arcs", [])
                if int(arc["start_chapter"]) <= current_chapter
            ]
            validation_fallback_outline["chapters"] = [
                chapter
                for chapter in validation_fallback_outline.get("chapters", [])
                if int(chapter["chapter_number"]) <= current_chapter
            ]
        trope_candidates = self._current_project_trope_candidates(project, state)
        expected_primary_trope_id = self._outline_primary_trope_id(current_outline)
        if mode == "initial":
            if current_chapter != 0:
                raise ValueError("initial_outline_requires_unstarted_project")
            expected_chapter_numbers = list(range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1))
        elif mode == "regenerate":
            ceiling = (
                current_chapter + INITIAL_OUTLINE_CHAPTER_COUNT
                if continuation_start is not None
                else normalize_project_outline(current_outline)["overall"][
                    "extension_ceiling_chapter"
                ]
            )
            expected_chapter_numbers = list(
                range(
                    current_chapter + 1,
                    min(current_chapter + INITIAL_OUTLINE_CHAPTER_COUNT, ceiling) + 1,
                )
            )
            if not expected_chapter_numbers:
                raise ValueError("outline_window_already_full")
        else:
            expected_chapter_numbers = outline_window_status(
                current_outline,
                current_chapter=current_chapter,
            )["next_chapter_numbers"]
            if not expected_chapter_numbers:
                raise ValueError("outline_window_already_full")
        if mode in {"initial", "regenerate"}:
            validated = validate_generated_opening_plan(
                validated.model_dump(mode="json"),
                expected_chapter_numbers=expected_chapter_numbers,
                trope_templates=trope_candidates,
                expected_primary_trope_id=expected_primary_trope_id,
                fallback_outline=validation_fallback_outline if mode == "regenerate" else None,
                committed_through_chapter=(
                    current_chapter if mode == "regenerate" else None
                ),
            )
        else:
            existing_character_names: set[str] = set()
            for item in [
                *(
                    project.get("character_profiles")
                    if isinstance(project.get("character_profiles"), list)
                    else []
                ),
                *(
                    state.get("characters")
                    if isinstance(state.get("characters"), list)
                    else []
                ),
            ]:
                if not isinstance(item, dict):
                    continue
                raw_name = str(item.get("name") or "").strip()
                canonical_name = self._canonical_character_name(raw_name)
                if raw_name:
                    existing_character_names.add(raw_name)
                if canonical_name:
                    existing_character_names.add(canonical_name)
            validated = validate_generated_continuation_plan(
                validated.model_dump(mode="json"),
                expected_chapter_numbers=expected_chapter_numbers,
                existing_character_names=existing_character_names,
                trope_templates=trope_candidates,
                expected_primary_trope_id=expected_primary_trope_id,
                fallback_outline=current_outline,
                committed_through_chapter=current_chapter,
            )

        generated_outline = validated.outline.model_dump(mode="json")
        if mode in {"extend", "regenerate"}:
            self._validate_generated_locked_tropes_match(
                current_outline,
                generated_outline,
                current_chapter=current_chapter,
                locked_through_chapter=(
                    continuation_start if mode == "regenerate" else None
                ),
            )
        if mode == "extend":
            generated_outline = self._extend_outline(
                current_outline,
                generated_outline,
                current_chapter=current_chapter,
            )
        elif mode == "regenerate":
            generated_outline = self._preserve_committed_outline(
                current_outline,
                generated_outline,
                current_chapter=current_chapter,
                immutable_arc_through=continuation_start,
            )
        final_validation_payload = validated.model_dump(mode="json")
        final_validation_payload["outline"] = generated_outline
        validate_generated_trope_selection(
            final_validation_payload,
            trope_candidates,
            expected_primary_trope_id=expected_primary_trope_id,
            fallback_outline=(
                validation_fallback_outline
                if mode == "regenerate"
                else current_outline if mode == "extend" else None
            ),
            committed_through_chapter=(
                current_chapter if mode in {"extend", "regenerate"} else None
            ),
        )
        cards = self._merge_generated_character_cards(
            [card.model_dump(mode="json") for card in validated.characters]
        )
        project["character_profiles"] = cards
        project["relationship_graph"] = merge_relationship_graph(
            project.get("relationship_graph"),
            graph_from_character_cards(cards),
        )
        project["pipeline_stage"] = "world_ready"
        first_arc = generated_outline["arcs"][0] if generated_outline["arcs"] else {}
        project["current_focus"] = str(first_arc.get("goal") or project.get("current_focus") or "")
        state["characters"] = cards
        state["outline"] = str(generated_outline["overall"].get("story") or state.get("outline") or "")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_path = self.story_system_dir / "plans" / f"{stamp}-{mode}.json"
        snapshot = {
            "schema_version": "generated-outline-plan/v1",
            "mode": mode,
            "outline": generated_outline,
            "characters": cards,
        }
        self._replace_json_transaction(
            {
                self.webnovel_dir / "outline.json": generated_outline,
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "state.json": state,
                snapshot_path: snapshot,
            }
        )
        return {**snapshot, "source": "generated"}

    def generate_outline_plan(
        self,
        generator: Any,
        *,
        mode: str,
        guidance: str = "",
        restart_from: str | None = None,
    ) -> dict[str, Any]:
        brief = self._planning_brief()
        normalized_guidance = guidance.strip()
        generate_parameters = inspect.signature(generator.generate).parameters
        supports_checkpoints = {
            "phase_payloads",
            "phase_callback",
        }.issubset(generate_parameters)
        if supports_checkpoints:
            fingerprint_source = {
                "mode": mode,
                "guidance": normalized_guidance,
                "brief": brief.model_dump(mode="json"),
            }
            fingerprint = sha256(
                json.dumps(
                    fingerprint_source,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            checkpoints = OutlineCheckpointStore(
                self.story_system_dir / "outline-generation"
            )
            checkpoints.prepare(fingerprint)
            if restart_from:
                checkpoints.invalidate_from(restart_from)

            def record_phase(
                phase: str,
                status: str,
                payload: dict[str, Any] | None,
                error: str,
            ) -> None:
                if status == "running":
                    checkpoints.mark_running(phase)
                elif status == "completed" and payload is not None:
                    checkpoints.complete(phase, payload)
                elif status == "failed":
                    checkpoints.fail(phase, error)

            plan = generator.generate(
                brief,
                mode=mode,
                guidance=normalized_guidance,
                phase_payloads=checkpoints.completed_payloads(),
                phase_callback=record_phase,
            )
        else:
            plan = generator.generate(
                brief,
                mode=mode,
                guidance=normalized_guidance,
            )
        return self.save_generated_outline_plan(plan, mode=mode)

    def outline_generation_checkpoints(self) -> dict[str, Any]:
        checkpoints = OutlineCheckpointStore(
            self.story_system_dir / "outline-generation"
        )
        status = checkpoints.status()
        payloads = checkpoints.completed_payloads()
        for phase in status.get("phases", []):
            if not isinstance(phase, dict):
                continue
            payload = payloads.get(str(phase.get("id") or ""))
            phase["has_payload"] = payload is not None
            if payload is not None:
                phase["payload"] = payload
        return status

    @staticmethod
    def _writer_scene_kind(scene_cards: list[dict[str, Any]], *, is_game_story: bool) -> str:
        return scene_kind_for_cards(scene_cards, is_game_story=is_game_story)

    def _writer_character_cards(
        self,
        state: dict[str, Any],
        selected_outline: dict[str, Any],
        *,
        scene_kind: str = "reality",
        is_game_story: bool = True,
    ) -> list[dict[str, Any]]:
        characters = [
            dict(item)
            for item in state.get("characters", [])
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and self._is_character_card(item)
        ]
        chapter = selected_outline.get("chapter") if isinstance(selected_outline.get("chapter"), dict) else {}
        cast = [str(item).strip() for item in chapter.get("cast", []) if str(item).strip()]

        protagonist = next(
            (
                card
                for card in characters
                if str(card.get("character_tier") or "").strip() == "protagonist"
                or str(card.get("role") or "").strip().lower() in {"protagonist", "主角"}
            ),
            None,
        )
        wanted = list(cast) if cast else [str(card.get("name") or "").strip() for card in characters[:6]]
        if protagonist:
            protagonist_name = str(protagonist.get("name") or "").strip()
            if protagonist_name and protagonist_name not in wanted:
                wanted.insert(0, protagonist_name)

        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for identifier in wanted:
            card = next(
                (item for item in characters if self._character_matches(item, identifier)),
                None,
            )
            if card is None:
                continue
            name = str(card.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            projected = project_character_for_scene(
                card,
                scene_kind=scene_kind,
                is_game_story=is_game_story,
            )
            selected.append(projected)
        return selected

    @staticmethod
    def _without_replaced_baseline_protagonists(
        characters: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cards = [dict(item) for item in characters if isinstance(item, dict)]

        def is_protagonist(card: dict[str, Any]) -> bool:
            return (
                str(card.get("character_tier") or "").strip().lower() == "protagonist"
                or str(card.get("role") or "").strip().lower() in {"protagonist", "主角"}
            )

        has_project_protagonist = any(
            is_protagonist(card)
            and str(card.get("introduced_by") or "").strip() != "baseline:protagonist"
            for card in cards
        )
        if not has_project_protagonist:
            return cards
        return [
            card
            for card in cards
            if not (
                is_protagonist(card)
                and str(card.get("introduced_by") or "").strip() == "baseline:protagonist"
            )
        ]

    @_with_project_update_lock
    def update_project(
        self,
        patch: dict[str, Any],
        *,
        replace_world_blueprint: bool = False,
    ) -> dict[str, Any]:
        world_blueprint_updated = patch.get("world_blueprint") is not None
        normalized_patch_genre_ids: list[str] | None = None
        patch_world_blueprint = patch.get("world_blueprint")
        if isinstance(patch_world_blueprint, dict) and "equipment_cards" in patch_world_blueprint:
            raw_equipment_cards = patch_world_blueprint.get("equipment_cards")
            if not isinstance(raw_equipment_cards, list):
                raise ValueError("invalid_equipment_cards")
            normalized_equipment_cards = normalize_equipment_cards(raw_equipment_cards)
            if len(normalized_equipment_cards) != len(raw_equipment_cards):
                raise ValueError("invalid_equipment_cards")
            patch_world_blueprint = dict(patch_world_blueprint)
            patch_world_blueprint["equipment_cards"] = normalized_equipment_cards
            patch = {**patch, "world_blueprint": patch_world_blueprint}
        if isinstance(patch_world_blueprint, dict) and "writing_style" in patch_world_blueprint:
            raw_writing_style = str(patch_world_blueprint.get("writing_style") or "").strip()
            normalized_writing_style = normalize_book_style(raw_writing_style)
            if raw_writing_style and not normalized_writing_style:
                raise ValueError("invalid_writing_style")
            patch_world_blueprint = dict(patch_world_blueprint)
            patch_world_blueprint["writing_style"] = normalized_writing_style
            patch = {**patch, "world_blueprint": patch_world_blueprint}
        if (
            patch_world_blueprint is not None
            and isinstance(patch_world_blueprint, dict)
            and "genre_plugin_ids" in patch_world_blueprint
        ):
            raw_genre_ids = patch_world_blueprint.get("genre_plugin_ids")
            if raw_genre_ids is None:
                genre_values: list[Any] = []
            elif isinstance(raw_genre_ids, str):
                genre_values = [raw_genre_ids]
            elif isinstance(raw_genre_ids, list):
                genre_values = raw_genre_ids
            else:
                raise ValueError("invalid_novel_type")

            normalized_patch_genre_ids = []
            for value in genre_values:
                if not str(value or "").strip():
                    continue
                resolved_id = resolve_novel_type_id(value)
                if not resolved_id:
                    raise ValueError("invalid_novel_type")
                if resolved_id not in normalized_patch_genre_ids:
                    normalized_patch_genre_ids.append(resolved_id)

        project = dict(self.project())
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        for key in (
            "title",
            "game_title",
            "world_summary",
            "author_constraints",
            "character_profiles",
            "relationship_graph",
            "enabled_skill_ids",
            "enabled_skill_module_ids",
            "status",
            "pipeline_stage",
            "project_lifecycle",
            "archived_at",
            "trashed_at",
            "pre_trash_lifecycle",
        ):
            if key in patch and patch[key] is not None:
                project[key] = patch[key]
        if isinstance(project.get("character_profiles"), list):
            project["character_profiles"] = filter_character_cards(project["character_profiles"])
        if isinstance(state.get("characters"), list):
            state["characters"] = filter_character_cards(state["characters"])
        for key in ("enabled_skill_ids", "enabled_skill_module_ids"):
            if key in patch and patch[key] is not None:
                state[key] = deepcopy(project[key])
        if "relationship_graph" in patch and patch.get("relationship_graph") is not None:
            project["relationship_graph"] = normalize_relationship_graph(patch["relationship_graph"])
        if patch.get("seed_outline") is not None:
            project["seed_outline"] = patch["seed_outline"]
            state["outline"] = patch["seed_outline"]
        if world_blueprint_updated:
            world_blueprint_patch = patch["world_blueprint"]
            world_blueprint = (
                deepcopy(world_blueprint_patch)
                if replace_world_blueprint
                else merge_world_blueprint(
                    project.get("world_blueprint"),
                    world_blueprint_patch,
                )
            )
            if normalized_patch_genre_ids is not None:
                world_blueprint = dict(world_blueprint)
                world_blueprint["genre_plugin_ids"] = normalized_patch_genre_ids
            project["world_blueprint"] = world_blueprint
            if isinstance(world_blueprint_patch, dict) and "equipment_cards" in world_blueprint_patch:
                state["equipment_cards"] = deepcopy(world_blueprint.get("equipment_cards") or [])
            if isinstance(world_blueprint_patch, dict) and "writing_style" in world_blueprint_patch:
                state["style"] = normalize_book_style(world_blueprint_patch.get("writing_style"))
            if isinstance(world_blueprint_patch, dict) and "genre_plugin_ids" in world_blueprint_patch:
                raw_genre_ids = world_blueprint.get("genre_plugin_ids")
                genre_plugin_ids = normalize_novel_type_ids(raw_genre_ids)
                explicitly_empty = raw_genre_ids in (None, "", []) or (
                    isinstance(raw_genre_ids, list)
                    and not any(str(item or "").strip() for item in raw_genre_ids)
                )
                synchronized_genre_ids: list[str] | None = None
                if genre_plugin_ids:
                    state["genre_plugin_ids"] = genre_plugin_ids
                    synchronized_genre_ids = genre_plugin_ids
                    primary_type = runtime_novel_type(genre_plugin_ids[0])
                    if primary_type is not None:
                        state["genre"] = primary_type.name
                elif explicitly_empty:
                    state["genre_plugin_ids"] = []
                    state["genre"] = ""
                    synchronized_genre_ids = []
                if synchronized_genre_ids is not None:
                    world_facts = (
                        state.get("world_facts")
                        if isinstance(state.get("world_facts"), list)
                        else []
                    )
                    state["world_facts"] = [
                        fact
                        for fact in world_facts
                        if not (
                            isinstance(fact, str)
                            and novel_type_id_from_metadata_fact(fact)
                        )
                    ]
                    if synchronized_genre_ids:
                        state["world_facts"].append(
                            f"小说类型：{synchronized_genre_ids[0]}"
                        )
        if patch.get("current_focus") is not None:
            project["current_focus"] = patch["current_focus"]
            state["current_focus"] = patch["current_focus"]
        elif isinstance(project.get("world_blueprint"), dict) and project["world_blueprint"].get("current_arc"):
            project["current_focus"] = project.get("current_focus") or project["world_blueprint"]["current_arc"]

        payloads = {
            self.webnovel_dir / "project.json": project,
            self.webnovel_dir / "state.json": state,
        }
        if world_blueprint_updated:
            master_path = self.story_system_dir / "MASTER_SETTING.json"
            master = dict(self._read_json(master_path, {}) or {})
            canonical_blueprint = deepcopy(project["world_blueprint"])
            master["world_blueprint"] = canonical_blueprint
            master_project = master.get("project")
            synchronized_master_project = (
                dict(master_project) if isinstance(master_project, dict) else {}
            )
            synchronized_master_project["world_blueprint"] = deepcopy(canonical_blueprint)
            for key in ("project_id", "active_story_id", "title", "game_title"):
                if key in project:
                    synchronized_master_project[key] = deepcopy(project[key])
            master["project"] = synchronized_master_project
            payloads[master_path] = master

        self._replace_json_transaction(payloads)
        if world_blueprint_updated:
            title = project.get("game_title") or project.get("title") or "未命名作品"
            try:
                sync_world_markdown(
                    self.root,
                    title,
                    project["world_blueprint"],
                )
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "world blueprint markdown sync failed",
                    exc_info=True,
                )
        return project

    @staticmethod
    def _merge_character_patch(current: Any, patch: Any) -> Any:
        if isinstance(current, dict) and isinstance(patch, dict):
            merged = dict(current)
            for key, value in patch.items():
                merged[key] = FileProjectStore._merge_character_patch(merged.get(key), value)
            return merged
        return patch

    @staticmethod
    def _character_matches(card: dict[str, Any], identifier: str) -> bool:
        target = str(identifier or "").strip()
        if not target:
            return False
        panel = card.get("game_panel") if isinstance(card.get("game_panel"), dict) else {}
        return target in {
            str(card.get("name") or "").strip(),
            str(card.get("game_id") or "").strip(),
            str(panel.get("game_id") or "").strip(),
        }

    def _completed_character_card(self, card: dict[str, Any], *, genre: str = "") -> dict[str, Any]:
        def drop_none(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: drop_none(item) for key, item in value.items() if item is not None}
            if isinstance(value, list):
                return [drop_none(item) for item in value]
            return value

        card = drop_none(card)
        raw_state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        normalized_card = _normalize_character_persistence_card(
            card,
            is_game_story=self._is_game_story_payload(self.project(), raw_state),
        )
        validated = CharacterState.model_validate(normalized_card)
        completed = complete_portrait(
            validated,
            genre=genre,
            story_function=str(normalized_card.get("story_function") or ""),
        )
        completed_card = self._merge_character_patch(
            normalized_card,
            completed.model_dump(exclude_defaults=True, exclude_none=True),
        )
        return _normalize_character_persistence_card(
            completed_card,
            is_game_story=self._is_game_story_payload(self.project(), raw_state),
        )

    def update_character(self, name: str, patch: dict[str, Any]) -> dict[str, Any]:
        identifier = str(name or "").strip()
        if not identifier:
            raise KeyError("character_not_found:")
        patch = dict(patch or {})

        visible_state = self.state()
        visible_cards = visible_state.get("characters") if isinstance(visible_state.get("characters"), list) else []
        current = next(
            (dict(item) for item in visible_cards if isinstance(item, dict) and self._character_matches(item, identifier)),
            None,
        )
        if current is None:
            raise KeyError(f"character_not_found:{identifier}")
        canonical_name = str(current.get("name") or "").strip()
        if patch.get("name") and str(patch["name"]).strip() != canonical_name:
            raise ValueError("character_name_immutable")

        merged = self._merge_character_patch(current, patch)
        merged["name"] = canonical_name
        completed = self._completed_character_card(merged, genre=str(visible_state.get("genre") or ""))

        raw_state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        raw_cards = [dict(item) for item in raw_state.get("characters", []) if isinstance(item, dict)]
        raw_index = next(
            (index for index, item in enumerate(raw_cards) if self._character_matches(item, canonical_name)),
            None,
        )
        if raw_index is None:
            raw_cards.append(completed)
        else:
            raw_cards[raw_index] = self._merge_character_patch(raw_cards[raw_index], completed)
        is_game_story = self._is_game_story_payload(self.project(), raw_state)
        raw_cards = [
            _normalize_character_persistence_card(card, is_game_story=is_game_story)
            for card in raw_cards
        ]
        raw_state["characters"] = raw_cards

        project = dict(self.project())
        project_cards = [dict(item) for item in project.get("character_profiles", []) if isinstance(item, dict)]
        project_index = next(
            (index for index, item in enumerate(project_cards) if self._character_matches(item, canonical_name)),
            None,
        )
        if project_index is None:
            project_cards.append(dict(completed))
        else:
            project_cards[project_index] = self._merge_character_patch(project_cards[project_index], completed)
        project["character_profiles"] = [
            _normalize_character_persistence_card(card, is_game_story=is_game_story)
            for card in project_cards
        ]
        self._replace_json_transaction(
            {
                self.webnovel_dir / "state.json": raw_state,
                self.webnovel_dir / "project.json": project,
            }
        )

        return raw_cards[raw_index if raw_index is not None else -1]

    def complete_character_portrait(self, name: str) -> dict[str, Any]:
        identifier = str(name or "").strip()
        visible_state = self.state()
        cards = visible_state.get("characters") if isinstance(visible_state.get("characters"), list) else []
        current = next(
            (dict(item) for item in cards if isinstance(item, dict) and self._character_matches(item, identifier)),
            None,
        )
        if current is None:
            raise KeyError(f"character_not_found:{identifier}")
        completed = self._completed_character_card(current, genre=str(visible_state.get("genre") or ""))
        return self.update_character(str(completed.get("name") or identifier), completed)

    def _read_chapter_records(
        self,
        *,
        ignore_errors: bool = False,
    ) -> list[tuple[int, dict[str, Any]]]:
        records: list[tuple[int, dict[str, Any]]] = []
        for number in self.chapter_numbers():
            try:
                chapter = self._read_json(
                    self.story_system_dir / "chapters" / f"{number:04d}.json",
                    {},
                )
            except (OSError, ValueError, json.JSONDecodeError):
                if not ignore_errors:
                    raise
                chapter = {}
            records.append((number, chapter if isinstance(chapter, dict) else {}))
        return records

    def _visible_state_from_chapters(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        chapters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        sanitized = self._sanitize_story_state(state)
        additions: list[dict[str, Any]] = []
        saved_characters = sanitized.get("characters") if isinstance(sanitized.get("characters"), list) else []
        project_profiles = {
            str(card.get("name") or "").strip(): card
            for card in project.get("character_profiles", [])
            if isinstance(card, dict) and str(card.get("name") or "").strip()
        }
        for index, saved in enumerate(saved_characters):
            if not isinstance(saved, dict):
                continue
            profile = project_profiles.get(str(saved.get("name") or "").strip())
            if not isinstance(profile, dict):
                continue
            if str(profile.get("character_tier") or "").strip().casefold() == "protagonist":
                promoted = dict(saved)
                promoted["role"] = "protagonist"
                promoted["character_tier"] = "protagonist"
                saved_characters[index] = promoted
        sanitized["characters"] = saved_characters
        protagonist_indexes = [
            index
            for index, card in enumerate(saved_characters)
            if isinstance(card, dict)
            and (
                str(card.get("role") or "").strip().casefold() in {"protagonist", "主角"}
                or str(card.get("character_tier") or "").strip().casefold() == "protagonist"
            )
        ]
        is_game_story = self._is_game_story_payload(project, sanitized)
        if protagonist_indexes and is_game_story:
            ledger = sanitized.get("progression_ledger") if isinstance(sanitized.get("progression_ledger"), dict) else {}
            real = ledger.get("real") if isinstance(ledger.get("real"), dict) else {}
            real_balance = real.get("end_balance") or real.get("balance")
            for index in protagonist_indexes:
                card = dict(saved_characters[index])
                self._sync_game_character_from_ledger(
                    card,
                    ledger,
                    chapter_number=int(sanitized.get("current_chapter") or 0),
                )
                if real_balance:
                    real_state = dict(card.get("real_state") or {})
                    current_real = dict(real_state.get("current") or {})
                    current_real["balance"] = real_balance
                    real_state["current"] = current_real
                    real_state.setdefault("recent_changes", [])
                    card["real_state"] = real_state
                saved_characters[index] = card
            sanitized["characters"] = saved_characters
        elif not protagonist_indexes and is_game_story:
            protagonist_card = self._protagonist_character_card(sanitized, project)
            if protagonist_card:
                additions.append(protagonist_card)
        if is_game_story:
            additions.extend(self._proposed_character_cards_from_outline(sanitized, project))
            for chapter in chapters:
                additions.extend(self._chapter_entity_cards(chapter))
        if additions:
            sanitized["characters"] = self._merge_character_cards(list(sanitized.get("characters") or []), additions)
        characters = sanitized.get("characters") if isinstance(sanitized.get("characters"), list) else []
        characters = self._without_replaced_baseline_protagonists(
            item for item in characters if isinstance(item, dict)
        )
        characters = remove_cross_character_aliases(
            item for item in characters if isinstance(item, dict)
        )
        genre = str(sanitized.get("genre") or project.get("genre") or "")
        sanitized["characters"] = [
            self._completed_character_card(dict(item), genre=genre)
            for item in characters
            if isinstance(item, dict) and self._is_character_card(item)
        ]
        return sanitized

    def state(self) -> dict[str, Any]:
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        project = self.project()
        records = self._read_chapter_records(ignore_errors=True)
        return self._visible_state_from_chapters(
            state if isinstance(state, dict) else {},
            project,
            [chapter for _, chapter in records],
        )

    def _valid_foreshadowing_ledger(self, raw_ledger: Any) -> list[ForeshadowingState]:
        parsed = self._parse_foreshadowing_ledger(raw_ledger)
        valid = [
            item
            for item in parsed
            if item.text.strip()
            and item.first_chapter >= 0
            and item.last_touched_chapter >= item.first_chapter
            and (
                item.resolved_chapter is None
                or item.resolved_chapter >= item.last_touched_chapter
            )
            and (item.status != "resolved" or item.resolved_chapter is not None)
            and (
                item.status not in {"open", "reinforced"}
                or item.resolved_chapter is None
            )
        ]
        return canonicalize_foreshadowing_ledger(valid)

    def foreshadowing_ledger(self) -> list[ForeshadowingState]:
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        raw_ledger = state.get("foreshadowing") if isinstance(state, dict) else None
        return self._valid_foreshadowing_ledger(raw_ledger)

    @staticmethod
    def foreshadowing_version(ledger: list[ForeshadowingState]) -> str:
        payload = json.dumps(
            [item.model_dump(mode="json") for item in ledger],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    @_with_project_update_lock
    def update_foreshadowing_ledger(
        self,
        ledger: list[ForeshadowingState],
        *,
        expected_version: str | None = None,
    ) -> list[ForeshadowingState]:
        canonical = canonicalize_foreshadowing_ledger(ledger)
        state_path = self.webnovel_dir / "state.json"
        state = self._read_json(state_path, {}) or {}
        if not isinstance(state, dict):
            raise ValueError("invalid_story_state")
        current = self._valid_foreshadowing_ledger(state.get("foreshadowing"))
        if expected_version is not None and expected_version != self.foreshadowing_version(current):
            raise ValueError("foreshadowing_version_conflict")
        if expected_version is None:
            current_keys = {
                normalize_foreshadowing_text(item.text)
                for item in current
            }
            canonical = canonicalize_foreshadowing_ledger(
                [
                    *current,
                    *[
                        item
                        for item in canonical
                        if normalize_foreshadowing_text(item.text) not in current_keys
                    ],
                ]
            )
        updated = dict(state)
        updated["foreshadowing"] = [item.model_dump() for item in canonical]
        existing = {
            normalize_foreshadowing_text(item.text): item
            for item in self._parse_foreshadowing_ledger(state.get("foreshadowing"))
        }
        previously_manual = {
            normalize_foreshadowing_text(item.text): item
            for item in self._parse_foreshadowing_ledger(state.get("manual_foreshadowing"))
        }
        manual: list[ForeshadowingState] = []
        for item in canonical:
            key = normalize_foreshadowing_text(item.text)
            prior = existing.get(key)
            if key in previously_manual or prior is None or item != prior:
                manual.append(item)
        updated["manual_foreshadowing"] = [
            item.model_dump()
            for item in canonicalize_foreshadowing_ledger(manual)
        ]
        self._write_json_atomic(state_path, updated)
        return canonical

    def chapter_numbers(self) -> list[int]:
        return self.chapter_store.chapter_numbers()

    def _has_chapter_files(self) -> bool:
        return self.chapter_store.has_chapters()

    def chapter(self, chapter_number: int | None = None) -> dict[str, Any]:
        if chapter_number is not None and chapter_number > 0:
            path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
            chapter = self._read_json(path)
            if not isinstance(chapter, dict):
                if not self._has_chapter_files():
                    raise FileNotFoundError("no_chapters")
                raise FileNotFoundError(f"chapter_not_found:{chapter_number}")
            raw_state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
            visible_state = self._visible_state_from_chapters(
                raw_state if isinstance(raw_state, dict) else {},
                self.project(),
                [chapter],
            )
            return self._hydrate_chapter_display_fields(chapter, state=visible_state)

        numbers = self.chapter_numbers()
        if not numbers:
            raise FileNotFoundError("no_chapters")
        target = chapter_number or numbers[-1]
        path = self.story_system_dir / "chapters" / f"{target:04d}.json"
        chapter = self._read_json(path)
        if not isinstance(chapter, dict):
            raise FileNotFoundError(f"chapter_not_found:{target}")
        return self._hydrate_chapter_display_fields(chapter)

    def _chapter_index_from_records(
        self,
        records: list[tuple[int, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for number, chapter in records:
            try:
                payload_chapter_number = int(chapter.get("chapter_number") or number)
            except (TypeError, ValueError):
                payload_chapter_number = number
            chapter_summary = chapter.get("chapter_summary")
            summary = chapter_summary if isinstance(chapter_summary, dict) else {}
            body = str(chapter.get("body") or "")
            summary_text = self._compact_text(summary.get("summary") or "", 320)
            next_focus = self._compact_text(
                chapter.get("next_outline") or summary.get("next_focus") or "",
                220,
            )
            quality_report = chapter.get("quality_report")
            simulation_status = chapter.get("simulation_status")
            entries.append(
                {
                    "chapter_number": payload_chapter_number,
                    "chapter_title": str(chapter.get("chapter_title") or f"第{number}章"),
                    "body_chars": len("".join(body.split())),
                    "summary": summary_text,
                    "next_focus": next_focus,
                    "has_quality_report": isinstance(quality_report, dict) and bool(quality_report),
                    "has_simulation": isinstance(simulation_status, dict) and bool(simulation_status),
                }
            )
        return entries

    def chapter_index(self) -> list[dict[str, Any]]:
        return self._chapter_index_from_records(self._read_chapter_records())

    def story_overview_data(self) -> dict[str, Any]:
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        project = self.project()
        records = self._read_chapter_records()
        return {
            "project": project,
            "state": self._visible_state_from_chapters(
                state if isinstance(state, dict) else {},
                project,
                [chapter for _, chapter in records],
            ),
            "chapters": self._chapter_index_from_records(records),
        }

    def review(self, chapter_number: int | None = None) -> dict[str, Any]:
        chapter = self.chapter(chapter_number)
        target = int(chapter.get("chapter_number") or chapter_number or 0)
        review = self._read_json(self.story_system_dir / "reviews" / f"{target:04d}.json")
        if isinstance(review, dict) and review:
            return _project_legacy_review(review)
        quality_report = chapter.get("quality_report")
        if isinstance(quality_report, dict) and quality_report:
            return _project_legacy_review(quality_report)
        return validate_bundle(chapter)

    def commit(self, *, message: str, operation: str = "manual", chapter_number: int | None = None) -> dict[str, Any]:
        commits_dir = self.story_system_dir / "commits"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest: list[dict[str, Any]] = []
        for path in [
            self.story_system_dir / "MASTER_SETTING.json",
            self.webnovel_dir / "project.json",
            self.webnovel_dir / "state.json",
            *sorted((self.story_system_dir / "chapters").glob("*.json")),
            *sorted((self.story_system_dir / "reviews").glob("*.json")),
            *sorted(self.chapters_dir.glob("*.md")),
        ]:
            if not path.exists() or not path.is_file():
                continue
            data = path.read_bytes()
            manifest.append(
                {
                    "path": path.relative_to(self.root).as_posix(),
                    "bytes": len(data),
                    "sha256": sha256(data).hexdigest(),
                }
            )
        payload = {
            "schema_version": "file-project-commit/v1",
            "timestamp": timestamp,
            "operation": operation,
            "message": message,
            "chapter_number": chapter_number,
            "project": self.summary(),
            "manifest": manifest,
        }
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", f"{operation}-ch{chapter_number}" if chapter_number else operation).strip("-")
        commit_path = commits_dir / f"{timestamp}-{slug or 'commit'}.json"
        self._write_json(commit_path, payload)
        self._write_json(commits_dir / "latest_commit.json", payload | {"commit_file": commit_path.relative_to(self.root).as_posix()})
        return payload | {"commit_file": commit_path.relative_to(self.root).as_posix()}

    def write_chapter(
        self,
        *,
        chapter_number: int,
        title: str,
        body: str,
        next_outline: str = "",
        summary: str = "",
        instructions: list[str] | None = None,
        overwrite: bool = False,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        if chapter_number <= 0:
            raise ValueError("chapter_number_must_be_positive")
        self._assert_chapter_not_frozen(chapter_number, "write")
        self._assert_opening_preflight(chapter_number)
        if not str(body).strip():
            raise ValueError("body_required")
        paths = self._chapter_paths(chapter_number, title)
        if paths["json"].exists() and not overwrite:
            raise FileExistsError(f"chapter_exists:{chapter_number}")

        state = self.state()
        current_chapter = max(int(state.get("current_chapter") or 0), chapter_number)
        chapter_summary = {
            "chapter_title": title,
            "cadence": "measured",
            "summary": summary or f"Manual chapter {chapter_number}.",
            "facts": [item for item in (instructions or []) if str(item).strip()] or ["manual draft"],
            "next_focus": next_outline or "continue",
            "primary_conflict": "manual draft",
            "secondary_conflict": "manual draft",
            "event_beat": "manual draft",
        }
        updated_story = dict(state)
        updated_story["current_chapter"] = current_chapter
        if not updated_story.get("timeline"):
            updated_story["timeline"] = [f"chapter {chapter_number}: {title}"]
        if not updated_story.get("chapter_summaries"):
            updated_story["chapter_summaries"] = [chapter_summary]

        chapter = {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "body": body,
            "cadence": "measured",
            "next_outline": next_outline or "continue",
            "chapter_summary": chapter_summary,
            "event_plan": {
                "chapter_number": chapter_number,
                "next_focus": next_outline or "continue",
                "stakes": summary or next_outline or "manual draft",
                "world_reactions": chapter_summary["facts"][:3],
            },
            "updated_story": updated_story,
            "manual_instructions": instructions or [],
        }
        chapter = self._hydrate_chapter_display_fields(chapter, updated_story)
        review = _manual_chapter_quality_report(
            chapter,
            genre_context=self._review_genre_context(),
        )
        chapter["quality_report"] = review
        self._append_workflow_log(
            chapter_number=chapter_number,
            chapter_title=title,
            review=review,
            operation="write",
        )

        synced_state = self._sync_after_chapter(chapter, updated_story)
        self._remove_chapter_markdowns(chapter_number)
        self._write_json(paths["json"], chapter)
        self._write_json(paths["review"], review)
        self._write_text(paths["markdown"], body)
        synced_state["current_chapter"] = max(int(synced_state.get("current_chapter") or 0), current_chapter)
        self._write_json(self.webnovel_dir / "state.json", synced_state)
        commit = self.commit(
            message=commit_message or f"write chapter {chapter_number}",
            operation="write",
            chapter_number=chapter_number,
        )
        return {
            "schema_version": "file-project-write/v1",
            "root": str(self.root),
            "chapter_number": chapter_number,
            "chapter_title": title,
            "files": {key: path.relative_to(self.root).as_posix() for key, path in paths.items() if path.exists()},
            "review": review,
            "commit": commit,
        }

    def _apply_historical_foreshadowing_projection(
        self,
        chapter: dict[str, Any],
        payloads: dict[Path, Any],
        projection: dict[str, Any],
    ) -> None:
        target_chapter = int(chapter.get("chapter_number") or 0)
        state_path = self.webnovel_dir / "state.json"
        if isinstance(payloads.get(state_path), dict):
            payloads[state_path]["foreshadowing"] = deepcopy(projection["final"])
            payloads[state_path]["manual_foreshadowing"] = deepcopy(
                projection.get("manual") or []
            )

        by_chapter = projection.get("by_chapter") or {}
        source_chapters = projection.get("chapters") or {}
        for chapter_number, ledger in by_chapter.items():
            if chapter_number < target_chapter:
                continue
            if chapter_number == target_chapter:
                target_snapshot = chapter.get("updated_story")
                if isinstance(target_snapshot, dict):
                    target_snapshot["foreshadowing"] = deepcopy(ledger)
                continue
            path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
            saved_chapter = deepcopy(payloads.get(path) or source_chapters.get(chapter_number))
            snapshot = saved_chapter.get("updated_story") if isinstance(saved_chapter, dict) else None
            if isinstance(snapshot, dict):
                snapshot["foreshadowing"] = deepcopy(ledger)
                payloads[path] = saved_chapter

    def _persist_historical_transaction(
        self,
        chapter: dict[str, Any],
        review: dict[str, Any],
        body: str,
        payloads: dict[Path, Any],
        *,
        operation: str,
        commit_message: str | None,
    ) -> tuple[dict[str, Path], dict[str, Any]]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        title = str(chapter.get("chapter_title") or f"Chapter {chapter_number}")
        paths = self._chapter_paths(chapter_number, title)
        existing_markdowns = list(self.chapters_dir.glob(f"{chapter_number:04d}*.md"))
        managed_snapshot = self._snapshot_managed_files(
            [
                *payloads,
                paths["json"],
                paths["review"],
                paths["markdown"],
                *existing_markdowns,
            ],
            [self.story_system_dir / "commits"],
        )
        try:
            payloads[paths["json"]] = chapter
            payloads[paths["review"]] = review
            self._replace_json_transaction(payloads)
            self._remove_chapter_markdowns(chapter_number)
            self._write_text(paths["markdown"], body)
            commit = self.commit(
                message=commit_message or f"{operation} chapter {chapter_number}",
                operation=operation,
                chapter_number=chapter_number,
            )
        except Exception:
            try:
                self._restore_managed_files(*managed_snapshot)
            except Exception as rollback_exc:
                raise RuntimeError("historical_persistence_rollback_failed") from rollback_exc
            raise
        return paths, commit

    @_with_project_update_lock
    def persist_bundle(
        self,
        bundle: Any,
        *,
        operation: str = "generate",
        commit_message: str | None = None,
        accept_quality_warnings: bool = False,
    ) -> dict[str, Any]:
        chapter = self._bundle_to_dict(bundle)
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            raise ValueError("chapter_number_must_be_positive")
        title = _normalize_chapter_title(str(chapter.get("chapter_title") or f"Chapter {chapter_number}"), chapter_number)
        chapter["chapter_title"] = title
        if isinstance(chapter.get("chapter_summary"), dict):
            chapter["chapter_summary"]["chapter_title"] = title
        body = str(chapter.get("body") or "")
        updated_story = chapter.get("updated_story")
        if hasattr(updated_story, "model_dump"):
            updated_story = updated_story.model_dump(mode="json")
            chapter["updated_story"] = updated_story
        quality_report = chapter.get("quality_report")
        if not isinstance(quality_report, dict) or not quality_report:
            quality_report = validate_bundle(chapter)
            chapter["quality_report"] = quality_report
        failure_reason = _bundle_generation_failure_reason(quality_report)
        if not body.strip():
            if operation in {"generate", "regenerate"}:
                if not failure_reason:
                    writing_review = quality_report.get("writing_review") if isinstance(quality_report, dict) else {}
                    if isinstance(writing_review, dict):
                        quality_issues = [str(item) for item in (writing_review.get("issues") or []) if str(item).strip()]
                    else:
                        quality_issues = []
                    if not quality_issues:
                        quality_issues = [str(item) for item in (quality_report.get("issues") or []) if str(item).strip()] if isinstance(quality_report, dict) else []
                    failure_reason = "; ".join(quality_issues[:4]) if quality_issues else "empty_body"
                if not failure_reason:
                    failure_reason = "empty_body"
                reason = failure_reason
                raise ValueError(f"{operation}_failed:{reason}")
            raise ValueError("body_required")
        if operation in {"generate", "regenerate"} and failure_reason:
            raise ValueError(f"{operation}_failed:{failure_reason}")
        chapter = self._ensure_regenerate_continuity_fields(
            chapter,
            chapter_number=chapter_number,
            chapter_title=title,
        )
        _assert_auto_chapter_length(body, operation=operation)

        review = quality_report
        if "writing_review" not in review:
            review = {
                "schema_version": "file-writing-review/v1",
                "writing_review": {"pass": bool(quality_report.get("ok")), "issues": quality_report.get("issues", [])},
                "quality_report": quality_report,
            }
            chapter["quality_report"] = review

        assertion_report = quality_report if isinstance(quality_report, dict) else {}
        if "writing_review" in review and isinstance(review["writing_review"], dict) and "writing_review" not in assertion_report:
            assertion_report = dict(assertion_report)
            assertion_report["writing_review"] = review["writing_review"]

        try:
            if accept_quality_warnings:
                assertion_report["manual_quality_override"] = True
                if isinstance(quality_report, dict):
                    quality_report["manual_quality_override"] = True
                if isinstance(review, dict):
                    review["manual_quality_override"] = True
            else:
                _assert_auto_chapter_quality(assertion_report, operation=operation)
            if bool(assertion_report.get("regeneration_degraded")):
                if isinstance(quality_report, dict):
                    quality_report["regeneration_degraded"] = True
                if isinstance(review, dict):
                    review["regeneration_degraded"] = True
        except ValueError:
            failed_dir = self.root / ".story-system" / "failed-drafts"
            failed_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            failed_path = failed_dir / f"{stamp}-{operation}-ch{chapter_number}.json"
            self._write_json(
                failed_path,
                {
                    "schema_version": "file-project-failed-draft/v1",
                    "operation": operation,
                    "chapter_number": chapter_number,
                    "chapter_title": title,
                    "body": body,
                    "review": review,
                },
            )
            raise

        historical_foreshadowing = (
            self._historical_foreshadowing_for_rewrite(chapter)
            if operation == "regenerate"
            else None
        )
        historical_rebase = (
            self._prepare_historical_attribute_rebase(chapter, updated_story)
            if operation == "regenerate"
            else None
        )

        if historical_rebase is not None:
            chapter, payloads = historical_rebase
            if historical_foreshadowing is not None:
                self._apply_historical_foreshadowing_projection(
                    chapter,
                    payloads,
                    historical_foreshadowing,
                )
            paths, commit = self._persist_historical_transaction(
                chapter,
                review,
                body,
                payloads,
                operation=operation,
                commit_message=commit_message,
            )
            self._append_workflow_log(
                chapter_number=chapter_number,
                chapter_title=title,
                review=review,
                operation=operation,
            )
            return {
                "schema_version": "file-project-persist-bundle/v1",
                "root": str(self.root),
                "chapter_number": chapter_number,
                "chapter_title": title,
                "files": {key: path.relative_to(self.root).as_posix() for key, path in paths.items() if path.exists()},
                "review": review,
                "commit": commit,
            }

        if historical_foreshadowing is not None:
            current_state = self.state()
            target_snapshot = self._validated_runtime_state(updated_story, current_state)
            base_state = self._usable_bundle_state(
                updated_story,
                current_state,
                target_chapter=chapter_number,
            )
            base_state = dict(base_state)
            base_state["foreshadowing"] = deepcopy(historical_foreshadowing["final"])
            chapter = self._hydrate_chapter_display_fields(chapter, base_state)
            synced_state, synced_project = self._prepare_sync_after_chapter(chapter, base_state)
            synced_state["foreshadowing"] = deepcopy(historical_foreshadowing["final"])

            if target_snapshot is not None:
                target_snapshot = self._sync_state_after_chapter(
                    deepcopy(target_snapshot),
                    chapter,
                )
                target_snapshot = self._sync_ledger_from_chapter_body(target_snapshot, chapter)
                target_snapshot["current_chapter"] = chapter_number
                chapter["updated_story"] = target_snapshot

            payloads = {
                self.webnovel_dir / "state.json": synced_state,
                self.webnovel_dir / "project.json": synced_project,
            }
            self._apply_historical_foreshadowing_projection(
                chapter,
                payloads,
                historical_foreshadowing,
            )
            paths, commit = self._persist_historical_transaction(
                chapter,
                review,
                body,
                payloads,
                operation=operation,
                commit_message=commit_message,
            )
            self._append_workflow_log(
                chapter_number=chapter_number,
                chapter_title=title,
                review=review,
                operation=operation,
            )
            return {
                "schema_version": "file-project-persist-bundle/v1",
                "root": str(self.root),
                "chapter_number": chapter_number,
                "chapter_title": title,
                "files": {key: path.relative_to(self.root).as_posix() for key, path in paths.items() if path.exists()},
                "review": review,
                "commit": commit,
            }

        self._append_workflow_log(
            chapter_number=chapter_number,
            chapter_title=title,
            review=review,
            operation=operation,
        )
        base_state = self._usable_bundle_state(
            updated_story,
            self.state(),
            target_chapter=chapter_number,
        )
        chapter = self._hydrate_chapter_display_fields(chapter, base_state)
        self._sync_after_chapter(chapter, base_state)

        paths = self._chapter_paths(chapter_number, title)
        self._remove_chapter_markdowns(chapter_number)
        self._write_json(paths["json"], chapter)
        self._write_json(paths["review"], review)
        self._write_text(paths["markdown"], body)
        commit = self.commit(
            message=commit_message or f"{operation} chapter {chapter_number}",
            operation=operation,
            chapter_number=chapter_number,
        )
        return {
            "schema_version": "file-project-persist-bundle/v1",
            "root": str(self.root),
            "chapter_number": chapter_number,
            "chapter_title": title,
            "files": {key: path.relative_to(self.root).as_posix() for key, path in paths.items() if path.exists()},
            "review": review,
            "commit": commit,
        }

    def _generation_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Reconcile accepted chapter bodies before planning another chapter."""

        reconciled = deepcopy(state)
        current_chapter = int(reconciled.get("current_chapter") or 0)
        for chapter_number in self.chapter_numbers():
            if current_chapter and chapter_number > current_chapter:
                break
            chapter_path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
            chapter = self._read_json(chapter_path, {}) or {}
            if isinstance(chapter, dict) and str(chapter.get("body") or "").strip():
                self._sync_ledger_from_chapter_body(reconciled, deepcopy(chapter))
        return reconciled

    def _generation_state_for_target(
        self,
        current_state: dict[str, Any],
        target_chapter: int,
    ) -> dict[str, Any]:
        """Build the same chapter-start state for generation and prompt previews."""

        numbers = self.chapter_numbers()
        latest_number = numbers[-1] if numbers else 0
        saved_current_chapter = max(latest_number, int(current_state.get("current_chapter") or 0))
        if target_chapter > saved_current_chapter:
            return self._generation_state(current_state)
        if target_chapter > 1:
            state = self._regeneration_base_state(target_chapter, current_state)
        else:
            state = self._conservative_regeneration_state(current_state)
        state["current_chapter"] = target_chapter - 1
        return state

    def generate_next_chapter(
        self,
        engine: Any | None = None,
        *,
        chapter_direction_id: str | None = None,
        commit_message: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        from packages.story_core.engine import StoryEngine

        state = self._generation_state(self.state())
        project = self.project()
        target_chapter = int(state.get("current_chapter") or 0) + 1
        chapter_direction = self._resolve_chapter_direction(state, project, target_chapter, chapter_direction_id)
        if chapter_direction:
            state = dict(state)
            ledger = dict(state.get("progression_ledger") or {})
            ledger["chapter_direction"] = chapter_direction
            state["progression_ledger"] = ledger
        story = StoryState.model_validate(self._story_state_payload_for_direction(state, project, target_chapter))
        generator = engine or StoryEngine()
        with prompt_template_scope(self.prompt_template_object, self.prompt_template_source), prompt_call_recording(
            self.prompt_call_log()
        ):
            bundle = generator.generate_next_chapter(story)
        if not persist:
            project_id = str(
                project.get("project_id")
                or project.get("active_story_id")
                or state.get("story_id")
                or self.root.name
            )
            candidate = self._save_candidate_from_bundle(bundle, project_id=project_id)
            return {
                "schema_version": "file-project-candidate/v1",
                "root": str(self.root),
                "chapter_number": candidate.chapter_number,
                "chapter_title": candidate.chapter_title,
                "candidate": candidate.to_dict(),
            }
        persisted = self.persist_bundle(bundle, operation="generate", commit_message=commit_message)
        return {
            "schema_version": "file-project-generate-next/v1",
            "root": str(self.root),
            "chapter_number": persisted["chapter_number"],
            "chapter_title": persisted["chapter_title"],
            "chapter_direction": chapter_direction,
            "persisted": persisted,
        }

    @_with_project_update_lock
    def confirm_candidate(self, candidate_id: str, *, accept_quality_warnings: bool = False) -> dict[str, Any]:
        candidate = self.candidate_store.get(candidate_id)
        if candidate is None:
            raise FileNotFoundError("candidate_not_found")
        project = self.project()
        project_id = str(
            project.get("project_id")
            or project.get("active_story_id")
            or self.state().get("story_id")
            or self.root.name
        )
        if candidate.project_id != project_id:
            raise FileNotFoundError("candidate_not_found")
        if candidate.status == "confirmed":
            return {"schema_version": "file-project-candidate-confirm/v1", "candidate": candidate.to_dict()}
        if candidate.status != "pending":
            raise ValueError("candidate_not_pending")
        payload = dict(candidate.submission_payload)
        if not payload:
            raise ValueError("candidate_submission_payload_missing")
        payload["body"] = candidate.body
        payload["chapter_title"] = candidate.chapter_title or payload.get("chapter_title")
        self.persist_bundle(
            payload,
            operation=candidate.operation,
            accept_quality_warnings=accept_quality_warnings,
        )
        candidate.confirm()
        self.candidate_store.save(candidate)
        return {"schema_version": "file-project-candidate-confirm/v1", "candidate": candidate.to_dict()}

    def _regeneration_variant(self, chapter_number: int) -> dict[str, Any]:
        variants = [
            {
                "id": "focus-conflict-cost",
                "axes": ["核心冲突", "人物付出的代价"],
                "avoid": [],
            },
            {
                "id": "focus-character-choice",
                "axes": ["人物选择", "关系变化"],
                "avoid": ["照搬上一版的行动顺序", "只替换措辞而不改变场面推进"],
            },
            {
                "id": "focus-payoff-hook",
                "axes": ["可见结果", "章末下一步"],
                "avoid": ["照搬上一版的行动顺序", "用说明代替人物行动"],
            },
        ]
        count = 0
        commits_dir = self.story_system_dir / "commits"
        if commits_dir.exists():
            for path in commits_dir.glob("*.json"):
                if path.name == "latest_commit.json":
                    continue
                try:
                    data = self._read_json(path, default={})
                except Exception:
                    continue
                if int(data.get("chapter_number") or 0) == chapter_number and str(data.get("operation") or "") in {
                    "generate",
                    "regenerate",
                    "rewrite",
                    "write",
                }:
                    count += 1
        return variants[count % len(variants)]

    def _regeneration_title_override(self, chapter_number: int, variant_id: str) -> str | None:
        return None

    @staticmethod
    def _global_author_constraints(raw_constraints: Any) -> list[str]:
        """Return reusable book rules; chapter beats belong to the outline."""

        constraints = raw_constraints if isinstance(raw_constraints, list) else []
        chapter_pattern = re.compile(r"第(?:\d+|[一二三四五六七八九十百]+)章")
        return [
            text
            for item in constraints
            if (text := str(item).strip())
            and not chapter_pattern.search(text)
        ]

    @staticmethod
    def _historical_character_profile(
        raw_profile: dict[str, Any],
        *,
        target_chapter: int,
    ) -> dict[str, Any]:
        """Keep stable characterization while removing facts learned later."""

        profile = deepcopy(raw_profile)
        identity = profile.get("identity_profile")
        if isinstance(identity, dict):
            profile["identity_profile"] = {
                key: value
                for key, value in identity.items()
                if key not in {"current_identity", "affiliation"}
            }
        current_life = profile.get("current_life_profile")
        if isinstance(current_life, dict):
            profile["current_life_profile"] = {
                key: value
                for key, value in current_life.items()
                if key not in {"economic_state", "immediate_problem"}
            }
        story_drive = profile.get("story_drive")
        if isinstance(story_drive, dict):
            profile["story_drive"] = {
                key: value
                for key, value in story_drive.items()
                if key != "immediate_goal"
            }
        background = profile.get("background_profile")
        if isinstance(background, dict) and isinstance(background.get("formative_events"), list):
            next_background = dict(background)
            next_background["formative_events"] = [
                event
                for event in background["formative_events"]
                if not re.search(r"第(?:\d+|[一二三四五六七八九十百]+)章|本章|当前章", str(event))
            ]
            profile["background_profile"] = next_background
        for field in (
            "game_panel",
            "game_state",
            "real_state",
            "memory",
            "location",
            "current_location",
            "current_emotion",
            "latest_chapter",
            "chapter_role",
        ):
            profile.pop(field, None)
        return profile

    def _conservative_regeneration_state(
        self,
        current_state: dict[str, Any],
    ) -> dict[str, Any]:
        project = self.project()
        world_blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        def static_character_cards(raw_characters: Any) -> list[dict[str, Any]]:
            if not isinstance(raw_characters, list):
                return []
            cards: list[dict[str, Any]] = []
            for raw_character in raw_characters:
                if not isinstance(raw_character, dict):
                    continue
                name = str(raw_character.get("name") or "").strip()
                role = str(raw_character.get("role") or "").strip()
                if not name or not role or is_non_character_card(raw_character):
                    continue
                character = {"name": name, "role": role}
                # Rewriting must discard chapter-specific runtime state without
                # erasing the stable portrait that tells the writer who this
                # person is and how they behave.
                for field in (
                    "character_tier",
                    "first_appearance",
                    "game_id",
                    "identity_profile",
                    "background_profile",
                    "current_life_profile",
                    "story_drive",
                    "performance_profile",
                    "dialogue_examples",
                    "relationship_notes",
                    "personality_portrait",
                    "character_type",
                    "core_motivation",
                    "behavior_logic",
                    "interaction_mode",
                    "poison_points",
                    "social_profile",
                    "psychological_profile",
                    "moral_profile",
                    "story_function",
                    "chapter_role",
                ):
                    if raw_character.get(field) not in (None, "", [], {}):
                        character[field] = deepcopy(raw_character[field])
                legacy_motivation = str(raw_character.get("motivation") or "").strip()
                legacy_personality = str(raw_character.get("personality") or "").strip()
                legacy_speech = str(raw_character.get("speech_style") or "").strip()
                legacy_goals = [
                    str(item).strip()
                    for item in raw_character.get("goals", [])
                    if str(item).strip()
                ] if isinstance(raw_character.get("goals"), list) else []
                if legacy_motivation and not character.get("core_motivation"):
                    character["core_motivation"] = legacy_motivation
                if legacy_personality and not character.get("behavior_logic"):
                    character["behavior_logic"] = legacy_personality
                if legacy_speech and not character.get("performance_profile"):
                    character["performance_profile"] = {"speech_style": legacy_speech}
                if not character.get("story_drive") and (legacy_motivation or legacy_goals):
                    character["story_drive"] = {
                        "immediate_goal": legacy_goals[0] if legacy_goals else legacy_motivation,
                        "long_term_goal": legacy_goals[-1] if len(legacy_goals) > 1 else "",
                        "motivation": legacy_motivation,
                    }
                game_id = str(character.get("game_id") or "").strip()
                if game_id:
                    character["game_panel"] = {"game_id": game_id}
                cards.append(character)
            return cards

        project_character_profiles = [
            self._historical_character_profile(card, target_chapter=1)
            for card in project.get("character_profiles", [])
            if isinstance(card, dict)
        ]
        static_characters = static_character_cards(project_character_profiles)
        if not static_characters:
            static_characters = static_character_cards(project.get("characters"))
        state_characters = static_character_cards(current_state.get("characters"))
        state_by_name = {
            str(character.get("name") or "").strip(): character
            for character in state_characters
            if str(character.get("name") or "").strip()
        }
        for index, character in enumerate(static_characters):
            current = state_by_name.get(str(character.get("name") or "").strip())
            if not isinstance(current, dict):
                continue
            merged = dict(character)
            merged.update(
                {
                    key: deepcopy(value)
                    for key, value in current.items()
                    if value not in (None, "", [], {})
                }
            )
            static_characters[index] = merged
        for character in static_characters:
            # The latest character card may contain results learned during the
            # book. A chapter-one rewrite needs the stable portrait, not the
            # character's later money problem, immediate goal, or chapter recap.
            current_life = character.get("current_life_profile")
            if isinstance(current_life, dict):
                character["current_life_profile"] = {
                    key: value
                    for key, value in current_life.items()
                    if key not in {"economic_state", "immediate_problem"}
                }
            story_drive = character.get("story_drive")
            if isinstance(story_drive, dict):
                character["story_drive"] = {
                    key: value
                    for key, value in story_drive.items()
                    if key != "immediate_goal"
                }
            background = character.get("background_profile")
            if isinstance(background, dict) and isinstance(background.get("formative_events"), list):
                next_background = dict(background)
                next_background["formative_events"] = [
                    event
                    for event in background["formative_events"]
                    if not any(marker in str(event) for marker in ("第一章", "第1章", "本章", "当前章"))
                ]
                character["background_profile"] = next_background
            character.pop("chapter_role", None)

        baseline = {
            "story_id": str(
                current_state.get("story_id")
                or project.get("active_story_id")
                or project.get("project_id")
                or "file-project"
            ),
            "outline": str(
                current_state.get("outline")
                or project.get("seed_outline")
                or project.get("title")
                or ""
            ),
            "genre": str(current_state.get("genre") or project.get("genre") or ""),
            "genre_plugin_ids": deepcopy(
                current_state.get("genre_plugin_ids")
                or world_blueprint.get("genre_plugin_ids")
                or []
            ),
            "style": str(current_state.get("style") or project.get("style") or ""),
            "current_chapter": 0,
            "author_constraints": deepcopy(
                project.get("author_constraints")
                or current_state.get("author_constraints")
                or []
            ),
            "enabled_skill_ids": deepcopy(
                resolve_enabled_skill_ids(project, current_state)
            ),
            "enabled_skill_module_ids": deepcopy(
                resolve_enabled_skill_module_ids(project, current_state) or []
            ),
            "characters": static_characters,
            "monster_profiles": [],
            "world_facts": [],
            "progression_ledger": {},
            "timeline": [],
            "foreshadowing": [],
            "chapter_summaries": [],
            "memory_index": [],
            "arc_recaps": [],
        }
        master_state = self.master_setting().get("state")
        if isinstance(master_state, dict) and int(master_state.get("current_chapter") or 0) == 0:
            opening_state = deepcopy(master_state)
            # MASTER_SETTING.state is the immutable chapter-zero snapshot. Keep
            # its opening resources and time, while taking editable book-level
            # configuration and static character portraits from current files.
            for field in (
                "story_id",
                "outline",
                "genre",
                "genre_plugin_ids",
                "style",
                "author_constraints",
                "enabled_skill_ids",
                "enabled_skill_module_ids",
                "characters",
            ):
                opening_state[field] = deepcopy(baseline[field])
            opening_state["current_chapter"] = 0
            for field in (
                "progression_ledger",
                "timeline",
                "foreshadowing",
                "chapter_summaries",
                "memory_index",
                "arc_recaps",
                "world_facts",
                "monster_profiles",
            ):
                opening_state.setdefault(field, deepcopy(baseline[field]))
            baseline = opening_state
        for field in ("novel_type", "novel_type_id", "novel_type_ids"):
            if field in current_state:
                baseline[field] = deepcopy(current_state[field])
        return baseline

    def _chapter_snapshot_state(
        self,
        chapter_number: int,
        current_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            chapter = self.chapter(chapter_number)
        except FileNotFoundError:
            return None
        updated_story = chapter.get("updated_story") if isinstance(chapter, dict) else None
        if not isinstance(updated_story, dict):
            return None
        try:
            snapshot_chapter = int(updated_story.get("current_chapter") or 0)
        except (TypeError, ValueError):
            return None
        if snapshot_chapter != chapter_number:
            return None
        hydrated_snapshot = self._conservative_regeneration_state(current_state)
        hydrated_snapshot.update(deepcopy(updated_story))
        usable = self._validated_runtime_state(hydrated_snapshot, current_state)
        return dict(usable) if usable is not None else None

    @staticmethod
    def _merge_regeneration_configuration(
        base_state: dict[str, Any],
        current_state: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(base_state)
        for field in (
            "author_constraints",
            "enabled_skill_ids",
            "enabled_skill_module_ids",
            "genre",
            "genre_plugin_ids",
            "style",
        ):
            if field in current_state:
                merged[field] = deepcopy(current_state[field])
        return merged

    def _regeneration_base_state(
        self,
        chapter_number: int,
        current_state: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_number = 0
        base_state: dict[str, Any] | None = None
        for previous_number in range(chapter_number - 1, 0, -1):
            base_state = self._chapter_snapshot_state(previous_number, current_state)
            if base_state is not None:
                snapshot_number = previous_number
                break
        if base_state is None:
            base_state = self._conservative_regeneration_state(current_state)

        replay_numbers = [
            number
            for number in self.chapter_numbers()
            if snapshot_number < number < chapter_number
        ]
        for previous_number in replay_numbers:
            chapter = self.chapter(previous_number)
            base_state = self._sync_state_after_chapter(base_state, deepcopy(chapter))
            base_state = self._sync_ledger_from_chapter_body(base_state, deepcopy(chapter))

        base_state["current_chapter"] = chapter_number - 1
        return self._merge_regeneration_configuration(base_state, current_state)

    @_with_project_update_lock
    def regenerate_chapter(
        self,
        chapter_number: int,
        engine: Any | None = None,
        *,
        variant: str | None = None,
        guidance: str | None = None,
        commit_message: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        # Model generation stays inside the per-project lock so a later rewrite
        # cannot be generated from state that another same-project rewrite replaces.
        # This intentionally blocks same-project edits; locks for other roots are independent.
        from packages.story_core.engine import StoryEngine

        if chapter_number < 1:
            raise ValueError("chapter_number_must_be_positive")
        self._assert_chapter_not_frozen(chapter_number, "regenerate")
        self._assert_opening_preflight(chapter_number)

        current_state = dict(self.state())
        if chapter_number > 1:
            base_state = self._regeneration_base_state(chapter_number, current_state)
        else:
            base_state = self._conservative_regeneration_state(current_state)

        base_state["current_chapter"] = chapter_number - 1
        ledger = dict(base_state.get("progression_ledger") or {})
        variant_payload = self._regeneration_variant(chapter_number)
        if variant:
            variant_payload = {**variant_payload, "id": variant}
            if variant == "progression-lead":
                variant_payload.setdefault("axes", ["把本书已有优势转化为可见成长和下一步机会"])
                variant_payload.setdefault(
                    "avoid",
                    ["公开解释隐藏优势", "擅自提前后续势力反应", "把账本说明写成正文高潮"],
                )
                variant_payload["skip_expansion"] = False
        variant_payload.setdefault("skip_expansion", False)
        guidance_text = self._compact_text(guidance, 1200)
        if guidance_text:
            variant_payload["rewrite_guidance"] = {"source": "book_dissection", "text": guidance_text}
        ledger["simulation_variant"] = variant_payload
        base_state["progression_ledger"] = ledger

        project = self.project()
        direction_payload = self._story_state_payload_for_direction(
            base_state,
            project,
            chapter_number,
        )
        story = StoryState.model_validate(direction_payload)
        generator = engine or StoryEngine()
        with prompt_template_scope(self.prompt_template_object, self.prompt_template_source), prompt_call_recording(
            self.prompt_call_log()
        ):
            bundle = generator.generate_next_chapter(story)
        if int(getattr(bundle, "chapter_number", 0) or 0) != chapter_number:
            raise ValueError(f"regenerated_wrong_chapter:{getattr(bundle, 'chapter_number', None)}")
        quality_report = getattr(bundle, "quality_report", None)
        writing_review = quality_report.get("writing_review") if isinstance(quality_report, dict) else None
        if isinstance(quality_report, dict):
            _promote_downstream_rewrite_status(quality_report)
        if (
            isinstance(quality_report, dict)
            and quality_report
            and not quality_report.get("regeneration_degraded")
            and quality_report.get("ok") is False
        ):
            issues = quality_report.get("issues") or []
            if isinstance(writing_review, dict):
                issues = [*issues, *(writing_review.get("issues") or [])]
            issue_text = "; ".join(str(item) for item in issues[:5] if str(item).strip())
            if _is_regeneration_continuity_failure(quality_report, writing_review if isinstance(writing_review, dict) else None):
                quality_report["regeneration_degraded"] = True
                quality_report["regeneration_quality_warning"] = [
                    str(item) for item in issues if str(item).strip()
                ][:10]
            elif not _regeneration_quality_blocking(
                quality_report,
                writing_review if isinstance(writing_review, dict) else None,
            ):
                quality_report["regeneration_quality_warning"] = [str(item) for item in issues if str(item).strip()][:10]
        title_override = _chapter_outline_title(
            direction_payload.get("outline_context"),
            chapter_number,
        ) or self._regeneration_title_override(chapter_number, str(variant_payload.get("id") or ""))
        if title_override:
            bundle.chapter_title = title_override
            if isinstance(getattr(bundle, "chapter_summary", None), dict):
                bundle.chapter_summary["chapter_title"] = title_override
        if not persist:
            project_id = str(
                project.get("project_id")
                or project.get("active_story_id")
                or current_state.get("story_id")
                or self.root.name
            )
            candidate = self._save_candidate_from_bundle(
                bundle,
                project_id=project_id,
                quality_report=quality_report if isinstance(quality_report, dict) else None,
                operation="regenerate",
            )
            return {
                "schema_version": "file-project-candidate/v1",
                "root": str(self.root),
                "chapter_number": candidate.chapter_number,
                "chapter_title": candidate.chapter_title,
                "candidate": candidate.to_dict(),
                "simulation_variant": variant_payload,
            }
        persisted = self.persist_bundle(
            bundle,
            operation="regenerate",
            commit_message=commit_message or f"regenerate chapter {chapter_number} ({variant_payload.get('id')})",
        )
        return {
            "schema_version": "file-project-regenerate/v1",
            "root": str(self.root),
            "chapter_number": persisted["chapter_number"],
            "chapter_title": persisted["chapter_title"],
            "simulation_variant": variant_payload,
            "persisted": persisted,
            "quality_warning": quality_report.get("regeneration_quality_warning")
            if isinstance(quality_report, dict)
            else None,
        }

    @_with_project_update_lock
    def rewrite_chapter(
        self,
        *,
        chapter_number: int,
        body: str,
        title: str | None = None,
        next_outline: str | None = None,
        instructions: list[str] | None = None,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        self._assert_chapter_not_frozen(chapter_number, "rewrite")
        self._assert_opening_preflight(chapter_number)
        if not str(body).strip():
            raise ValueError("body_required")
        chapter = dict(self.chapter(chapter_number))
        next_title = title or str(chapter.get("chapter_title") or f"Chapter {chapter_number}")
        chapter["chapter_title"] = next_title
        chapter["body"] = body
        if next_outline is not None:
            chapter["next_outline"] = next_outline or "continue"
        chapter["manual_instructions"] = [*(chapter.get("manual_instructions") or []), *(instructions or [])]
        summary = dict(chapter.get("chapter_summary") or {})
        summary["chapter_title"] = next_title
        summary.setdefault("cadence", chapter.get("cadence") or "measured")
        existing_summary = self._compact_text(summary.get("summary"), 320)
        summary["summary"] = (
            existing_summary
            if existing_summary and not self._is_placeholder_text(existing_summary)
            else self._compact_text(body, 320)
        )
        if instructions:
            summary["facts"] = [item for item in instructions if str(item).strip()]
        else:
            summary.setdefault("facts", ["manual rewrite"])
        # A manual body rewrite has no evidence extractor. Keeping the old
        # chapter's thread claims would be less safe than leaving them empty.
        summary["unresolved_threads"] = []
        summary["resolved_threads"] = []
        summary.setdefault("next_focus", chapter.get("next_outline") or "continue")
        summary.setdefault("primary_conflict", "manual rewrite")
        summary.setdefault("secondary_conflict", "manual rewrite")
        summary.setdefault("event_beat", "manual rewrite")
        chapter["chapter_summary"] = summary
        chapter.setdefault("cadence", "measured")
        chapter.setdefault("next_outline", summary.get("next_focus") or "continue")
        chapter["chapter_intent"] = {
            "next_focus": chapter["next_outline"],
            "primary_conflict": summary.get("primary_conflict") or "manual rewrite",
        }
        chapter["event_plan"] = {
            "chapter_number": chapter_number,
            "next_focus": chapter["next_outline"],
            "summary": summary.get("summary") or f"Manual rewrite chapter {chapter_number}.",
            "stakes": summary.get("summary") or chapter["next_outline"],
            "world_reactions": summary.get("facts", [])[:3],
        }
        chapter["simulation_plan"] = {
            "chapter_number": chapter_number,
            "chapter_goal": chapter["next_outline"],
        }
        current_state = self.state()
        current_chapter = int(current_state.get("current_chapter") or 0)
        updated_story = self._generation_state_for_target(current_state, chapter_number)
        updated_story.setdefault("timeline", [f"chapter {chapter_number}: {next_title}"])
        updated_story.setdefault("chapter_summaries", [summary])
        chapter["updated_story"] = updated_story

        chapter = self._hydrate_chapter_display_fields(chapter, updated_story)
        review = _manual_chapter_quality_report(
            chapter,
            genre_context=self._review_genre_context(),
        )
        chapter["quality_report"] = review
        historical_foreshadowing = self._historical_foreshadowing_for_rewrite(chapter)
        if historical_foreshadowing is not None:
            target_state = self._sync_state_after_chapter(
                self._state_before_chapter(chapter_number),
                chapter,
            )
            target_state = self._sync_ledger_from_chapter_body(target_state, chapter)
            target_state["current_chapter"] = chapter_number
            chapter["updated_story"] = target_state

            global_state = deepcopy(current_state)
            global_state["foreshadowing"] = deepcopy(historical_foreshadowing["final"])
            global_state["manual_foreshadowing"] = deepcopy(
                historical_foreshadowing.get("manual") or []
            )
            global_state["current_chapter"] = current_chapter
            payloads = {self.webnovel_dir / "state.json": global_state}
            self._apply_historical_foreshadowing_projection(
                chapter,
                payloads,
                historical_foreshadowing,
            )
            paths, commit = self._persist_historical_transaction(
                chapter,
                review,
                body,
                payloads,
                operation="rewrite",
                commit_message=commit_message,
            )
        else:
            self._sync_after_chapter(chapter, updated_story)
            paths = self._chapter_paths(chapter_number, next_title)
            self._remove_chapter_markdowns(chapter_number)
            self._write_json(paths["json"], chapter)
            self._write_json(paths["review"], review)
            self._write_text(paths["markdown"], body)
            commit = self.commit(
                message=commit_message or f"rewrite chapter {chapter_number}",
                operation="rewrite",
                chapter_number=chapter_number,
            )
        self._append_workflow_log(
            chapter_number=chapter_number,
            chapter_title=next_title,
            review=review,
            operation="rewrite",
        )
        return {
            "schema_version": "file-project-rewrite/v1",
            "root": str(self.root),
            "chapter_number": chapter_number,
            "chapter_title": next_title,
            "files": {key: path.relative_to(self.root).as_posix() for key, path in paths.items() if path.exists()},
            "review": review,
            "commit": commit,
        }

    def summary(self) -> dict[str, Any]:
        project = self.project()
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        chapters = [
            {
                "chapter_number": entry["chapter_number"],
                "chapter_title": entry["chapter_title"],
            }
            for entry in self.chapter_index()
        ]
        return {
            "schema_version": "file-project-summary/v1",
            "root": str(self.root),
            "project_id": project.get("project_id"),
            "title": project.get("title") or state.get("outline"),
            "active_story_id": project.get("active_story_id") or state.get("story_id"),
            "current_chapter": state.get("current_chapter") or (chapters[-1]["chapter_number"] if chapters else 0),
            "chapter_count": len(chapters),
            "chapters": chapters,
        }

    def query(self, keyword: str, *, max_results: int = 20) -> dict[str, Any]:
        needle = keyword.strip()
        if not needle:
            raise ValueError("keyword_required")
        results: list[dict[str, Any]] = []
        search_paths = [
            self.story_system_dir / "MASTER_SETTING.json",
            self.webnovel_dir / "project.json",
            self.webnovel_dir / "state.json",
            *sorted((self.story_system_dir / "chapters").glob("*.json")),
            *sorted(self.chapters_dir.glob("*.md")),
        ]
        for path in search_paths:
            if not path.exists() or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            index = text.find(needle)
            if index < 0:
                continue
            start = max(0, index - 80)
            end = min(len(text), index + len(needle) + 120)
            results.append(
                {
                    "file": str(path.relative_to(self.root)),
                    "match": needle,
                    "snippet": text[start:end].replace("\r\n", "\n"),
                }
            )
            if len(results) >= max_results:
                break
        return {
            "schema_version": "file-project-query/v1",
            "root": str(self.root),
            "keyword": needle,
            "result_count": len(results),
            "results": results,
        }

    def _world_relevance_text(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        target_chapter: int,
        outline_context: dict[str, Any],
        scene_cards: Any = None,
        *,
        current_chapter: int,
    ) -> str:
        chapter = (
            outline_context.get("chapter")
            if isinstance(outline_context.get("chapter"), dict)
            else {}
        )
        parts: list[str] = []
        if target_chapter > current_chapter:
            parts.append(str(state.get("current_focus") or project.get("current_focus") or ""))

        chapter_fields = (
            "title",
            "goal",
            "action",
            "payoff",
            "turn",
            "ending_hook",
            "line",
            "scene_line",
        )
        parts.extend(str(chapter.get(field) or "") for field in chapter_fields)

        scene_fields = ("title", "purpose", *chapter_fields[1:])
        parts.extend(
            str(card.get(field) or "")
            for card in (scene_cards if isinstance(scene_cards, list) else [])
            if isinstance(card, dict)
            for field in scene_fields
        )
        return "\n".join(part for part in parts if part.strip())

    def _continuity_interface_for_target(
        self,
        target_chapter: int,
        chapter_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        numbers = set(chapter_numbers if chapter_numbers is not None else self.chapter_numbers())

        def adjacent(number: int) -> dict[str, Any] | None:
            if number < 1 or number not in numbers:
                return None
            try:
                chapter = self.chapter(number)
            except FileNotFoundError:
                return None
            return chapter if isinstance(chapter, dict) else None

        return build_continuity_interface(
            target_chapter,
            previous=adjacent(target_chapter - 1),
            next_chapter=adjacent(target_chapter + 1),
        )

    def _story_state_payload_for_direction(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        target_chapter: int,
    ) -> dict[str, Any]:
        raw_project_outline = self.project_outline()
        outline_source = str(raw_project_outline.get("source") or "")
        project_outline = dict(raw_project_outline)
        project_outline.pop("source", None)
        world_blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        outline_context = dict(select_outline_context(project_outline, target_chapter))
        known_chapter_numbers = self.chapter_numbers()
        continuity_interface = self._continuity_interface_for_target(target_chapter, known_chapter_numbers)
        if continuity_interface:
            outline_context["continuity_interface"] = continuity_interface
        latest_number = max(known_chapter_numbers or [0])
        current_chapter = max(latest_number, int(state.get("current_chapter") or 0))
        profile_latest_chapter = max(
            [
                int(card.get("latest_chapter") or 0)
                for card in project.get("character_profiles", [])
                if isinstance(card, dict)
                and str(card.get("latest_chapter") or "").strip().isdigit()
            ]
            or [0]
        )
        historical_target = target_chapter <= max(latest_number, profile_latest_chapter)
        relevance_text = self._world_relevance_text(
            state,
            project,
            target_chapter,
            outline_context,
            current_chapter=current_chapter,
        )
        scoped_world = select_world_context(
            world_blueprint,
            relevance_text,
            max_rules=8,
        )
        equipment_cards = merge_equipment_cards(
            world_blueprint.get("equipment_cards"),
            state.get("equipment_cards"),
        ).cards
        if isinstance(world_blueprint.get("power_system_spec"), dict):
            scoped_world["power_system_spec"] = deepcopy(world_blueprint["power_system_spec"])
        state_genre_ids = state.get("genre_plugin_ids")
        project_genre_ids = world_blueprint.get("genre_plugin_ids")
        genre_plugin_ids = normalize_novel_type_ids(state_genre_ids)
        if not genre_plugin_ids:
            genre_plugin_ids = normalize_novel_type_ids(project_genre_ids)
        project_profiles = {
            str(card.get("name") or "").strip(): (
                self._historical_character_profile(card, target_chapter=target_chapter)
                if historical_target
                else card
            )
            for card in project.get("character_profiles", [])
            if isinstance(card, dict) and str(card.get("name") or "").strip()
        }
        characters: list[dict[str, Any]] = []
        for item in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(item, dict) or is_non_character_card(item):
                continue
            panel = item.get("game_panel") if isinstance(item.get("game_panel"), dict) else {}
            character = deepcopy(item)
            character["name"] = str(item.get("name") or panel.get("game_id") or "主角")
            character["role"] = str(item.get("role") or "protagonist")
            character["game_id"] = str(item.get("game_id") or panel.get("game_id") or "")
            profile = project_profiles.get(character["name"])
            if isinstance(profile, dict):
                for field in (
                    "role",
                    "character_tier",
                    "first_appearance",
                    "identity_profile",
                    "background_profile",
                    "current_life_profile",
                    "story_drive",
                    "performance_profile",
                    "dialogue_examples",
                    "relationship_notes",
                    "personality_portrait",
                    "character_type",
                    "core_motivation",
                    "behavior_logic",
                    "interaction_mode",
                    "poison_points",
                ):
                    value = profile.get(field)
                    if value not in (None, "", [], {}):
                        if historical_target and isinstance(value, dict) and isinstance(character.get(field), dict):
                            character[field] = merge_character_profile(character[field], value)
                        else:
                            character[field] = deepcopy(value)
                drive = profile.get("story_drive") if isinstance(profile.get("story_drive"), dict) else {}
                if not character.get("goals"):
                    character["goals"] = [
                        value
                        for key in ("immediate_goal", "long_term_goal")
                        if (value := str(drive.get(key) or "").strip())
                    ]
                if str(profile.get("character_tier") or "").strip().casefold() == "protagonist":
                    character["role"] = "protagonist"
                    character["character_tier"] = "protagonist"
            characters.append(character)
            if len(characters) >= 4:
                break
        opening_arc = (
            world_blueprint.get("opening_arc")
            if isinstance(world_blueprint.get("opening_arc"), dict)
            else {}
        )
        golden_chapters = (
            opening_arc.get("golden_three_chapters")
            if isinstance(opening_arc.get("golden_three_chapters"), dict)
            else {}
        )
        opening_chapter = golden_chapters.get(str(target_chapter))
        if not isinstance(opening_chapter, dict):
            opening_chapter = golden_chapters.get(target_chapter)
        stable_chapter_facts = []
        if outline_source != "saved":
            stable_chapter_facts = (
                opening_chapter.get("must_include")
                if isinstance(opening_chapter, dict) and isinstance(opening_chapter.get("must_include"), list)
                else []
            )
        merged_world_facts = list(
            dict.fromkeys(
                str(item).strip()
                for item in [*stable_chapter_facts, *(state.get("world_facts") or [])]
                if str(item).strip()
            )
        )
        return {
            "story_id": str(state.get("story_id") or project.get("active_story_id") or project.get("project_id") or "file-project"),
            "outline": str(state.get("outline") or project.get("seed_outline") or project.get("title") or ""),
            "genre": str(state.get("genre") or project.get("genre") or ""),
            "genre_plugin_ids": genre_plugin_ids,
            "style": str(state.get("style") or project.get("style") or ""),
            "current_chapter": int(state.get("current_chapter") or 0),
            "enabled_skill_ids": resolve_enabled_skill_ids(project, state),
            "enabled_skill_module_ids": resolve_enabled_skill_module_ids(project, state) or [],
            "author_constraints": self._global_author_constraints(
                project.get("author_constraints") or state.get("author_constraints") or []
            ),
            "world_facts": merged_world_facts,
            "progression_ledger": dict(state.get("progression_ledger") or {}),
            "world_context": scoped_world,
            "characters": characters,
            "timeline": [
                deepcopy(item)
                for item in (state.get("timeline") or [])
                if isinstance(item, dict)
                and 0 < int(item.get("chapter_number") or 0) < target_chapter
            ][-8:],
            "chapter_summaries": [
                {
                    **deepcopy(item),
                    "cadence": (
                        item.get("cadence")
                        if item.get("cadence") in {"urgent", "measured", "breathing"}
                        else "measured"
                    ),
                }
                for item in (state.get("chapter_summaries") or [])
                if isinstance(item, dict)
                and 0 < int(item.get("chapter_number") or 0) < target_chapter
                and str(item.get("summary") or "").strip()
            ][-3:],
            "monster_profiles": [
                deepcopy(item)
                for item in world_blueprint.get("monster_profiles", [])[:20]
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ],
            "equipment_cards": equipment_cards,
            "outline_context": outline_context,
        }

    def _chapter_direction_options(self, state: dict[str, Any], project: dict[str, Any], chapter_number: int) -> dict[str, Any]:
        story = StoryState.model_validate(self._story_state_payload_for_direction(state, project, chapter_number))
        return build_chapter_direction_options(story, chapter_number)

    def _resolve_chapter_direction(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        chapter_number: int,
        chapter_direction_id: str | None,
    ) -> dict[str, Any]:
        direction_id = str(chapter_direction_id or "").strip()
        if not direction_id:
            return {}
        options = self._chapter_direction_options(state, project, chapter_number)
        for option in options.get("options", []):
            if isinstance(option, dict) and str(option.get("id") or "") == direction_id:
                return option
        raise ValueError(f"unknown_chapter_direction:{direction_id}")

    def writing_packet(
        self,
        chapter_number: int | None = None,
    ) -> dict[str, Any]:
        packet, game_context, target = self._build_writing_packet(chapter_number)
        return normalize_legacy_economy_prompt_value(
            packet,
            game_context=game_context,
            chapter_number=target,
        )

    def _build_writing_packet(
        self,
        chapter_number: int | None = None,
    ) -> tuple[dict[str, Any], bool, int]:
        current_state = dict(self.state())
        project = self.project()
        world_blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        forbidden_breaks = world_blueprint.get("forbidden_breaks") if isinstance(world_blueprint.get("forbidden_breaks"), list) else []
        numbers = self.chapter_numbers()
        latest_number = numbers[-1] if numbers else 0
        saved_current_chapter = max(latest_number, int(current_state.get("current_chapter") or 0))
        if chapter_number is None:
            state = self._generation_state(current_state)
            target = int(state.get("current_chapter") or latest_number or 0) + 1
        else:
            target = int(chapter_number)
            state = self._generation_state_for_target(current_state, target)
        prior_numbers = [number for number in numbers if number < int(target or 0)]
        latest_context_number = prior_numbers[-1] if prior_numbers else 0
        latest_chapter = self.chapter(latest_context_number) if latest_context_number else {}
        project_outline = dict(self.project_outline())
        project_outline.pop("source", None)
        selected_outline = select_outline_context(project_outline, int(target or 0))
        outline_context = {
            key: selected_outline[key]
            for key in ("overall", "active_arc", "chapter")
        }
        chapter_outline = outline_context["chapter"] if isinstance(outline_context.get("chapter"), dict) else {}
        recent = []
        for number in prior_numbers[-3:]:
            item = self.chapter(number)
            recent.append(
                {
                    "chapter_number": item.get("chapter_number"),
                    "chapter_title": item.get("chapter_title"),
                    "summary": (item.get("chapter_summary") or {}).get("summary"),
                    "next_focus": item.get("next_outline") or (item.get("event_plan") or {}).get("next_focus"),
                }
            )
        scene_cards: list[dict[str, Any]] = []
        if chapter_outline:
            chapter = int(chapter_outline.get("chapter_number") or target or 0)
            title = self._compact_text(chapter_outline.get("title"), 80) or f"第{chapter}章剧情点"
            goal = self._compact_text(chapter_outline.get("goal"), 220)
            action = self._compact_text(chapter_outline.get("action"), 220)
            payoff = self._compact_text(chapter_outline.get("payoff"), 220)
            turn = self._compact_text(chapter_outline.get("turn"), 220)
            hook = self._compact_text(chapter_outline.get("ending_hook"), 180)
            scene_cards.append(
                {
                    "id": f"outline-beat-{chapter}",
                    "title": title,
                    "purpose": payoff or goal or action or turn or "按大纲推进本章明确结果。",
                    "goal": goal,
                    "action": action,
                    "payoff": payoff,
                    "turn": turn,
                    "ending_hook": hook,
                    "chapter": chapter,
                    "source": "outline_context.chapter",
                    "line": chapter_outline.get("line"),
                    "scene_line": chapter_outline.get("scene_line"),
                }
            )
        is_game_story = self._is_game_story_payload(project, state)
        scene_kind = self._writer_scene_kind(scene_cards, is_game_story=is_game_story)
        current_chapter = saved_current_chapter
        relevance_text = self._world_relevance_text(
            state,
            project,
            int(target or 0),
            outline_context,
            scene_cards,
            current_chapter=current_chapter,
        )
        scoped_world = select_world_context(
            world_blueprint,
            relevance_text,
            max_rules=8,
        )
        relevant_monster_profiles = _select_relevant_monster_profiles(
            world_blueprint.get("monster_profiles"),
            relevance_text,
            max_profiles=6,
        )
        target_min_chars = FILE_CHAPTER_TARGET_MIN_CHARS
        target_max_chars = FILE_CHAPTER_MAX_CHARS
        acceptance_min_chars = FILE_CHAPTER_MIN_CHARS
        acceptance_max_chars = FILE_CHAPTER_HARD_MAX_CHARS
        hard_locks = [
            (
                f"正文目标为{target_min_chars}至{target_max_chars}字；"
                f"低于{acceptance_min_chars}字或超过{acceptance_max_chars}字不能通过章节检查，"
                f"超过{target_max_chars}字应压缩。"
            ),
            "新人物出场前必须先有角色卡；没有角色卡只能作为待出场对象提出，不能直接写成已出场角色。",
        ]
        if is_game_story:
            hard_locks[1:1] = [
                "前十章每章必须给出可见成长或可见收益，不能连续只给线索。",
                "装备称呼统一写法杖或新手法杖，不用木杖、抬杖、握杖、杖身、杖尖这类生硬简称。",
                "游戏内说前置任务或前置条件，不写任务门槛。",
            ]
        current_focus = state.get("current_focus") or project.get("current_focus")
        if current_focus and int(target or 0) > current_chapter:
            hard_locks.append(f"当前主线焦点：{self._compact_text(current_focus, 220)}")
        if chapter_outline:
            goal = self._compact_text(chapter_outline.get("goal"), 220)
            payoff = self._compact_text(chapter_outline.get("payoff"), 220)
            hook = self._compact_text(chapter_outline.get("ending_hook"), 180)
            if goal:
                hard_locks.append(f"第{target}章目标：{goal}")
            if payoff:
                hard_locks.append(f"第{target}章必须兑现：{payoff}")
            if hook:
                hard_locks.append(f"第{target}章结尾钩子：{hook}")
        hard_locks.extend(
            _progression_governance_hard_locks(
                world_blueprint.get("progression_rules"),
                scoped_world.get("progression_rules"),
            )
        )
        hard_locks.extend(str(item) for item in forbidden_breaks[:4] if str(item).strip())
        characters = self._writer_character_cards(
            state,
            selected_outline,
            scene_kind=scene_kind,
            is_game_story=is_game_story,
        )
        equipment_cards: list[dict[str, Any]] = []
        if is_game_story:
            all_equipment = (
                world_blueprint.get("equipment_cards")
                if isinstance(world_blueprint.get("equipment_cards"), list)
                else []
            )
            relevance_folded = relevance_text.casefold()
            character_names = {
                str(card.get("name") or "").strip().casefold()
                for card in characters
                if str(card.get("name") or "").strip()
            }
            relevant_equipment = [
                card
                for card in all_equipment if isinstance(card, dict)
                if (
                    str(card.get("name") or "").strip().casefold() in relevance_folded
                    or str(card.get("current_owner") or "").strip().casefold() in character_names
                )
            ]
            equipment_cards = equipment_cards_for_context(
                relevant_equipment or all_equipment,
                names=[
                    str(card.get("name") or "")
                    for card in relevant_equipment
                    if isinstance(card, dict)
                ],
                owners=[str(card.get("name") or "") for card in characters],
                limit=12,
            )
            if equipment_cards:
                scoped_world["equipment_cards"] = deepcopy(equipment_cards)
        relationship_context = select_relationship_subgraph(
            project.get("relationship_graph"),
            [str(card.get("name") or "") for card in characters],
        )
        chapter_direction_options = (
            self._chapter_direction_options(state, project, int(target or 0))
            if int(target or 0) > current_chapter and not chapter_outline
            else {}
        )
        enabled_skill_ids = resolve_enabled_skill_ids(project, state)
        enabled_skill_module_ids = resolve_enabled_skill_module_ids(project, state)
        skill_context = {
            purpose: skill_pack_prompt_context(
                enabled_skill_ids,
                enabled_module_ids=enabled_skill_module_ids,
                purpose=purpose,
                max_chars_per_pack=2600,
            )
            for purpose in ("writer", "dialogue", "style", "genre", "continuity", "reviewer")
        }
        packet_project = dict(project)
        packet_project["character_profiles"] = characters
        scoped_author_constraints = self._global_author_constraints(
            project.get("author_constraints") or state.get("author_constraints") or []
        )
        packet_project["author_constraints"] = scoped_author_constraints
        packet_project.pop("relationship_graph", None)
        if int(target or 0) <= current_chapter:
            packet_project.pop("current_focus", None)
        packet_project["world_blueprint"] = scoped_world
        power_system = power_system_context_for_state(
            world_blueprint.get("power_system_spec"),
            progression_ledger=state.get("progression_ledger"),
            characters=state.get("characters"),
        )
        foreshadowing_context = select_unresolved_foreshadowing(
            self._parse_foreshadowing_ledger(state.get("foreshadowing")),
            chapter_number=int(target or 0),
            limit=8,
        )
        title_contract = (
            {
                "style": "tomato_concrete_short_title",
                "rules": [
                    "4到10字左右，像真实章节目录，不像广告文案",
                    "优先使用具体事件、地点、道具、职业、NPC服务点或委托名",
                    "可以有悬念，但不要用“他/别人/没人知道”这类营销句式",
                    "避免材料数量、铜币账目、成本核算、后台规则和说明句",
                ],
                "examples": ["登录建号", "职业学徒", "任务委托", "低级野怪区", "回村补给"],
            }
            if is_game_story
            else {
                "style": "concrete_short_title",
                "rules": [
                    "4到10字左右，像真实章节目录，不像广告文案",
                    "优先使用具体事件、地点、物件或人物关系",
                    "可以有悬念，但不要用“他/别人/没人知道”这类营销句式",
                    "避免数量清单、成本核算、后台规则和说明句",
                ],
                "examples": ["雪山来客", "断剑回响", "旧信开封", "夜访祖祠"],
            }
        )
        style_rules = (
            [
                "句子要完整，人物行动、理由和结果要接得上；对话不能省略必要的连接词、原因、条件和态度。",
                "网游信息通过动作、数值、道具消耗、位置变化和直接后果表现，不用旁白解释后台处理过程。",
                "每个场景都要有目标、阻力、结果或危机，结尾必须留下下一步问题。",
                "前10章节奏要快，连续两章不能只拿线索不给成长；下一章至少兑现一个可见成长：等级、经验大幅推进、技能、装备、货币补给或任务权限。",
                "装备称呼统一：普通叙述只写“法杖”或“新手法杖”，修理、持握、表面裂纹和攻击动作都用完整称呼；“裂纹杖芯”作为道具名可以保留。",
                "人物先行：本章要出场的新NPC必须先在角色卡里有候选卡；模型只能提出建议，不能直接改写既有角色主档。",
            ]
            if is_game_story
            else [
                "句子要完整，人物行动、理由和结果要接得上；对话不能省略必要的连接词、原因、条件和态度。",
                "设定通过行动、器物变化、身体反应、环境后果和人物关系表现，不用旁白解释后台过程。",
                "每个场景都要有目标、阻力、结果或危机，结尾必须留下下一步问题。",
                "连续两章不能只增加线索而没有可见推进；推进内容必须服从本书大纲和当前阶段。",
                "人物先行：本章要出场的新人物必须先有角色卡；模型只能提出建议，不能直接改写既有角色主档。",
            ]
        )
        volume_plan = world_blueprint.get("volume_plan") or {}
        active_arc = (
            outline_context.get("active_arc")
            if isinstance(outline_context.get("active_arc"), dict)
            else {}
        )
        outline_arcs = [
            item
            for item in project_outline.get("arcs", [])
            if isinstance(item, dict)
        ]
        first_arc = min(
            outline_arcs,
            key=lambda item: int(item.get("start_chapter") or 1),
            default={},
        )
        if (
            len(outline_arcs) > 1
            and active_arc
            and str(active_arc.get("id") or "") != str(first_arc.get("id") or "")
        ):
            start_chapter = int(active_arc.get("start_chapter") or target or 1)
            end_chapter = int(active_arc.get("end_chapter") or start_chapter)
            volume_plan = {
                "volume_title": str(active_arc.get("title") or ""),
                "target_chapters": max(end_chapter - start_chapter + 1, 1),
                "core_goal": str(active_arc.get("goal") or ""),
                "phase_beats": [
                    {
                        "range": f"{start_chapter}-{end_chapter}",
                        "goal": str(active_arc.get("payoff") or active_arc.get("goal") or ""),
                    }
                ],
                "long_threads": list(
                    (world_blueprint.get("volume_plan") or {}).get("long_threads")
                    or []
                ),
            }
        packet = {
            "schema_version": "file-writing-packet/v1",
            "root": str(self.root),
            "target_chapter": target,
            "chapter_number": target,
            "scene_kind": scene_kind,
            "latest_chapter_number": latest_context_number,
            "prose_renderer": prose_renderer_contract(),
            "target_chars": {"min": target_min_chars, "max": target_max_chars},
            "acceptance_chars": {"min": acceptance_min_chars, "max": acceptance_max_chars},
            "hard_locks": hard_locks,
            "monster_profiles": relevant_monster_profiles,
            "equipment_cards": equipment_cards,
            "scene_cards": scene_cards,
            "outline_context": outline_context,
            "character_cards": characters,
            "relationship_context": relationship_context,
            "foreshadowing_context": [item.model_dump() for item in foreshadowing_context],
            "title_contract": title_contract,
            "style_rules": style_rules,
            "outline_constraints": {
                "volume_plan": volume_plan,
                "longform_framework": world_blueprint.get("longform_framework") or {},
                "chapter_formula": world_blueprint.get("chapter_formula") or [],
                "forbidden_breaks": forbidden_breaks,
            },
            "project": packet_project,
            "state": {
                "story_id": state.get("story_id"),
                "genre": state.get("genre"),
                "style": state.get("style"),
                "current_chapter": state.get("current_chapter"),
                "current_focus": (
                    state.get("current_focus") or project.get("current_focus")
                    if int(target or 0) > current_chapter
                    else ""
                ),
                "time_state": state.get("time_state") or world_blueprint.get("time_state", {}),
                "author_constraints": scoped_author_constraints,
                "world_facts": state.get("world_facts", [])[-20:],
                "characters": characters,
            },
            "recent_chapters": recent,
            "latest_review": self.review(latest_context_number) if latest_context_number else {},
            "latest_event_plan": latest_chapter.get("event_plan", {}) if isinstance(latest_chapter, dict) else {},
            "chapter_direction_options": chapter_direction_options,
            "skill_context": {key: value for key, value in skill_context.items() if value},
        }
        if power_system:
            packet["power_system"] = power_system
        return packet, is_game_story, int(target or 0)

    def _prompt_plan_from_chapter(self, chapter: dict[str, Any]) -> dict[str, Any]:
        plan: dict[str, Any] = {}
        for key in (
            "character_moves",
            "chapter_intent",
            "event_plan",
            "memory_constraints",
            "chapter_seed",
            "simulation_plan",
            "world_events",
            "scene_cards",
            "style_guidance",
            "governance",
            "writing_taskbook",
        ):
            value = chapter.get(key)
            if value not in (None, "", [], {}):
                plan[key] = value
        return plan

    @staticmethod
    def _prompt_entry(
        *,
        key: str,
        title: str,
        agent: str,
        stage: str,
        content: str,
        source: str,
        description: str = "",
        module_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        text = str(content or "")
        return {
            "key": key,
            "title": title,
            "agent": agent,
            "stage": stage,
            "source": source,
            "description": description,
            "content": text,
            "chars": len(text),
            "module_keys": list(module_keys or []),
        }

    @staticmethod
    def _prompt_review_payload(review: Any) -> dict[str, Any]:
        if not isinstance(review, dict):
            return {}
        nested = review.get("writing_review") if isinstance(review.get("writing_review"), dict) else None
        if nested:
            merged = dict(nested)
            for key in ("ok", "pass", "issues", "revision_plan", "scores"):
                if key in review and key not in merged:
                    merged[key] = review[key]
            return merged
        return review

    def _slim_prompt_preview_value(self, value: Any, *, depth: int = 0) -> Any:
        if depth > 4:
            return self._compact_text(value, 160)
        if isinstance(value, str):
            return self._compact_text(value, 180)
        if isinstance(value, list):
            return [self._slim_prompt_preview_value(item, depth=depth + 1) for item in value[:8]]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if item in (None, "", [], {}):
                    continue
                result[str(key)] = self._slim_prompt_preview_value(item, depth=depth + 1)
            return result
        return value

    def _compact_prompt_preview_packet(self, packet: Any) -> dict[str, Any]:
        if not isinstance(packet, dict):
            return {}

        state = packet.get("state") if isinstance(packet.get("state"), dict) else {}
        outline_context = packet.get("outline_context") if isinstance(packet.get("outline_context"), dict) else {}
        chapter_outline = outline_context.get("chapter") if isinstance(outline_context.get("chapter"), dict) else {}
        characters = packet.get("character_cards") if isinstance(packet.get("character_cards"), list) else []
        if not characters:
            characters = state.get("characters") if isinstance(state.get("characters"), list) else []

        loaded_skill_modules: dict[tuple[str, str], dict[str, Any]] = {}
        skill_context = packet.get("skill_context") if isinstance(packet.get("skill_context"), dict) else {}
        for purpose, packs in skill_context.items():
            if not isinstance(packs, list):
                continue
            for pack in packs:
                if not isinstance(pack, dict):
                    continue
                skill_id = str(pack.get("skill_id") or pack.get("name") or "").strip()
                modules = pack.get("modules") if isinstance(pack.get("modules"), list) else []
                if not modules and pack.get("root_skill"):
                    modules = [{"module_id": "root", "title": "根模块"}]
                for module in modules:
                    if not isinstance(module, dict):
                        continue
                    module_id = str(module.get("module_id") or "root").strip()
                    key = (skill_id, module_id)
                    item = loaded_skill_modules.setdefault(
                        key,
                        {
                            "skill_id": skill_id,
                            "module_id": module_id,
                            "title": str(module.get("title") or module_id).strip(),
                            "purposes": [],
                        },
                    )
                    if purpose not in item["purposes"]:
                        item["purposes"].append(purpose)

        preview = {
            "schema_version": packet.get("schema_version"),
            "target_chapter": packet.get("target_chapter"),
            "target_chars": self._slim_prompt_preview_value(packet.get("target_chars")),
            "acceptance_chars": self._slim_prompt_preview_value(packet.get("acceptance_chars")),
            "scene_kind": packet.get("scene_kind"),
            "instruction": self._compact_text(packet.get("instruction"), 260),
            "hard_locks": [self._compact_text(item, 160) for item in packet.get("hard_locks", [])[:10]],
            "scene_cards": self._slim_prompt_preview_value(packet.get("scene_cards", [])[:6]),
            "chapter_outline": self._slim_prompt_preview_value(chapter_outline),
            "characters": [
                {
                    "name": item.get("name"),
                    "role": item.get("role"),
                    "location": self._compact_text(item.get("location"), 80),
                    "goal": self._compact_text(item.get("goal"), 140),
                }
                for item in characters[:6]
                if isinstance(item, dict)
            ],
            "title_contract": self._slim_prompt_preview_value(packet.get("title_contract")),
            "style_rules": [self._compact_text(item, 180) for item in packet.get("style_rules", [])[:6]],
            "loaded_skill_modules": list(loaded_skill_modules.values()),
            "note": "这里只显示本章执行约束；完整上下文由其他模块展示，完整写作包仍由 writing_packet 接口返回。",
        }
        return {key: value for key, value in preview.items() if value not in (None, "", [], {})}

    def prompt_preview(self, chapter_number: int | None = None) -> dict[str, Any]:
        with prompt_template_scope(self.prompt_template_object, self.prompt_template_source):
            return self._prompt_preview(chapter_number)

    def _prompt_preview(self, chapter_number: int | None = None) -> dict[str, Any]:
        from packages.story_core.orchestrator import (
            StoryOrchestrator,
            _genre_context_for_prompt,
            _render_compression_length_prompt,
            _render_expansion_length_prompt,
            _review_context_facts,
            _story_snapshot,
        )
        from packages.story_core.prompt_modules import modules_for_stage, prompt_module_catalog
        from packages.story_core.genre_stages.registry import genre_stage_profile_for

        numbers = self.chapter_numbers()
        latest_number = numbers[-1] if numbers else 0
        state = self.state()
        project = self.project()
        game_context = self._is_game_story_payload(project, state)
        target = int(chapter_number or state.get("current_chapter") or latest_number or 1)
        chapter: dict[str, Any] = {}
        try:
            chapter = self.chapter(target)
        except FileNotFoundError:
            chapter = {}

        state_before_chapter = self._generation_state_for_target(dict(state), target)
        direction_payload = self._story_state_payload_for_direction(
            state_before_chapter,
            project,
            target,
        )
        story = StoryState.model_validate(direction_payload)
        profile = genre_stage_profile_for(story)
        orchestrator = StoryOrchestrator()
        writing_packet, _, _ = self._build_writing_packet(target)
        plan = self._prompt_plan_from_chapter(chapter)
        plan["scene_cards"] = writing_packet.get("scene_cards", [])
        if isinstance(writing_packet.get("power_system"), dict):
            plan["power_system"] = writing_packet["power_system"]
        body = str(chapter.get("body") or "")
        review = chapter.get("quality_report") if isinstance(chapter.get("quality_report"), dict) else {}
        if not review and chapter:
            try:
                review = self.review(target)
            except FileNotFoundError:
                review = {}
        review = self._prompt_review_payload(review)
        core_context = _story_snapshot(story)
        writer_context = orchestrator._build_writer_context(story, target, plan)
        character_context = profile.prepare_writer_context(context=writer_context).character_context
        genre_context = _genre_context_for_prompt(story, target, plan)
        modules: list[dict[str, Any]] = [
            self._prompt_entry(
                key="core_context",
                title="核心上下文模块",
                agent="context",
                stage="核心上下文",
                content=json.dumps(core_context, ensure_ascii=False, indent=2),
                source="orchestrator._story_snapshot",
                description="主线、世界事实、账本、最近记忆和活世界信号；不包含完整人物角色卡。",
            ),
            self._prompt_entry(
                key="character_context",
                title="本章人物模块",
                agent="context",
                stage="人物角色卡",
                content=json.dumps(character_context, ensure_ascii=False, indent=2),
                source="orchestrator._character_context_for_prompt",
                description="按本章计划提取出场人物的角色卡；不是全量人物库。",
            ),
            self._prompt_entry(
                key="genre_context",
                title="题材写法模块",
                agent="context",
                stage="题材写法",
                content=json.dumps(genre_context, ensure_ascii=False, indent=2),
                source="orchestrator._genre_context_for_prompt",
                description="按项目题材单独选择写法。当前网游项目加载网游模块，其他题材加载对应模块。",
            ),
        ]
        enabled_skill_ids = resolve_enabled_skill_ids(project, state)
        enabled_skill_module_ids = resolve_enabled_skill_module_ids(project, state)
        for purpose, title in (
            ("writer", "正文写作 Skill"),
            ("dialogue", "对话 Skill"),
            ("style", "风格 Skill"),
            ("genre", "题材 Skill"),
            ("continuity", "连续性 Skill"),
            ("reviewer", "审稿 Skill"),
        ):
            skill_context = skill_pack_prompt_context(
                enabled_skill_ids,
                enabled_module_ids=enabled_skill_module_ids,
                purpose=purpose,
                max_chars_per_pack=2600,
            )
            if not skill_context:
                continue
            modules.append(
                self._prompt_entry(
                    key=f"skill_context_{purpose}",
                    title=title,
                    agent="context",
                    stage="Skill",
                    content=json.dumps(skill_context, ensure_ascii=False, indent=2),
                    source=f"skill_packs.enabled_skill_ids.{purpose}",
                    description="按用途裁剪后的本地 skill 包内容；只在相关阶段读取。",
                )
            )
        if isinstance(review, dict) and review:
            modules.append(
                self._prompt_entry(
                    key="review_context",
                    title="审稿报告模块",
                    agent="review",
                    stage="审稿报告",
                    content=json.dumps(review, ensure_ascii=False, indent=2),
                    source="chapter.quality_report",
                    description="改稿阶段才读取的审稿问题和修复清单。",
                )
            )
        packet_preview = self._compact_prompt_preview_packet(writing_packet)
        if isinstance(writing_packet.get("power_system"), dict):
            packet_preview["power_system"] = self._slim_prompt_preview_value(
                writing_packet["power_system"]
            )
        modules.append(
            self._prompt_entry(
                key="packet_context",
                title="写作包预览模块",
                agent="codex",
                stage="写作包",
                content=json.dumps(packet_preview, ensure_ascii=False, indent=2),
                source="file_project_store.writing_packet_compact_preview",
                description="给人工/Codex查看的压缩写作包；完整写作包仍由写作包接口返回。",
            )
        )

        prompts: list[dict[str, Any]] = [
            self._prompt_entry(
                key="director_plan",
                title="章节规划补全 Prompt",
                agent="director",
                stage="剧情计划生成",
                content=orchestrator._render_plan_prompt(story, target),
                source="rebuilt_from_state_before_chapter",
                description="生成 event_plan、chapter_intent、scene_cards 等结构化剧情计划。",
                module_keys=["core_context", "outline_context"],
            ),
            self._prompt_entry(
                key="writer_body",
                title="整章正文 Prompt",
                agent="writer",
                stage="整章正文生成",
                content=orchestrator._render_body_prompt(story, target, plan),
                source="rebuilt_from_chapter_plan",
                description="整章正文实际提示词，按输出要求、本章方向、本章事实、出场人物和正文写法五块装配。",
                module_keys=[
                    "core_context",
                    "outline_context",
                    "chapter_plan",
                    "character_context",
                    "genre_context",
                    "style_context",
                    "skill_context_writer",
                    "skill_context_dialogue",
                    "skill_context_style",
                    "skill_context_genre",
                    "writing_taskbook",
                ],
            ),
        ]

        taskbook = plan.get("writing_taskbook")
        if isinstance(taskbook, dict):
            taskbook_module = self._prompt_entry(
                key="writing_taskbook",
                title="本章方向模块",
                agent="context",
                stage="本章方向",
                content=format_taskbook_brief_section(taskbook),
                source="chapter.writing_taskbook",
                description="只保留本章目标、场面推进和收束，不重复通用风格规则。",
            )
            modules.append(taskbook_module)
            prompts.append(
                self._prompt_entry(
                    key="writing_taskbook",
                    title="写作任务书 Prompt 片段",
                    agent="writer",
                    stage="写作任务书",
                    content=taskbook_module["content"],
                    source="chapter.writing_taskbook",
                    description="整章正文读取的场景任务、风格合同和场面写法模板。",
                    module_keys=["writing_taskbook"],
                )
            )

        if body.strip():
            source_body_placeholder = f"[原正文由 source_body 注入；面板不展示正文全文；当前正文 {len(body)} 字。]"
            chapter_seed = plan.get("chapter_seed") if isinstance(plan.get("chapter_seed"), dict) else {}
            expansion_prompt = _render_expansion_length_prompt(
                story,
                source_body=source_body_placeholder,
                chapter_number=target,
                event_plan=plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {},
                world_facts=_review_context_facts(story),
            )
            compression_prompt = _render_compression_length_prompt(
                story,
                source_body=source_body_placeholder,
                chapter_number=target,
                event_plan=plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {},
                world_facts=_review_context_facts(story),
                outline_anchor=chapter_seed.get("outline_anchor"),
            )
            prompts.extend(
                [
                    self._prompt_entry(
                        key="revision",
                        title="审稿改稿 Prompt",
                        agent="writer",
                        stage="审稿改稿",
                        content=orchestrator._render_revision_prompt(
                            story,
                            target,
                            source_body_placeholder,
                            plan,
                            review if isinstance(review, dict) else {},
                        ),
                        source="rebuilt_from_chapter_body_and_review",
                        description="章节未通过写作审稿时，用于自动改稿的完整提示词。",
                        module_keys=["core_context", "character_context", "genre_context", "writing_taskbook", "review_context"],
                    ),
                    self._prompt_entry(
                        key="expansion",
                        title="章节扩写 Prompt",
                        agent="writer",
                        stage="章节扩写",
                        content=expansion_prompt,
                        source="rebuilt_conditional_prompt",
                        description="正文低于目标篇幅时触发。",
                        module_keys=["source_body"],
                    ),
                    self._prompt_entry(
                        key="compression",
                        title="章节压缩 Prompt",
                        agent="writer",
                        stage="章节压缩",
                        content=compression_prompt,
                        source="rebuilt_conditional_prompt",
                        description="正文超过目标篇幅时触发。",
                        module_keys=["source_body"],
                    ),
                ]
            )

        prompts.append(
            self._prompt_entry(
                key="review_agents",
                title="读者/编辑/审稿 Agent 说明",
                agent="review",
                stage="质量审稿",
                content="\n".join(
                    [
                        "读者 agent、编辑 agent、审稿 agent 当前主要读取章节正文和质量报告执行本地规则/函数检查。",
                        "它们不是独立调用 LLM 的隐藏提示词；如果后续接入 LLM 审稿，应把对应 prompt 也写入本接口。",
                    ]
                ),
                source="local_rule_based_review",
                description="说明为什么这里没有额外隐藏 prompt。",
                module_keys=["review_context"],
            )
        )

        artifact_stages = {
            "director_plan": "director",
            "writer_body": "writer",
            "writing_taskbook": "writer",
            "revision": "revision",
            "expansion": "length",
            "compression": "length",
            "review_agents": "review",
        }
        prompt_entry_ids = {id(entry) for entry in prompts}
        for entry in [*modules, *prompts]:
            content = normalize_legacy_economy_prompt_value(
                str(entry.get("content") or ""),
                game_context=game_context,
                chapter_number=target,
            )
            entry["content"] = content
            entry["chars"] = len(content)
            entry["genre_stage_profile"] = profile.profile_id
            genre_stage = (
                artifact_stages.get(str(entry.get("key") or ""), "")
                if id(entry) in prompt_entry_ids
                else ""
            )
            entry["genre_stage"] = genre_stage
            entry["genre_stage_modules"] = list(profile.modules_for(genre_stage))

        return {
            "schema_version": "file-project-prompt-preview/v1",
            "project_id": self.project().get("project_id") or self.root.name,
            "chapter_number": target,
            "chapter_title": chapter.get("chapter_title") or "",
            "source": "rebuilt_from_current_project_files",
            "reconstructed": True,
            "has_chapter": bool(chapter),
            "genre_stage_profile": profile.profile_id,
            "module_catalog": prompt_module_catalog(),
            "stage_modules": {
                stage: [module.key for module in modules_for_stage(stage)]
                for stage in ("planning", "writing", "revision", "validation")
            },
            "modules": modules,
            "prompts": prompts,
        }

    def prompt_context(self, chapter_number: int | None = None) -> dict[str, Any]:
        from packages.story_core.prompt_modules import prompt_module_catalog

        preview = self.prompt_preview(chapter_number)
        available_modules = []
        available_keys: set[str] = set()
        for module in preview.get("modules", []):
            item = dict(module)
            item["available"] = True
            available_modules.append(item)
            available_keys.add(str(item.get("key") or ""))
        for spec in prompt_module_catalog():
            key = str(spec.get("key") or "")
            if not key or key in available_keys or key == "source_body":
                continue
            available_modules.append(
                {
                    "key": key,
                    "title": spec.get("title") or key,
                    "agent": spec.get("owner") or "context",
                    "stage": spec.get("stage") or "context",
                    "source": spec.get("owner") or "context",
                    "description": spec.get("description") or "",
                    "content": "",
                    "chars": 0,
                    "module_keys": list(spec.get("depends_on") or []),
                    "available": False,
                    "reason": "not_provided_for_chapter",
                }
            )
        return {
            "schema_version": "file-project-prompt-context/v1",
            "project_id": preview.get("project_id"),
            "chapter_number": preview.get("chapter_number"),
            "chapter_title": preview.get("chapter_title"),
            "source": "current_project_context",
            "module_catalog": preview.get("module_catalog", []),
            "stage_modules": preview.get("stage_modules", {}),
            "modules": available_modules,
        }
