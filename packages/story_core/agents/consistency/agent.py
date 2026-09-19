"""Focused consistency agent.

The agent answers exactly one question: *does the draft
contradict the established facts or the approved director
plan?* It does not grade literary style; style findings stay
warnings the user can accept and ship with.

A runtime exception or malformed response means the facts were
**not verified**; it is not evidence that the draft contradicted
canon. Those availability findings remain visible but advisory,
while actual established-fact contradictions may still block.
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
    if isinstance(response, list):
        return {"issues": response}
    payload = getattr(response, "payload", None)
    if isinstance(payload, dict) and payload:
        return payload
    if isinstance(payload, list):
        return {"issues": payload}
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        import json
        import re

        normalized = text.strip()
        fenced = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```",
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if fenced:
            normalized = fenced.group(1).strip()
        try:
            parsed = json.loads(normalized)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"issues": parsed}
    return {}


def _current_character_state(card: dict[str, Any]) -> dict[str, Any]:
    """Project only the current state of a character for the prompt."""
    state: dict[str, Any] = {}
    for namespace in ("current_state", "real_state", "game_state"):
        value = card.get(namespace)
        if isinstance(value, dict):
            current = value.get("current") if isinstance(value.get("current"), dict) else value
            if current:
                state[namespace] = current
    return state


def _json_inline(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


_GENERIC_CANON_SOURCES = {
    "",
    "canon",
    "canonical",
    "canon.fact",
    "canon.character",
    "canon.entity",
    "canon.relationship",
    "canon.timeline",
    "canon.world_rule",
    "canon.foreshadowing",
    "consistency",
    "fact",
    "facts",
}


def _evidence_token(value: Any) -> str:
    """Normalize a source/evidence token for exact snapshot matching."""
    if isinstance(value, str):
        return " ".join(value.split()).strip().casefold()
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip().casefold()


def _snapshot_evidence(
    snapshot: dict[str, Any] | None,
) -> tuple[set[str], set[str]]:
    """Return exact source and evidence tokens exposed by a review snapshot.

    This intentionally reads only the plain snapshot projection. It does not
    inspect the live registry, director beats, caller-supplied character cards,
    or the finding message itself.
    """
    if not isinstance(snapshot, dict) or not snapshot:
        return set(), set()

    if snapshot.get("historical_rewrite") and not bool(
        snapshot.get("bounded_state_available")
    ):
        # A degraded historical snapshot is deliberately not evidence.
        return set(), set()

    sources: set[str] = set()
    evidence: set[str] = set()

    def add_item(collection: str, index: int, item: Any) -> None:
        if not isinstance(item, dict):
            return
        sources.add(f"canon.{collection}:{index}".casefold())
        source = _evidence_token(item.get("source"))
        if source and source not in _GENERIC_CANON_SOURCES:
            sources.add(source)
        for key in (
            "evidence",
            "source_sentence",
            "value",
            "fact",
            "text",
            "summary",
            "message",
            "marker",
        ):
            token = _evidence_token(item.get(key))
            if token:
                evidence.add(token)

    for collection in ("facts", "relationships", "timeline", "foreshadowing"):
        for index, item in enumerate(snapshot.get(collection) or []):
            add_item(collection.rstrip("s"), index, item)

    for index, rule in enumerate(snapshot.get("world_rules") or []):
        sources.add(f"canon.world_rule:{index}".casefold())
        token = _evidence_token(rule)
        if token:
            evidence.add(token)

    for index, card in enumerate(snapshot.get("characters") or []):
        if not isinstance(card, dict):
            continue
        name = _evidence_token(card.get("name"))
        if name:
            sources.add(f"canon.character:{name}")
        add_item("character", index, card)

    for index, entity in enumerate(snapshot.get("entities") or []):
        if not isinstance(entity, dict):
            continue
        entity_id = _evidence_token(entity.get("entity_id"))
        if entity_id:
            sources.add(f"canon.entity:{entity_id}")
        add_item("entity", index, entity)

    return sources, evidence


def _has_verified_canon_evidence(
    *,
    source: str,
    canon_evidence: str | None,
    canon_snapshot: dict[str, Any] | None,
) -> bool:
    sources, evidence = _snapshot_evidence(canon_snapshot)
    if not sources and not evidence:
        return False
    source_token = _evidence_token(source)
    evidence_token = _evidence_token(canon_evidence)
    return (
        source_token in sources
        or source_token in evidence
        or evidence_token in sources
        or evidence_token in evidence
    )


def _evidence_label(item: dict[str, Any], *, fallback: str) -> str:
    source = str(item.get("source") or fallback).strip() or fallback
    chapter = item.get("chapter_number")
    evidence = str(item.get("evidence") or item.get("source_sentence") or "").strip()
    parts = [source]
    if chapter is not None:
        parts.append(f"第{chapter}章")
    if evidence:
        parts.append(f"证据：{evidence}")
    return " | ".join(parts)


def _render_canon_snapshot(snapshot: dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict) or not snapshot:
        return ""

    as_of = snapshot.get("as_of_chapter", "?")
    lines = [
        f"## Canon 审稿快照（截至第 {as_of} 章）",
        (
            f"- state_source={snapshot.get('state_source', 'unknown')}；"
            f"historical_rewrite={bool(snapshot.get('historical_rewrite'))}；"
            f"bounded_state_available={bool(snapshot.get('bounded_state_available'))}"
        ),
    ]
    if snapshot.get("historical_rewrite") and not snapshot.get("bounded_state_available"):
        lines.append(
            "- 警告：目标是历史章节，但没有可用的章前状态快照。"
            "不得用当前项目状态倒推历史事实；缺证据的项目一律视为未核验。"
        )

    facts = snapshot.get("facts") or []
    if facts:
        lines.append("### 已确认事实")
        for index, fact in enumerate(facts):
            if not isinstance(fact, dict):
                continue
            subject = str(fact.get("subject") or "全局")
            field = str(fact.get("field") or "fact")
            label = _evidence_label(fact, fallback=f"canon.fact:{index}")
            lines.append(
                f"- [{label}] {subject} · {field}：{_json_inline(fact.get('value'))}"
            )

    rules = snapshot.get("world_rules") or []
    if rules:
        lines.append("### 世界规则")
        for index, rule in enumerate(rules):
            lines.append(f"- [canon.world_rule:{index}] {rule}")

    characters = snapshot.get("characters") or []
    if characters:
        lines.append("### 人物章前状态")
        for card in characters:
            if not isinstance(card, dict):
                continue
            lines.append(
                f"- [canon.character:{card.get('name', '未命名')}] "
                f"{card.get('name', '未命名')}：{_json_inline(card)}"
            )

    entities = snapshot.get("entities") or []
    if entities:
        lines.append("### Canon 实体")
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            lines.append(
                f"- [canon.entity:{entity.get('entity_id', '')}] "
                f"{entity.get('kind', '')}/{entity.get('name', '')}："
                f"{_json_inline(entity.get('attributes') or {})}"
            )

    relationships = snapshot.get("relationships") or []
    if relationships:
        lines.append("### 已确认关系")
        for index, edge in enumerate(relationships):
            if not isinstance(edge, dict):
                continue
            label = _evidence_label(edge, fallback=f"canon.relationship:{index}")
            lines.append(
                f"- [{label}] {edge.get('subject_name', edge.get('subject_id', '?'))} "
                f"--{edge.get('predicate', '?')}/{edge.get('polarity', '?')}--> "
                f"{edge.get('object_name', edge.get('object_id', '?'))}"
            )

    timeline = snapshot.get("timeline") or []
    if timeline:
        lines.append("### 已确认时间线")
        for index, marker in enumerate(timeline):
            if not isinstance(marker, dict):
                continue
            label = _evidence_label(marker, fallback=f"canon.timeline:{index}")
            lines.append(f"- [{label}] {marker.get('marker', '')}")

    foreshadowing = snapshot.get("foreshadowing") or []
    if foreshadowing:
        lines.append("### 伏笔状态")
        for index, item in enumerate(foreshadowing):
            if isinstance(item, dict):
                label = _evidence_label(item, fallback=f"canon.foreshadowing:{index}")
                lines.append(f"- [{label}] {_json_inline(item)}")

    return "\n".join(lines)


def build_consistency_prompt(
    body: str,
    director_artifact: DirectorArtifact,
    active_facts: list[dict[str, Any]],
    *,
    character_states: list[dict[str, Any]] | None = None,
    canon_snapshot: dict[str, Any] | None = None,
) -> str:
    """Render the focused consistency prompt.

    The prompt names the chapters facts to check (director
    artifact, active continuity facts, current character state
    so the model can see the protagonist's equipment, level,
    quest progress, etc.) and asks for structured findings
    only. It explicitly tells the model not to grade style or
    recommend prose improvements — those go through the
    soft-review path.
    """
    beats = "\n".join(
        f"- 顺序{beat.order} · 地点：{beat.location} · 动作：{beat.action} · 结果：{beat.result}"
        for beat in director_artifact.scene_beats
    )
    facts = "\n".join(
        f"- {fact.get('subject', '?')} · {fact.get('field', '?')}：{fact.get('value', '?')}"
        for fact in active_facts
    )
    state_lines: list[str] = []
    for card in character_states or []:
        name = card.get("name", "未命名")
        current = _current_character_state(card)
        if current:
            import json

            state_lines.append(
                f"- {name}：{json.dumps(current, ensure_ascii=False, separators=(',', ':'))}"
            )
    character_state_section = (
        f"## 角色当前状态\n" + "\n".join(state_lines) if state_lines else ""
    )
    canon_snapshot_section = _render_canon_snapshot(canon_snapshot)
    return (
        "你是小说事实一致性 agent。\n"
        "只判断正文是否与既定事实矛盾。导演计划用于理解本章意图，不是已经发生的事实。\n"
        "正文调整导演动作、过程、地点细节或收尾镜头，不算事实冲突；确需指出时使用 "
        "code=plan.deviation、blocking=false、source=director_plan。不要评价文笔、风格、对话自然度。\n"
        "blocking=true 只允许用于与 Canon 审稿快照中可核验事实的直接矛盾。"
        "source 必须指向快照中存在的具体来源；也可用 evidence 原样引用快照证据。"
        "缺少历史快照时不得用当前状态猜测旧章事实；无法精确对应时必须 blocking=false。\n"
        "如果出现矛盾,返回 code / message / blocking / source 四个字段的 JSON 列表，"
        "必要时附带 evidence 字段。\n"
        "如果没有矛盾,返回空列表 []。\n\n"
        f"## 章节目标\n{director_artifact.chapter_goal}\n\n"
        f"## 场景节拍\n{beats}\n\n"
        f"## 收尾状态\n{director_artifact.ending_state}\n\n"
        f"## 既定事实\n{facts or '（无）'}\n\n"
        + (f"{character_state_section}\n\n" if character_state_section else "")
        + (f"{canon_snapshot_section}\n\n" if canon_snapshot_section else "")
        + f"## 正文\n{body}\n\n"
        "只检查：人物身份、位置、职业、等级、属性、装备、库存、任务、已知信息和已确认时间线。"
        "不要评价文笔、节奏、对话、修辞或爽点。"
    )


_STYLE_CODES: set[str] = {
    "style.report_voice",
    "style.ai_tone",
    "style.abstract",
    "dialogue.unnatural",
    "exposition.too_dense",
}


def _downgrade_non_factual(
    code: str,
    source: str,
    blocking: bool,
    *,
    canon_snapshot: dict[str, Any] | None = None,
    canon_evidence: str | None = None,
    require_canon_evidence: bool = False,
) -> bool:
    """Only established-fact contradictions may block confirmation.

    The director artifact is an executable writing plan, not committed canon.
    A draft may realise a beat with a different action or move the final camera
    position without creating a continuity error. Keep those findings visible,
    but do not let them masquerade as factual contradictions. Review runtime
    failures likewise mean "unverified", never "canon contradicted".
    """
    normalized_code = code.strip().lower()
    if normalized_code in {"consistency.unavailable", "consistency.invalid_response"}:
        return False
    if (
        code in _STYLE_CODES
        or normalized_code.startswith("style.")
        or normalized_code.startswith("dialogue.")
        or normalized_code.startswith("exposition.")
    ):
        return False
    normalized_source = source.strip().lower()
    if normalized_source.startswith("顺序") or normalized_source in {
        "收尾状态",
        "场景节拍",
        "导演计划",
        "director",
        "director_plan",
    }:
        return False

    # The focused model boundary is allowed to block only when it can point
    # back to the current chapter-bounded Canon projection. Keep deterministic
    # non-model gates backward compatible; their source names are explicit.
    if require_canon_evidence and normalized_source not in {
        "deterministic",
        "rewrite_guidance",
        "writer",
    }:
        return _has_verified_canon_evidence(
            source=source,
            canon_evidence=canon_evidence,
            canon_snapshot=canon_snapshot,
        )
    return blocking


@dataclass
class ConsistencyFinding:
    """One consistency finding surfaced by the focused review boundary.

    Only established-fact contradictions are allowed to stay blocking. Style,
    dialogue, exposition and director-plan deviations are automatically kept
    advisory even if a caller accidentally constructs them with
    ``blocking=True``. This also protects deterministic pipeline findings that
    bypass the model-response adapter.
    """

    code: str
    message: str
    source: str = "consistency"
    blocking: bool = True

    def __post_init__(self) -> None:
        self.blocking = _downgrade_non_factual(self.code, self.source, self.blocking)


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
        character_states: list[dict[str, Any]] | None = None,
        canon_snapshot: dict[str, Any] | None = None,
    ) -> list[ConsistencyFinding]:
        prompt = build_consistency_prompt(
            body,
            director_artifact,
            active_facts,
            character_states=character_states,
            canon_snapshot=canon_snapshot,
        )
        request = _ModelRequest(
            prompt=prompt,
            stage="consistency",
            metadata={
                "chapter_number": director_artifact.chapter_number,
                "agent": "consistency",
                "schema_version": director_artifact.schema_version,
                "canon_snapshot_schema": str(
                    (canon_snapshot or {}).get("schema_version") or ""
                ),
                "canon_as_of_chapter": (canon_snapshot or {}).get("as_of_chapter"),
            },
        )
        # Runtime/model availability is not a fact about the manuscript. Surface
        # verification failures so the caller can mark the review as degraded,
        # but never treat them as proof of a canon contradiction.
        try:
            response = self._runtime.complete(request)
        except Exception as exc:  # noqa: BLE001 — public boundary
            return [
                ConsistencyFinding(
                    code="consistency.unavailable",
                    message=f"事实审稿未完成：{type(exc).__name__}: {exc}",
                    source="consistency",
                    blocking=False,
                )
            ]
        if getattr(response, "ok", True) is False:
            error = str(getattr(response, "error", "") or "model_call_failed")
            return [
                ConsistencyFinding(
                    code="consistency.unavailable",
                    message=f"事实审稿未完成：{error}",
                    source="consistency",
                    blocking=False,
                )
            ]
        payload = _extract_payload(response)
        issues = payload.get("issues") if isinstance(payload, dict) else None
        if not isinstance(issues, list):
            return [
                ConsistencyFinding(
                    code="consistency.invalid_response",
                    message="事实审稿未返回结构化 issues 列表；本次仅标记为未完成核验。",
                    source="consistency",
                    blocking=False,
                )
            ]
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
            source = str(issue.get("source") or "consistency")
            canon_evidence_raw = (
                issue.get("canon_evidence")
                or issue.get("evidence")
                or issue.get("source_sentence")
            )
            canon_evidence = (
                str(canon_evidence_raw).strip()
                if canon_evidence_raw is not None
                else None
            )
            # Canon evidence is a boundary for model output only. Deterministic
            # contract gates are constructed outside this adapter and must keep
            # their own hard/soft disposition (for example hook landing).
            blocking = _downgrade_non_factual(
                code,
                source,
                blocking,
                canon_snapshot=canon_snapshot,
                canon_evidence=canon_evidence,
                require_canon_evidence=True,
            )
            findings.append(
                ConsistencyFinding(
                    code=code,
                    message=message,
                    source=source,
                    blocking=blocking,
                )
            )
        return findings


def focused_consistency_review(
    body: str,
    *,
    director_artifact: DirectorArtifact,
    active_facts: list[dict[str, Any]],
    runtime: ConsistencyRuntime,
    character_states: list[dict[str, Any]] | None = None,
    canon_snapshot: dict[str, Any] | None = None,
) -> list[ConsistencyFinding]:
    """Convenience entry point for the orchestrator's confirmation path."""
    agent = FocusedConsistencyAgent(runtime=runtime)
    return agent.review(
        body=body,
        director_artifact=director_artifact,
        active_facts=active_facts,
        character_states=character_states,
        canon_snapshot=canon_snapshot,
    )


__all__ = [
    "ConsistencyRuntime",
    "ConsistencyFinding",
    "FocusedConsistencyAgent",
    "build_consistency_prompt",
    "focused_consistency_review",
]
