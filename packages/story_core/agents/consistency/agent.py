"""Focused consistency agent.

The agent answers exactly one question: *does the draft
contradict the established facts or the approved director
plan?* It does not grade literary style; style findings stay
warnings the user can accept and ship with.

The runtime boundary mirrors the writer / director agent shape
so a CLI / HTTP API swap is invisible to the agent. A test
double can return a canned payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..contracts import DirectorArtifact


class ConsistencyRuntime(Protocol):
    """Anything that can fulfil one consistency model call."""

    def complete(self, request: Any) -> Any: ...


@dataclass
class _ModelRequest:
    prompt: str
    stage: str
    metadata: dict[str, Any]


def _extract_payload(response: Any) -> dict[str, Any]:
    if response is None:
        return {}
    if isinstance(response, dict):
        return response
    payload = getattr(response, "payload", None)
    if isinstance(payload, dict):
        return payload
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        import json

        try:
            parsed = json.loads(text)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def build_consistency_prompt(
    body: str,
    director_artifact: DirectorArtifact,
    active_facts: list[dict[str, Any]],
) -> str:
    """Render the focused consistency prompt.

    The prompt names the chapters facts to check (director
    artifact, active continuity facts) and asks for structured
    findings only. It explicitly tells the model not to grade
    style or recommend prose improvements — those go through
    the soft-review path.
    """
    beats = "\n".join(
        f"- 顺序{beat.order} · 地点：{beat.location} · 动作：{beat.action} · 结果：{beat.result}"
        for beat in director_artifact.scene_beats
    )
    facts = "\n".join(
        f"- {fact.get('subject', '?')} · {fact.get('field', '?')}：{fact.get('value', '?')}"
        for fact in active_facts
    )
    return (
        "你是小说事实一致性 agent。\n"
        "只判断正文是否与下列既定事实或导演计划矛盾。不要评价文笔、风格、对话自然度。\n"
        "如果出现矛盾,返回 code / message / blocking / source 四个字段的 JSON 列表。\n"
        "如果没有矛盾,返回空列表 []。\n\n"
        f"## 章节目标\n{director_artifact.chapter_goal}\n\n"
        f"## 场景节拍\n{beats}\n\n"
        f"## 收尾状态\n{director_artifact.ending_state}\n\n"
        f"## 既定事实\n{facts or '（无）'}\n\n"
        f"## 正文\n{body}"
    )


@dataclass
class ConsistencyFinding:
    """One factual contradiction surfaced by the agent.

    The agent is the only source of these findings; the
    deterministic checks live in ``continuity.checks``.
    ``blocking`` is preserved if the runtime tagged it
    blocking, but the wrapper downgrades style issues to
    advisory so the user can accept them.
    """

    code: str
    message: str
    source: str = "consistency"
    blocking: bool = True


_STYLE_CODES: set[str] = {
    "style.report_voice",
    "style.ai_tone",
    "style.abstract",
    "dialogue.unnatural",
    "exposition.too_dense",
}


def _downgrade_style(code: str, blocking: bool) -> bool:
    """Advisory only: never let a style finding block a chapter."""
    if code in _STYLE_CODES:
        return False
    return blocking


class FocusedConsistencyAgent:
    """The single factual-consistency boundary."""

    def __init__(self, runtime: ConsistencyRuntime) -> None:
        self._runtime = runtime

    def review(
        self,
        *,
        body: str,
        director_artifact: DirectorArtifact,
        active_facts: list[dict[str, Any]],
    ) -> list[ConsistencyFinding]:
        prompt = build_consistency_prompt(body, director_artifact, active_facts)
        request = _ModelRequest(
            prompt=prompt,
            stage="consistency",
            metadata={
                "chapter_number": director_artifact.chapter_number,
                "agent": "consistency",
                "schema_version": director_artifact.schema_version,
            },
        )
        response = self._runtime.complete(request)
        payload = _extract_payload(response)
        issues = payload.get("issues") if isinstance(payload, dict) else None
        if not isinstance(issues, list):
            return []
        findings: list[ConsistencyFinding] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            code = str(issue.get("code") or "").strip()
            message = str(issue.get("message") or "").strip()
            if not code or not message:
                continue
            blocking_raw = issue.get("blocking")
            blocking = bool(blocking_raw) if blocking_raw is not None else True
            findings.append(
                ConsistencyFinding(
                    code=code,
                    message=message,
                    source=str(issue.get("source") or "consistency"),
                    blocking=_downgrade_style(code, blocking),
                )
            )
        return findings


def focused_consistency_review(
    body: str,
    *,
    director_artifact: DirectorArtifact,
    active_facts: list[dict[str, Any]],
    runtime: ConsistencyRuntime,
) -> list[ConsistencyFinding]:
    """Convenience entry point for the orchestrator's confirmation path."""
    agent = FocusedConsistencyAgent(runtime=runtime)
    return agent.review(
        body=body,
        director_artifact=director_artifact,
        active_facts=active_facts,
    )


__all__ = [
    "ConsistencyRuntime",
    "ConsistencyFinding",
    "FocusedConsistencyAgent",
    "build_consistency_prompt",
    "focused_consistency_review",
]
