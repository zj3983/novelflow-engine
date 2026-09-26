"""Author-facing model readiness, separate from machine capability contracts."""
from datetime import datetime, timedelta, timezone
import hashlib

from .capabilities import CapabilityProvenance, CapabilityRecord, ModelCapabilityResolver, _timestamp_is_expired
from .capability_refresh import refresh_capabilities
from .contracts import ModelRequest
from .runtime_gateway import RuntimeModelGateway


def usability_view(status="untested", *, stage="planner"):
    presentations = {
        "ready": ("模型已连接", "模型连接正常。可以发起创作；具体内容能否完成会在开始时检查。", "success", True),
        "untested": ("尚未检测", "当前模型还没有有效的检测结果，请先测试模型。", "neutral", False),
        "connection_error": ("连接未成功", "暂时无法使用当前模型。请检查密钥和连接地址，也可以稍后重新检测。", "warning", False),
        "blocked": ("需要完善设置", "请补全当前模型的连接设置，再测试模型。", "warning", False),
    }
    heading, message, tone, can_continue = presentations[status]
    actions = [{"id": "test", "label": "重新检测" if status != "untested" else "测试模型"}]
    if status in {"blocked", "connection_error"}:
        actions += [{"id": "edit_connection", "label": "检查连接设置"}, {"id": "choose_model", "label": "更换模型"}]
    return {"status": status, "heading": heading, "message": message, "tone": tone, "can_continue": can_continue, "actions": actions}


def read_model_usability(runtime, *, resolver=None, stage="planner"):
    """Report connection readiness; task suitability stays with execution preflight."""
    resolver = resolver or ModelCapabilityResolver()
    # User capability declarations cannot prove a working connection.
    identity = resolver.identity(runtime.provider_id, runtime.base_url, runtime.model, runtime.protocol)
    cached = resolver.store.get_profile(identity)
    record = cached.verified_capabilities.get("text_generation") if cached else None
    status = "untested"
    fingerprint = _connection_fingerprint(runtime)
    if record and record.provenance.source == "runtime_observation" and record.provenance.note.endswith(":" + fingerprint) and not _timestamp_is_expired(record.provenance.expires_at):
        if record.state == "supported":
            status = "ready"
        elif record.provenance.note.startswith("connection_test_failed:"):
            status = "connection_error"
    return usability_view(status, stage=stage)


def _connection_fingerprint(runtime):
    return hashlib.sha256((runtime.api_key + "\0" + runtime.codex_command + "\0" + runtime.base_url).encode()).hexdigest()


def test_model_usability(runtime, *, resolver=None, refresh=None, gateway=None, stage="planner"):
    resolver = resolver or ModelCapabilityResolver()
    if runtime.protocol.endswith("_cli"):
        # An explicit connection test is permitted for CLI; no hard output cap
        # is claimed, and no capability stress probe is attempted.
        response = (gateway or RuntimeModelGateway(capability_resolver=resolver)).complete_resolved(runtime, ModelRequest(
            prompt="Reply OK.", provider=runtime.provider_id, model=runtime.model,
            operation="model_usability_test", max_tokens=64, timeout_seconds=20,
            metadata={"max_retries": 1, "max_response_bytes": 16384},
        ))
        connected = response.ok
    else:
        result = (refresh or refresh_capabilities)(runtime, resolver=resolver)
        connected = any(step["step"] == "connectivity" and step["status"] == "success" for step in result["steps"])
    identity = resolver.identity(runtime.provider_id, runtime.base_url, runtime.model, runtime.protocol)
    resolver.store.record_runtime_observation(identity, "text_generation", CapabilityRecord(
        "supported" if connected else "unknown",
        provenance=CapabilityProvenance.for_source(
            "runtime_observation", expires_at=(datetime.now(timezone.utc) + timedelta(hours=24 if connected else 1)).isoformat(),
            note=("connection_test_succeeded:" if connected else "connection_test_failed:") + _connection_fingerprint(runtime),
        ),
    ))
    return read_model_usability(runtime, resolver=resolver, stage=stage)
