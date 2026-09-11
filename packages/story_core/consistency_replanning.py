"""Bounded, plan-only repair for the pre-Writer consistency gate.

This module deliberately keeps the replan operation separate from both the
historical state replay and the Writer.  A caller supplies a read-only source
snapshot and a planner callback; this module builds the structured Director
request, invokes the callback once, and evaluates the returned plan again
against the same historical boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from packages.story_core.character_inspection import ConsistencyWarning
from packages.story_core.generation_consistency_gate import (
    GenerationConsistencyGate,
    evaluate_generation_consistency,
)


MAX_CONSISTENCY_REPLAN_ATTEMPTS = 1
ConsistencyReplanStatus = Literal[
    "replanned_clear",
    "replanned_with_warnings",
    "still_blocking",
    "failed",
]


class ConsistencyReplanConstraints(BaseModel):
    """The non-negotiable planning constraints sent to the Director."""

    preserve_chapter_objective: bool = True
    preserve_established_canon: bool = True
    preserve_historical_state: bool = True
    remove_or_replace_contradictory_actions: bool = True
    no_retroactive_state_changes: bool = True
    structured_plan_only: bool = True


class ConsistencyReplanRequest(BaseModel):
    """Server-built Director input for one bounded current-chapter replan."""

    schema_version: Literal["consistency-replan-request/v1"] = (
        "consistency-replan-request/v1"
    )
    target_chapter: int = Field(ge=1)
    historical_boundary: int = Field(ge=0)
    original_plan: dict[str, Any] = Field(default_factory=dict)
    consistency_gate: GenerationConsistencyGate
    blocking_findings: list[ConsistencyWarning] = Field(default_factory=list)
    constraints: ConsistencyReplanConstraints = Field(
        default_factory=ConsistencyReplanConstraints
    )
    attempt_number: int = Field(ge=1)
    director_guidance: str = ""


class ConsistencyReplanResult(BaseModel):
    """The revised plan and the server's immediate authoritative recheck."""

    schema_version: Literal["consistency-replan-result/v1"] = (
        "consistency-replan-result/v1"
    )
    target_chapter: int = Field(ge=1)
    historical_boundary: int = Field(ge=0)
    attempt_number: int = Field(ge=1)
    original_plan_summary: dict[str, Any] = Field(default_factory=dict)
    revised_plan: dict[str, Any] = Field(default_factory=dict)
    addressed_warning_codes: list[str] = Field(default_factory=list)
    original_gate: GenerationConsistencyGate
    remaining_gate: GenerationConsistencyGate
    status: ConsistencyReplanStatus
    error: str = ""


