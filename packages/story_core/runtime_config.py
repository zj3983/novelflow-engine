from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.story_core.env import load_environment_files
from packages.story_core.models import AgentSettings, NewCharacterPolicy, default_model_name


load_environment_files()


logger = logging.getLogger(__name__)


AgentRuntimeName = Literal["character", "director", "writer", "memory"]
AGENT_RUNTIME_NAMES: tuple[AgentRuntimeName, ...] = ("character", "director", "writer", "memory")
RuntimeProvider = Literal["openai", "codexcli"]
RuntimeStage = Literal["planner", "writer", "memory"]
RUNTIME_STAGES: tuple[RuntimeStage, ...] = ("planner", "writer", "memory")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")


class OpenAIRuntimeSettings(BaseModel):
    api_key: str = ""
    base_url: str = ""
    provider: RuntimeProvider | None = None
    codex_command: str = ""


class ProviderRuntimeConfiguration(_StrictModel):
    api_key: str = ""
    base_url: str = ""
    codex_command: str = ""
    planner: str = "gpt-5.6-sol"
    writer: str = "gpt-5.6-sol"
    memory: str = "gpt-5.6-terra"


def _default_api_key() -> str:
    return os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")


def _default_base_url() -> str:
    return (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("NOVEL_AUTOGROWTH_BASE_URL")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def _default_provider() -> RuntimeProvider:
    provider = os.getenv("NOVEL_LLM_PROVIDER", "codexcli").strip().lower()
    return "openai" if provider in {"openai", "http", "api"} else "codexcli"


def _default_codex_command() -> str:
    return os.getenv("NOVEL_CODEX_COMMAND", "codex")


def _default_openai_configuration() -> ProviderRuntimeConfiguration:
    model = default_model_name()
    return ProviderRuntimeConfiguration(
        api_key=_default_api_key(),
        base_url=_default_base_url(),
        planner=model,
        writer=model,
        memory=model,
    )


def _default_codexcli_configuration() -> ProviderRuntimeConfiguration:
    return ProviderRuntimeConfiguration(codex_command=_default_codex_command())


class ProviderConfigurations(_StrictModel):
    codexcli: ProviderRuntimeConfiguration = Field(default_factory=_default_codexcli_configuration)
    openai: ProviderRuntimeConfiguration = Field(default_factory=_default_openai_configuration)


class CompatibilityAgentConnection(_StrictModel):
    api_key: str = ""
    base_url: str = ""
    provider: RuntimeProvider | None = None
    codex_command: str = ""


class RuntimeCompatibilityConfiguration(_StrictModel):
    agents: dict[AgentRuntimeName, CompatibilityAgentConnection] = Field(default_factory=dict)


class RuntimeConfiguration(_StrictModel):
    provider: RuntimeProvider = Field(default_factory=_default_provider)
    providers: ProviderConfigurations = Field(default_factory=ProviderConfigurations)
    compatibility: RuntimeCompatibilityConfiguration = Field(
        default_factory=RuntimeCompatibilityConfiguration
    )
    temperature: float = 0.7
    new_character_policy: NewCharacterPolicy = "Director review"

    @model_validator(mode="after")
    def _selected_provider_has_all_stage_models(self) -> "RuntimeConfiguration":
        selected = getattr(self.providers, self.provider)
        blank_stages = [stage for stage in RUNTIME_STAGES if not getattr(selected, stage).strip()]
        if blank_stages:
            raise ValueError(
                f"selected provider {self.provider!r} has blank stage model(s): {', '.join(blank_stages)}"
            )
        return self


class StageRuntimeSettings(_StrictModel):
    provider: RuntimeProvider
    model: str
    api_key: str = ""
    base_url: str = ""
    codex_command: str = ""
    temperature: float = 0.7
    new_character_policy: NewCharacterPolicy = "Director review"


LEGACY_CONFIG_FILE = Path(os.path.dirname(os.path.abspath(__file__))) / "runtime_config.json"
CONFIG_FILE = Path(
    os.getenv(
        "NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH",
        str(Path.home() / ".novel-autogrowth-engine" / "runtime_config.json"),
    )
)

_lock = RLock()
_runtime_configuration = RuntimeConfiguration()
_runtime_configuration_error: str | None = None
_agent_runtime_settings: dict[str, OpenAIRuntimeSettings] = {}


def _atomic_write_configuration(configuration: RuntimeConfiguration, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(configuration.model_dump(mode="json"), indent=2, ensure_ascii=False)
    fd, temporary_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix="runtime_config_",
        suffix=".json",
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


def _legacy_stage_model(provider: RuntimeProvider, value: object, fallback: str) -> str:
    model = str(value or fallback).strip()
    if provider == "codexcli" and model == "qwen3.6-plus":
        return fallback
    return model


def _migrate_legacy_configuration(data: dict) -> RuntimeConfiguration:
    global_data = data.get("global") if isinstance(data.get("global"), dict) else {}
    strategy = data.get("strategy") if isinstance(data.get("strategy"), dict) else data
    raw_provider = global_data.get("provider", data.get("provider", _default_provider()))
    provider: RuntimeProvider = "openai" if str(raw_provider).lower() == "openai" else "codexcli"

    providers = ProviderConfigurations()
    selected = getattr(providers, provider).model_copy(deep=True)
    selected.api_key = str(global_data.get("api_key", data.get("api_key", selected.api_key)) or "")
    selected.base_url = str(global_data.get("base_url", data.get("base_url", selected.base_url)) or "")
    selected.codex_command = str(
        global_data.get("codex_command", data.get("codex_command", selected.codex_command)) or ""
    )
    selected.planner = _legacy_stage_model(provider, strategy.get("director_model"), selected.planner)
    selected.writer = _legacy_stage_model(provider, strategy.get("writer_model"), selected.writer)
    selected.memory = _legacy_stage_model(provider, strategy.get("memory_model"), selected.memory)
    setattr(providers, provider, selected)

    legacy_agents = data.get("agents") if isinstance(data.get("agents"), dict) else {}
    compatibility_agents = {
        agent_name: CompatibilityAgentConnection.model_validate(
            {
                key: settings.get(key)
                for key in ("api_key", "base_url", "provider", "codex_command")
                if key in settings
            }
        )
        for agent_name, settings in legacy_agents.items()
        if agent_name in AGENT_RUNTIME_NAMES and isinstance(settings, dict)
    }

    return RuntimeConfiguration(
        provider=provider,
        providers=providers,
        compatibility=RuntimeCompatibilityConfiguration(agents=compatibility_agents),
        temperature=strategy.get("temperature", 0.7),
        new_character_policy=strategy.get("new_character_policy", "Director review"),
    )


def _is_new_configuration(data: dict) -> bool:
    return "providers" in data


def _read_runtime_configuration(config_path: Path) -> tuple[RuntimeConfiguration, bool]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("configuration root must be an object")
    if _is_new_configuration(data):
        return RuntimeConfiguration.model_validate(data), False
    return _migrate_legacy_configuration(data), True


def _record_main_configuration_error(config_path: Path, exc: Exception) -> str:
    global _runtime_configuration_error
    message = f"invalid runtime configuration at {config_path}: {exc}"
    with _lock:
        _runtime_configuration_error = message
    logger.error(
        "Failed to parse runtime configuration at %s (%s)",
        config_path,
        type(exc).__name__,
    )
    return message


def load_runtime_configuration(
    path: str | os.PathLike[str] | None = None,
) -> RuntimeConfiguration:
    global _runtime_configuration_error
    config_path = Path(path) if path is not None else CONFIG_FILE
    is_main_configuration = config_path == CONFIG_FILE
    try:
        configuration, _ = _read_runtime_configuration(config_path)
        if is_main_configuration:
            with _lock:
                _runtime_configuration_error = None
        return configuration
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, ValueError)
            and str(exc).startswith("invalid runtime configuration")
            else f"invalid runtime configuration at {config_path}: {exc}"
        )
        if is_main_configuration:
            message = _record_main_configuration_error(config_path, exc)
        if message == str(exc):
            raise
        raise ValueError(message) from exc


