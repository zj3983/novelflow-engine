"""Runtime model provider settings API.

This router owns the public runtime-config/v2 contract.  Story routes should not
need to know how provider accounts, protocol adapters, or connection probes work.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.codex_cli_provider import (
    codex_cli_update_status,
    read_codex_cli_models,
    read_codex_cli_version,
    read_latest_codex_cli_version,
)
from packages.story_core.model_gateway.contracts import ModelRequest
from packages.story_core.model_gateway.model_discovery import discover_provider_models
from packages.story_core.model_gateway.provider_catalog import (
    BUILTIN_PROVIDER_IDS,
    provider_definition,
)
from packages.story_core.model_gateway.runtime_gateway import RuntimeModelGateway
from packages.story_core.models import NewCharacterPolicy
from packages.story_core.runtime_config import (
    RuntimeConfiguration,
    RuntimeStage,
    StageRuntimeSettings,
    get_runtime_configuration,
    set_runtime_configuration,
)


router = APIRouter()
_MASKED_API_KEY = "********"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeSettingsTestRequest(_StrictModel):
    stage: RuntimeStage
    runtime_settings: RuntimeConfiguration


class RuntimeSettingsTestResponse(_StrictModel):
    ok: bool
    provider: str
    stage: RuntimeStage
    model: str
    protocol: str
    diagnosis: str = ""
    message: str


class RuntimeApiKeyRevealRequest(_StrictModel):
    provider_id: str


class RuntimeApiKeyRevealResponse(_StrictModel):
    api_key: str


class RuntimeModelDiscoveryRequest(_StrictModel):
    provider_id: str
    runtime_settings: RuntimeConfiguration


class RuntimeDiscoveredModel(_StrictModel):
    model_id: str
    compatibility: Literal["supported", "unsupported", "unknown"]
    endpoint: str
    reason: str


class RuntimeModelDiscoveryResponse(_StrictModel):
    provider: str
    protocol: str
    models: list[RuntimeDiscoveredModel]


class RuntimeStrategyResponse(_StrictModel):
    mode: str = "LLM-assisted"
    temperature: float = 0.7
    new_character_policy: NewCharacterPolicy = "Director review"


class RuntimeStrategyRequest(RuntimeStrategyResponse):
    mode: Literal["LLM-assisted"] = "LLM-assisted"


class CodexCLIInfoResponse(_StrictModel):
    available: bool
    command: str
    version: str
    models: list[str] = Field(default_factory=list)
    latest_version: str = ""
    update_status: Literal["current", "available", "unknown"] = "unknown"


def _serialize_runtime_settings(
    configuration: RuntimeConfiguration | None = None,
) -> dict[str, object]:
    data = (configuration or get_runtime_configuration()).model_dump(mode="json")
    for account in data["accounts"].values():
        if account.get("api_key"):
            account["api_key"] = _MASKED_API_KEY
    if data["image"].get("api_key"):
        data["image"]["api_key"] = _MASKED_API_KEY
    return data


def _restore_masked_api_keys(configuration: RuntimeConfiguration) -> RuntimeConfiguration:
    restored = configuration.model_copy(deep=True)
    stored = get_runtime_configuration()
    for provider_id, account in restored.accounts.items():
        if account.api_key == _MASKED_API_KEY:
            stored_account = stored.accounts.get(provider_id)
            account.api_key = stored_account.api_key if stored_account else ""
    if restored.image.api_key == _MASKED_API_KEY:
        restored.image.api_key = stored.image.api_key
    return restored


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except (AttributeError, ValueError):
        return False


def _validated_provider_account(
    configuration: RuntimeConfiguration,
    provider_id: str,
):
    try:
        definition = provider_definition(provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="unknown_provider") from exc
    account = configuration.accounts.get(provider_id)
    if account is None:
        raise HTTPException(status_code=422, detail="provider_account_missing")
    if definition.requires_api_key and not account.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key_required")
    if not definition.protocol.endswith("_cli") and not _valid_http_url(account.base_url):
        raise HTTPException(status_code=422, detail="invalid_base_url")
    return definition, account


def _validate_selected_accounts(configuration: RuntimeConfiguration) -> None:
    unknown_accounts = set(configuration.accounts) - set(BUILTIN_PROVIDER_IDS)
    if unknown_accounts:
        raise HTTPException(status_code=422, detail="unknown_provider")
    for stage in ("planner", "writer"):
        binding = getattr(configuration.stages, stage)
        _validated_provider_account(configuration, binding.provider_id)
        if not binding.model.strip():
            raise HTTPException(status_code=422, detail="model_required")


def _resolve_candidate_stage_runtime(
    configuration: RuntimeConfiguration,
    stage: RuntimeStage,
) -> StageRuntimeSettings:
    binding = getattr(configuration.stages, stage)
    definition, account = _validated_provider_account(configuration, binding.provider_id)
    return StageRuntimeSettings(
        provider_id=binding.provider_id,
        protocol=definition.protocol,
        model=binding.model,
        api_key=account.api_key,
        base_url=account.base_url.rstrip("/"),
        codex_command=account.codex_command,
        temperature=configuration.temperature,
        new_character_policy=configuration.new_character_policy,
    )


def _resolve_candidate_provider_runtime(
    configuration: RuntimeConfiguration,
    provider_id: str,
) -> StageRuntimeSettings:
    definition, account = _validated_provider_account(configuration, provider_id)
    model = next(
        iter(account.custom_models or definition.planner_models or definition.writer_models),
        "model-discovery",
    )
    return StageRuntimeSettings(
        provider_id=provider_id,
        protocol=definition.protocol,
        model=model,
        api_key=account.api_key,
        base_url=account.base_url.rstrip("/"),
        codex_command=account.codex_command,
        temperature=configuration.temperature,
        new_character_policy=configuration.new_character_policy,
    )


_CONNECTION_DIAGNOSES = {
    "authentication_failed": (
        "authentication_failed",
        "API 密钥无效或没有访问权限",
    ),
    "missing_api_key": ("authentication_failed", "尚未配置 API 密钥"),
    "model_not_found": ("model_not_found", "模型不存在或当前账号无权使用"),
    "rate_limited": ("rate_limited", "请求受到限流，请稍后重试"),
    "request_timed_out": (
        "request_timed_out",
        "连接超时，请检查网络和 API 地址",
    ),
    "invalid_base_url": ("invalid_base_url", "API 地址格式不正确"),
    "invalid_provider_response": (
        "protocol_mismatch",
        "返回格式与所选协议不匹配",
    ),
    "unsupported_protocol": (
        "protocol_mismatch",
        "当前服务商与调用协议不匹配",
    ),
    "response_too_large": ("invalid_response", "服务返回内容过大"),
    "provider_unavailable": ("provider_unavailable", "服务暂时不可用"),
}


def _connection_diagnosis(error: str) -> tuple[str, str]:
    return _CONNECTION_DIAGNOSES.get(
        str(error or ""),
        ("unknown", "连接失败，请检查服务商配置"),
    )


@router.get("/runtime-settings/providers")
def read_runtime_providers() -> dict[str, object]:
    providers = []
    for provider_id in BUILTIN_PROVIDER_IDS:
        definition = provider_definition(provider_id)
        providers.append(
            {
                "provider_id": definition.provider_id,
                "name": definition.name,
                "protocol": definition.protocol,
                "default_base_url": definition.default_base_url,
                "planner_models": list(definition.planner_models),
                "writer_models": list(definition.writer_models),
                "requires_api_key": definition.requires_api_key,
                "base_url_editable": definition.base_url_editable,
                "help_text": definition.help_text,
            }
        )
    return {"schema_version": "provider-catalog/v1", "providers": providers}


@router.get("/runtime-settings")
def read_runtime_settings() -> dict[str, object]:
    return _serialize_runtime_settings()


@router.put("/runtime-settings")
def update_runtime_settings(payload: RuntimeConfiguration) -> dict[str, object]:
    candidate = _restore_masked_api_keys(payload)
    _validate_selected_accounts(candidate)
    return _serialize_runtime_settings(set_runtime_configuration(candidate))


@router.post("/runtime-settings/reveal-api-key")
def reveal_runtime_api_key(
    payload: RuntimeApiKeyRevealRequest,
    response: Response,
) -> RuntimeApiKeyRevealResponse:
    configuration = get_runtime_configuration()
    if payload.provider_id == "image":
        api_key = configuration.image.api_key
    else:
        try:
            provider_definition(payload.provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="provider_not_found") from exc
        account = configuration.accounts.get(payload.provider_id)
        api_key = account.api_key if account else ""
    if not api_key:
        raise HTTPException(status_code=404, detail="api_key_not_configured")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return RuntimeApiKeyRevealResponse(api_key=api_key)


@router.post("/runtime-settings/test")
def test_runtime_settings(payload: RuntimeSettingsTestRequest) -> RuntimeSettingsTestResponse:
    candidate = _restore_masked_api_keys(payload.runtime_settings)
    _validate_selected_accounts(candidate)
    runtime = _resolve_candidate_stage_runtime(candidate, payload.stage)
    request = ModelRequest(
        prompt="只回复 pong。",
        provider=runtime.provider_id,
        model=runtime.model,
        operation="runtime_connection_test",
        max_tokens=256,
        timeout_seconds=30,
    )
    result = RuntimeModelGateway().complete_resolved(runtime, request)
    diagnosis, message = ("", "连接成功") if result.ok else _connection_diagnosis(result.error)
    return RuntimeSettingsTestResponse(
        ok=result.ok,
        provider=runtime.provider_id,
        stage=payload.stage,
        model=runtime.model,
        protocol=runtime.protocol,
        diagnosis=diagnosis,
        message=message,
    )


@router.post(
    "/runtime-settings/discover-models",
    response_model=RuntimeModelDiscoveryResponse,
)
def discover_runtime_models(
    payload: RuntimeModelDiscoveryRequest,
) -> RuntimeModelDiscoveryResponse:
    candidate = _restore_masked_api_keys(payload.runtime_settings)
    runtime = _resolve_candidate_provider_runtime(candidate, payload.provider_id)
    try:
        models = discover_provider_models(runtime)
    except Exception as exc:
        error = getattr(exc, "code", "") or type(exc).__name__
        raise HTTPException(status_code=502, detail=f"model_discovery_failed:{error}") from exc
    return RuntimeModelDiscoveryResponse(
        provider=runtime.provider_id,
        protocol=runtime.protocol,
        models=[RuntimeDiscoveredModel(**item) for item in models],
    )


@router.get("/runtime-settings/cli-info")
def read_runtime_cli_info() -> CodexCLIInfoResponse:
    account = get_runtime_configuration().accounts.get("codexcli")
    command = (account.codex_command if account else "") or "codex"
    models = read_codex_cli_models()
    try:
        version = read_codex_cli_version(command)
    except Exception:
        return CodexCLIInfoResponse(available=False, command=command, version="", models=models)
    try:
        latest_version = read_latest_codex_cli_version()
        update_status = codex_cli_update_status(version, latest_version)
    except Exception:
        latest_version = ""
        update_status = "unknown"
    return CodexCLIInfoResponse(
        available=True,
        command=command,
        version=version,
        models=models,
        latest_version=latest_version,
        update_status=update_status,
    )


@router.get("/runtime-strategy")
def read_runtime_strategy() -> dict[str, object]:
    configuration = get_runtime_configuration()
    return RuntimeStrategyResponse(
        temperature=configuration.temperature,
        new_character_policy=configuration.new_character_policy,
    ).model_dump(mode="json")


@router.put("/runtime-strategy")
def update_runtime_strategy(payload: RuntimeStrategyRequest) -> dict[str, object]:
    candidate = get_runtime_configuration()
    candidate.temperature = payload.temperature
    candidate.new_character_policy = payload.new_character_policy
    saved = set_runtime_configuration(candidate)
    return RuntimeStrategyResponse(
        mode=payload.mode,
        temperature=saved.temperature,
        new_character_policy=saved.new_character_policy,
    ).model_dump(mode="json")


def init_runtime_settings_routes() -> APIRouter:
    return router
