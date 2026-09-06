from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.story_core.env import load_environment_files
from packages.story_core.model_gateway.provider_catalog import (
    BUILTIN_PROVIDER_IDS,
    ProviderProtocol,
    provider_definition,
    provider_id_for_base_url,
)
from packages.story_core.models import AgentSettings, NewCharacterPolicy


load_environment_files()
logger = logging.getLogger(__name__)

_DPAPI_PREFIX = "dpapi:v1:"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _windows_dpapi(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("windows_dpapi_unavailable")
    source = ctypes.create_string_buffer(data)
    source_blob = _DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    result_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    flags = 0x01
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source_blob),
            "Novel Autogrowth API key",
            None,
            None,
            None,
            flags,
            ctypes.byref(result_blob),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source_blob),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(result_blob),
        )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result_blob.pbData, result_blob.cbData)
    finally:
        kernel32.LocalFree(result_blob.pbData)


def _protect_api_key(value: str) -> str:
    secret = str(value or "")
    if not secret or secret.startswith(_DPAPI_PREFIX) or os.name != "nt":
        return secret
    encrypted = _windows_dpapi(secret.encode("utf-8"), protect=True)
    return f"{_DPAPI_PREFIX}{base64.b64encode(encrypted).decode('ascii')}"


def _unprotect_api_key(value: str) -> str:
    secret = str(value or "")
    if not secret.startswith(_DPAPI_PREFIX):
        return secret
    payload = base64.b64decode(secret[len(_DPAPI_PREFIX) :], validate=True)
    return _windows_dpapi(payload, protect=False).decode("utf-8")


AgentRuntimeName = Literal["character", "director", "writer", "memory"]
AGENT_RUNTIME_NAMES: tuple[AgentRuntimeName, ...] = ("character", "director", "writer", "memory")

# Kept as a public compatibility symbol while callers move to provider IDs.
RuntimeProvider = str
RuntimeStage = Literal["planner", "writer"]
RuntimeStageInput = Literal["planner", "writer", "memory", "director", "consistency"]
RUNTIME_STAGES: tuple[RuntimeStage, ...] = ("planner", "writer")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")


class OpenAIRuntimeSettings(BaseModel):
    api_key: str = ""
    base_url: str = ""
    provider: RuntimeProvider | None = None
    codex_command: str = ""


class ProviderAccount(_StrictModel):
    api_key: str = ""
    base_url: str = ""
    custom_models: list[str] = Field(default_factory=list)
    codex_command: str = ""


class StageBinding(_StrictModel):
    provider_id: str
    model: str

    @model_validator(mode="after")
    def _model_is_not_blank(self) -> "StageBinding":
        if not self.model.strip():
            raise ValueError("stage binding model must not be blank")
        return self


class StageBindings(_StrictModel):
    planner: StageBinding
    writer: StageBinding


