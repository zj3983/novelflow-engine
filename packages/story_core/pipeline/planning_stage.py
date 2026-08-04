"""Chapter-plan resolution, retries, and bounded quality revision."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


PlanModelCall = Callable[[str, str], tuple[str, str]]
PlanReview = Callable[[dict[str, Any]], list[str]]
PlanPrepare = Callable[[dict[str, Any]], dict[str, Any]]
PlanningEvent = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class PlanningStageResult:
    ok: bool
    plan: dict[str, Any] = field(default_factory=dict)
    planning_source: str = "model_fallback"
    planning_modules: list[str] = field(default_factory=list)
    error: str = ""
    issues: list[str] = field(default_factory=list)


def _parse_plan(text: str, *, error_prefix: str) -> tuple[dict[str, Any], str]:
    try:
        parsed = json.loads(text)
    except Exception as exc:
        return {}, f"{error_prefix}:{exc}"
    if not isinstance(parsed, dict):
        return {}, f"{error_prefix}:root_not_object"
    return parsed, ""


def resolve_chapter_plan(
    *,
    outline_plan: dict[str, Any] | None,
    build_prompt: Callable[[], str],
    call_model: PlanModelCall,
    review_plan: PlanReview,
    build_revision_prompt: Callable[[str, dict[str, Any], list[str]], str],
    prepare_plan: PlanPrepare | None = None,
    on_event: PlanningEvent | None = None,
) -> PlanningStageResult:
    planning_source = "outline" if outline_plan is not None else "model_fallback"
    planning_modules = ["chapter_planning"] if outline_plan is not None else ["chapter_planning", "planner_model"]
    director_prompt = ""
    if outline_plan is not None:
        plan_text = json.dumps(outline_plan, ensure_ascii=False)
        plan_error = ""
    else:
        director_prompt = build_prompt()
        plan_text, plan_error = call_model(director_prompt, "剧情计划生成")

    if plan_error and "有效 JSON" in plan_error:
        if on_event:
            on_event("format_retry", {"error": plan_error})
        retry_prompt = "\n".join(
            [
                director_prompt,
                "上一次返回不是有效 JSON。请重新生成，只输出一个完整 JSON 对象，不要代码块、解释或前后缀。",
            ]
        )
        plan_text, plan_error = call_model(retry_prompt, "剧情计划格式重试")
    if plan_error:
        return PlanningStageResult(
            ok=False,
            planning_source=planning_source,
            planning_modules=planning_modules,
            error=plan_error or "plan_empty",
        )

    plan, parse_error = _parse_plan(plan_text, error_prefix="outline_plan_parse_failed")
    if parse_error:
        return PlanningStageResult(
            ok=False,
            planning_source=planning_source,
            planning_modules=planning_modules,
            error=parse_error,
        )
    if prepare_plan is not None:
        plan = prepare_plan(plan)

    issues = review_plan(plan)
    if planning_source == "outline":
        issues = [issue for issue in issues if "attribute_allocation_decision" in issue]
    if issues:
        if on_event:
            on_event("quality_retry", {"issues": issues, "rejected_plan": plan})
        if not director_prompt:
            director_prompt = build_prompt()
        retry_text, retry_error = call_model(
            build_revision_prompt(director_prompt, plan, issues),
            "剧情计划重做",
        )
        if retry_error:
            return PlanningStageResult(
                ok=False,
                planning_source=planning_source,
                planning_modules=planning_modules,
                error=f"director_plan_quality_failed:{'; '.join(issues)}; retry:{retry_error}",
                issues=issues,
            )
        plan, parse_error = _parse_plan(retry_text, error_prefix="director_plan_quality_failed:retry_parse_failed")
        if parse_error:
            return PlanningStageResult(
                ok=False,
                planning_source=planning_source,
                planning_modules=planning_modules,
                error=parse_error,
                issues=issues,
            )
        if prepare_plan is not None:
            plan = prepare_plan(plan)
        issues = review_plan(plan)
        if issues:
            if on_event:
                on_event("quality_failed", {"issues": issues, "rejected_plan": plan})
            return PlanningStageResult(
                ok=False,
                planning_source=planning_source,
                planning_modules=planning_modules,
                error=f"director_plan_quality_failed:{'; '.join(issues)}",
                issues=issues,
            )

    return PlanningStageResult(
        ok=True,
        plan=plan,
        planning_source=planning_source,
        planning_modules=planning_modules,
    )
