"""Aggregate deterministic chapter reviewers into one compatible report.

This module is now a thin shim around `ReviewService`. It keeps the historical
`review_chapter_body(...)` signature for callers that orchestrate review +
aggregate genres, but delegates the actual hard-gate / soft-review split to
the canonical `ReviewService`. Raw reviewer reports are read from the
service's `raw_reports` diagnostics so the legacy aggregate fields (scores,
consolidated review blocks) still flow into callers that depend on them.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from packages.story_core.attribute_evidence import character_evidence_names
from packages.story_core.models import StoryState

from .service import ReviewService


ReviewFunction = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ReviewDependencies:
    profile_for: Callable[[Any], Any]
    review_continuity: ReviewFunction
    review_fragments: Callable[[str], list[str]]
    review_consistency: ReviewFunction
    review_style: ReviewFunction
    review_prose_quality: ReviewFunction
    review_adversarial_cuts: ReviewFunction
    review_ai_flavor: ReviewFunction
    review_reader_feel: ReviewFunction
    review_cold_reader: ReviewFunction
    review_plot_spine: ReviewFunction
    review_critical_rules: ReviewFunction
    build_scene_repair: Callable[..., list[dict[str, Any]]]
    report_progress: Callable[[Any], None]


def review_protagonist_names(
    event_plan: dict[str, Any],
    simulation_plan: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    names: list[str] = []

    def add(value: object) -> None:
        name = str(value or "").strip()
        if not name or len(name) > 12:
            return
        if name in {"主角", "玩家", "散人", "NPC", "系统", "旁人", "众人"}:
            return
        if name not in names:
            names.append(name)

    def scan_plan(plan: dict[str, Any]) -> None:
        primary = plan.get("primary_conflict")
        if isinstance(primary, dict):
            add(primary.get("lead"))
        for action in plan.get("ordered_actions") or []:
            if isinstance(action, dict):
                add(action.get("name"))

    if isinstance(event_plan, dict):
        scan_plan(event_plan)
    if isinstance(simulation_plan, dict):
        nested_event_plan = simulation_plan.get("event_plan")
        if isinstance(nested_event_plan, dict):
            scan_plan(nested_event_plan)
        performance = simulation_plan.get("character_performance")
        if isinstance(performance, dict):
            for name in performance:
                add(name)
    return tuple(names[:4])


def story_review_genre_context(story: StoryState) -> dict[str, Any]:
    return {"genre": story.genre, "genre_plugin_ids": list(story.genre_plugin_ids)}


def review_character_names(story: StoryState) -> tuple[str, ...]:
    names = character_evidence_names(
        character
        for character in story.characters
        if character.lifecycle_state in {"active", "approved"} and not character.frozen
    )
    return tuple(sorted(names, key=lambda value: (-len(value), value)))


def _review_exception_result(name: str, exc: Exception) -> dict[str, Any]:
    return {
        "pass": False,
        "scores": {f"{name}_exception": 4},
        "issues": [f"审稿器{name}异常：{exc}"],
        "revision_plan": [f"修复审稿器{name}异常后重新审核。"],
    }


def _build_genre_review(
    *,
    body: str,
    chapter_number: int,
    event_plan: dict[str, Any],
    world_facts: list[str] | None,
    simulation_plan: dict[str, Any] | None,
    protagonist_names: tuple[str, ...],
    character_names: tuple[str, ...],
    genre_context: Any,
    dependencies: ReviewDependencies,
    report_progress: Callable[[Any], None],
) -> dict[str, Any]:
    profile = dependencies.profile_for(genre_context)
    review = getattr(profile, "review_chapter", None)
    if not callable(review):
        return {
            "pass": True,
            "scores": {},
            "issues": [],
            "revision_plan": [],
            "active_genre_reviews": {},
        }
    genre_review_context = {
        "chapter_number": chapter_number,
        "body": body,
        "event_plan": event_plan,
        "world_facts": world_facts or [],
        "simulation_plan": simulation_plan or {},
        "protagonist_aliases": protagonist_names,
        "character_names": character_names or (),
    }
    try:
        return review(context=genre_review_context)
    except Exception as exc:
        report_progress(f"review[genre] exception: {exc}")
        return _review_exception_result("genre", exc)


def review_chapter_body(
    chapter_number: int,
    body: str,
    event_plan: dict[str, Any],
    world_facts: list[str] | None = None,
    simulation_plan: dict[str, Any] | None = None,
    world_events: list[dict[str, Any]] | None = None,
    scene_cards: list[dict[str, Any]] | None = None,
    genre_context: Any = None,
    protagonist_aliases: tuple[str, ...] | None = None,
    character_names: tuple[str, ...] | None = None,
    *,
    dependencies: ReviewDependencies,
    min_chapter_chars: int,
    target_chapter_chars: str,
    chapter_char_tolerance: int,
) -> dict[str, Any]:
    compact_body = "".join(body.split())
    simulation_plan = simulation_plan or {}
    protagonist_names = protagonist_aliases or review_protagonist_names(event_plan, simulation_plan)
    previous_summary = str(
        simulation_plan.get("previous_summary")
        or event_plan.get("previous_summary")
        or event_plan.get("summary")
        or ""
    )
    continuity_interface = (
        simulation_plan.get("continuity_interface")
        if isinstance(simulation_plan.get("continuity_interface"), dict)
        else {}
    )

    # The service is the only place that invokes the underlying reviewers.
    service = ReviewService(
        review_continuity=dependencies.review_continuity,
        review_fragments=dependencies.review_fragments,
        review_consistency=dependencies.review_consistency,
        review_critical_rules=dependencies.review_critical_rules,
        profile_for=dependencies.profile_for,
        review_style=dependencies.review_style,
        review_prose_quality=dependencies.review_prose_quality,
        review_adversarial_cuts=dependencies.review_adversarial_cuts,
        review_ai_flavor=dependencies.review_ai_flavor,
        review_reader_feel=dependencies.review_reader_feel,
        review_cold_reader=dependencies.review_cold_reader,
        review_plot_spine=dependencies.review_plot_spine,
        min_chars=min_chapter_chars,
        char_tolerance=chapter_char_tolerance,
    )

    hard_context = {
        "continuity_interface": continuity_interface,
        "world_events": world_events or [],
        "scene_cards": scene_cards or [],
        "chapter_number": chapter_number,
        "genre_context": genre_context,
        "event_plan": event_plan,
        "world_facts": world_facts or [],
        "simulation_plan": simulation_plan,
        "protagonist_aliases": protagonist_names,
        "character_names": character_names or (),
    }
    soft_context = dict(hard_context)
    soft_context["previous_summary"] = previous_summary

    hard = service.run_hard_gate(body=body, context=hard_context)
    soft = service.run_soft_review(body=body, context=soft_context)
    combined = service.combine(hard, soft)
    review_result_payload = combined.to_dict()

    hard_raw = hard.diagnostics.get("raw_reports", {}) if isinstance(hard.diagnostics, dict) else {}
    soft_raw = soft.diagnostics.get("raw_reports", {}) if isinstance(soft.diagnostics, dict) else {}

    continuity_review = _normalize_report(hard_raw.get("continuity"))
    fragments_issues = list(hard_raw.get("fragments") or [])
    consistency_review = _normalize_report(hard_raw.get("consistency"))
    style_review = _normalize_report(soft_raw.get("style"))
    prose_quality_review = _normalize_report(soft_raw.get("prose_quality"))
    adversarial_cut_review = _normalize_report(soft_raw.get("adversarial_cut"))
    ai_flavor_review = _normalize_report(soft_raw.get("ai_flavor"))
    reader_feel_review = _normalize_report(soft_raw.get("reader_feel"))
    cold_reader_review = _normalize_report(soft_raw.get("cold_reader"))
    plot_spine_review = _normalize_report(soft_raw.get("plot_spine"))
    critical_review = _normalize_report(hard_raw.get("critical"))
    genre_review = _normalize_report(hard_raw.get("genre"))

    scene_contract_failures = (
        consistency_review.get("scene_contract_failures")
        if isinstance(consistency_review.get("scene_contract_failures"), list)
        else []
    )
    scene_repair_plan = dependencies.build_scene_repair(consistency_review, scene_cards or [])

    active_genre_reviews = genre_review.get("active_genre_reviews", {}) if isinstance(genre_review, dict) else {}
    if not isinstance(active_genre_reviews, dict):
        active_genre_reviews = {}

    scores: dict[str, int] = {
        "webnovel_hook": 8 if len(compact_body) >= min_chapter_chars - chapter_char_tolerance else 5,
        "background_integration": 8,
        "protagonist_motivation": 8,
        "genre_rules": 8,
        "world_reaction": 8,
        "chapter_ending_hook": 8 if event_plan.get("next_focus") or event_plan.get("stakes") else 5,
        "continuity": 8,
    }
    if continuity_review.get("hard_error"):
        scores["continuity"] = min(scores["continuity"], 4)

    issues: list[str] = []
    revision_plan: list[str] = []
    issues.extend(continuity_review.get("issues", []) or [])
    revision_plan.extend(continuity_review.get("revision_plan", []) or [])
    if fragments_issues:
        scores["continuity"] = min(scores["continuity"], 5)
        issues.extend(fragments_issues)
        revision_plan.extend(
            "补全该句的谓语、宾语或明确指代，不要用压缩短语代替完整中文。" for _ in fragments_issues
        )
    if len(compact_body) < min_chapter_chars - chapter_char_tolerance:
        scores["webnovel_hook"] = min(scores["webnovel_hook"], 5)
        issues.append(
            f"章节字数偏少：当前约{len(compact_body)}字，番茄长篇建议至少{min_chapter_chars}字。"
        )
        revision_plan.append(
            f"扩写到{target_chapter_chars}，补足场景、动作、对话、可见后果和章末钩子，避免摘要化。"
        )

    if simulation_plan:
        scores["simulation_plan_alignment"] = 8
        if not simulation_plan.get("review_focus") or not simulation_plan.get("character_performance"):
            scores["simulation_plan_alignment"] = 6
            issues.append(
                "统一场景推演/表演蓝图不完整：缺少角色表演或审稿重点，后续章节容易变成只有事件、没有角色反应。"
            )
            revision_plan.append(
                "补齐 simulation_plan.character_performance 与 simulation_plan.review_focus，再让正文按角色行事习惯、配角边界和信息可见性展开。"
            )

    for key, score in genre_review.get("scores", {}).items():
        scores[key] = min(scores.get(key, score), score)
    _merge_legacy_review(genre_review, scores=scores, issues=issues, revision_plan=revision_plan)
    _merge_legacy_review(consistency_review, scores=scores, issues=issues, revision_plan=revision_plan, prefix="world_event_")
    _merge_legacy_review(style_review, scores=scores, issues=issues, revision_plan=revision_plan, prefix="prose_style_")
    _merge_legacy_review(critical_review, scores=scores, issues=issues, revision_plan=revision_plan, prefix="critical_")
    _merge_legacy_review(ai_flavor_review, scores=scores, issues=issues, revision_plan=revision_plan, prefix="ai_flavor_")
    _merge_legacy_review(reader_feel_review, scores=scores, issues=issues, revision_plan=revision_plan, prefix="reader_feel_")

    cold_reader_pass = bool(cold_reader_review.get("pass", True))
    for key, score in cold_reader_review.get("scores", {}).items():
        scores[f"cold_reader_{key}"] = 8 if cold_reader_pass and int(score or 0) >= 3 else min(7, int(score or 0))
    for issue in cold_reader_review.get("issues", []):
        reason = issue.get("reason") if isinstance(issue, dict) else str(issue)
        if reason and reason not in issues:
            issues.append(reason)
    for item in cold_reader_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    _merge_legacy_review(plot_spine_review, scores=scores, issues=issues, revision_plan=revision_plan)

    report = {
        "pass": combined.status != "blocked",
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "review_summary": {
            "core_passed": combined.status != "blocked",
            "soft_passed": combined.status != "blocked",
            "status": combined.status,
        },
        "active_genre_reviews": active_genre_reviews,
        "consistency_review": consistency_review,
        "prose_style_review": style_review,
        "prose_quality_review": prose_quality_review,
        "adversarial_cut_review": adversarial_cut_review,
        "ai_flavor_review": ai_flavor_review,
        "reader_feel_review": reader_feel_review,
        "cold_reader_review": cold_reader_review,
        "plot_spine_review": plot_spine_review,
        "critical_review": critical_review,
        "world_state_review": _merge_world_state_reviews(
            _build_world_state_review(issues, revision_plan),
            genre_review.get("world_state_review", {}) if isinstance(genre_review, dict) else {},
        ),
        "scene_contract_failures": scene_contract_failures,
        "scene_repair_plan": scene_repair_plan,
        "continuity_interface_review": continuity_review,
        "downstream_rewrite_required": bool(continuity_review.get("downstream_rewrite_required")),
        "downstream_chapter_number": continuity_review.get("downstream_chapter_number"),
        "review_result": review_result_payload,
    }
    report.update(active_genre_reviews)
    return report


def _normalize_report(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _build_world_state_review(issues: list[str], revision_plan: list[str]) -> dict[str, Any]:
    surfaces: dict[str, dict[str, Any]] = {}

    def add(surface: str, issue: str, patch: str) -> None:
        entry = surfaces.setdefault(surface, {"surface": surface, "issues": [], "suggested_patch": patch})
        if issue not in entry["issues"]:
            entry["issues"].append(issue)

    rules = (
        ("timeline", ("时间", "日期", "昼夜", "时序", "先后顺序"), "更新 world_blueprint.timeline，明确事件时间、持续时长和先后顺序。"),
        ("location", ("地点", "位置", "距离", "路线", "空间"), "更新 world_blueprint.locations，明确地点、距离、路线和场景转换条件。"),
        ("relationships", ("人物关系", "关系变化", "信任", "敌意", "立场"), "更新 world_blueprint.relationships，记录人物立场、关系变化及其可见依据。"),
        ("causality", ("因果", "动机", "后果", "前因", "结果矛盾"), "更新 world_blueprint.causality，固化关键行动的动机、条件和后果。"),
        ("world_rules", ("世界规则", "设定冲突", "规则矛盾", "世界观"), "更新 world_blueprint.rules，记录已建立规则、适用条件和例外边界。"),
    )
    for issue in issues:
        text = str(issue)
        for surface, tokens, patch in rules:
            if any(token in text for token in tokens):
                add(surface, text, patch)

    patch_plan: list[str] = []
    for entry in surfaces.values():
        patch = str(entry["suggested_patch"])
        if patch not in patch_plan:
            patch_plan.append(patch)
    for item in revision_plan:
        text = str(item)
        if any(token in text for token in ("世界档案", "world_blueprint")) and text not in patch_plan:
            patch_plan.append(text)
    return {
        "pass": not surfaces,
        "issues": list(surfaces.values()),
        "patch_plan": patch_plan[:8],
        "affected_surfaces": list(surfaces),
    }


def _merge_world_state_reviews(*reviews: Any) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    patch_plan: list[str] = []
    affected_surfaces: list[str] = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        for issue in review.get("issues", []):
            if isinstance(issue, dict) and issue not in issues:
                issues.append(issue)
        for patch in review.get("patch_plan", []):
            text = str(patch)
            if text and text not in patch_plan:
                patch_plan.append(text)
        for surface in review.get("affected_surfaces", []):
            text = str(surface)
            if text and text not in affected_surfaces:
                affected_surfaces.append(text)
    return {
        "pass": not issues,
        "issues": issues,
        "patch_plan": patch_plan[:8],
        "affected_surfaces": affected_surfaces,
    }


def _merge_legacy_review(
    review: Any,
    *,
    scores: dict[str, int],
    issues: list[str],
    revision_plan: list[str],
    prefix: str = "",
) -> None:
    if not isinstance(review, dict):
        return
    for key, score in review.get("scores", {}).items():
        # Merge with prefix when provided; for unprefixed reviews
        # (e.g. plot_spine) keep the source keys as-is so callers
        # can read ``scores["plot_spine_critical"]`` at the top
        # level — this matches the legacy v1 contract that the
        # chapter review envelope used to expose.
        scores[f"{prefix}{key}"] = score
    for issue in review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
