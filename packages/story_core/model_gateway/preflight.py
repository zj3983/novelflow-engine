"""Request-level model capability and token-budget preflight.

The report intentionally contains counts and safe model identity only. It never
contains prompt text, credentials, or a raw provider URL.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import math
from typing import Any, Mapping

from .capabilities import (
    KNOWN_CAPABILITIES,
    KNOWN_LIMITS,
    ContextPreflightResult,
    ModelProfile,
    preflight_context,
    safe_base_url_for_diagnostics,
)
from .contracts import ModelRequest


TOKEN_ESTIMATE_METHOD = "utf8_bytes_div3_v1"
SAFETY_MARGIN_RATIO = 0.15
SAFETY_MARGIN_MIN_TOKENS = 128
UNKNOWN_INPUT_GUARD_TOKENS = 32_768
UNKNOWN_CONTEXT_GUARD_TOKENS = 32_768
UNKNOWN_OUTPUT_GUARD_TOKENS = 16_384
DEFAULT_OUTPUT_RESERVATION_TOKENS = 4_096


@dataclass(frozen=True)
class ModelPreflightPlan:
    request: ModelRequest
    report: Mapping[str, Any]

    @property
    def ready(self) -> bool:
        status = self.report.get("status")
        return status == "READY" or (
            status == "COMPACT" and self.report.get("recheck_status") == "READY"
        )


class ModelPreflightBlockedError(RuntimeError):
    """A required model call was stopped before its provider adapter ran."""

    def __init__(self, report: Mapping[str, Any]) -> None:
        self.report = dict(report)
        status = str(self.report.get("status") or "BLOCKED")
        reason = str(self.report.get("reason") or "model_preflight_blocked")
        super().__init__(f"model_preflight_{status.lower()}:{reason}")


def _positive_limit(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _record(profile: ModelProfile, name: str):
    return profile.effective_capability(name)


def _expired(expires_at: str | None, *, now: str) -> bool:
    if not expires_at:
        return False
    try:
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry <= current
    except ValueError:
        return True


def _record_summary(record: Any, *, now: str) -> dict[str, Any]:
    provenance = record.provenance
    return {
        "state": record.state,
        "source": provenance.source,
        "verification_status": provenance.verification_status,
        "verified_at": provenance.verified_at,
        "expires_at": provenance.expires_at,
        "expired": _expired(provenance.expires_at, now=now),
        "value": record.value if record.state == "supported" else None,
    }


def _estimate_message(message: Mapping[str, Any]) -> tuple[int, int]:
    try:
        encoded = json.dumps(
            dict(message), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError):
        encoded = str(message).encode("utf-8", errors="replace")
    # Byte-based estimation is deliberately conservative for Chinese text and
    # remains a heuristic; it is not a tokenizer result.
    return math.ceil(len(encoded) / 3), len(encoded)


def _input_estimates(request: ModelRequest) -> tuple[int, int, int, int, tuple[str, ...]]:
    messages = request.normalized_messages()
    optional_indexes = tuple(request.optional_input_messages or ())
    if any(isinstance(index, bool) or not isinstance(index, int) for index in optional_indexes):
        return 0, 0, 0, 0, ("optional_input_index_invalid",)
    if len(set(optional_indexes)) != len(optional_indexes):
        return 0, 0, 0, 0, ("optional_input_index_duplicate",)
    if any(index < 0 or index >= len(request.messages) for index in optional_indexes):
        return 0, 0, 0, 0, ("optional_input_index_out_of_range",)

    system_offset = 1 if request.system_prompt.strip() else 0
    optional_normalized_indexes = {index + system_offset for index in optional_indexes}
    required_tokens = optional_tokens = required_bytes = optional_bytes = 0
    for index, message in enumerate(messages):
        estimated, byte_count = _estimate_message(message)
        if index in optional_normalized_indexes:
            optional_tokens += estimated
            optional_bytes += byte_count
        else:
            required_tokens += estimated
            required_bytes += byte_count
    return required_tokens, optional_tokens, required_bytes, optional_bytes, ()


def _compact_optional_messages(request: ModelRequest) -> ModelRequest:
    optional = set(request.optional_input_messages)
    return replace(
        request,
        messages=tuple(
            message for index, message in enumerate(request.messages) if index not in optional
        ),
        optional_input_messages=(),
    )


def _required_capabilities(request: ModelRequest) -> tuple[str, ...]:
    raw = request.metadata.get("required_capabilities", ())
    values = [str(item).strip() for item in raw] if isinstance(raw, (list, tuple, set)) else []
    if request.json_mode:
        values.append("json_mode")
    return tuple(dict.fromkeys(item for item in values if item))


def _output_enforcement(protocol: str) -> dict[str, str]:
    """Describe the adapter boundary that enforces the planned output cap."""

    methods = {
        "openai_compatible": "max_tokens_request_field",
        "anthropic": "max_tokens_request_field",
        "gemini": "generation_config_max_output_tokens",
    }
    if protocol in methods:
        return {
            "state": "supported",
            "source": "repository_adapter_contract",
            "method": methods[protocol],
        }
    if protocol in {"codex_cli", "antigravity_cli"}:
        return {
            "state": "unsupported",
            "source": "repository_adapter_contract",
            "method": "cli_has_no_per_request_output_limit",
        }
    return {"state": "unknown", "source": "unknown", "method": "unknown"}


def _context_result(
    request: ModelRequest,
    profile: ModelProfile,
    *,
    allow_split: bool,
    now: str,
) -> tuple[ContextPreflightResult, dict[str, int | None], dict[str, int | None], tuple[str, ...]]:
    required, optional, required_bytes, optional_bytes, input_errors = _input_estimates(request)
    output_limit = _positive_limit(_record(profile, "max_output_tokens").value) if (
        _record(profile, "max_output_tokens").state == "supported"
    ) else None
    context_limit = _positive_limit(_record(profile, "context_window").value) if (
        _record(profile, "context_window").state == "supported"
    ) else None
    input_limit = _positive_limit(_record(profile, "input_token_limit").value) if (
        _record(profile, "input_token_limit").state == "supported"
    ) else None

    requested_output = request.max_tokens
    if requested_output is None:
        reserved_output = min(
            DEFAULT_OUTPUT_RESERVATION_TOKENS,
            output_limit or UNKNOWN_OUTPUT_GUARD_TOKENS,
        )
    else:
        reserved_output = int(requested_output)
    safety_margin = max(
        SAFETY_MARGIN_MIN_TOKENS,
        math.ceil((required + optional) * SAFETY_MARGIN_RATIO),
    )

    effective_input_limit = input_limit or UNKNOWN_INPUT_GUARD_TOKENS
    effective_context_limit = context_limit or UNKNOWN_CONTEXT_GUARD_TOKENS
    effective_output_limit = output_limit or UNKNOWN_OUTPUT_GUARD_TOKENS
    result = preflight_context(
        estimated_required_input=required,
        estimated_optional_input=optional,
        reserved_output=reserved_output,
        safety_margin=safety_margin,
        input_limit=effective_input_limit,
        context_limit=effective_context_limit,
        max_output_limit=effective_output_limit,
        allow_split=allow_split,
    )
    effective_limits = {
        "input_token_limit": input_limit,
        "context_window": context_limit,
        "max_output_tokens": output_limit,
        "input_guard": None if input_limit is not None else UNKNOWN_INPUT_GUARD_TOKENS,
        "context_guard": None if context_limit is not None else UNKNOWN_CONTEXT_GUARD_TOKENS,
        "output_guard": None if output_limit is not None else UNKNOWN_OUTPUT_GUARD_TOKENS,
    }
    estimates = {
        "required_input_tokens": required,
        "optional_input_tokens": optional,
        "reserved_output_tokens": reserved_output,
        "safety_margin_tokens": safety_margin,
        "estimated_input_bytes_required": required_bytes,
        "estimated_input_bytes_optional": optional_bytes,
    }
    return result, effective_limits, estimates, input_errors


def preflight_request(
    profile: ModelProfile,
    request: ModelRequest,
    *,
    allow_split: bool = False,
    now: str | None = None,
) -> ModelPreflightPlan:
    """Return a safe, explainable plan for the exact provider request."""

    now = now or datetime.now(timezone.utc).isoformat()
    identity = profile.identity
    required = _required_capabilities(request)
    output_enforcement = _output_enforcement(profile.identity.protocol)
    capability_names = set(KNOWN_CAPABILITIES)
    capability_names.update(required)
    if request.temperature is not None:
        capability_names.add("temperature")
    if request.metadata.get("stream"):
        capability_names.add("streaming")
    capability_report = {
        name: _record_summary(_record(profile, name), now=now)
        for name in sorted(capability_names)
    }
    limit_report = {
        name: _record_summary(_record(profile, name), now=now)
        for name in KNOWN_LIMITS
    }

    effective = request
    adjustments: list[dict[str, str]] = []
    temp = _record(profile, "temperature")
    if effective.temperature is not None and temp.state == "unsupported":
        effective = replace(effective, temperature=None)
        adjustments.append({
            "parameter": "temperature",
            "action": "omitted",
            "reason": "known_unsupported",
        })
    metadata = dict(effective.metadata)
    if metadata.get("stream"):
        streaming = _record(profile, "streaming")
        if streaming.state == "unsupported":
            metadata["stream"] = False
            adjustments.append({
                "parameter": "stream",
                "action": "disabled",
                "reason": "known_unsupported",
            })
        elif streaming.state == "unknown":
            # Existing runtime behavior preserves unknown streaming settings;
            # keep that behavior visible instead of pretending it is verified.
            adjustments.append({
                "parameter": "stream",
                "action": "preserved",
                "reason": "capability_unknown_legacy_compatibility",
            })
    effective = replace(effective, metadata=metadata)

    result, effective_limits, estimates, input_errors = _context_result(
        effective, profile, allow_split=allow_split, now=now
    )
    unsupported = [
        name for name in required
        if _record(profile, name).state == "unsupported"
    ]
    unknown_required = [
        name for name in required
        if _record(profile, name).state == "unknown"
    ]
    status = result.status
    reason = result.reason
    if input_errors:
        status = "BLOCKED"
        reason = input_errors[0]
    elif unsupported:
        status = "BLOCKED"
        reason = "required_capability_unsupported"
    output_record = _record(profile, "max_output_tokens")
    output_cap = (
        _positive_limit(output_record.value)
        if output_record.state == "supported"
        else UNKNOWN_OUTPUT_GUARD_TOKENS
    )
    output_limit_exceeded = (
        request.max_tokens is not None and int(request.max_tokens) > output_cap
    )
    if not input_errors and not unsupported and output_limit_exceeded:
        status = "BLOCKED"
        reason = (
            "max_output_limit_exceeded"
            if output_record.state == "supported"
            else "requested_output_over_unknown_compatibility_guard"
        )
    elif (
        not input_errors
        and not unsupported
        and output_enforcement["state"] != "supported"
    ):
        status = "BLOCKED"
        reason = (
            "max_output_limit_not_enforceable_by_adapter"
            if output_enforcement["state"] == "unsupported"
            else "max_output_limit_enforcement_unknown"
        )

    compacted_indexes: tuple[int, ...] = ()
    recheck_status: str | None = None
    pre_compaction_estimates = dict(estimates)
    hard_blocker = bool(
        input_errors
        or unsupported
        or output_limit_exceeded
        or output_enforcement["state"] != "supported"
    )
    if (
        not hard_blocker
        and status in {"COMPACT", "SPLIT", "BLOCKED"}
        and effective.optional_input_messages
    ):
        candidate_indexes = tuple(effective.optional_input_messages)
        compacted = _compact_optional_messages(effective)
        compact_result, compact_limits, compact_estimates, compact_errors = _context_result(
            compacted, profile, allow_split=allow_split, now=now
        )
        recheck_status = compact_result.status
        if compact_result.status == "READY" and not compact_errors:
            status = "COMPACT"
            reason = "optional_context_compacted_and_rechecked"
            compacted_indexes = candidate_indexes
            effective = compacted
            effective_limits = compact_limits
            estimates = compact_estimates
            adjustments.append({
                "parameter": "optional_input_messages",
                "action": "removed_and_rechecked",
                "reason": "context_budget_compaction",
            })
        elif compact_errors:
            status = "BLOCKED"
            reason = compact_errors[0]
        elif compact_result.status == "COMPACT":
            # A second COMPACT means the declared optional messages were not
            # enough to establish a safe request. Keep the original request.
            status = "BLOCKED"
            reason = "optional_compaction_did_not_resolve_budget"
        else:
            status = compact_result.status
            reason = compact_result.reason
    elif status == "COMPACT" and not effective.optional_input_messages:
        # A required-only request cannot be compacted safely. Do not turn the
        # legacy unknown-limit state into silent truncation or provider failure.
        status = "BLOCKED"
        reason = "context_limit_unknown_or_optional_context_not_declared"

    if status in {"READY", "COMPACT"} and effective.max_tokens is None:
        default_output = int(estimates["reserved_output_tokens"] or 0)
        effective = replace(effective, max_tokens=default_output)
        adjustments.append({
            "parameter": "max_tokens",
            "action": "bounded_default",
            "reason": "unknown_output_request_bound",
        })

    if unsupported:
        repair_actions = [
            "选择明确支持所需能力的模型，或修正该 provider/model 的能力声明；任务的结构化输出要求不会被移除。"
        ]
    elif reason == "max_output_limit_not_enforceable_by_adapter":
        repair_actions = [
            "切换到能够执行 max_tokens 硬上限的协议，或升级当前 CLI adapter 以提供可验证的输出限制。"
        ]
    elif reason == "max_output_limit_enforcement_unknown":
        repair_actions = [
            "为当前协议配置经过验证的 max_tokens 执行方式；未验证前不能按预算调用模型。"
        ]
    elif status == "SPLIT":
        repair_actions = [
            "使用当前业务已有的任务拆分或分阶段入口；此模型调用边界不会自行切分或改变任务 ownership。"
        ]
    elif status == "BLOCKED":
        repair_actions = [
            "检查精确 provider、endpoint 与 requested model；配置该模型的 input_token_limit、context_window 和 max_output_tokens，或减少显式 optional 输入。必要事实、硬约束和执行契约不能裁减。"
        ]
    else:
        repair_actions = []
    unknown_limits = [
        name for name, record in limit_report.items() if record["state"] != "supported"
    ]
    report: dict[str, Any] = {
        "schema_version": "model-preflight/v1",
        "status": status,
        "recheck_status": recheck_status,
        "reason": reason,
        "provider": identity.provider_id,
        "protocol": identity.protocol,
        "normalized_base_url": safe_base_url_for_diagnostics(
            identity.normalized_base_url
        ),
        "requested_model": identity.requested_model,
        "resolved_model": identity.resolved_model,
        "capabilities": capability_report,
        "limits": limit_report,
        "effective_preflight_guards": effective_limits,
        "estimates": estimates,
        "pre_compaction_estimates": (
            pre_compaction_estimates if compacted_indexes else None
        ),
        "estimate_method": TOKEN_ESTIMATE_METHOD,
        "estimate_is_exact_tokenization": False,
        "safety_margin": {
            "method": "max(minimum, ceil(estimated_input_tokens * ratio))",
            "minimum_tokens": SAFETY_MARGIN_MIN_TOKENS,
            "ratio": SAFETY_MARGIN_RATIO,
            "applied_tokens": estimates["safety_margin_tokens"],
        },
        "unknown_capability_policy": (
            "continue_with_native_request_and_downstream_validation"
            if unknown_required else "continue_bounded_without_claiming_support"
        ),
        "unknown_required_capabilities": unknown_required,
        "unknown_limit_policy": {
            "action": "bounded_legacy_compatibility_guard",
            "unknown_limits": unknown_limits,
            "input_tokens": UNKNOWN_INPUT_GUARD_TOKENS,
            "context_tokens": UNKNOWN_CONTEXT_GUARD_TOKENS,
            "max_output_tokens": UNKNOWN_OUTPUT_GUARD_TOKENS,
        },
        "output_enforcement": output_enforcement,
        "compacted_optional_message_indexes": list(compacted_indexes),
        "adjustments": adjustments,
        "repair_actions": repair_actions,
    }
    return ModelPreflightPlan(request=effective, report=report)


__all__ = [
    "DEFAULT_OUTPUT_RESERVATION_TOKENS",
    "ModelPreflightPlan",
    "ModelPreflightBlockedError",
    "SAFETY_MARGIN_MIN_TOKENS",
    "SAFETY_MARGIN_RATIO",
    "TOKEN_ESTIMATE_METHOD",
    "UNKNOWN_CONTEXT_GUARD_TOKENS",
    "UNKNOWN_INPUT_GUARD_TOKENS",
    "UNKNOWN_OUTPUT_GUARD_TOKENS",
    "preflight_request",
]