def save_runtime_configuration(
    configuration: RuntimeConfiguration | dict,
    path: str | os.PathLike[str] | None = None,
) -> RuntimeConfiguration:
    config_path = Path(path) if path is not None else CONFIG_FILE
    with _lock:
        global _runtime_configuration_error
        validated = _validate_runtime_configuration(configuration)
        _atomic_write_configuration(validated, config_path)
        if config_path == CONFIG_FILE:
            _runtime_configuration_error = None
        return validated.model_copy(deep=True)


def _validate_runtime_configuration(
    configuration: RuntimeConfiguration | dict,
) -> RuntimeConfiguration:
    data = (
        configuration.model_dump(mode="python", warnings=False)
        if isinstance(configuration, RuntimeConfiguration)
        else configuration
    )
    return RuntimeConfiguration.model_validate(data)


def _commit_runtime_update(
    update: Callable[[RuntimeConfiguration], None],
) -> RuntimeConfiguration:
    with _lock:
        global _runtime_configuration, _runtime_configuration_error
        candidate = _validate_runtime_configuration(_runtime_configuration)
        update(candidate)
        validated = _validate_runtime_configuration(candidate)
        _atomic_write_configuration(validated, CONFIG_FILE)
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
        _atomic_write_configuration(validated, CONFIG_FILE)
        _runtime_configuration = validated
        _runtime_configuration_error = None
        return _runtime_configuration.model_copy(deep=True)