class ImageRuntimeConfiguration(_StrictModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    model: str = ""


def _default_codex_command() -> str:
    return os.getenv("NOVEL_CODEX_COMMAND", "codex")


def _default_antigravity_command() -> str:
    return os.getenv("NOVEL_ANTIGRAVITY_COMMAND", "agy")


def _default_accounts() -> dict[str, ProviderAccount]:
    accounts = {
        provider_id: ProviderAccount(base_url=provider_definition(provider_id).default_base_url)
        for provider_id in BUILTIN_PROVIDER_IDS
    }
    accounts["codexcli"].codex_command = _default_codex_command()
    accounts["antigravity"].codex_command = _default_antigravity_command()
    return accounts


def _default_binding(stage: RuntimeStage) -> StageBinding:
    definition = provider_definition("codexcli")
    models = definition.planner_models if stage == "planner" else definition.writer_models
    return StageBinding(provider_id="codexcli", model=models[0])


def _default_stage_bindings() -> StageBindings:
    return StageBindings(planner=_default_binding("planner"), writer=_default_binding("writer"))


class RuntimeConfiguration(_StrictModel):
    schema_version: Literal["runtime-config/v2"] = "runtime-config/v2"
    accounts: dict[str, ProviderAccount] = Field(default_factory=_default_accounts)
    stages: StageBindings = Field(default_factory=_default_stage_bindings)
    image: ImageRuntimeConfiguration = Field(default_factory=ImageRuntimeConfiguration)
    temperature: float = 0.7
    new_character_policy: NewCharacterPolicy = "Director review"

    @model_validator(mode="after")
    def _bindings_reference_catalog_accounts(self) -> "RuntimeConfiguration":
        for stage in RUNTIME_STAGES:
            binding = getattr(self.stages, stage)
            try:
                provider_definition(binding.provider_id)
            except KeyError as exc:
                raise ValueError(
                    f"{stage} provider_id {binding.provider_id!r} is not in provider catalog"
                ) from exc
            if binding.provider_id not in self.accounts:
                raise ValueError(
                    f"{stage} provider account {binding.provider_id!r} does not exist"
                )
        return self


class StageRuntimeSettings(_StrictModel):
    provider_id: str
    protocol: ProviderProtocol
    model: str
    api_key: str = ""
    base_url: str = ""
    codex_command: str = ""
    temperature: float = 0.7
    new_character_policy: NewCharacterPolicy = "Director review"

    @property
    def provider(self) -> str:
        return self.provider_id


class ImageRuntimeSettings(_StrictModel):
    api_key: str
    base_url: str
    model: str


class ImageRuntimeConfigurationError(ValueError):
    pass


LEGACY_CONFIG_FILE = Path(os.path.dirname(os.path.abspath(__file__))) / "runtime_config.json"
DEFAULT_CONFIG_FILE = Path.home() / ".novel-autogrowth-engine" / "runtime_config.json"
CONFIG_FILE = Path(os.getenv("NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH", str(DEFAULT_CONFIG_FILE)))

_lock = RLock()
_runtime_configuration = RuntimeConfiguration()
_runtime_configuration_error: str | None = None
_agent_runtime_settings: dict[str, OpenAIRuntimeSettings] = {}


def _configuration_storage_data(configuration: RuntimeConfiguration) -> dict:
    data = configuration.model_dump(mode="json")
    for account in data.get("accounts", {}).values():
        if isinstance(account, dict):
            account["api_key"] = _protect_api_key(account.get("api_key", ""))
    image = data.get("image")
    if isinstance(image, dict):
        image["api_key"] = _protect_api_key(image.get("api_key", ""))
    return data


def _configuration_runtime_data(data: dict) -> dict:
    restored = deepcopy(data)
    for collection_name in ("accounts", "providers"):
        collection = restored.get(collection_name, {})
        if isinstance(collection, dict):
            for account in collection.values():
                if isinstance(account, dict):
                    account["api_key"] = _unprotect_api_key(account.get("api_key", ""))
    agents = restored.get("compatibility", {}).get("agents", {})
    if isinstance(agents, dict):
        for agent in agents.values():
            if isinstance(agent, dict):
                agent["api_key"] = _unprotect_api_key(agent.get("api_key", ""))
    image = restored.get("image")
    if isinstance(image, dict):
        image["api_key"] = _unprotect_api_key(image.get("api_key", ""))
    return restored


def _backup_pre_provider_v2(
    path: Path,
    backup_directory: Path | None = None,
) -> Path | None:
    backup_parent = backup_directory or path.parent
    backup = backup_parent / "runtime_config.pre-provider-v2.json"
    if not path.exists() or backup.exists():
        return backup if backup.exists() else None
    backup_parent.mkdir(parents=True, exist_ok=True)
    try:
        with backup.open("xb") as handle:
            handle.write(path.read_bytes())
    except FileExistsError:
        pass
    return backup


def _atomic_write_configuration(configuration: RuntimeConfiguration, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(_configuration_storage_data(configuration), indent=2, ensure_ascii=False)
    fd, temporary_path = tempfile.mkstemp(
        dir=str(path.parent), prefix="runtime_config_", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        os.replace(temporary_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def _catalog_model(provider_id: str, stage: RuntimeStage) -> str:
    definition = provider_definition(provider_id)
    models = definition.planner_models if stage == "planner" else definition.writer_models
    return models[0] if models else "model"


def _provider_id_from_legacy(provider: object, base_url: str) -> str:
    raw = str(provider or "codexcli").strip().lower()
    if raw == "codexcli":
        return "codexcli"
    if raw in BUILTIN_PROVIDER_IDS and raw != "openai":
        return raw
    return provider_id_for_base_url(base_url) if base_url.strip() else "openai"


def _account_from_legacy(data: dict, provider_id: str) -> ProviderAccount:
    default_url = provider_definition(provider_id).default_base_url
    return ProviderAccount(
        api_key=str(data.get("api_key") or ""),
        base_url=str(data.get("base_url") or default_url),
        custom_models=[],
        codex_command=str(data.get("codex_command") or ("codex" if provider_id == "codexcli" else "")),
    )


def _legacy_model(data: dict, key: str, fallback: str) -> str:
    return str(data.get(key) or fallback).strip()


def _migrate_v1_configuration(data: dict) -> RuntimeConfiguration:
    accounts = _default_accounts()
    providers = data.get("providers") if isinstance(data.get("providers"), dict) else {}
    codex_data = providers.get("codexcli") if isinstance(providers.get("codexcli"), dict) else {}
    openai_data = providers.get("openai") if isinstance(providers.get("openai"), dict) else {}

    accounts["codexcli"] = _account_from_legacy(codex_data, "codexcli")
    api_provider_id = _provider_id_from_legacy("openai", str(openai_data.get("base_url") or ""))
    if openai_data:
        accounts[api_provider_id] = _account_from_legacy(openai_data, api_provider_id)

    selected_name = str(data.get("provider") or "codexcli").lower()
    selected_id = "codexcli" if selected_name == "codexcli" else api_provider_id
    selected_data = codex_data if selected_id == "codexcli" else openai_data
    planner_fallback = _catalog_model(selected_id, "planner")
    planner = str(selected_data.get("planner") or "").strip()
    if not planner:
        planner = str(selected_data.get("memory") or planner_fallback).strip()
    writer = _legacy_model(selected_data, "writer", _catalog_model(selected_id, "writer"))

    return RuntimeConfiguration(
        accounts=accounts,
        stages=StageBindings(
            planner=StageBinding(provider_id=selected_id, model=planner),
            writer=StageBinding(provider_id=selected_id, model=writer),
        ),
        image=data.get("image") or ImageRuntimeConfiguration(),
        temperature=data.get("temperature", 0.7),
        new_character_policy=data.get("new_character_policy", "Director review"),
    )


def _migrate_global_configuration(data: dict) -> RuntimeConfiguration:
    global_data = data.get("global") if isinstance(data.get("global"), dict) else data
    strategy = data.get("strategy") if isinstance(data.get("strategy"), dict) else data
    base_url = str(global_data.get("base_url") or "")
    provider_id = _provider_id_from_legacy(global_data.get("provider"), base_url)
    accounts = _default_accounts()
    accounts[provider_id] = _account_from_legacy(global_data, provider_id)

    planner = str(strategy.get("director_model") or "").strip()
    if not planner:
        planner = str(strategy.get("memory_model") or _catalog_model(provider_id, "planner")).strip()
    writer = _legacy_model(strategy, "writer_model", _catalog_model(provider_id, "writer"))
    configuration = RuntimeConfiguration(
        accounts=accounts,
        stages=StageBindings(
            planner=StageBinding(provider_id=provider_id, model=planner),
            writer=StageBinding(provider_id=provider_id, model=writer),
        ),
        image=data.get("image") or ImageRuntimeConfiguration(),
        temperature=strategy.get("temperature", 0.7),
        new_character_policy=strategy.get("new_character_policy", "Director review"),
    )

    legacy_agents = data.get("agents") if isinstance(data.get("agents"), dict) else {}
    for agent_name, settings in legacy_agents.items():
        if agent_name in AGENT_RUNTIME_NAMES and isinstance(settings, dict):
            _apply_agent_settings(configuration, agent_name, OpenAIRuntimeSettings.model_validate(settings))
    return configuration


def _read_runtime_configuration(path: Path) -> tuple[RuntimeConfiguration, bool]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("configuration root must be an object")
    data = _configuration_runtime_data(data)
    if data.get("schema_version") == "runtime-config/v2":
        return RuntimeConfiguration.model_validate(data), False
    if "providers" in data:
        return _migrate_v1_configuration(data), True
    return _migrate_global_configuration(data), True


def _record_main_configuration_error(path: Path, exc: Exception) -> str:
    global _runtime_configuration_error
    message = f"invalid runtime configuration at {path}: {exc}"
    with _lock:
        _runtime_configuration_error = message
    logger.error("Failed to parse runtime configuration at %s (%s)", path, type(exc).__name__)
    return message


def load_runtime_configuration(path: str | os.PathLike[str] | None = None) -> RuntimeConfiguration:
    global _runtime_configuration_error
    config_path = Path(path) if path is not None else CONFIG_FILE
    is_main = config_path == CONFIG_FILE
    try:
        configuration, _ = _read_runtime_configuration(config_path)
        if is_main:
            with _lock:
                _runtime_configuration_error = None
        return configuration
    except Exception as exc:
        message = f"invalid runtime configuration at {config_path}: {exc}"
        if is_main:
            message = _record_main_configuration_error(config_path, exc)
        raise ValueError(message) from exc


def _strip_model_display_name(value: Any) -> Any:
    if isinstance(value, str) and "\t" in value:
        return value.split("\t")[0].strip()
    return value


def _validate_runtime_configuration(
    configuration: RuntimeConfiguration | dict,
) -> RuntimeConfiguration:
    data = (
        configuration.model_dump(mode="python", warnings=False)
        if isinstance(configuration, RuntimeConfiguration)
        else dict(configuration) if isinstance(configuration, dict) else configuration
    )
    if isinstance(data, dict):
        stages = data.get("stages")
        if isinstance(stages, dict):
            for stage_name, stage_val in stages.items():
                if isinstance(stage_val, dict) and "model" in stage_val:
                    stage_val["model"] = _strip_model_display_name(stage_val["model"])
        accounts = data.get("accounts")
        if isinstance(accounts, dict):
            for acc in accounts.values():
                if isinstance(acc, dict) and isinstance(acc.get("custom_models"), list):
                    acc["custom_models"] = [_strip_model_display_name(m) for m in acc["custom_models"]]
    return RuntimeConfiguration.model_validate(data)


def _write_validated(
    configuration: RuntimeConfiguration,
    path: Path,
    *,
    backup_pre_v2: bool = False,
) -> None:
    if backup_pre_v2 and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            already_v2 = (
                isinstance(existing, dict)
                and existing.get("schema_version") == "runtime-config/v2"
            )
        except (OSError, ValueError):
            already_v2 = False
        if not already_v2:
            _backup_pre_provider_v2(path)
    _atomic_write_configuration(configuration, path)


def save_runtime_configuration(
    configuration: RuntimeConfiguration | dict,
    path: str | os.PathLike[str] | None = None,
) -> RuntimeConfiguration:
    config_path = Path(path) if path is not None else CONFIG_FILE
    with _lock:
        global _runtime_configuration_error
        validated = _validate_runtime_configuration(configuration)
        _write_validated(validated, config_path, backup_pre_v2=config_path == CONFIG_FILE)
        if config_path == CONFIG_FILE:
            _runtime_configuration_error = None
        return validated.model_copy(deep=True)


def _commit_runtime_update(update: Callable[[RuntimeConfiguration], None]) -> RuntimeConfiguration:
    with _lock:
        global _runtime_configuration, _runtime_configuration_error
        candidate = _validate_runtime_configuration(_runtime_configuration)
        update(candidate)
        validated = _validate_runtime_configuration(candidate)
        _write_validated(validated, CONFIG_FILE, backup_pre_v2=True)
        _runtime_configuration = validated
        _runtime_configuration_error = None
        return validated.model_copy(deep=True)


def get_runtime_configuration() -> RuntimeConfiguration:
    with _lock:
        return _runtime_configuration.model_copy(deep=True)


def set_runtime_configuration(configuration: RuntimeConfiguration | dict) -> RuntimeConfiguration:
    with _lock:
        global _runtime_configuration, _runtime_configuration_error
        validated = _validate_runtime_configuration(configuration)
        _write_validated(validated, CONFIG_FILE, backup_pre_v2=True)
        _runtime_configuration = validated
        _runtime_configuration_error = None
        return validated.model_copy(deep=True)


def resolve_stage_runtime(stage: RuntimeStageInput) -> StageRuntimeSettings:
    if stage not in ("planner", "writer", "memory", "director", "consistency"):
        raise ValueError(f"unknown runtime stage: {stage}")
    # The ``director`` stage reuses the ``planner`` provider binding
    # so existing configurations cover the new agent. The mapping
    # lives in the runtime config (not in the director agent) so
    # the boundary test can pin the whitelist in one place.
    resolved_stage: RuntimeStage = (
        "planner" if stage in ("memory", "director") else
        "writer" if stage == "consistency" else stage
    )
    configuration = get_runtime_configuration()
    binding = getattr(configuration.stages, resolved_stage)
    account = configuration.accounts[binding.provider_id]
    definition = provider_definition(binding.provider_id)
    return StageRuntimeSettings(
        provider_id=binding.provider_id,
        protocol=definition.protocol,
        model=_strip_model_display_name(binding.model),
        api_key=account.api_key,
        base_url=account.base_url.rstrip("/"),
        codex_command=account.codex_command,
        temperature=configuration.temperature,
        new_character_policy=configuration.new_character_policy,
    )


def resolve_image_runtime() -> ImageRuntimeSettings:
    image = get_runtime_configuration().image
    api_key = image.api_key.strip()
    base_url = image.base_url.strip().rstrip("/")
    model = image.model.strip()
    if not image.enabled or not api_key or not base_url or not model:
        raise ImageRuntimeConfigurationError("image_runtime_not_configured")
    return ImageRuntimeSettings(api_key=api_key, base_url=base_url, model=model)


def _load_config_from_file() -> None:
    with _lock:
        global _runtime_configuration, _runtime_configuration_error
        if CONFIG_FILE.exists():
            try:
                configuration, migrated = _read_runtime_configuration(CONFIG_FILE)
                validated = _validate_runtime_configuration(configuration)
                if migrated:
                    _write_validated(validated, CONFIG_FILE, backup_pre_v2=True)
                _runtime_configuration = validated
                _runtime_configuration_error = None
            except Exception as exc:
                _record_main_configuration_error(CONFIG_FILE, exc)
            return
        if LEGACY_CONFIG_FILE.exists():
            try:
                configuration, _ = _read_runtime_configuration(LEGACY_CONFIG_FILE)
                validated = _validate_runtime_configuration(configuration)
                _backup_pre_provider_v2(LEGACY_CONFIG_FILE, CONFIG_FILE.parent)
                _write_validated(validated, CONFIG_FILE, backup_pre_v2=True)
                _runtime_configuration = validated
                _runtime_configuration_error = None
            except Exception as exc:
                _runtime_configuration_error = f"invalid runtime configuration at {LEGACY_CONFIG_FILE}: {exc}"


def get_runtime_configuration_error() -> str | None:
    with _lock:
        return _runtime_configuration_error


def _stage_for_agent(agent_name: AgentRuntimeName | None) -> RuntimeStage:
    return "writer" if agent_name == "writer" else "planner"


def _settings_for_stage(configuration: RuntimeConfiguration, stage: RuntimeStage) -> OpenAIRuntimeSettings:
    binding = getattr(configuration.stages, stage)
    account = configuration.accounts[binding.provider_id]
    return OpenAIRuntimeSettings(
        api_key=account.api_key,
        base_url=account.base_url,
        provider=binding.provider_id,
        codex_command=account.codex_command,
    )


def get_runtime_settings() -> OpenAIRuntimeSettings:
    with _lock:
        return _settings_for_stage(_runtime_configuration, "planner")


def _settings_provider_id(settings: OpenAIRuntimeSettings) -> str:
    provider = str(settings.provider or "").strip().lower()
    if provider == "codexcli":
        return "codexcli"
    if provider in BUILTIN_PROVIDER_IDS and provider != "openai":
        return provider
    if settings.base_url.strip():
        return provider_id_for_base_url(settings.base_url)
    return "openai"


def _apply_connection(
    configuration: RuntimeConfiguration,
    stage: RuntimeStage,
    settings: OpenAIRuntimeSettings,
) -> None:
    provider_id = _settings_provider_id(settings)
    existing = configuration.accounts.get(provider_id, ProviderAccount())
    configuration.accounts[provider_id] = ProviderAccount(
        api_key=settings.api_key,
        base_url=settings.base_url or existing.base_url or provider_definition(provider_id).default_base_url,
        custom_models=existing.custom_models,
        codex_command=settings.codex_command or existing.codex_command,
    )
    getattr(configuration.stages, stage).provider_id = provider_id


def set_runtime_settings(settings: OpenAIRuntimeSettings | dict) -> OpenAIRuntimeSettings:
    next_settings = OpenAIRuntimeSettings.model_validate(settings)

    def apply(configuration: RuntimeConfiguration) -> None:
        _apply_connection(configuration, "planner", next_settings)
        _apply_connection(configuration, "writer", next_settings)

    configuration = _commit_runtime_update(apply)
    return _settings_for_stage(configuration, "planner")


def get_agent_runtime_settings(agent_name: AgentRuntimeName) -> OpenAIRuntimeSettings:
    with _lock:
        return _settings_for_stage(_runtime_configuration, _stage_for_agent(agent_name))


def _apply_agent_settings(
    configuration: RuntimeConfiguration,
    agent_name: AgentRuntimeName,
    settings: OpenAIRuntimeSettings,
) -> None:
    _apply_connection(configuration, _stage_for_agent(agent_name), settings)


def set_agent_runtime_settings(
    agent_name: AgentRuntimeName,
    settings: OpenAIRuntimeSettings | dict,
) -> OpenAIRuntimeSettings:
    next_settings = OpenAIRuntimeSettings.model_validate(settings)
    configuration = _commit_runtime_update(
        lambda candidate: _apply_agent_settings(candidate, agent_name, next_settings)
    )
    return _settings_for_stage(configuration, _stage_for_agent(agent_name))


def _strategy_settings_from_configuration(configuration: RuntimeConfiguration) -> AgentSettings:
    planner = configuration.stages.planner.model
    writer = configuration.stages.writer.model
    return AgentSettings(
        global_model=planner,
        character_model=planner,
        director_model=planner,
        writer_model=writer,
        memory_model=planner,
        temperature=configuration.temperature,
        new_character_policy=configuration.new_character_policy,
    )


def get_runtime_strategy_settings() -> AgentSettings:
    with _lock:
        return _strategy_settings_from_configuration(_runtime_configuration)


def _apply_strategy_settings(configuration: RuntimeConfiguration, strategy: AgentSettings) -> None:
    configuration.stages.planner.model = strategy.director_model or strategy.global_model
    configuration.stages.writer.model = strategy.writer_model or strategy.global_model
    configuration.temperature = strategy.temperature
    configuration.new_character_policy = strategy.new_character_policy


def set_runtime_strategy_settings(settings: AgentSettings | dict) -> AgentSettings:
    strategy = AgentSettings.model_validate(settings)
    configuration = _commit_runtime_update(
        lambda candidate: _apply_strategy_settings(candidate, strategy)
    )
    return _strategy_settings_from_configuration(configuration)


def get_all_runtime_settings() -> dict[str, object]:
    return {
        "global": get_runtime_settings(),
        "agents": {name: get_agent_runtime_settings(name) for name in AGENT_RUNTIME_NAMES},
        "strategy": get_runtime_strategy_settings(),
    }


def set_all_runtime_settings(settings: dict) -> dict[str, object]:
    if settings.get("schema_version") == "runtime-config/v2" or "accounts" in settings:
        set_runtime_configuration(settings)
        return get_all_runtime_settings()
    global_settings = (
        OpenAIRuntimeSettings.model_validate(settings["global"])
        if settings.get("global") is not None
        else None
    )
    raw_agents = settings.get("agents")
    agents = {
        name: OpenAIRuntimeSettings.model_validate(raw_agents[name])
        for name in AGENT_RUNTIME_NAMES
        if isinstance(raw_agents, dict) and name in raw_agents
    }
    strategy = (
        AgentSettings.model_validate(settings["strategy"])
        if settings.get("strategy") is not None
        else None
    )

    def apply(configuration: RuntimeConfiguration) -> None:
        if global_settings is not None:
            _apply_connection(configuration, "planner", global_settings)
            _apply_connection(configuration, "writer", global_settings)
        for name, agent_settings in agents.items():
            _apply_agent_settings(configuration, name, agent_settings)
        if strategy is not None:
            _apply_strategy_settings(configuration, strategy)

    _commit_runtime_update(apply)
    return get_all_runtime_settings()


def _partial_runtime_settings(
    data: dict | None, *, default_provider: RuntimeProvider | None = None
) -> OpenAIRuntimeSettings:
    data = data or {}
    return OpenAIRuntimeSettings(
        api_key=data.get("api_key") or "",
        base_url=data.get("base_url") or "",
        provider=data.get("provider", default_provider),
        codex_command=data.get("codex_command") or "",
    )


def resolve_openai_runtime_settings(
    agent_name: AgentRuntimeName | None = None,
    overrides: dict | None = None,
) -> OpenAIRuntimeSettings:
    if overrides is None:
        stage = _stage_for_agent(agent_name)
        with _lock:
            settings = _settings_for_stage(_runtime_configuration, stage)
            settings.base_url = settings.base_url.rstrip("/")
            return settings
    global_settings = _partial_runtime_settings(overrides.get("global"), default_provider="openai")
    agent_settings = (
        _partial_runtime_settings((overrides.get("agents") or {}).get(agent_name))
        if agent_name
        else OpenAIRuntimeSettings()
    )
    selected = OpenAIRuntimeSettings(
        api_key=agent_settings.api_key or global_settings.api_key,
        base_url=(agent_settings.base_url or global_settings.base_url).rstrip("/"),
        provider=agent_settings.provider or global_settings.provider or "openai",
        codex_command=agent_settings.codex_command or global_settings.codex_command or _default_codex_command(),
    )
    selected.provider = _settings_provider_id(selected)
    return selected


_load_config_from_file()