def plan_to_dict(value: Any) -> dict[str, Any]:
    """Copy a structured Director/legacy plan into a JSON-shaped mapping.

    Generation jobs may receive either a legacy ``dict`` or a Pydantic
    ``DirectorArtifact`` from the gate.  Keeping this normalization in the
    shared replanning module prevents one API path from silently dropping the
    plan metadata when the other path preserves it.
    """

    if isinstance(value, Mapping):
        return {str(key): deepcopy(item) for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
        except TypeError:
            dumped = model_dump()
        if isinstance(dumped, Mapping):
            return {str(key): deepcopy(item) for key, item in dumped.items()}
    return {}


def _compact_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Keep Director input structural without copying simulation/state dumps."""

    allowed = (
        "chapter_number",
        "chapter_title",
        "chapter_goal",
        "opening_state",
        "ending_state",
        "hook",
        "chapter_intent",
        "character_moves",
        "action_briefs",
        "scene_beats",
        "scene_cards",
        "event_plan",
        "entity_requirements",
        "payoff_contract",
        "chapter_sop",
    )
    compact: dict[str, Any] = {}
    for key in allowed:
        value = plan.get(key)
        if value not in (None, "", [], {}):
            compact[key] = deepcopy(value)
    return compact


def summarize_plan(plan: Any) -> dict[str, Any]:
    """Return a small deterministic summary suitable for job responses."""

    payload = plan_to_dict(plan)
    summary: dict[str, Any] = {}
    for key in (
        "chapter_number",
        "chapter_title",
        "chapter_goal",
        "opening_state",
        "ending_state",
        "hook",
    ):
        if payload.get(key) not in (None, ""):
            summary[key] = deepcopy(payload[key])
    intent = payload.get("chapter_intent")
    if isinstance(intent, Mapping):
        for key in ("chapter_title", "chapter_goal", "next_focus", "primary_conflict"):
            if key not in summary and intent.get(key) not in (None, ""):
                summary[key] = deepcopy(intent[key])
    for key in ("character_moves", "action_briefs", "scene_beats", "scene_cards"):
        value = payload.get(key)
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    return summary


def _guidance_payload(
    *,
    target_chapter: int,
    historical_boundary: int,
    original_plan: Mapping[str, Any],
    findings: list[ConsistencyWarning],
    constraints: ConsistencyReplanConstraints,
) -> dict[str, Any]:
    return {
        "target_chapter": target_chapter,
        "historical_boundary": historical_boundary,
        "original_plan": _compact_plan(original_plan),
        "blocking_findings": [
            {
                "code": warning.code,
                "character_name": warning.character_name,
                "target_chapter": warning.target_chapter,
                "expected": deepcopy(warning.expected),
                "observed": deepcopy(warning.observed),
                "evidence": deepcopy(warning.evidence),
                "suggestion": warning.suggestion,
            }
            for warning in findings
        ],
        "constraints": constraints.model_dump(mode="json"),
    }


def build_director_replan_guidance(request: ConsistencyReplanRequest) -> str:
    """Render compact structured evidence plus immutable-history instructions."""

    payload = _guidance_payload(
        target_chapter=request.target_chapter,
        historical_boundary=request.historical_boundary,
        original_plan=request.original_plan,
        findings=request.blocking_findings,
        constraints=request.constraints,
    )
    return "\n".join(
        [
            "## 一致性重新规划（只处理当前目标章节）",
            "历史事实是不可变输入。不得修改历史章节、Knowledge Ledger、技能获得时间、装备所有权、关系历史或角色历史位置。",
            "只能改变当前章节的结构化计划；不得通过声称历史已经改变来消除冲突。",
            "优先级：历史一致性 > 已建立 canon > 本章目标 > 风格偏好。尽量保留本章目标，替换最小的矛盾动作。",
            "如果要表达本章内的转移或揭示，必须作为本章计划动作，不得当作章节开始时已经发生。",
            "只返回可供 Writer 执行的结构化计划 JSON，不返回解释、正文或状态自评。",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        ]
    )


def build_consistency_replan_request(
    *,
    target_chapter: int,
    original_plan: Any,
    consistency_gate: GenerationConsistencyGate | Mapping[str, Any],
    attempt_number: int = 1,
    constraints: ConsistencyReplanConstraints | None = None,
) -> ConsistencyReplanRequest:
    """Build the request from server-owned plan/gate data."""

    if attempt_number < 1:
        raise ValueError("replan_attempt_invalid")
    gate = (
        consistency_gate
        if isinstance(consistency_gate, GenerationConsistencyGate)
        else GenerationConsistencyGate.model_validate(consistency_gate)
    )
    plan = plan_to_dict(original_plan)
    request = ConsistencyReplanRequest(
        target_chapter=int(target_chapter),
        historical_boundary=int(target_chapter) - 1,
        original_plan=plan,
        consistency_gate=gate,
        blocking_findings=[
            warning for warning in gate.warnings if warning.severity == "error"
        ],
        constraints=constraints or ConsistencyReplanConstraints(),
        attempt_number=attempt_number,
    )
    return request.model_copy(
        update={"director_guidance": build_director_replan_guidance(request)}
    )


def _result(
    *,
    request: ConsistencyReplanRequest,
    original_gate: GenerationConsistencyGate,
    revised_plan: Mapping[str, Any] | None,
    remaining_gate: GenerationConsistencyGate,
    status: ConsistencyReplanStatus,
    error: str = "",
) -> ConsistencyReplanResult:
    old_codes = {item.code for item in original_gate.blocking_warnings}
    new_codes = {item.code for item in remaining_gate.blocking_warnings}
    return ConsistencyReplanResult(
        target_chapter=request.target_chapter,
        historical_boundary=request.historical_boundary,
        attempt_number=request.attempt_number,
        original_plan_summary=summarize_plan(request.original_plan),
        revised_plan=deepcopy(dict(revised_plan or {})),
        addressed_warning_codes=sorted(old_codes - new_codes),
        original_gate=original_gate,
        remaining_gate=remaining_gate,
        status=status,
        error=error,
    )


def run_consistency_replan(
    *,
    source: Any,
    target_chapter: int,
    original_plan: Any,
    original_gate: GenerationConsistencyGate | Mapping[str, Any],
    plan_replanner: Callable[[ConsistencyReplanRequest], Any],
    fallback_root: Any | None = None,
    attempt_number: int = 1,
) -> ConsistencyReplanResult:
    """Run one Director replan and immediately recompute the gate.

    ``original_gate`` is retained as job evidence, but the source and original
    plan are always evaluated again here.  This makes a client-provided or
    stale warning list irrelevant to the decision.
    """

    if attempt_number > MAX_CONSISTENCY_REPLAN_ATTEMPTS:
        raise ValueError("replan_attempt_limit")
    request = build_consistency_replan_request(
        target_chapter=target_chapter,
        original_plan=original_plan,
        consistency_gate=original_gate,
        attempt_number=attempt_number,
    )
    authoritative_original_gate = evaluate_generation_consistency(
        source,
        request.original_plan,
        target_chapter=request.target_chapter,
        fallback_root=fallback_root,
    )
    request = request.model_copy(
        update={
            "consistency_gate": authoritative_original_gate,
            "blocking_findings": [
                warning
                for warning in authoritative_original_gate.warnings
                if warning.severity == "error"
            ],
        }
    )
    request = request.model_copy(
        update={"director_guidance": build_director_replan_guidance(request)}
    )
    try:
        revised_plan = plan_to_dict(plan_replanner(request))
        if not revised_plan:
            raise ValueError("replanned_plan_empty")
        revised_gate = evaluate_generation_consistency(
            source,
            revised_plan,
            target_chapter=request.target_chapter,
            fallback_root=fallback_root,
        )
    except Exception as exc:
        return _result(
            request=request,
            original_gate=authoritative_original_gate,
            revised_plan=None,
            remaining_gate=authoritative_original_gate,
            status="failed",
            error=f"{type(exc).__name__}:{exc}",
        )

    status: ConsistencyReplanStatus
    if revised_gate.status == "blocking":
        status = "still_blocking"
    elif revised_gate.status == "warnings":
        status = "replanned_with_warnings"
    else:
        status = "replanned_clear"
    return _result(
        request=request,
        original_gate=authoritative_original_gate,
        revised_plan=revised_plan,
        remaining_gate=revised_gate,
        status=status,
    )


__all__ = [
    "MAX_CONSISTENCY_REPLAN_ATTEMPTS",
    "ConsistencyReplanConstraints",
    "ConsistencyReplanRequest",
    "ConsistencyReplanResult",
    "ConsistencyReplanStatus",
    "build_consistency_replan_request",
    "build_director_replan_guidance",
    "plan_to_dict",
    "run_consistency_replan",
    "summarize_plan",
]