def resolve_stage_runtime(stage: RuntimeStage) -> StageRuntimeSettings:
    if stage not in RUNTIME_STAGES:
        raise ValueError(f"unknown runtime stage: {stage}")
    configuration = get_runtime_configuration()
    selected = getattr(configuration.providers, configuration.provider)
    return StageRuntimeSettings(
        provider=configuration.provider,
        model=getattr(selected, stage),
        api_key=selected.api_key,
        base_url=selected.base_url.rstrip("/"),
        codex_command=selected.codex_command,
        temperature=configuration.temperature,
        new_character_policy=configuration.new_character_policy,
    )


def _load_config_from_file() -> None:
    with _lock:
        global _runtime_configuration, _runtime_configuration_error
        if CONFIG_FILE.exists():
            try:
                configuration, migrated = _read_runtime_configuration(CONFIG_FILE)
                validated = _validate_runtime_configuration(configuration)
                if migrated:
                    _atomic_write_configuration(validated, CONFIG_FILE)
                _runtime_configuration = validated
                _runtime_configuration_error = None
            except Exception as exc:
                _record_main_configuration_error(CONFIG_FILE, exc)
            return

        if LEGACY_CONFIG_FILE.exists():
            try:
                configuration, _ = _read_runtime_configuration(LEGACY_CONFIG_FILE)
                validated = _validate_runtime_configuration(configuration)
                _atomic_write_configuration(validated, CONFIG_FILE)
                _runtime_configuration = validated
                _runtime_configuration_error = None
            except Exception as exc:
                _runtime_configuration_error = (
                    f"invalid runtime configuration at {LEGACY_CONFIG_FILE}: {exc}"
                )


def get_runtime_configuration_error() -> str | None:
    with _lock:
        return _runtime_configuration_error


_load_config_from_file()


def _empty_runtime_settings() -> OpenAIRuntimeSettings:
    return OpenAIRuntimeSettings(api_key="", base_url="")


def _runtime_settings_from_configuration(
    configuration: RuntimeConfiguration,
) -> OpenAIRuntimeSettings:
    selected = getattr(configuration.providers, configuration.provider)
    return OpenAIRuntimeSettings(
        api_key=selected.api_key,
        base_url=selected.base_url,
        provider=configuration.provider,
        codex_command=selected.codex_command,
    )


def get_runtime_settings() -> OpenAIRuntimeSettings:
    with _lock:
        return _runtime_settings_from_configuration(_runtime_configuration)


def _apply_runtime_settings(
    configuration: RuntimeConfiguration,
    settings: OpenAIRuntimeSettings,
) -> None:
    if settings.provider is not None:
        configuration.provider = settings.provider
    selected = getattr(configuration.providers, configuration.provider)
    selected.api_key = settings.api_key
    selected.base_url = settings.base_url
    selected.codex_command = settings.codex_command


def set_runtime_settings(settings: OpenAIRuntimeSettings | dict) -> OpenAIRuntimeSettings:
    next_settings = OpenAIRuntimeSettings.model_validate(settings)
    configuration = _commit_runtime_update(
        lambda candidate: _apply_runtime_settings(candidate, next_settings)
    )
    return _runtime_settings_from_configuration(configuration)


def get_agent_runtime_settings(agent_name: AgentRuntimeName) -> OpenAIRuntimeSettings:
    with _lock:
        compatibility_settings = _runtime_configuration.compatibility.agents.get(agent_name)
        if compatibility_settings is not None:
            return OpenAIRuntimeSettings.model_validate(
                compatibility_settings.model_dump(mode="json")
            )
        return _agent_runtime_settings.get(agent_name, _empty_runtime_settings()).model_copy(deep=True)


def set_agent_runtime_settings(
    agent_name: AgentRuntimeName,
    settings: OpenAIRuntimeSettings | dict,
) -> OpenAIRuntimeSettings:
    next_settings = OpenAIRuntimeSettings.model_validate(settings)
    connection = CompatibilityAgentConnection.model_validate(
        next_settings.model_dump(mode="python")
    )
    _commit_runtime_update(
        lambda candidate: candidate.compatibility.agents.__setitem__(agent_name, connection)
    )
    return next_settings.model_copy(deep=True)


def _strategy_settings_from_configuration(configuration: RuntimeConfiguration) -> AgentSettings:
    selected = getattr(configuration.providers, configuration.provider)
    return AgentSettings(
        global_model=selected.planner,
        character_model=selected.planner,
        director_model=selected.planner,
        writer_model=selected.writer,
        memory_model=selected.memory,
        temperature=configuration.temperature,
        new_character_policy=configuration.new_character_policy,
    )


def get_runtime_strategy_settings() -> AgentSettings:
    with _lock:
        return _strategy_settings_from_configuration(_runtime_configuration)


def _apply_strategy_settings(
    configuration: RuntimeConfiguration,
    strategy: AgentSettings,
) -> None:
    selected = getattr(configuration.providers, configuration.provider)
    selected.planner = strategy.director_model or strategy.global_model
    selected.writer = strategy.writer_model or strategy.global_model
    selected.memory = strategy.memory_model or strategy.global_model
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
        "agents": {
            agent_name: get_agent_runtime_settings(agent_name)
            for agent_name in AGENT_RUNTIME_NAMES
        },
        "strategy": get_runtime_strategy_settings(),
    }


def set_all_runtime_settings(settings: dict) -> dict[str, object]:
    if "providers" in settings:
        set_runtime_configuration(settings)
        return get_all_runtime_settings()
    global_settings = (
        OpenAIRuntimeSettings.model_validate(settings["global"])
        if settings.get("global") is not None
        else None
    )
    agents = settings.get("agents")
    agent_settings = {
        agent_name: CompatibilityAgentConnection.model_validate(agents[agent_name])
        for agent_name in AGENT_RUNTIME_NAMES
        if isinstance(agents, dict) and agent_name in agents
    }
    strategy = (
        AgentSettings.model_validate(settings["strategy"])
        if settings.get("strategy") is not None
        else None
    )

    def apply_all(configuration: RuntimeConfiguration) -> None:
        if global_settings is not None:
            _apply_runtime_settings(configuration, global_settings)
        configuration.compatibility.agents.update(agent_settings)
        if strategy is not None:
            _apply_strategy_settings(configuration, strategy)

    _commit_runtime_update(apply_all)
    return get_all_runtime_settings()


def _partial_runtime_settings(
    data: dict | None,
    *,
    default_provider: RuntimeProvider | None = None,
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
        global_settings = get_runtime_settings()
        agent_settings = get_agent_runtime_settings(agent_name) if agent_name else _empty_runtime_settings()
    else:
        global_settings = _partial_runtime_settings(
            overrides.get("global"),
            default_provider="openai",
        )
        agent_settings = (
            _partial_runtime_settings((overrides.get("agents") or {}).get(agent_name))
            if agent_name
            else _empty_runtime_settings()
        )
    return OpenAIRuntimeSettings(
        api_key=agent_settings.api_key or global_settings.api_key or _default_api_key(),
        base_url=(agent_settings.base_url or global_settings.base_url or _default_base_url()).rstrip("/"),
        provider=agent_settings.provider or global_settings.provider or _default_provider(),
        codex_command=agent_settings.codex_command or global_settings.codex_command or _default_codex_command(),
    )
